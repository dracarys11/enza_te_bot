"""Versioned, non-authorizing schema checks for saved observations."""
from __future__ import annotations

from typing import Any, Mapping


SCHEMA_VERSION = 1
REQUIRED_ROOT_FIELDS = frozenset({
    "schema_version", "observation_id", "capture_provenance",
    "facts", "inferences", "unknowns",
})
REQUIRED_ELEMENT_FIELDS = frozenset({
    "source", "verification_level", "confidence", "visual_evidence",
    "geometry_classification",
})


class ObservationArtifactSchemaError(ValueError):
    """Raised when an artifact violates the versioned evidence contract."""


def validate_observation_artifact(data: Mapping[str, Any]) -> None:
    """Validate required evidence fields without promoting any evidence."""
    missing = sorted(REQUIRED_ROOT_FIELDS - set(data))
    if missing:
        raise ObservationArtifactSchemaError(f"missing required artifact fields: {', '.join(missing)}")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ObservationArtifactSchemaError(f"unsupported schema_version: {data.get('schema_version')!r}")
    if not isinstance(data.get("observation_id"), str) or not data["observation_id"].strip():
        raise ObservationArtifactSchemaError("observation_id must be a non-empty string")
    capture = data["capture_provenance"]
    if not isinstance(capture, Mapping):
        raise ObservationArtifactSchemaError("capture_provenance must be an object")
    if not isinstance(capture.get("source"), str) or not capture["source"].strip():
        raise ObservationArtifactSchemaError("capture_provenance.source is required")
    if not isinstance(capture.get("screenshot_reference"), str) or not capture["screenshot_reference"].strip():
        raise ObservationArtifactSchemaError("capture_provenance.screenshot_reference is required")
    for field in ("facts", "inferences", "unknowns"):
        if not isinstance(data[field], list):
            raise ObservationArtifactSchemaError(f"{field} must be a list")
    facts = {str(item) for item in data["facts"]}
    promoted = sorted(facts.intersection(str(item) for item in data["inferences"]))
    if promoted:
        raise ObservationArtifactSchemaError("inference promoted to fact")

    elements = data.get("visible_elements", [])
    if not isinstance(elements, list):
        raise ObservationArtifactSchemaError("visible_elements must be a list")
    for index, element in enumerate(elements):
        if not isinstance(element, Mapping):
            raise ObservationArtifactSchemaError(f"visible_elements[{index}] must be an object")
        missing_element = sorted(REQUIRED_ELEMENT_FIELDS - set(element))
        if missing_element:
            raise ObservationArtifactSchemaError(
                f"visible_elements[{index}] missing: {', '.join(missing_element)}")
        source = str(element["source"]).upper()
        verification = str(element["verification_level"]).upper()
        geometry = str(element["geometry_classification"]).upper()
        if not str(element["visual_evidence"]).strip():
            raise ObservationArtifactSchemaError(f"visible_elements[{index}].visual_evidence is required")
        try:
            confidence = float(element["confidence"])
        except (TypeError, ValueError) as error:
            raise ObservationArtifactSchemaError(f"visible_elements[{index}].confidence is invalid") from error
        if not 0 <= confidence <= 1:
            raise ObservationArtifactSchemaError(f"visible_elements[{index}].confidence is outside [0, 1]")
        if source == "SCREENSHOT" and verification == "VERIFIED":
            raise ObservationArtifactSchemaError("screenshot evidence cannot be VERIFIED")
        if source == "SCREENSHOT" and geometry in {"CLICKABLE", "ACTION_TARGET"}:
            raise ObservationArtifactSchemaError("screenshot evidence cannot be promoted to clickable")


__all__ = ["SCHEMA_VERSION", "ObservationArtifactSchemaError", "validate_observation_artifact"]
