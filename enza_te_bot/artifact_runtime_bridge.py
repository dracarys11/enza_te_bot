"""Read-only bridge from governance observation artifacts to runtime models.

Artifact data is evidence, not authorization.  This loader never creates a
``HomeProvenance`` or any ActionGate permission and is intentionally absent
from the production execution path.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping

from perception_models import Observation, UIElement
from observation_artifact_schema import validate_observation_artifact


class ArtifactValidationError(ValueError):
    """Raised when a saved observation cannot be safely converted."""


@dataclass(frozen=True)
class ArtifactProvenance:
    """Non-authorizing source metadata retained for audit/replay only."""

    artifact_path: str
    source: str
    screenshot_reference: str
    metadata: Mapping[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "source": self.source,
            "screenshot_reference": self.screenshot_reference,
            "metadata": dict(self.metadata),
            "authorizes_execution": False,
        }


def _viewport(data: Mapping[str, Any]) -> tuple[float, float]:
    value = data.get("viewport")
    if isinstance(value, Mapping):
        try:
            width, height = float(value["width"]), float(value["height"])
            if width > 0 and height > 0:
                return width, height
        except (KeyError, TypeError, ValueError):
            pass
    environment = data.get("environment")
    if isinstance(environment, Mapping):
        viewport = environment.get("viewport")
        if isinstance(viewport, Mapping):
            try:
                width, height = float(viewport["width"]), float(viewport["height"])
                if width > 0 and height > 0:
                    return width, height
            except (KeyError, TypeError, ValueError):
                pass
    # Some saved observation artifacts intentionally omit viewport metadata.
    # A referenced screenshot is still an authoritative geometry source for
    # coordinate normalization; it does not promote the observation to
    # verified runtime evidence.
    reference = None
    provenance = data.get("capture_provenance")
    if isinstance(provenance, Mapping):
        reference = provenance.get("screenshot_reference") or provenance.get("screenshot")
    if isinstance(reference, str) and reference.strip():
        candidates = [
            Path(reference),
            Path(__file__).resolve().parent / reference,
            Path(__file__).resolve().parent.parent / reference,
        ]
        for candidate in candidates:
            if candidate.exists():
                try:
                    from PIL import Image
                    with Image.open(candidate) as image:
                        width, height = image.size
                    if width > 0 and height > 0:
                        return float(width), float(height)
                except (OSError, ImportError):
                    break
    raise ArtifactValidationError("observation artifact has no valid viewport")


def _state(data: Mapping[str, Any]) -> tuple[str, str, float | None]:
    raw = data.get("state", data.get("page_state"))
    if not isinstance(raw, Mapping):
        # Older observation artifacts recorded the page identity only as
        # screenshot-derived prose.  Preserve that distinction explicitly;
        # this fallback is still INFERENCE, never runtime verification.
        text = " ".join(str(item) for key in ("inferences", "facts")
                         for item in data.get(key, ()) if isinstance(item, str))
        visible = data.get("visible_elements", ())
        if any(isinstance(item, Mapping) and "プロデュース選択" in str(item.get("name", ""))
               for item in visible):
            return "PRODUCE_SELECTION", "INFERENCE", 0.95
        if "プロデュース選択" in text:
            return "PRODUCE_SELECTION", "INFERENCE", None
        raise ArtifactValidationError("observation artifact has no state evidence")
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip():
        raise ArtifactValidationError("state evidence has no label")
    # Artifacts often include a Japanese display label in parentheses.  Keep
    # the stable machine-facing prefix as the runtime business-state label.
    label = label.split("(", 1)[0].strip()
    classification = str(raw.get("classification", "UNKNOWN")).upper()
    confidence = raw.get("confidence")
    try:
        confidence = float(confidence) if confidence is not None else None
    except (TypeError, ValueError):
        confidence = None
    return label, classification, confidence


_BOUND_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _element_bbox(raw: Any, width: float, height: float) -> tuple[float, float, float, float] | None:
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        values = [float(item) for item in raw]
        if all(0 <= item <= 1 for item in values) and values[0] < values[2] and values[1] < values[3]:
            return tuple(values)  # already normalized [left, top, right, bottom]
    if not isinstance(raw, str):
        return None
    values = [float(item) for item in _BOUND_RE.findall(raw)]
    if len(values) != 4:
        return None
    left, top, box_width, box_height = values
    if box_width <= 0 or box_height <= 0 or left < 0 or top < 0:
        return None
    right, bottom = left + box_width, top + box_height
    if right > width or bottom > height:
        return None
    return left / width, top / height, right / width, bottom / height


def _provenance(data: Mapping[str, Any], artifact_path: Path) -> ArtifactProvenance:
    raw = data.get("capture_provenance")
    if not isinstance(raw, Mapping):
        raise ArtifactValidationError("missing artifact provenance/source metadata")
    screenshot = raw.get("screenshot_reference") or raw.get("screenshot")
    source = raw.get("source")
    if not isinstance(source, str) or not source.strip():
        raise ArtifactValidationError("missing artifact source metadata")
    if not isinstance(screenshot, str) or not screenshot.strip():
        raise ArtifactValidationError("missing screenshot reference")
    return ArtifactProvenance(str(artifact_path), source.strip(), screenshot.strip(), dict(raw))


def load_observation_artifact(path: str | Path) -> Observation:
    """Load one saved artifact as an untrusted runtime ``Observation``."""
    artifact_path = Path(path)
    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArtifactValidationError(f"cannot load observation artifact: {error}") from error
    if not isinstance(data, Mapping):
        raise ArtifactValidationError("observation artifact root must be an object")
    try:
        validate_observation_artifact(data)
    except ValueError as error:
        raise ArtifactValidationError(str(error)) from error
    observation_id = data.get("observation_id")
    timestamp = data.get("timestamp")
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise ArtifactValidationError("observation artifact has no observation_id")
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise ArtifactValidationError("observation artifact has no timestamp")
    provenance = _provenance(data, artifact_path)
    width, height = _viewport(data)
    label, classification, confidence = _state(data)

    elements: list[UIElement] = []
    for index, raw_element in enumerate(data.get("visible_elements", ())):
        if not isinstance(raw_element, Mapping):
            continue
        bbox = _element_bbox(raw_element.get("bounds", raw_element.get("approx_bounds")), width, height)
        if bbox is None:
            # Preserve malformed visual evidence in frame metadata rather than
            # inventing a clickable geometry.
            continue
        # Schema validation above guarantees these fields; do not provide
        # permissive defaults that could turn incomplete evidence into a
        # seemingly usable element.
        source = str(raw_element["source"]).upper()
        verification = str(raw_element["verification_level"]).upper()
        visual_evidence = raw_element["visual_evidence"]
        geometry_classification = str(raw_element["geometry_classification"]).upper()
        elements.append(UIElement(
            element_id=f"artifact:{observation_id}:{index}",
            bbox=bbox,
            role=str(raw_element.get("role", "unknown")),
            semantic=str(raw_element["name"]) if raw_element.get("name") is not None else None,
            confidence=float(raw_element["confidence"]),
            detector=f"artifact:{source.lower()}",
            metadata={
                "source": source,
                "verification_level": verification,
                "visual_evidence": str(visual_evidence),
                "geometry_classification": geometry_classification,
                "artifact_classification": classification,
            },
        ))

    # Artifact classifications are never promoted to runtime VERIFIED.  The
    # explicit status is retained so callers can require a fresh collector
    # observation before any authorization decision.
    observation_status = "VISIBLE_ONLY" if classification in {"INFERENCE", "PROVISIONAL", "UNKNOWN"} else "ARTIFACT_UNVERIFIED"
    # Preserve uncertainty detail verbatim in the runtime observation.  These
    # fields are evidence metadata, never authorization.
    unknowns = data.get("unknowns", [])
    blocking_unknowns = data.get("blocking_unknowns", [])
    uncertainty_reason = data.get("uncertainty_reason")
    business_state = {
        "state": label,
        "classification": classification,
        "confidence": confidence,
        "evidence_source": "artifact",
        "unknowns": unknowns,
        "blocking_unknowns": blocking_unknowns,
        "uncertainty_reason": uncertainty_reason,
    }
    frame_metadata = {
        "artifact_provenance": provenance.as_dict(),
        "artifact_classification": classification,
        "artifact_path": str(artifact_path),
        "authorization_provenance": False,
        "unknowns": unknowns,
        "blocking_unknowns": blocking_unknowns,
        "uncertainty_reason": uncertainty_reason,
    }
    environment = data.get("environment")
    if isinstance(environment, Mapping):
        frame_metadata["environment"] = dict(environment)
    return Observation(
        observation_id=observation_id,
        captured_at=timestamp,
        game_window={"left": 0, "top": 0, "width": width, "height": height,
                     "coordinate_space": "artifact_viewport"},
        business_state=business_state,
        screenshot_path=provenance.screenshot_reference,
        elements=tuple(elements),
        frame_metadata=frame_metadata,
        candidate_actions=tuple(str(item) for item in data.get("candidate_actions", ()) if isinstance(item, str)),
        confidence=confidence,
        observation_status=observation_status,
    )


__all__ = ["ArtifactValidationError", "ArtifactProvenance", "load_observation_artifact"]
