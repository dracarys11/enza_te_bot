"""Offline integrity validation for versioned benchmark evidence bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read evidence manifest: {manifest_path}: {error}") from error
    if not isinstance(manifest, dict) or not isinstance(manifest.get("artifacts"), list):
        raise ValueError("evidence manifest must contain an artifacts array")
    return manifest


def validate_evidence_bundle(project_root: Path, manifest_path: Path) -> list[str]:
    """Return deterministic missing-artifact and digest errors without mutation."""
    manifest = _load_manifest(manifest_path)
    errors: list[str] = []
    for index, entry in enumerate(manifest["artifacts"]):
        if not isinstance(entry, dict):
            errors.append(f"artifacts[{index}] must be an object")
            continue
        relative_path = entry.get("artifact_path")
        expected_sha256 = entry.get("sha256")
        if not isinstance(relative_path, str) or not relative_path:
            errors.append(f"artifacts[{index}].artifact_path must be a non-empty string")
            continue
        artifact_path = project_root / relative_path
        if not artifact_path.is_file():
            errors.append(f"missing evidence artifact: {relative_path}")
            continue
        actual_sha256 = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            errors.append(
                f"evidence hash mismatch: {relative_path}: "
                f"expected {expected_sha256}, got {actual_sha256}"
            )
    return errors
