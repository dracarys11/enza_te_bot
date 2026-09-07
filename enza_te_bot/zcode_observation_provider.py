"""Observation-only adapter for saved/output from a ZCode environment agent.

The adapter translates one ZCode observation payload into the repository's
versioned ``ObservationArtifact`` shape.  It has no navigation or actuation
API; ``execute`` deliberately raises to make that boundary explicit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from observation_artifact_schema import SCHEMA_VERSION, validate_observation_artifact


class ZCodeObservationError(ValueError):
    """Raised when a ZCode payload cannot be represented as evidence."""


@runtime_checkable
class ZCodeObservationSource(Protocol):
    def observe(self) -> Mapping[str, Any]:
        """Return one observation payload without performing an action."""


@dataclass(frozen=True, slots=True)
class ZCodeObservation:
    """One observation plus its non-authorizing environment metadata."""

    timestamp: str
    screenshot_reference: str
    artifact: Mapping[str, Any]
    environment_metadata: Mapping[str, Any]
    status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "screenshot_reference": self.screenshot_reference,
            "artifact": dict(self.artifact),
            "environment_metadata": dict(self.environment_metadata),
            "status": self.status,
        }

class ZCodeObservationProvider:
    """Convert a callable/object ZCode observation source; never executes."""

    def __init__(self, source: ZCodeObservationSource | Callable[[], Mapping[str, Any]]):
        if not callable(source) and not isinstance(source, ZCodeObservationSource):
            raise TypeError("source must be callable or implement observe()")
        self._source = source

    def _capture(self) -> Mapping[str, Any]:
        payload = self._source() if callable(self._source) else self._source.observe()
        if not isinstance(payload, Mapping):
            raise ZCodeObservationError("ZCode observation must be an object")
        return payload

    def observe(self) -> ZCodeObservation:
        raw = self._capture()
        nested = raw.get("artifact")
        artifact_source = nested if isinstance(nested, Mapping) else raw
        artifact = dict(artifact_source)
        provenance = artifact.get("capture_provenance")
        if not isinstance(provenance, Mapping):
            provenance = {}
        provenance = dict(provenance)
        screenshot = (provenance.get("screenshot_reference")
                      or raw.get("screenshot_reference")
                      or raw.get("screenshot"))
        if not isinstance(screenshot, str) or not screenshot.strip():
            raise ZCodeObservationError("ZCode observation requires screenshot_reference")
        provenance["source"] = str(provenance.get("source") or "ZCODE")
        provenance["screenshot_reference"] = screenshot.strip()

        timestamp = artifact.get("timestamp") or raw.get("timestamp")
        if not isinstance(timestamp, str) or not timestamp.strip():
            timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        observation_id = artifact.get("observation_id") or raw.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise ZCodeObservationError("ZCode observation requires observation_id")

        artifact.update({
            "schema_version": SCHEMA_VERSION,
            "observation_id": observation_id.strip(),
            "timestamp": timestamp.strip(),
            "capture_provenance": provenance,
            "facts": list(artifact.get("facts", [])),
            "inferences": list(artifact.get("inferences", [])),
            "unknowns": list(artifact.get("unknowns", [])),
        })
        environment = artifact.get("environment") or raw.get("environment")
        environment_metadata = dict(environment) if isinstance(environment, Mapping) else {}
        # A ZCode screenshot payload is evidence only.  It must not become a
        # runtime VERIFIED observation merely because environment metadata is
        # present; the existing artifact bridge keeps it VISIBLE_ONLY.
        status = "VISIBLE_ONLY" if environment_metadata else "UNKNOWN"
        if not environment_metadata:
            artifact["unknowns"] = list(artifact["unknowns"]) + [
                "ZCODE_ENVIRONMENT_METADATA_MISSING",
            ]
        artifact["provider_status"] = status
        validate_observation_artifact(artifact)
        return ZCodeObservation(
            timestamp=timestamp.strip(), screenshot_reference=screenshot.strip(),
            artifact=artifact, environment_metadata=environment_metadata, status=status,
        )

    def execute(self, *_: Any, **__: Any) -> None:
        raise ZCodeObservationError("ZCodeObservationProvider is observation-only")


__all__ = [
    "ZCodeObservationError", "ZCodeObservationSource", "ZCodeObservation",
    "ZCodeObservationProvider",
]
