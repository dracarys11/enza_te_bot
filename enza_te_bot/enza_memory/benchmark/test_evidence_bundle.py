import hashlib
import json
from pathlib import Path

from evidence_bundle import validate_evidence_bundle


ARTIFACT_PATH = "enza_memory/observations/OBS_012.json"


def _write_manifest(root: Path, content: bytes) -> Path:
    manifest_path = root / "enza_memory/benchmark/evidence/v0.3/manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps({
            "schema_version": 1,
            "benchmark_version": "v0.3",
            "ownership_model": "immutable_external_evidence_bundle",
            "artifact_root": "repository_root",
            "artifacts": [{
                "artifact_path": ARTIFACT_PATH,
                "sha256": hashlib.sha256(content).hexdigest(),
                "source": "test fixture",
                "revision": "test revision",
            }],
        }),
        encoding="utf-8",
    )
    return manifest_path


def test_clean_checkout_validation_detects_missing_evidence(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path, b"frozen evidence")
    assert validate_evidence_bundle(tmp_path, manifest_path) == [
        f"missing evidence artifact: {ARTIFACT_PATH}"
    ]


def test_clean_checkout_validation_detects_hash_mismatch(tmp_path: Path):
    manifest_path = _write_manifest(tmp_path, b"frozen evidence")
    artifact = tmp_path / ARTIFACT_PATH
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"modified evidence")
    errors = validate_evidence_bundle(tmp_path, manifest_path)
    assert len(errors) == 1
    assert errors[0].startswith(f"evidence hash mismatch: {ARTIFACT_PATH}:")


def test_clean_checkout_validation_accepts_frozen_evidence(tmp_path: Path):
    content = b"frozen evidence"
    manifest_path = _write_manifest(tmp_path, content)
    artifact = tmp_path / ARTIFACT_PATH
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(content)
    assert validate_evidence_bundle(tmp_path, manifest_path) == []
