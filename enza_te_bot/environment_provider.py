"""Small environment boundary for structured, offline-testable interaction.

This module deliberately does not connect to ZCode or alter the live execution
paths.  It describes the narrow interface an environment backend may provide:
observe, execute an already-authorized action intent, and verify its evidence.
The planner and existing RoomAdapter remain the owners of strategy and room
results respectively.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import secrets
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from perception_models import ActionResult, ActionTarget, FailureReason, Observation


@dataclass(frozen=True)
class ActionIntent:
    """A bounded execution request, never a strategic decision."""

    action_name: str
    target: ActionTarget | None = None
    coordinate: tuple[float, float] | None = None
    expected_state: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    action_intent_id: str = field(default_factory=lambda: f"intent_{secrets.token_hex(16)}")

    def __post_init__(self) -> None:
        if not str(self.action_name).strip():
            raise ValueError("ActionIntent requires an action name.")
        if not str(self.action_intent_id).strip():
            raise ValueError("ActionIntent requires an action_intent_id.")
        object.__setattr__(self, "action_name", str(self.action_name))
        object.__setattr__(self, "action_intent_id", str(self.action_intent_id))
        if self.coordinate is not None:
            if len(self.coordinate) != 2 or not all(0 <= float(value) <= 1 for value in self.coordinate):
                raise ValueError("ActionIntent coordinate must be normalized.")
            object.__setattr__(self, "coordinate", (float(self.coordinate[0]), float(self.coordinate[1])))

    def as_dict(self) -> dict[str, Any]:
        return {
            "action_intent_id": self.action_intent_id,
            "action_name": self.action_name,
            "target": {
                "runtime_element_id": self.target.runtime_element_id,
                "semantic": self.target.semantic,
                "relation": dict(self.target.relation),
                "fallback_bbox": list(self.target.fallback_bbox) if self.target and self.target.fallback_bbox else None,
                "allow_fallback": self.target.allow_fallback if self.target else False,
            } if self.target else None,
            "coordinate": list(self.coordinate) if self.coordinate is not None else None,
            "expected_state": self.expected_state,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class VerificationResult:
    """Independent evidence verdict for one executed ActionIntent."""

    verified: bool
    observation: Observation | None = None
    failure: FailureReason | None = None
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "observation": self.observation.as_dict() if self.observation else None,
            "failure": self.failure.value if self.failure else None,
            "detail": self.detail,
        }


@runtime_checkable
class EnvironmentProvider(Protocol):
    """Observation and bounded actuation boundary below Room Adapters."""

    def observe(self) -> Observation:
        """Return one fresh structured observation."""

    def execute(self, action: ActionIntent) -> ActionResult:
        """Execute only the supplied action; never select strategy."""

    def verify(self, action_result: ActionResult) -> VerificationResult:
        """Evaluate independent post-action evidence."""


class MockEnvironmentProvider:
    """Deterministic provider for offline contract tests.

    It changes only its in-memory observation; it has no browser, PyAutoGUI, or
    other input-injection dependency.
    """

    def __init__(self, initial_observation: Observation,
                 transitions: Mapping[str, Sequence[Observation] | Observation] | None = None,
                 *, unavailable_actions: Sequence[str] = ()) -> None:
        self._current = initial_observation
        self._transitions: dict[str, list[Observation]] = {}
        for name, values in (transitions or {}).items():
            self._transitions[str(name)] = list(values) if isinstance(values, (list, tuple)) else [values]
        self._unavailable = {str(name) for name in unavailable_actions}
        self.observation_history: list[Observation] = [initial_observation]
        self.executed_intents: list[ActionIntent] = []

    def observe(self) -> Observation:
        return self._current

    def execute(self, action: ActionIntent) -> ActionResult:
        before = self._current
        self.executed_intents.append(action)
        if action.action_name in self._unavailable:
            return ActionResult(
                action.action_name, issued=False, failure=FailureReason.SAFETY_BLOCKED,
                before_observation=before, metadata={"expected_state": action.expected_state},
                requested_action=action.action_name, coordinate=action.coordinate,
            )
        if action.action_name not in self._transitions:
            return ActionResult(
                action.action_name, issued=False, failure=FailureReason.TARGET_NOT_FOUND,
                before_observation=before, metadata={"expected_state": action.expected_state},
                requested_action=action.action_name, coordinate=action.coordinate,
            )

        candidates = self._transitions[action.action_name]
        after = candidates.pop(0) if candidates else before
        self._current = after
        self.observation_history.append(after)
        return ActionResult(
            action.action_name, issued=True, immediate_observation_id=after.observation_id,
            before_observation=before, after_observation=after,
            metadata={"expected_state": action.expected_state},
            requested_action=action.action_name, executed_action=action.action_name,
            coordinate=action.coordinate,
        )

    def verify(self, action_result: ActionResult) -> VerificationResult:
        if not action_result.issued:
            return VerificationResult(False, action_result.after_observation,
                                      action_result.failure or FailureReason.SAFETY_BLOCKED,
                                      "action was not issued")
        observation = action_result.after_observation
        if observation is None:
            return VerificationResult(False, None, FailureReason.PERCEPTION_UNCERTAIN,
                                      "post-action observation is missing")
        state = str(observation.business_state.get("state", ""))
        if observation.observation_status in {"UNKNOWN", "UNREADABLE"} or state in {"UNKNOWN", "CONFIRMED_UNKNOWN"}:
            return VerificationResult(False, observation, FailureReason.CONFIRMED_UNKNOWN,
                                      "post-action observation is unknown")
        expected = action_result.metadata.get("expected_state")
        if expected and state != expected:
            return VerificationResult(False, observation, FailureReason.STATE_UNEXPECTED,
                                      f"expected {expected}, found {state}")
        return VerificationResult(True, observation)


__all__ = [
    "Observation", "ActionResult", "ActionIntent", "VerificationResult",
    "EnvironmentProvider", "MockEnvironmentProvider",
]
