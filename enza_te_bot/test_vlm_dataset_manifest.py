from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "enza_memory/evidence_metadata/vlm_annotations/observations.jsonl"
FULL_INPUTS = ROOT / "enza_memory/benchmark/vlm_runs/v0.1/inputs_full.jsonl"


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_full_manifest_count_matches_source() -> None:
    source = _records(SOURCE)
    full = _records(FULL_INPUTS)
    assert len(source) == 883
    assert len(full) == len(source)


def test_full_manifest_schema_and_paths() -> None:
    records = _records(FULL_INPUTS)
    assert records
    for record in records:
        assert set(record) == {"image", "sha256"}
        assert isinstance(record["image"], str) and record["image"]
        assert isinstance(record["sha256"], str) and len(record["sha256"]) == 64
        image = ROOT / record["image"]
        assert image.is_file()
        assert hashlib.sha256(image.read_bytes()).hexdigest() == record["sha256"]


def test_full_manifest_preserves_source_order_and_images() -> None:
    source = _records(SOURCE)
    full = _records(FULL_INPUTS)
    assert [record["image"] for record in full] == [record["image"] for record in source]
    assert [record["sha256"] for record in full] == [record["sha256"] for record in source]
