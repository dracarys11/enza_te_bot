#!/usr/bin/env python3
"""Build the offline v0.1 VLM observation annotation dataset.

The collector has an intentionally narrow allow-list: WING run images,
python-click migration images, and image paths explicitly referenced by the
benchmark cases. It does not walk caches, logs, or the rest of the workspace.
Visual fields remain UNKNOWN because this builder has no model backend.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

try:  # Package import for tests; direct import for ``python tools/...py``.
    from tools.vlm_observation_extractor import extract_observation
except ModuleNotFoundError:  # pragma: no cover - direct script form
    from vlm_observation_extractor import extract_observation


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
OUTPUT_FIELDS = {"image", "sha256", "observation", "confidence", "vlm_status"}
METADATA_FIELDS = {"run_id", "trajectory", "failure", "failure_category"}


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _case_image_paths(root: Path, case_root: Path) -> set[Path]:
    paths: set[Path] = set()
    for case_file in sorted(case_root.glob("*.json")):
        try:
            payload = json.loads(case_file.read_text())
        except (OSError, json.JSONDecodeError):
            continue

        def visit(value: Any) -> None:
            if isinstance(value, str) and Path(value).suffix.lower() in IMAGE_SUFFIXES:
                candidate = (root / value).resolve()
                if candidate.is_file():
                    paths.add(candidate)
            elif isinstance(value, dict):
                for child in value.values():
                    visit(child)
            elif isinstance(value, list):
                for child in value:
                    visit(child)

        visit(payload)
    return paths


def collect_images(root: Path, benchmark_cases: Path) -> list[Path]:
    """Collect only the declared evidence corpus, deterministically."""
    paths: set[Path] = set()
    for allowed_root in (root / "enza_memory/wing_runs", root / "enza_memory/migration/python_click_migration"):
        if allowed_root.is_dir():
            paths.update(path.resolve() for path in allowed_root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)
    paths.update(_case_image_paths(root, benchmark_cases))
    return sorted(paths, key=lambda path: _relative(root, path))


def _load_existing_metadata(path: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return result
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        source_path = record.get("source_path")
        if isinstance(source_path, str):
            result[source_path] = record
    return result


def _iter_json_values(value: Any) -> Iterable[Any]:
    """Yield nested JSON values without assigning meaning to free text."""
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _iter_json_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_json_values(child)


def _load_evidence_joins(root: Path) -> dict[str, dict[str, Any]]:
    """Join image references to factual records already in the repository.

    The join is intentionally exact (or basename-equal for records that store
    a repository-relative path from another working directory).  No labels are
    inferred from image names, folders, or annotation output.
    """
    joins: dict[str, dict[str, Any]] = {}
    roots = (
        root / "enza_memory/observations",
        root / "enza_memory/trajectories",
        root / "enza_memory/failures",
        root / "enza_memory/wing_runs",
    )
    for search_root in roots:
        if not search_root.is_dir():
            continue
        for source in sorted(search_root.rglob("*.json")):
            try:
                payload = json.loads(source.read_text())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            strings = [item for item in _iter_json_values(payload) if isinstance(item, str)]
            referenced = {
                Path(item).as_posix()
                for item in strings
                if Path(item).suffix.lower() in IMAGE_SUFFIXES
            }
            if not referenced:
                continue
            run_id = payload.get("run_id") if isinstance(payload, dict) else None
            if run_id is None and isinstance(payload, dict):
                run_id = payload.get("run")
            failure_category = None
            if isinstance(payload, dict):
                failure_category = payload.get("failure_category") or payload.get("failure_class")
            for reference in referenced:
                key = reference.lstrip("./")
                if "wing_runs" in source.parts and not key.startswith("enza_memory/"):
                    run_index = source.parts.index("wing_runs")
                    run_root = Path(*source.parts[: run_index + 2])
                    key = (run_root / key).as_posix()
                entry = joins.setdefault(key, {})
                if run_id is not None and "run_id" not in entry:
                    entry["run_id"] = run_id
                if "failures" in source.parts and failure_category is not None and "failure_category" not in entry:
                    entry["failure_category"] = failure_category
                if "trajectories" in source.parts:
                    entry.setdefault("trajectory", _relative(root, source))
                if "failures" in source.parts:
                    entry.setdefault("failure", _relative(root, source))
    return joins


def _metadata_for_image(root: Path, path: Path, joins: dict[str, dict[str, Any]]) -> dict[str, Any]:
    relative = _relative(root, path)
    candidates = (relative, path.as_posix(), path.name)
    result: dict[str, Any] = {}
    for candidate in candidates:
        result.update(joins.get(candidate.lstrip("./"), {}))
    # A WING run directory is an explicit durable source of run identity.
    parts = Path(relative).parts
    if "wing_runs" in parts and "run_id" not in result:
        index = parts.index("wing_runs")
        if index + 1 < len(parts):
            result["run_id"] = parts[index + 1]
    return {field: result.get(field) for field in METADATA_FIELDS if field in result}


def _annotation(
    root: Path,
    path: Path,
    metadata: dict[str, dict[str, Any]],
    joins: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    relative = _relative(root, path)
    result = extract_observation(path)
    result["image"] = relative
    result["vlm_status"] = "UNKNOWN"
    existing = metadata.get(relative, {})
    factual = _metadata_for_image(root, path, joins)
    if existing.get("run_id") is not None:
        factual.setdefault("run_id", existing["run_id"])
    if factual:
        result["metadata"] = factual
    return result


def build_dataset(root: Path, output_dir: Path, benchmark_cases: Path | None = None) -> dict[str, Any]:
    benchmark_cases = benchmark_cases or (root / "benchmark_cases")
    paths = collect_images(root, benchmark_cases)
    existing = _load_existing_metadata(root / "enza_memory/evidence_metadata/metadata_records.jsonl")
    joins = _load_evidence_joins(root)
    records = [_annotation(root, path, existing, joins) for path in paths]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "observations.jsonl"
    output_path.write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records))

    counts = Counter(record["vlm_status"] for record in records)
    duplicate_hashes = sum(count - 1 for count in Counter(record["sha256"] for record in records).values() if count > 1)
    missing_metadata = sum(1 for record in records if not record.get("metadata", {}).get("run_id"))
    missing_trajectory = sum(1 for record in records if not record.get("metadata", {}).get("trajectory"))
    missing_failure = sum(1 for record in records if not record.get("metadata", {}).get("failure"))
    report = "\n".join([
        "# VLM Observation Annotation Report v0.1",
        "",
        f"- Total images processed: {len(records)}",
        f"- Successful annotations: {counts.get('OBSERVED', 0)}",
        f"- UNKNOWN annotations: {counts.get('UNKNOWN', 0)}",
        f"- UNKNOWN rate: {(counts.get('UNKNOWN', 0) / len(records) if records else 0):.3f}",
        f"- Records with factual metadata: {len(records) - missing_metadata}",
        f"- Missing metadata fields (run_id unavailable): {missing_metadata}",
        f"- Missing metadata fields (trajectory unavailable): {missing_trajectory}",
        f"- Missing metadata fields (failure unavailable): {missing_failure}",
        f"- Duplicate images detected (extra records by SHA-256): {duplicate_hashes}",
        "- Unsupported cases: none; only the declared evidence roots and benchmark image references were considered.",
        "",
        "All visual fields are fail-closed UNKNOWN in this offline, model-free build. Original images were read-only.",
        "",
    ])
    (output_dir / "annotation_report.md").write_text(report)
    return {
        "total_images": len(records),
        "annotations_created": len(records),
        "unknown_count": counts.get("UNKNOWN", 0),
        "unknown_rate": counts.get("UNKNOWN", 0) / len(records) if records else 0,
        "duplicate_images": duplicate_hashes,
        "records_with_metadata": len(records) - missing_metadata,
        "output": str(output_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir or args.project_root / "enza_memory/evidence_metadata/vlm_annotations"
    print(json.dumps(build_dataset(args.project_root, output_dir), indent=2))


if __name__ == "__main__":
    main()
