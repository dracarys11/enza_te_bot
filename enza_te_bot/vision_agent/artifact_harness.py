"""Offline, observation-first persistence for Vision provider artifacts."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

from vision_observation_schema import VisionContractError, VisionObservation


_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PROVIDER_DIRECTORIES = {
    "agy": "agy",
    "gemini": "gemini",
    "paddle": "paddle",
    "zcode": "zcode",
}
_GEMINI_SKILL_DIRECTORIES = {
    "gemini_vision_v1": "v1",
    "gemini_vision_v1_1": "v1_1",
    "gemini_vision_v2": "v2",
}


class VisionArtifactRoutingError(ValueError):
    """Raised when an artifact cannot be safely routed or persisted."""


def _safe_segment(value: str, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_SEGMENT.fullmatch(value):
        raise VisionArtifactRoutingError(f"{field} is not a safe path segment: {value!r}")
    return value


def _provider_directory(provider: str) -> str:
    key = _safe_segment(provider, "provider").casefold()
    try:
        return _PROVIDER_DIRECTORIES[key]
    except KeyError as error:
        raise VisionArtifactRoutingError(f"unsupported provider: {provider!r}") from error


def _skill_directory(provider_directory: str, skill_version: str) -> str | None:
    _safe_segment(skill_version, "skill_version")
    if provider_directory == "agy":
        if skill_version not in _GEMINI_SKILL_DIRECTORIES:
            raise VisionArtifactRoutingError(
                f"unsupported AGY vision skill version: {skill_version!r}"
            )
        return skill_version
    if provider_directory != "gemini":
        return None
    try:
        return _GEMINI_SKILL_DIRECTORIES[skill_version]
    except KeyError as error:
        raise VisionArtifactRoutingError(
            f"unsupported Gemini skill version: {skill_version!r}"
        ) from error


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    """Atomically publish a complete JSON file without replacing a peer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    except FileExistsError as error:
        raise VisionArtifactRoutingError(f"artifact already exists: {path}") from error
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class VisionArtifactHarness:
    """Persist extraction output below its observation case directory."""

    test_data_root: Path
    suite: str = "ob003"

    def case_directory(self, case_id: str) -> Path:
        return self.test_data_root / _safe_segment(self.suite, "suite") / _safe_segment(
            case_id, "case_id"
        )

    def output_path(self, case_id: str, provider: str, skill_version: str) -> Path:
        provider_directory = _provider_directory(provider)
        destination = self.case_directory(case_id) / "providers" / provider_directory
        skill_directory = _skill_directory(provider_directory, skill_version)
        if skill_directory is not None:
            destination /= skill_directory
        return destination / "vision_output.json"

    def persist(
        self,
        observation: Mapping[str, Any],
        *,
        case_id: str,
        provider: str,
        model: str,
        skill_version: str,
        created_at: str,
        provenance: Mapping[str, str] | None = None,
    ) -> Path:
        """Write one new VisionObservation and update its case manifest."""
        payload = deepcopy(dict(observation))
        errors = VisionObservation.validate(payload)
        if errors:
            raise VisionContractError(errors)
        return self._persist_payload(
            payload,
            case_id=case_id,
            provider=provider,
            model=model,
            skill_version=skill_version,
            created_at=created_at,
            provenance=provenance,
        )

    def persist_raw_sensor(
        self,
        sensor_payload: Mapping[str, Any],
        *,
        case_id: str,
        provider: str,
        model: str,
        skill_version: str,
        created_at: str,
        provenance: Mapping[str, str] | None = None,
    ) -> Path:
        """Persist a non-VisionObservation sensor artifact via the same route."""
        payload = deepcopy(dict(sensor_payload))
        if not isinstance(payload.get("text_regions"), list):
            raise VisionArtifactRoutingError("raw sensor text_regions must be a list")
        return self._persist_payload(
            payload,
            case_id=case_id,
            provider=provider,
            model=model,
            skill_version=skill_version,
            created_at=created_at,
            provenance=provenance,
        )

    def _persist_payload(
        self,
        payload: dict[str, Any],
        *,
        case_id: str,
        provider: str,
        model: str,
        skill_version: str,
        created_at: str,
        provenance: Mapping[str, str] | None,
    ) -> Path:
        """Write one new provider artifact without replacing an existing peer."""
        for value, field in (
            (model, "model"),
            (created_at, "created_at"),
        ):
            if not isinstance(value, str) or not value.strip():
                raise VisionArtifactRoutingError(f"{field} must be a non-empty string")

        case_directory = self.case_directory(case_id)
        source = case_directory / "source_screenshot.png"
        if not source.is_file():
            raise VisionArtifactRoutingError(f"case source screenshot is missing: {source}")
        screenshot_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()

        destination = self.output_path(case_id, provider, skill_version)
        if destination.exists():
            raise VisionArtifactRoutingError(f"artifact already exists: {destination}")

        provider_directory = _provider_directory(provider)
        canonical_provider = next(
            name for name in ("AGY", "Gemini", "Paddle", "ZCode")
            if name.casefold() == provider_directory
        )
        payload["metadata"] = {
            "provider": canonical_provider,
            "model": model,
            "skill_version": skill_version,
            "case_id": case_id,
            "source_image": "source_screenshot.png",
            "screenshot_sha256": screenshot_sha256,
            "created_at": created_at,
        }

        manifest_path = case_directory / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("case_id") != case_id:
                raise VisionArtifactRoutingError("manifest case_id does not match destination case")
            if manifest.get("source") != {
                "file": "source_screenshot.png",
                "sha256": screenshot_sha256,
            }:
                raise VisionArtifactRoutingError("manifest source does not match local screenshot")
        else:
            manifest = {
                "case_id": case_id,
                "source": {
                    "file": "source_screenshot.png",
                    "sha256": screenshot_sha256,
                },
                "providers": [],
                "unresolved_artifacts": [],
            }

        relative_artifact = destination.relative_to(case_directory).as_posix()
        entries = manifest.setdefault("providers", [])
        if any(entry.get("artifact") == relative_artifact for entry in entries):
            raise VisionArtifactRoutingError(
                f"manifest already contains artifact: {relative_artifact}"
            )
        _write_json_exclusive(destination, payload)
        artifact_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
        entry: dict[str, Any] = {
            "name": canonical_provider,
            "artifact": relative_artifact,
            "artifact_sha256": artifact_sha256,
            "provider": canonical_provider,
            "model": model,
            "skill_version": skill_version,
            "screenshot_sha256": screenshot_sha256,
        }
        if provenance:
            entry["provenance"] = dict(provenance)
        entries.append(entry)
        try:
            _write_json_atomic(manifest_path, manifest)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return destination


__all__ = ["VisionArtifactHarness", "VisionArtifactRoutingError"]
