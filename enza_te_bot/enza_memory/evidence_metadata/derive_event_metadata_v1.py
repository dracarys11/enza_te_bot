#!/usr/bin/env python
"""Event Schema Derivation Prototype v1 (OFFLINE_ONLY).

Reads  enza_memory/evidence_metadata/metadata_records.jsonl  (read-only) and
emits  enza_memory/evidence_metadata/event_metadata_v1.jsonl  plus
enza_memory/evidence_metadata/migration_report.md.

For each image record, derives  event = {action, phase, result, state}  ONLY
where durable evidence supports it:

- REVIEW_MANIFEST_JOIN : review_batches manifests carry human-workflow
  page/phase/recommended_action for their images (confidence 0.75).
- OBS_ARTIFACT_JOIN    : an OBS artifact's TOP-LEVEL screenshot binding
  inherits that artifact's explicit page_state label, and a normalized
  PASS/FAIL only from an explicit season_result numeric observation
  (confidence 0.9).
- FILENAME_CONVENTION  : capture-time naming by the producing agent/operator
  encodes intent (confidence 0.6 — never FACT).
- VLM fields, when ever filled in a future records version, are treated as
  observations only: they may support appearance-only derivations at
  confidence <= 0.5 and can never promote a field to FACT.

Everything else stays null / UNKNOWN.  No runtime files are touched and
metadata_records.jsonl is never modified.
"""
from __future__ import annotations

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RECORDS_PATH = os.path.join(BASE_DIR, "enza_memory", "evidence_metadata", "metadata_records.jsonl")
OUT_PATH = os.path.join(BASE_DIR, "enza_memory", "evidence_metadata", "event_metadata_v1.jsonl")
REPORT_PATH = os.path.join(BASE_DIR, "enza_memory", "evidence_metadata", "migration_report.md")
OBS_DIR = os.path.join(BASE_DIR, "enza_memory", "observations")
REVIEW_BATCHES_DIR = os.path.join(
    BASE_DIR, "enza_memory", "migration", "python_click_migration", "review_batches")

CONF_OBS = 0.9
CONF_REVIEW = 0.75
CONF_FILENAME = 0.6
CONF_VLM_CAP = 0.5
LOW_CONFIDENCE_THRESHOLD = 0.7

# filename token -> (state, phase, action) ; None = do not derive that field
FILENAME_RULES = [
    ("rank_screen", "SEASON_RESULT", None, None),
    ("kettei_sent", "SCHEDULE", "POST_ACTION_WAIT", "VOCAL_DECIDE_SENT"),
    ("schedule", "SCHEDULE", None, None),
    ("winghome", "WING_HOME", None, None),
    ("home", "WING_HOME", None, None),
    ("lobby", "MAIN_LOBBY", None, None),
    ("after_lesson", "WING_HOME", "POST_ACTION", None),
    ("event_skip", None, None, "SKIP"),
    ("event", None, None, None),
    ("dialog", "DIALOGUE", None, None),
    ("dlg", "DIALOGUE", None, None),
    ("choice", "CHOICE", None, None),
    ("result", "RESULT", None, None),
    ("season", "SEASON_TRANSITION", None, None),
    ("audition_selection", "AUDITION_SELECT", None, None),
    ("audition", "AUDITION", None, None),
    ("skill_board", "SKILL_BOARD", None, None),
    ("input_ready", "AUDITION_BATTLE", "INPUT_READY", None),
    ("stuck_frame", "AUDITION_BATTLE", "STUCK_VISUAL_STATE", None),
    ("auto_toggle", "AUDITION_BATTLE", None, "AUTO_TOGGLE"),
    ("manual_input", "AUDITION_BATTLE", None, "MANUAL_INPUT"),
    ("speed", "AUDITION_BATTLE", None, "SPEED_CYCLE"),
    ("battle", "AUDITION_BATTLE", None, None),
    ("comm", "COMMUNICATION", None, None),
]

# recovered-frame directory -> state
DIR_STATE_RULES = [
    ("recovered_historical_frames/battle/", "AUDITION_BATTLE"),
    ("recovered_historical_frames/result/", "RESULT"),
    ("recovered_historical_frames/choice/", "CHOICE"),
    ("recovered_historical_frames/audition_selection/", "AUDITION_SELECT"),
    ("recovered_historical_frames/season/", "SEASON_TRANSITION"),
    ("recovered_frames/event_choice/", "CHOICE"),
    ("recovered_frames/dialogue/", "DIALOGUE"),
    ("recovered_frames/skill_board/", "SKILL_BOARD"),
    ("recovered_frames/replacement/", "SKILL_REPLACEMENT"),
]


def load_review_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    if not os.path.isdir(REVIEW_BATCHES_DIR):
        return index
    for batch in sorted(os.listdir(REVIEW_BATCHES_DIR)):
        manifest = os.path.join(REVIEW_BATCHES_DIR, batch, "review_manifest.jsonl")
        if not os.path.isfile(manifest):
            continue
        with open(manifest, encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for key in ("original_copy", "annotated_copy", "annotated_image"):
                    value = entry.get(key)
                    if isinstance(value, str):
                        index.setdefault(os.path.basename(value), {
                            "page": entry.get("page"),
                            "phase": entry.get("phase"),
                            "recommended_action": entry.get("recommended_action"),
                            "source_event": entry.get("source_event")
                            or entry.get("event_context"),
                        })
    return index


def load_obs_index() -> dict[str, dict]:
    """Top-level screenshot sha256 -> explicit OBS claims (label + season result)."""
    index: dict[str, dict] = {}
    if not os.path.isdir(OBS_DIR):
        return index
    for name in sorted(os.listdir(OBS_DIR)):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(OBS_DIR, name), encoding="utf-8") as fh:
                artifact = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        digest = artifact.get("screenshot_sha256")
        if not digest or not artifact.get("screenshot"):
            continue
        label = (artifact.get("page_state") or {}).get("label")
        result = None
        for numeric in artifact.get("numeric_observations") or []:
            field = str(numeric.get("field", ""))
            value = str(numeric.get("value", ""))
            if "result" in field.lower():
                lowered = value.lower()
                if "pass" in lowered:
                    result = "PASS"
                elif "fail" in lowered:
                    result = "FAIL"
        index[digest] = {"label": label, "result": result}
    return index


def leading_state(label: str | None) -> str | None:
    if not label:
        return None
    token = label.split("(")[0].split(":")[0].strip()
    return token or None


def derive_from_filename(rel_path: str) -> tuple[str | None, str | None, str | None]:
    name = rel_path.rsplit("/", 1)[-1].lower()
    for token, state, phase, action in FILENAME_RULES:
        if token in name:
            return state, phase, action
    for dir_token, state in DIR_STATE_RULES:
        if dir_token in rel_path.replace(os.sep, "/").lower():
            return state, None, None
    return None, None, None


def derive_vlm_observation(record: dict) -> tuple[str | None, str | None, str | None, list[str]]:
    """VLM fields are observations only: they can never promote to FACT.

    v0.1 records carry vlm_status=PENDING with null fields, so this never
    fires today; the guard exists so a future records version cannot silently
    convert visual guesses into FACT-graded event fields.
    """
    vlm = record.get("vlm") or {}
    if vlm.get("vlm_status") == "PENDING":
        return None, None, None, []
    notes = ["VLM_FIELDS_PRESENT: treated as APPEARANCE_ONLY observation, confidence capped"]
    state = vlm.get("state")
    phase = vlm.get("phase")
    action = None
    if vlm.get("visible_controls"):
        action = "+".join(str(c) for c in vlm["visible_controls"][:3])
    return state, phase, action, notes


def derive_event(record: dict, review_index: dict, obs_index: dict) -> dict:
    rel_path = record["source_path"]
    digest = record["record_id"]
    fields = {"action": None, "phase": None, "result": None, "state": None}
    sources: dict[str, str] = {}
    notes: list[str] = []
    confidence = 0.0
    authority = "NONE"
    source = "NO_SUPPORTING_EVIDENCE"

    # 1) OBS artifact join (top-level screenshot only): strongest evidence
    obs = obs_index.get(digest)
    if obs:
        state = leading_state(obs.get("label"))
        if state:
            fields["state"] = state
            sources["state"] = "OBS_ARTIFACT_JOIN(page_state.label verbatim-derived)"
        if obs.get("result"):
            fields["result"] = obs["result"]
            sources["result"] = "OBS_ARTIFACT_JOIN(explicit season_result numeric observation)"
        confidence = max(confidence, CONF_OBS)
        authority = "OBS_ARTIFACT"
        source = "OBS_ARTIFACT_JOIN"
        notes.append("OBS top-level screenshot binding: explicit session-observed claims")

    # 2) review manifest join (human-workflow metadata)
    review = review_index.get(os.path.basename(rel_path))
    if review:
        if fields["state"] is None and review.get("page"):
            fields["state"] = review["page"]
            sources["state"] = "REVIEW_MANIFEST_JOIN(page)"
        if fields["phase"] is None and review.get("phase"):
            fields["phase"] = review["phase"]
            sources["phase"] = "REVIEW_MANIFEST_JOIN(phase)"
        if fields["action"] is None and review.get("recommended_action"):
            fields["action"] = review["recommended_action"]
            sources["action"] = "REVIEW_MANIFEST_JOIN(recommended_action)"
        confidence = max(confidence, CONF_REVIEW)
        if authority == "NONE":
            authority = "REVIEW_MANIFEST"
            source = "REVIEW_MANIFEST_JOIN"

    # 3) filename convention (capture-time intent; never FACT)
    if confidence < CONF_FILENAME:
        state, phase, action = derive_from_filename(rel_path)
        for field, value in (("state", state), ("phase", phase), ("action", action)):
            if value and fields[field] is None:
                fields[field] = value
                sources[field] = "FILENAME_CONVENTION"
        if any(fields.values()):
            confidence = max(confidence, CONF_FILENAME)
            if authority == "NONE":
                authority = "FILENAME_CONVENTION"
                source = "FILENAME_CONVENTION"

    # 4) VLM fields: observations only, capped below FACT threshold
    vlm_state, vlm_phase, vlm_action, vlm_notes = derive_vlm_observation(record)
    notes.extend(vlm_notes)
    for field, value in (("state", vlm_state), ("phase", vlm_phase), ("action", vlm_action)):
        if value and fields[field] is None:
            fields[field] = value
            sources[field] = "VLM_APPEARANCE_ONLY"
            confidence = max(confidence, CONF_VLM_CAP)
            if authority == "NONE":
                authority = "APPEARANCE_ONLY"
                source = "VLM_APPEARANCE_ONLY"

    derived = [v for v in fields.values() if v is not None]
    if not derived:
        classification = "UNKNOWN"
        confidence = 0.0
        authority = "NONE"
        source = "NO_SUPPORTING_EVIDENCE"
    elif len(derived) == len(fields) and confidence >= LOW_CONFIDENCE_THRESHOLD:
        classification = "DERIVED_COMPLETE"
    else:
        classification = "PARTIAL"

    return {
        "schema_version": 1,
        "artifact_type": "EVENT_METADATA_RECORD",
        "record_id": digest,
        "source_path": rel_path,
        "event": fields,
        "event_provenance": {
            "source": source,
            "authority_type": authority,
            "confidence": round(confidence, 2),
        },
        "classification": classification,
        "low_confidence": bool(derived and confidence < LOW_CONFIDENCE_THRESHOLD),
        "field_sources": sources,
        "derivation_notes": notes,
    }


def main() -> int:
    if not os.path.isfile(RECORDS_PATH):
        print(f"input missing: {RECORDS_PATH}")
        return 2
    review_index = load_review_index()
    obs_index = load_obs_index()

    records = []
    with open(RECORDS_PATH, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))

    events = [derive_event(record, review_index, obs_index) for record in records]

    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")

    total = len(events)
    complete = sum(1 for e in events if e["classification"] == "DERIVED_COMPLETE")
    partial = sum(1 for e in events if e["classification"] == "PARTIAL")
    unknown = sum(1 for e in events if e["classification"] == "UNKNOWN")
    low_conf = sum(1 for e in events if e["low_confidence"])
    by_authority: dict[str, int] = {}
    for e in events:
        by_authority[e["event_provenance"]["authority_type"]] = (
            by_authority.get(e["event_provenance"]["authority_type"], 0) + 1)

    report = f"""# Event Schema Derivation Prototype v1 — Migration Report

- mode: OFFLINE_ONLY (metadata_records.jsonl read-only; runtime untouched)
- input: enza_memory/evidence_metadata/metadata_records.jsonl
- output: enza_memory/evidence_metadata/event_metadata_v1.jsonl

## Counts

| metric | count |
|---|---|
| TOTAL | {total} |
| DERIVED_COMPLETE | {complete} |
| PARTIAL | {partial} |
| UNKNOWN | {unknown} |
| LOW_CONFIDENCE (derived, confidence < {LOW_CONFIDENCE_THRESHOLD}) | {low_conf} |

## Derivation sources used (authority_type)

| authority_type | records |
|---|---|
""" + "\n".join(f"| {k} | {v} |" for k, v in sorted(by_authority.items())) + f"""

## Rules honored

- Only durable, provable sources promoted: review manifests (page/phase/
  recommended_action, confidence {CONF_REVIEW}), OBS top-level screenshot
  bindings (explicit page_state label and explicit season_result PASS/FAIL,
  confidence {CONF_OBS}), capture-time filename conventions (confidence
  {CONF_FILENAME}, never FACT).
- VLM fields are observations only: even when present in a future records
  version they are capped at {CONF_VLM_CAP} and can never promote a field to
  FACT.  v0.1 records are vlm_status=PENDING, so no VLM derivation fired.
- Unsupported records stay UNKNOWN with authority_type NONE — never guessed.

**EVENT_SCHEMA_DERIVATION_PROTOTYPE_READY**
"""
    with open(REPORT_PATH, "w", encoding="utf-8") as fh:
        fh.write(report)

    print(f"TOTAL={total} DERIVED_COMPLETE={complete} PARTIAL={partial} "
          f"UNKNOWN={unknown} LOW_CONFIDENCE={low_conf}")
    print(f"written: {OUT_PATH}")
    print(f"written: {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
