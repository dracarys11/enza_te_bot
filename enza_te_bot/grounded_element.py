"""GroundedElement schema v0.1: raw perception -> ActionBoundary intermediate layer.

A GroundedElement is a visual region from the fused VisionObservation, bound to
its text evidence, geometry source, confidence, and provenance. It expresses
WHERE grounded visual+text facts exist and nothing else:

- no action, no intent, no strategy, no semantic state (forbidden fields are
  rejected at build time, same policy as VisionObservation)
- no authorization: producing a GroundedElement never permits an action
- text evidence with no matching text region stays UNKNOWN, never guessed
"""
from __future__ import annotations

import json
from numbers import Real
from pathlib import Path
from typing import Any, Mapping, Sequence

from vision_observation_schema import FORBIDDEN_FIELDS

# Geometry emitted by this layer is always in the original screenshot viewport
# coordinate space. Phase 1 verified PaddleOCR bbox coordinate identity; until
# paddleocr_baseline.py reruns with preprocessing disabled, geometry provenance
# is recorded per element so downstream consumers can audit it.
GEOMETRY_SPACE = "original_viewport"

# Evidence statuses for the text side of a grounded element.
TEXT_EVIDENCE_MATCHED = "MATCHED"
TEXT_EVIDENCE_UNKNOWN = "UNKNOWN"

VALID_SOURCES = frozenset({"paddle", "gemini", "agy", "tesseract"})


class GroundedElementError(ValueError):
    """Raised when a grounded element would overclaim or is malformed."""


def _reject_forbidden(payload: Mapping[str, Any], path: str) -> None:
    for key, value in payload.items():
        if key in FORBIDDEN_FIELDS:
            raise GroundedElementError(f"forbidden semantic field '{key}' at {path}")
        if isinstance(value, Mapping):
            _reject_forbidden(value, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, Mapping):
                    _reject_forbidden(item, f"{path}[{index}]")


def _viewport_bbox(value: object, field: str) -> tuple[float, float, float, float]:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or not all(isinstance(v, Real) for v in value)
    ):
        raise GroundedElementError(f"{field} must be a [x, y, width, height] bbox")
    x, y, width, height = (float(v) for v in value)
    if width <= 0 or height <= 0:
        raise GroundedElementError(f"{field} must have positive width and height")
    return x, y, width, height


def _source_of(region: Mapping[str, Any]) -> str:
    source = region.get("source", "gemini")
    if source not in VALID_SOURCES:
        raise GroundedElementError(f"unknown region source '{source}'")
    return str(source)


def build_text_evidence(text_region: Mapping[str, Any]) -> dict[str, Any]:
    """Text-evidence record bound to one OCR text region (no interpretation)."""
    text = text_region.get("text")
    region_id = text_region.get("id")
    confidence = text_region.get("confidence")
    if not isinstance(text, str) or not text.strip():
        raise GroundedElementError("text evidence requires visible text")
    if not isinstance(region_id, str) or not region_id.strip():
        raise GroundedElementError("text evidence requires a text region id")
    if not isinstance(confidence, Real) or not 0.0 <= float(confidence) <= 1.0:
        raise GroundedElementError("text evidence requires a confidence in [0, 1]")
    return {
        "text_region_id": str(region_id),
        "text": text,
        "confidence": float(confidence),
        "source": _source_of(text_region),
    }


def build_grounded_element(interaction: Mapping[str, Any],
                           text_regions_by_id: Mapping[str, Mapping[str, Any]],
                           *, observation_id: str) -> dict[str, Any]:
    """Fuse one interaction candidate with its linked text evidence."""
    _reject_forbidden(interaction, "interaction_candidate")
    element_id = interaction.get("id")
    if not isinstance(element_id, str) or not element_id.strip():
        raise GroundedElementError("interaction candidate requires an id")
    bbox = _viewport_bbox(interaction.get("bbox"), "interaction bbox")
    visual_confidence = interaction.get(
        "interaction_confidence", interaction.get("confidence"))
    if not isinstance(visual_confidence, Real) or not 0.0 <= float(visual_confidence) <= 1.0:
        raise GroundedElementError("interaction candidate requires a confidence in [0, 1]")

    evidence: list[dict[str, Any]] = []
    for text_id in interaction.get("linked_text_ids", []):
        region = text_regions_by_id.get(text_id)
        if region is None:
            # Linked id that fusion could not ground stays UNKNOWN, not guessed.
            continue
        evidence.append(build_text_evidence(region))

    status = TEXT_EVIDENCE_MATCHED if evidence else TEXT_EVIDENCE_UNKNOWN
    grounding_confidence = (
        float(visual_confidence) if status == TEXT_EVIDENCE_UNKNOWN
        else min(float(visual_confidence), min(item["confidence"] for item in evidence))
    )
    return {
        "element_id": str(element_id),
        "source_observation_id": str(observation_id),
        "bbox": [bbox[0], bbox[1], bbox[2], bbox[3]],
        "geometry_space": GEOMETRY_SPACE,
        "text_evidence_status": status,
        "text_evidence": evidence,
        "visual_confidence": float(visual_confidence),
        "grounding_confidence": grounding_confidence,
        "provenance": {
            "visual": _source_of(interaction),
            "text": evidence[0]["source"] if evidence else None,
        },
    }


def build_grounded_elements(fused_observation: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Generate all GroundedElements from a fused VisionObservation payload."""
    observation_id = fused_observation.get("observation_id")
    if not isinstance(observation_id, str) or not observation_id.strip():
        raise GroundedElementError("fused observation requires an observation_id")
    text_regions_by_id = {
        str(region.get("id")): region
        for region in fused_observation.get("text_regions", [])
        if isinstance(region, Mapping) and region.get("id")
    }
    elements = [
        build_grounded_element(
            interaction, text_regions_by_id, observation_id=observation_id)
        for interaction in fused_observation.get("interaction_candidates", [])
        if isinstance(interaction, Mapping)
    ]
    return elements


def elements_with_text(elements: Sequence[Mapping[str, Any]], text: str) -> list[dict[str, Any]]:
    """Offline lookup helper: elements whose text evidence contains `text`."""
    return [
        element for element in elements
        if any(item["text"] == text for item in element.get("text_evidence", []))
    ]


def build_from_file(path: str | Path) -> list[dict[str, Any]]:
    """Build grounded elements from a fused_observation.json artifact."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return build_grounded_elements(payload)


__all__ = [
    "GEOMETRY_SPACE", "TEXT_EVIDENCE_MATCHED", "TEXT_EVIDENCE_UNKNOWN",
    "GroundedElementError", "build_text_evidence", "build_grounded_element",
    "build_grounded_elements", "elements_with_text", "build_from_file",
]
