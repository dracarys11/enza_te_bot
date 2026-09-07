"""Observation Interpreter v0.1 for enza.

Consumes a VisionObservation payload (see vision_observation_schema.py) and
produces an ObservationInterpretation: grounded facts, evidence-backed
semantic candidates, unknowns, and action candidates WITHOUT coordinates,
execution permission, strategy, or screen predictions.

This module performs interpretation only:
- no image processing, no OCR, no automation, no clicking
- semantic identity requires evidence (title_text_read / roundtrip_verified);
  coordinate_only and shape_only are forbidden identity sources
- supported labels are restricted to the WING minimal loop:
  HOME, WING_SELECTION, TRAINING_SETTINGS (+ VOCAL_INCREMENT action)
"""
from __future__ import annotations

from typing import Any, Iterable

from vision_observation_schema import VisionObservation

# Identity sources that may establish a semantic candidate. Anything else
# (coordinate_only, shape_only, ...) must leave the state UNKNOWN.
ALLOWED_IDENTITY_SOURCES = frozenset({"title_text_read", "roundtrip_verified"})

# Minimum OCR confidence for a text region to be usable as title evidence.
TITLE_EVIDENCE_MIN_CONFIDENCE = 0.9

# Known label signatures for the minimal loop. Each entry maps a semantic
# label to the exact title text that may establish it. Matching is exact
# (no fuzzy, no substrings) — approximate matches must stay UNKNOWN.
LABEL_TITLE_SIGNATURES: dict[str, tuple[str, ...]] = {
    # MVP-loop signature; the actual on-canvas HOME title text is not yet
    # verified against the live environment — treat "ホーム" as provisional
    # until a live vision pass confirms it.
    "HOME": ("ホーム",),
    "TRAINING_SETTINGS": ("研修設定",),
    "WING_SELECTION": ("W.I.N.G.",),
}

# Buttons that open a supported state, matched via linked text.
OPEN_TARGET_BY_TEXT = {
    "研修設定": "TRAINING_SETTINGS",
}


def _text_regions(obs: VisionObservation) -> list[dict[str, Any]]:
    return obs.text_regions


def _high_confidence_titles(obs: VisionObservation) -> list[dict[str, Any]]:
    return [
        region
        for region in _text_regions(obs)
        if isinstance(region.get("confidence"), (int, float))
        and float(region["confidence"]) >= TITLE_EVIDENCE_MIN_CONFIDENCE
    ]


def _visible_facts(obs: VisionObservation) -> list[str]:
    facts: list[str] = []
    for region in _text_regions(obs):
        facts.append(
            f"text '{region.get('text')}' at bbox (reported, coordinates withheld)"
            if False
            else f"text_region {region.get('id')}: '{region.get('text')}' (ocr {region.get('confidence')})"
        )
    for region in obs.numeric_regions:
        facts.append(
            f"numeric_region {region.get('id')}: value={region.get('value')} "
            f"max={region.get('max_value')} raw='{region.get('raw_text')}'"
        )
    for overlay in obs.overlay_regions:
        facts.append(
            f"overlay {overlay.get('id')} present, blocks "
            f"{len(overlay.get('blocked_element_ids', []))} element(s)"
        )
    for uncertainty in obs.uncertainties:
        facts.append(f"uncertainty reported: {uncertainty.get('reason')}")
    return facts


def _semantic_candidates(
    obs: VisionObservation, roundtrip_verified_labels: Iterable[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (candidates, unknowns). Coordinate/shape evidence never qualifies."""
    candidates: list[dict[str, Any]] = []
    unknowns: list[str] = []

    matched_labels: set[str] = set()

    # 1. Title-text evidence (exact signature match on high-confidence OCR).
    #    A text region linked to an interaction candidate is a BUTTON LABEL,
    #    not a screen title — e.g. '研修設定' on the W.I.N.G. selection screen
    #    names a button there, it does not make that screen TRAINING_SETTINGS.
    button_label_ids = {
        tid
        for element in obs.interaction_candidates
        for tid in element.get("linked_text_ids", [])
    }
    for label, titles in LABEL_TITLE_SIGNATURES.items():
        for region in _high_confidence_titles(obs):
            if region.get("id") in button_label_ids:
                continue
            if region.get("text") in titles:
                candidates.append(
                    {
                        "label": label,
                        "evidence_refs": [
                            f"text_region:{region.get('id')} ('{region.get('text')}', "
                            f"conf {region.get('confidence')})"
                        ],
                        "identity_source": "title_text_read",
                        "confidence": float(region["confidence"]),
                    }
                )
                matched_labels.add(label)

    # 2. Roundtrip-verified labels supplied by caller memory (not derivable
    #    from a single screenshot).
    for label in roundtrip_verified_labels:
        if label not in matched_labels:
            candidates.append(
                {
                    "label": label,
                    "evidence_refs": ["caller_memory:roundtrip_verified"],
                    "identity_source": "roundtrip_verified",
                    "confidence": 0.8,
                }
            )
            matched_labels.add(label)

    # 3. Overlays without a readable title text remain explicitly unknown —
    #    presence of a panel is a visual fact, not an identity.
    titled_overlay_ids = {
        tid for overlay in obs.overlay_regions for tid in overlay.get("linked_text_ids", [])
    }
    for overlay in obs.overlay_regions:
        if not set(overlay.get("linked_text_ids", [])) & titled_overlay_ids:
            unknowns.append(
                f"overlay {overlay.get('id')}: identity UNKNOWN — presence is a "
                f"coordinate/shape fact only, no title text evidence"
            )
    return candidates, unknowns


def _unknowns(obs: VisionObservation, semantic_unknowns: list[str]) -> list[str]:
    unknowns = list(semantic_unknowns)
    for region in _text_regions(obs):
        conf = region.get("confidence")
        if isinstance(conf, (int, float)) and float(conf) < TITLE_EVIDENCE_MIN_CONFIDENCE:
            unknowns.append(
                f"text_region {region.get('id')} ('{region.get('text')}'): below title-evidence "
                f"confidence ({conf} < {TITLE_EVIDENCE_MIN_CONFIDENCE}) — unusable as identity"
            )
    for uncertainty in obs.uncertainties:
        unknowns.append(f"unreadable region reported: {uncertainty.get('reason')}")
    if not semantic_unknowns and not obs.uncertainties:
        unknowns.append("no unresolved identity questions in supported loop labels")
    return unknowns


def _permitted_actions(obs: VisionObservation) -> list[dict[str, Any]]:
    """Action candidates for the minimal loop. Never coordinates or permission.

    Supported: VOCAL_INCREMENT (numeric counter under a ボーカル label with
    value < max, plus an interaction candidate in that column), and
    OPEN_TRAINING_SETTINGS (element linked to the 研修設定 text).
    """
    actions: list[dict[str, Any]] = []

    # VOCAL_INCREMENT: find the ボーカル label, then numeric + interaction
    # candidates horizontally aligned with it (same column).
    vocal_labels = [r for r in _text_regions(obs) if r.get("text") == "ボーカル"]
    for label in vocal_labels:
        lx, ly, lw, lh = label["bbox"]
        l_center_x = lx + lw / 2
        for numeric in obs.numeric_regions:
            nx, ny, nw, nh = numeric["bbox"]
            n_center_x = nx + nw / 2
            same_column = abs(n_center_x - l_center_x) < 120 and ny > ly
            value = numeric.get("value")
            max_value = numeric.get("max_value")
            below_max = (
                isinstance(value, (int, float))
                and isinstance(max_value, (int, float))
                and value < max_value
            )
            if not (same_column and below_max):
                continue
            # Right-side circle button in the same column band is the
            # increment candidate; left/right ordering is an assumption and
            # is carried as an uncertainty, never as a coordinate.
            column_buttons = [
                e
                for e in obs.interaction_candidates
                if isinstance(e.get("bbox"), (list, tuple))
                and abs((e["bbox"][0] + e["bbox"][2] / 2) - l_center_x) < 120
                and abs((e["bbox"][1] + e["bbox"][3] / 2) - ny) < 60
                and e.get("appearance", {}).get("shape") == "circle_button"
            ]
            if not column_buttons:
                continue
            rightmost = max(column_buttons, key=lambda e: e["bbox"][0])
            actions.append(
                {
                    "action_type": "VOCAL_INCREMENT",
                    "target_element_id": rightmost.get("id"),
                    "evidence_refs": [
                        f"source_observation:{obs.observation_id}",
                        f"text_region:{label.get('id')} ('ボーカル')",
                        f"numeric_region:{numeric.get('id')} (value {value}/{max_value})",
                        f"interaction_candidate:{rightmost.get('id')} (circle_button, column-right)",
                    ],
                    "uncertainty_status": (
                        "ASSUMED: right-of-counter circle is the increment control; "
                        "left/right ordering unverified; verify by counter delta after action"
                    ),
                }
            )

    # OPEN_TRAINING_SETTINGS: any interaction candidate linked to the text.
    for element in obs.interaction_candidates:
        linked = element.get("linked_text_ids", [])
        linked_texts = [r.get("text") for r in _text_regions(obs) if r.get("id") in linked]
        if "研修設定" in linked_texts:
            actions.append(
                {
                    "action_type": "OPEN_TRAINING_SETTINGS",
                    "target_element_id": element.get("id"),
                    "evidence_refs": [
                        f"source_observation:{obs.observation_id}",
                        f"interaction_candidate:{element.get('id')} linked to text '研修設定'",
                    ],
                    "uncertainty_status": "STABLE: label-linked button (title text read)",
                }
            )

    return actions


def interpret(
    vision_payload: dict[str, Any],
    *,
    roundtrip_verified_labels: Iterable[str] = (),
) -> dict[str, Any]:
    """Interpret a VisionObservation payload into an ObservationInterpretation."""
    obs = VisionObservation.from_payload(vision_payload)  # contract-enforced input
    candidates, semantic_unknowns = _semantic_candidates(obs, roundtrip_verified_labels)
    return {
        "observation_id": obs.observation_id,
        "visible_facts": _visible_facts(obs),
        "semantic_candidates": candidates,
        "unknowns": _unknowns(obs, semantic_unknowns),
        "permitted_actions": _permitted_actions(obs),
        # Explicitly absent by contract: click coordinates, execution
        # permission, strategy, next-screen prediction.
    }
