"""Deterministic action-target resolution with fail-closed ambiguity handling."""
from __future__ import annotations

from dataclasses import dataclass

from perception_models import ActionTarget, FailureReason, Observation, UIElement


@dataclass(frozen=True)
class TargetResolution:
    element: UIElement | None = None
    bbox: tuple[float, float, float, float] | None = None
    source: str | None = None
    failure: FailureReason | None = None
    candidates: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.bbox is not None and self.failure is None


def resolve_action_target(observation: Observation, target: ActionTarget) -> TargetResolution:
    """Resolve strong runtime evidence first; fallback is opt-in only."""
    if target.runtime_element_id:
        element = observation.element(target.runtime_element_id)
        if element is not None:
            return TargetResolution(element, element.bbox, "runtime_element")
        # A named runtime target is intentional: do not silently weaken it to
        # semantic or box matching unless the caller explicitly permits that.
        if not target.allow_fallback:
            return TargetResolution(failure=FailureReason.TARGET_NOT_FOUND)
    candidates = list(observation.elements)
    if target.semantic:
        candidates = [candidate for candidate in candidates if candidate.semantic == target.semantic]
    for key, value in target.relation.items():
        candidates = [candidate for candidate in candidates if candidate.metadata.get(key) == value]
    if len(candidates) == 1:
        return TargetResolution(candidates[0], candidates[0].bbox, "semantic_or_geometry")
    if len(candidates) > 1:
        return TargetResolution(failure=FailureReason.TARGET_AMBIGUOUS,
                                candidates=tuple(candidate.element_id for candidate in candidates))
    if target.allow_fallback and target.fallback_bbox is not None:
        return TargetResolution(bbox=target.fallback_bbox, source="configured_fallback")
    return TargetResolution(failure=FailureReason.TARGET_NOT_FOUND)


def configured_action_target(action: dict) -> ActionTarget:
    """Explicit legacy bridge: a taught named action may opt into its own box.

    This is deliberately not a generic fallback.  The caller must already have
    selected a specific configured action under the old state/action registry.
    """
    box = action.get("box")
    if not isinstance(box, (list, tuple)):
        raise ValueError("Configured action has no normalized fallback box.")
    return ActionTarget(fallback_bbox=tuple(float(value) for value in box), allow_fallback=True)
