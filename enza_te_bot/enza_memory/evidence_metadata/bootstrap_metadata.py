#!/usr/bin/env python
"""Evidence Metadata Bootstrap Pipeline v0.1 (OFFLINE_ONLY).

Scans the durable evidence corpus for images and emits one deterministic
metadata record per image plus a field coverage report.  Prepares the corpus
for a later VLM evaluation pass (Vision Evidence Retrieval v0.2).

Guarantees:
- original images are opened READ-ONLY and never modified;
- all writes stay inside enza_memory/evidence_metadata/;
- deterministic fields only (hash, path, stat, path/filename derivations,
  durable-manifest joins); VLM fields are emitted as PENDING nulls;
- forbidden process fields (authority_type, failure_category,
  planner_decision, execution_permission) are never generated.

Usage: .venv/bin/python enza_memory/evidence_metadata/bootstrap_metadata.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE_DIR, "enza_memory", "evidence_metadata")

IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
SCAN_ROOTS = (
    "enza_memory/wing_runs",
    "enza_memory/migration/python_click_migration",
    "enza_memory/self_exploration",
    os.path.join("ai_decisions", "observations", "screenshots"),
)
REVIEW_BATCHES_DIR = os.path.join(
    "enza_memory", "migration", "python_click_migration", "review_batches")
OBS_DIR = os.path.join("enza_memory", "observations")

FILENAME_CLOCK_RE = re.compile(r"^(\d{8})_(\d{6})_")
SESSION_TOKEN_RE = re.compile(r"^(\d{8})_(\d{6})_(\d{6,})_")

VLM_PENDING_FIELDS = ("state", "phase", "event_type", "visible_text",
                      "visible_controls", "layout_family")
FORBIDDEN_FIELDS = ("authority_type", "failure_category",
                    "planner_decision", "execution_permission")


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_dimensions(path: str) -> tuple[int | None, int | None]:
    try:
        from PIL import Image  # noqa: PLC0415 - optional dependency, read-only
        with Image.open(path) as im:
            return int(im.width), int(im.height)
    except Exception:  # noqa: BLE001 - dimensions are best-effort, never fatal
        return None, None


def load_obs_index() -> dict[str, dict[str, str | None]]:
    """sha256 -> {captured_at, run_id} from durable OBS evidence bindings."""
    index: dict[str, dict[str, str | None]] = {}
    if not os.path.isdir(OBS_DIR):
        return index
    for name in sorted(os.listdir(OBS_DIR)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(OBS_DIR, name)
        try:
            with open(path, encoding="utf-8") as fh:
                artifact = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        run_id = artifact.get("run_id")
        refs = list(artifact.get("evidence_references") or [])
        screenshot = artifact.get("screenshot")
        screenshot_digest = artifact.get("screenshot_sha256")
        if screenshot and screenshot_digest:
            refs.append({"path": screenshot, "integrity": {"digest": screenshot_digest},
                         "captured_at": artifact.get("captured_at")
                         or artifact.get("provenance", {}).get("captured_at")})
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            digest = ((ref.get("integrity") or {}).get("digest"))
            if not digest:
                continue
            captured_at = ref.get("captured_at")
            entry = index.setdefault(digest, {"captured_at": None, "run_id": None})
            if captured_at and not entry["captured_at"]:
                entry["captured_at"] = captured_at
            if run_id and not entry["run_id"]:
                entry["run_id"] = run_id
    return index


def load_review_manifest_index() -> dict[str, dict[str, str | None]]:
    """image basename -> {source_run} across review batches that carry manifests."""
    index: dict[str, dict[str, str | None]] = {}
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
                source_run = entry.get("source_run")
                for key in ("original_copy", "annotated_copy", "annotated_image"):
                    value = entry.get(key)
                    if isinstance(value, str):
                        index.setdefault(os.path.basename(value),
                                         {"source_run": source_run})
    return index


def corpus_category_and_role(rel_path: str) -> tuple[str, str]:
    parts = rel_path.replace(os.sep, "/").split("/")
    if parts[0] == "enza_memory" and len(parts) > 2 and parts[1] == "wing_runs":
        return "RUN_SCREENSHOTS", "ORIGINAL_EVIDENCE"
    if parts[0] == "enza_memory" and len(parts) > 3 and parts[1] == "self_exploration":
        return "SELF_EXPLORATION_SCREENSHOTS", "ORIGINAL_EVIDENCE"
    if "review_batches" in parts:
        if "annotated" in parts:
            return "REVIEW_BATCH_ANNOTATED", "ANNOTATED_OVERLAY"
        return "REVIEW_BATCH_ORIGINAL", "ORIGINAL_EVIDENCE"
    if "recovered_historical_frames" in parts:
        return "RECOVERED_HISTORICAL_FRAME", "ORIGINAL_EVIDENCE"
    if "recovered_frames" in parts:
        return "RECOVERED_FRAME", "ORIGINAL_EVIDENCE"
    if parts[0] == "ai_decisions":
        return "OBS_SCREENSHOT", "ORIGINAL_EVIDENCE"
    return "UNCATEGORIZED", "ORIGINAL_EVIDENCE"


def derive_run_id(rel_path: str, *, category: str,
                  manifest_index: dict, obs_index: dict, digest: str,
                  ) -> tuple[str | None, str]:
    parts = rel_path.replace(os.sep, "/").split("/")
    if category == "RUN_SCREENSHOTS":
        return parts[2], "PATH_WING_RUNS_DIR"
    if category == "SELF_EXPLORATION_SCREENSHOTS":
        return parts[2], "PATH_SELF_EXPLORATION_DIR"
    if category in {"REVIEW_BATCH_ORIGINAL", "REVIEW_BATCH_ANNOTATED"}:
        entry = manifest_index.get(os.path.basename(rel_path))
        if entry and entry.get("source_run"):
            return entry["source_run"], "REVIEW_MANIFEST_JOIN"
    obs_entry = obs_index.get(digest)
    if obs_entry and obs_entry.get("run_id"):
        return obs_entry["run_id"], "OBS_EVIDENCE_JOIN"
    return None, "NOT_DERIVABLE"


def derive_timestamp(rel_path: str, obs_index: dict, digest: str,
                     ) -> tuple[str | None, str]:
    obs_entry = obs_index.get(digest)
    if obs_entry and obs_entry.get("captured_at"):
        return obs_entry["captured_at"], "OBS_EVIDENCE_JOIN"
    match = FILENAME_CLOCK_RE.match(os.path.basename(rel_path))
    if match:
        date, clock = match.group(1), match.group(2)
        iso = f"{date[0:4]}-{date[4:6]}-{date[6:8]}T{clock[0:2]}:{clock[2:4]}:{clock[4:6]}"
        return iso, "FILENAME_CLOCK_LOCAL_UNKNOWN_TZ"
    return None, "NOT_DERIVABLE"


def iter_images() -> list[str]:
    found: list[str] = []
    for root in SCAN_ROOTS:
        root_abs = os.path.join(BASE_DIR, root)
        if not os.path.isdir(root_abs):
            continue
        for dirpath, _dirnames, filenames in os.walk(root_abs):
            for name in sorted(filenames):
                if os.path.splitext(name)[1].lower() in IMAGE_EXTS:
                    found.append(os.path.join(dirpath, name))
    return sorted(found)


def build_record(path_abs: str) -> dict:
    rel_path = os.path.relpath(path_abs, BASE_DIR)
    digest = sha256_of(path_abs)
    stat = os.stat(path_abs)
    width, height = image_dimensions(path_abs)
    category, image_role = corpus_category_and_role(rel_path)
    run_id, run_id_source = derive_run_id(
        rel_path, category=category, manifest_index=MANIFEST_INDEX,
        obs_index=OBS_INDEX, digest=digest)
    captured_at, timestamp_source = derive_timestamp(rel_path, OBS_INDEX, digest)
    session_hint = None
    session_match = SESSION_TOKEN_RE.match(os.path.basename(rel_path))
    if session_match:
        session_hint = session_match.group(3)
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    return {
        "schema_version": 1,
        "artifact_type": "EVIDENCE_METADATA_RECORD",
        "record_id": digest,
        "source_path": rel_path.replace(os.sep, "/"),
        "sha256": digest,
        "file_size_bytes": stat.st_size,
        "width": width,
        "height": height,
        "corpus_category": category,
        "image_role": image_role,
        "run_id": run_id,
        "run_id_source": run_id_source,
        "session_hint": session_hint,
        "captured_at": captured_at,
        "timestamp_source": timestamp_source,
        "file_mtime_utc": mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vlm": {field: None for field in VLM_PENDING_FIELDS} | {"vlm_status": "PENDING"},
    }


def build_coverage_report(records: list[dict], total_images: int) -> dict:
    fields = [
        ("sha256", "SHA256_OF_FILE"),
        ("source_path", "SCAN_ROOTS_WALK"),
        ("run_id", "PATH_WING_RUNS_DIR | PATH_SELF_EXPLORATION_DIR | REVIEW_MANIFEST_JOIN | OBS_EVIDENCE_JOIN"),
        ("captured_at", "OBS_EVIDENCE_JOIN | FILENAME_CLOCK_LOCAL_UNKNOWN_TZ"),
        ("file_mtime_utc", "FILE_STAT"),
        ("corpus_category", "PATH_PATTERN"),
        ("image_role", "PATH_PATTERN"),
        ("width", "IMAGE_HEADER"),
        ("height", "IMAGE_HEADER"),
        *[(f"vlm.{name}", "PENDING_VLM_PASS") for name in VLM_PENDING_FIELDS],
    ]
    rows = []
    for field, source in fields:
        if field.startswith("vlm."):
            continue  # handled as a block below
        filled = sum(1 for r in records if r.get(field) is not None)
        rows.append({
            "field": field,
            "filled_count": filled,
            "missing_count": len(records) - filled,
            "source": source,
        })
    vlm_block = {
        "field": "vlm (state/phase/event_type/visible_text/visible_controls/layout_family)",
        "filled_count": 0,
        "missing_count": len(records) * len(VLM_PENDING_FIELDS),
        "source": "PENDING_VLM_PASS",
    }
    rows.append(vlm_block)
    return {
        "schema_version": 1,
        "artifact_type": "EVIDENCE_METADATA_COVERAGE_REPORT",
        "generated_at": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "OFFLINE_ONLY (read-only scan; no image modified)",
        "total_images": total_images,
        "records_written": len(records),
        "forbidden_fields_generated": FORBIDDEN_FIELDS,
        "forbidden_fields_count": 0,
        "fields": rows,
    }


def render_coverage_md(report: dict) -> str:
    lines = [
        "# Evidence Metadata Bootstrap — Coverage Report v0.1",
        "",
        f"- generated_at: {report['generated_at']} (OFFLINE_ONLY, read-only scan)",
        f"- total_images: {report['total_images']} · records_written: {report['records_written']}",
        f"- forbidden fields generated: {report['forbidden_fields_count']}",
        "",
        "| field | filled_count | missing_count | source |",
        "|---|---|---|---|",
    ]
    for row in report["fields"]:
        lines.append(f"| {row['field']} | {row['filled_count']} | {row['missing_count']} | {row['source']} |")
    lines += [
        "",
        "VLM-pending fields (state/phase/event_type/visible_text/visible_controls/layout_family) are intentionally null until the VLM pass.",
        "",
        "**EVIDENCE_METADATA_BOOTSTRAP_READY**",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    global MANIFEST_INDEX, OBS_INDEX
    OBS_INDEX = load_obs_index()
    MANIFEST_INDEX = load_review_manifest_index()

    images = iter_images()
    records = [build_record(path) for path in images]

    os.makedirs(OUT_DIR, exist_ok=True)
    records_path = os.path.join(OUT_DIR, "metadata_records.jsonl")
    with open(records_path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    report = build_coverage_report(records, total_images=len(images))
    with open(os.path.join(OUT_DIR, "coverage_report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, "coverage_report.md"), "w", encoding="utf-8") as fh:
        fh.write(render_coverage_md(report))

    # self-check: forbidden fields absent, source paths exist, digest sample re-verified
    for record in records[:5] + records[-5:]:
        for forbidden in FORBIDDEN_FIELDS:
            assert forbidden not in record, f"forbidden field present: {forbidden}"
        path_abs = os.path.join(BASE_DIR, record["source_path"])
        assert os.path.isfile(path_abs), f"missing source: {record['source_path']}"
        assert sha256_of(path_abs) == record["sha256"], f"digest drift: {record['source_path']}"

    print(f"images scanned: {len(images)}")
    print(f"records written: {records_path}")
    for row in report["fields"]:
        print(f"  {row['field']}: filled={row['filled_count']} missing={row['missing_count']} ({row['source']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
