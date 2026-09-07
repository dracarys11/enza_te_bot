"""VisionObservation contract v0.1 for enza.

Strict screenshot-to-data interface between an upstream vision adapter and
the environment agent. This module is ONLY schema + validation:

- no OCR, no image processing, no browser control, no clicking
- no semantic interpretation: the vision layer reports visual facts
  (text regions, coordinates, shapes, numbers, overlays) and nothing else

Design rules (from Phase 1E/2 audit failures):
- Text recognition and semantic interpretation are separated: forbidden
  fields (semantic_state, action, recommendation, ...) are rejected at load.
- Honesty channel: low-confidence regions must be covered by an explicit
  uncertainty entry, or the observation is rejected — unreadable means
  reported, never guessed.
- Coordinates are facts, state names are not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# Fields the vision layer must never emit. Text recognition and semantic
# interpretation must stay separated (audit: "panel appeared" != "known screen").
FORBIDDEN_FIELDS = frozenset(
    {
        "semantic_state",
        "page_name",
        "screen_name",
        "state",
        "current_state",
        "action",
        "intent",
        "recommendation",
        "recommended_action",
        "next_step",
        "next_action",
        "button_purpose",
        "game_progress",
    }
)

# A region whose recognition confidence falls below this must be covered by an
# entry in `uncertainties`, otherwise the observation is rejected rather than
# silently carrying a probably-wrong reading.
LOW_CONFIDENCE_THRESHOLD = 0.6

# 4-tuple [x, y, width, height] in viewport pixels.
BBox = tuple[int, int, int, int]


def _bbox_of(region: dict[str, Any]) -> BBox | None:
    raw = region.get("bbox")
    if (
        isinstance(raw, (list, tuple))
        and len(raw) == 4
        and all(isinstance(v, (int, float)) for v in raw)
    ):
        return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    return None


def _boxes_overlap(a: BBox, b: BBox) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _forbidden_key_errors(payload: dict[str, Any]) -> list[str]:
    # Check at every nesting level: hiding "action" inside a region dict is
    # the same contract violation as putting it at the top level.
    errors: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in FORBIDDEN_FIELDS:
                    errors.append(f"forbidden semantic field '{key}' at {path}")
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    walk(payload, "$")
    return errors


@dataclass(frozen=True)
class VisionObservation:
    """Validated visual-facts-only output of the vision adapter."""

    observation_id: str
    capture: dict[str, Any]
    viewport: dict[str, int]
    text_regions: list[dict[str, Any]] = field(default_factory=list)
    interaction_candidates: list[dict[str, Any]] = field(default_factory=list)
    numeric_regions: list[dict[str, Any]] = field(default_factory=list)
    overlay_regions: list[dict[str, Any]] = field(default_factory=list)
    uncertainties: list[dict[str, Any]] = field(default_factory=list)
    visual_changes: list[dict[str, Any]] | None = None  # optional

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "VisionObservation":
        errors = cls.validate(payload)
        if errors:
            raise VisionContractError(errors)
        return cls(
            observation_id=payload["observation_id"],
            capture=payload["capture"],
            viewport=payload["viewport"],
            text_regions=payload.get("text_regions", []),
            interaction_candidates=payload.get("interaction_candidates", []),
            numeric_regions=payload.get("numeric_regions", []),
            overlay_regions=payload.get("overlay_regions", []),
            uncertainties=payload.get("uncertainties", []),
            visual_changes=payload.get("visual_changes"),
        )

    @staticmethod
    def validate(payload: Any) -> list[str]:
        """Return a list of contract violations ([] == valid)."""
        if not isinstance(payload, dict):
            return ["payload must be a JSON object"]

        errors = _forbidden_key_errors(payload)

        if not isinstance(payload.get("observation_id"), str) or not payload.get(
            "observation_id"
        ):
            errors.append("observation_id must be a non-empty string")

        capture = payload.get("capture")
        if not isinstance(capture, dict):
            errors.append("capture must be an object with timestamp/frame_id/screenshot_digest")
        else:
            for key in ("timestamp", "frame_id", "screenshot_digest"):
                if not isinstance(capture.get(key), str) or not capture.get(key):
                    errors.append(f"capture.{key} must be a non-empty string")

        viewport = payload.get("viewport")
        if not isinstance(viewport, dict) or not (
            isinstance(viewport.get("width"), int) and isinstance(viewport.get("height"), int)
        ):
            errors.append("viewport.width and viewport.height are required integers")

        # --- text regions: id, text, bbox, confidence ---
        for i, region in enumerate(payload.get("text_regions", []) or []):
            if not isinstance(region, dict):
                errors.append(f"text_regions[{i}] must be an object")
                continue
            for key in ("id", "text"):
                if not isinstance(region.get(key), str) or not region.get(key):
                    errors.append(f"text_regions[{i}].{key} must be a non-empty string")
            if _bbox_of(region) is None:
                errors.append(f"text_regions[{i}].bbox must be [x,y,w,h] numbers")
            conf = region.get("confidence")
            if not isinstance(conf, (int, float)) or not 0.0 <= float(conf) <= 1.0:
                errors.append(f"text_regions[{i}].confidence must be within [0,1]")

        # --- numeric regions: raw_text, value, max_value, bbox, confidence ---
        for i, region in enumerate(payload.get("numeric_regions", []) or []):
            if not isinstance(region, dict):
                errors.append(f"numeric_regions[{i}] must be an object")
                continue
            for key in ("id", "raw_text"):
                if not isinstance(region.get(key), str) or not region.get(key):
                    errors.append(f"numeric_regions[{i}].{key} must be a non-empty string")
            for key in ("value", "max_value"):
                if not isinstance(region.get(key), (int, float)):
                    errors.append(f"numeric_regions[{i}].{key} must be a number")
            if _bbox_of(region) is None:
                errors.append(f"numeric_regions[{i}].bbox must be [x,y,w,h] numbers")
            conf = region.get("confidence")
            if not isinstance(conf, (int, float)) or not 0.0 <= float(conf) <= 1.0:
                errors.append(f"numeric_regions[{i}].confidence must be within [0,1]")

        # --- interaction candidates: bbox, appearance, linked_text_ids, confidence ---
        for i, element in enumerate(payload.get("interaction_candidates", []) or []):
            if not isinstance(element, dict):
                errors.append(f"interaction_candidates[{i}] must be an object")
                continue
            if _bbox_of(element) is None:
                errors.append(f"interaction_candidates[{i}].bbox must be [x,y,w,h] numbers")
            appearance = element.get("appearance")
            if not isinstance(appearance, dict) or not (
                isinstance(appearance.get("shape"), str) and appearance.get("shape")
            ):
                errors.append(
                    f"interaction_candidates[{i}].appearance.shape must be a non-empty string"
                )
            if not isinstance(element.get("linked_text_ids", []), list):
                errors.append(f"interaction_candidates[{i}].linked_text_ids must be a list")
            conf = element.get("interaction_confidence")
            if not isinstance(conf, (int, float)) or not 0.0 <= float(conf) <= 1.0:
                errors.append(
                    f"interaction_candidates[{i}].interaction_confidence must be within [0,1]"
                )

        # --- overlays: bbox + blocked_element_ids ---
        for i, overlay in enumerate(payload.get("overlay_regions", []) or []):
            if not isinstance(overlay, dict):
                errors.append(f"overlay_regions[{i}] must be an object")
                continue
            if _bbox_of(overlay) is None:
                errors.append(f"overlay_regions[{i}].bbox must be [x,y,w,h] numbers")
            if not isinstance(overlay.get("blocked_element_ids", []), list):
                errors.append(f"overlay_regions[{i}].blocked_element_ids must be a list")
            if not isinstance(overlay.get("linked_text_ids", []), list):
                errors.append(f"overlay_regions[{i}].linked_text_ids must be a list")

        # --- uncertainties: honesty channel ---
        uncertainties = payload.get("uncertainties", [])
        if not isinstance(uncertainties, list):
            errors.append("uncertainties must be a list")
            uncertainties = []
        for i, uncertainty in enumerate(uncertainties):
            if not isinstance(uncertainty, dict) or _bbox_of(uncertainty) is None:
                errors.append(f"uncertainties[{i}] must be an object with a [x,y,w,h] bbox")
            elif not isinstance(uncertainty.get("reason"), str) or not uncertainty.get("reason"):
                errors.append(f"uncertainties[{i}].reason must be a non-empty string")

        # Low-confidence regions must be covered by an uncertainty entry:
        # an unreadable reading is only acceptable when it is reported as such.
        uncertainty_boxes = [_bbox_of(u) for u in uncertainties if isinstance(u, dict)]
        uncertainty_boxes = [b for b in uncertainty_boxes if b is not None]

        def low_conf_uncovered(kind: str, regions: Iterable[dict[str, Any]]) -> None:
            for region in regions:
                if not isinstance(region, dict):
                    continue
                conf = region.get("confidence", region.get("interaction_confidence"))
                if isinstance(conf, (int, float)) and float(conf) < LOW_CONFIDENCE_THRESHOLD:
                    bbox = _bbox_of(region)
                    if bbox is None or not any(
                        _boxes_overlap(bbox, ubox) for ubox in uncertainty_boxes
                    ):
                        errors.append(
                            f"{kind} '{region.get('id', '?')}' has confidence {conf} < "
                            f"{LOW_CONFIDENCE_THRESHOLD} but no uncertainty entry covers its bbox"
                        )

        low_conf_uncovered("text_region", payload.get("text_regions", []) or [])
        low_conf_uncovered("numeric_region", payload.get("numeric_regions", []) or [])
        low_conf_uncovered("interaction_candidate", payload.get("interaction_candidates", []) or [])

        changes = payload.get("visual_changes")
        if changes is not None and not isinstance(changes, list):
            errors.append("visual_changes must be a list when present")

        return errors


class VisionContractError(ValueError):
    """Raised when a payload violates the VisionObservation contract."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("VisionObservation contract violations:\n" + "\n".join(f"- {e}" for e in errors))
