"""Small, deterministic structured-perception vocabulary.

These objects describe what was observed; they intentionally contain no game
policy and do not perform actions.  They are JSON-ready evidence adapters for
the existing JSONL trace store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Mapping, Sequence


class FailureReason(str, Enum):
    PERCEPTION_UNCERTAIN = "PERCEPTION_UNCERTAIN"
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    ROUTE_GEOMETRY_UNCERTAIN = "ROUTE_GEOMETRY_UNCERTAIN"
    STATE_UNEXPECTED = "STATE_UNEXPECTED"
    EFFECT_NOT_VERIFIED = "EFFECT_NOT_VERIFIED"
    SP_UNREADABLE = "SP_UNREADABLE"
    SP_DID_NOT_DECREASE = "SP_DID_NOT_DECREASE"
    APPEAL_REPLACE_ACTION_REQUIRED = "APPEAL_REPLACE_ACTION_REQUIRED"
    CONFIRMED_UNKNOWN = "CONFIRMED_UNKNOWN"
    TIMEOUT = "TIMEOUT"
    SAFETY_BLOCKED = "SAFETY_BLOCKED"


def normalized_box(box: Sequence[float]) -> tuple[float, float, float, float]:
    if len(box) != 4:
        raise ValueError("Normalized bbox must have four values.")
    value = tuple(float(item) for item in box)
    if not (0 <= value[0] < value[2] <= 1 and 0 <= value[1] < value[3] <= 1):
        raise ValueError("Normalized bbox must be contained in [0, 1].")
    return value


@dataclass(frozen=True)
class UIElement:
    element_id: str
    bbox: tuple[float, float, float, float]
    role: str
    center: tuple[float, float] | None = None
    semantic: str | None = None
    visual_state: str | None = None
    confidence: float = 1.0
    detector: str = "unknown"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.element_id:
            raise ValueError("UIElement requires a runtime element_id.")
        bbox = normalized_box(self.bbox)
        object.__setattr__(self, "bbox", bbox)
        computed = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        center = self.center or computed
        if len(center) != 2 or not all(0 <= float(value) <= 1 for value in center):
            raise ValueError("UIElement center must be normalized.")
        object.__setattr__(self, "center", (float(center[0]), float(center[1])))
        if not 0 <= float(self.confidence) <= 1:
            raise ValueError("UIElement confidence must be in [0, 1].")

    def as_dict(self) -> dict[str, Any]:
        return {"element_id": self.element_id, "bbox": list(self.bbox), "center": list(self.center or ()),
                "role": self.role, "semantic": self.semantic, "visual_state": self.visual_state,
                "confidence": self.confidence, "detector": self.detector, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class NumericObservation:
    name: str
    value: int | float | None
    confidence: float
    raw: str = ""
    reason: str | None = None
    detector: str = "ocr"

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "value": self.value, "confidence": self.confidence,
                "raw": self.raw, "reason": self.reason, "detector": self.detector}


@dataclass(frozen=True)
class VisualStructure:
    structure_id: str
    kind: str
    bbox: tuple[float, float, float, float]
    members: tuple[UIElement, ...]
    confidence: float
    detector: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"structure_id": self.structure_id, "kind": self.kind, "bbox": list(self.bbox),
                "members": [member.as_dict() for member in self.members], "confidence": self.confidence,
                "detector": self.detector, "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class Observation:
    observation_id: str
    captured_at: str
    game_window: Mapping[str, Any]
    business_state: Mapping[str, Any]
    screenshot_path: str | None = None
    elements: tuple[UIElement, ...] = ()
    numerics: tuple[NumericObservation, ...] = ()
    structures: tuple[VisualStructure, ...] = ()
    frame_metadata: Mapping[str, Any] = field(default_factory=dict)
    candidate_actions: tuple[str, ...] = ()
    confidence: float | None = None
    observation_status: str = "VERIFIED"

    @classmethod
    def fresh(cls, *, game_window: Mapping[str, Any], business_state: Mapping[str, Any],
              screenshot_path: str | None = None, elements: Sequence[UIElement] = (),
              numerics: Sequence[NumericObservation] = (), structures: Sequence[VisualStructure] = (),
              frame_metadata: Mapping[str, Any] | None = None,
              candidate_actions: Sequence[str] = (), confidence: float | None = None,
              observation_status: str = "VERIFIED") -> "Observation":
        timestamp = datetime.now().isoformat(timespec="milliseconds")
        ids = [element.element_id for element in elements]
        if len(ids) != len(set(ids)):
            raise ValueError("Observation UIElement runtime IDs must be unique.")
        return cls(f"obs:{datetime.now():%Y%m%d_%H%M%S_%f}", timestamp, dict(game_window), dict(business_state),
                   screenshot_path, tuple(elements), tuple(numerics), tuple(structures), dict(frame_metadata or {}),
                   tuple(str(action) for action in candidate_actions), confidence, str(observation_status))

    def element(self, element_id: str) -> UIElement | None:
        return next((element for element in self.elements if element.element_id == element_id), None)

    @property
    def detected_state(self) -> str | None:
        """Convenience view of the detected business-state label."""
        value = self.business_state.get("state")
        return str(value) if value is not None else None

    @property
    def visible_elements(self) -> tuple[UIElement, ...]:
        """Alias used by environment providers for detected UI elements."""
        return self.elements

    @property
    def unknowns(self) -> Any:
        """Uncertainty claims carried through artifact conversion."""
        return self.frame_metadata.get("unknowns", ())

    @property
    def blocking_unknowns(self) -> Any:
        """Unknowns that block a safe downstream decision."""
        return self.frame_metadata.get("blocking_unknowns", ())

    @property
    def uncertainty_reason(self) -> Any:
        """Human-readable reason retained for an uncertain observation."""
        return self.frame_metadata.get("uncertainty_reason")

    def as_dict(self) -> dict[str, Any]:
        return {"observation_id": self.observation_id, "captured_at": self.captured_at,
                "screenshot_path": self.screenshot_path, "game_window": dict(self.game_window),
                "business_state": dict(self.business_state), "elements": [item.as_dict() for item in self.elements],
                "numerics": [item.as_dict() for item in self.numerics],
                "structures": [item.as_dict() for item in self.structures],
                "frame_metadata": dict(self.frame_metadata), "candidate_actions": list(self.candidate_actions),
                "confidence": self.confidence, "observation_status": self.observation_status}


@dataclass(frozen=True)
class ActionTarget:
    runtime_element_id: str | None = None
    semantic: str | None = None
    relation: Mapping[str, Any] = field(default_factory=dict)
    fallback_bbox: tuple[float, float, float, float] | None = None
    allow_fallback: bool = False

    def __post_init__(self) -> None:
        if not self.runtime_element_id and not self.semantic and self.fallback_bbox is None:
            raise ValueError("ActionTarget needs an element id, semantic selector, or fallback bbox.")
        if self.fallback_bbox is not None:
            object.__setattr__(self, "fallback_bbox", normalized_box(self.fallback_bbox))


@dataclass(frozen=True)
class EffectEvidence:
    destination_state: str | None = None
    destination_confidence: float | None = None
    numeric_before: int | float | None = None
    numeric_after: int | float | None = None
    verified: bool = False
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"destination_state": self.destination_state, "destination_confidence": self.destination_confidence,
                "numeric_before": self.numeric_before, "numeric_after": self.numeric_after,
                "verified": self.verified, "detail": self.detail}


@dataclass(frozen=True)
class ActionResult:
    action_name: str
    issued: bool
    immediate_observation_id: str | None = None
    destination_verified: bool = False
    effect: EffectEvidence | None = None
    committed: bool = False
    failure: FailureReason | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    requested_action: str | None = None
    executed_action: str | None = None
    coordinate: tuple[float, float] | None = None
    before_observation: Observation | None = None
    after_observation: Observation | None = None

    def __post_init__(self) -> None:
        requested = self.requested_action or self.action_name
        executed = self.executed_action
        if executed is None and self.issued:
            executed = self.action_name
        if self.coordinate is not None:
            if len(self.coordinate) != 2 or not all(0 <= float(value) <= 1 for value in self.coordinate):
                raise ValueError("ActionResult coordinate must be normalized.")
            object.__setattr__(self, "coordinate", (float(self.coordinate[0]), float(self.coordinate[1])))
        object.__setattr__(self, "requested_action", str(requested))
        object.__setattr__(self, "executed_action", str(executed) if executed is not None else None)

    def as_dict(self) -> dict[str, Any]:
        def observation_payload(observation: Observation | None) -> dict[str, Any] | None:
            return observation.as_dict() if observation is not None else None

        return {"action_name": self.action_name, "issued": self.issued,
                "immediate_observation_id": self.immediate_observation_id,
                "destination_verified": self.destination_verified,
                "effect": self.effect.as_dict() if self.effect else None,
                "committed": self.committed,
                "failure": self.failure.value if self.failure else None,
                "metadata": dict(self.metadata), "requested_action": self.requested_action,
                "executed_action": self.executed_action,
                "coordinate": list(self.coordinate) if self.coordinate is not None else None,
                "before_observation": observation_payload(self.before_observation),
                "after_observation": observation_payload(self.after_observation)}
