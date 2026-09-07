"""Bounded, offline-testable provider for calibrated navigation actions.

This is deliberately separate from the live EnvironmentProvider.  The
production runner is not wired to it; the mock models the evidence contract so
exploration can be tested without injecting input.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from action_gate import valid_observation_provenance
from environment_provider import ActionIntent
from perception_models import Observation


SUPPORTED_NAVIGATION_ACTIONS = frozenset({
    "produce_open", "preparation_next", "cancel_overlay",
})


class ActionProviderResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class ActionExecution:
    """Result plus the evidence needed for a trajectory step."""

    result: ActionProviderResult
    action: str
    before_observation: Observation | None
    after_observation: Observation | None
    verification: Mapping[str, Any]
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "result": self.result.value,
            "action": self.action,
            "before_obs": self.before_observation.as_dict() if self.before_observation else None,
            "after_obs": self.after_observation.as_dict() if self.after_observation else None,
            "verification": dict(self.verification),
            "reason": self.reason,
        }


@runtime_checkable
class ActionProvider(Protocol):
    def observe(self) -> Observation:
        """Return the current fresh observation."""

    def execute(self, action: ActionIntent, observation: Observation | None = None) -> ActionExecution:
        """Execute one approved navigation action and record before/after evidence."""


def _fresh_verified(observation: Observation) -> bool:
    if observation.observation_status in {"UNKNOWN", "UNREADABLE", "VISIBLE_ONLY", "ARTIFACT_UNVERIFIED"}:
        return False
    provenance = observation.frame_metadata.get("provenance")
    if provenance is None:
        provenance = observation.frame_metadata.get("home_provenance")
    return provenance is not None and valid_observation_provenance(provenance, observation)


class MockActionProvider:
    """Deterministic action provider; it never calls a mouse/browser API."""

    def __init__(
        self,
        initial_observation: Observation,
        transitions: Mapping[str, Sequence[Observation] | Observation],
        *, calibrated_actions: Sequence[str] = (),
    ) -> None:
        self._current = initial_observation
        self._transitions = {
            str(name): list(value) if isinstance(value, (list, tuple)) else [value]
            for name, value in transitions.items()
        }
        self._calibrated = {str(name) for name in calibrated_actions}
        self.trajectory: list[dict[str, Any]] = []

    def observe(self) -> Observation:
        return self._current

    def execute(self, action: ActionIntent, observation: Observation | None = None) -> ActionExecution:
        name = str(action.action_name)
        before = self.observe()
        if name not in SUPPORTED_NAVIGATION_ACTIONS:
            return self._record(ActionExecution(
                ActionProviderResult.FAILED, name, before, None,
                {"verified": False}, "RESOURCE_OR_UNSUPPORTED_ACTION",
            ))
        supplied = observation or before
        if supplied.observation_id != before.observation_id or not _fresh_verified(supplied):
            return self._record(ActionExecution(
                ActionProviderResult.FAILED, name, supplied, None,
                {"verified": False}, "STALE_OR_UNVERIFIED_OBSERVATION",
            ))
        if name not in self._calibrated:
            return self._record(ActionExecution(
                ActionProviderResult.FAILED, name, before, None,
                {"verified": False}, "UNCALIBRATED_TARGET",
            ))
        queue = self._transitions.get(name)
        if not queue:
            return self._record(ActionExecution(
                ActionProviderResult.FAILED, name, before, None,
                {"verified": False}, "NO_VERIFICATION_OBSERVATION",
            ))
        after = queue.pop(0)
        if after.observation_id == before.observation_id:
            return self._record(ActionExecution(
                ActionProviderResult.FAILED, name, before, after,
                {"verified": False, "new_observation": False}, "STALE_AFTER_OBSERVATION",
            ))
        if after.observation_status in {"UNKNOWN", "UNREADABLE"} or after.detected_state in {"UNKNOWN", "CONFIRMED_UNKNOWN"}:
            self._current = after
            return self._record(ActionExecution(
                ActionProviderResult.UNKNOWN, name, before, after,
                {"verified": False, "new_observation": True}, "POST_ACTION_UNKNOWN",
            ))
        self._current = after
        return self._record(ActionExecution(
            ActionProviderResult.SUCCESS, name, before, after,
            {"verified": True, "new_observation": True},
        ))

    def _record(self, result: ActionExecution) -> ActionExecution:
        self.trajectory.append(result.as_dict())
        return result


__all__ = [
    "SUPPORTED_NAVIGATION_ACTIONS", "ActionProviderResult", "ActionExecution",
    "ActionProvider", "MockActionProvider",
]
