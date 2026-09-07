"""Offline action-request and permission boundary for exploration."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Mapping, Protocol

from action_gate import ActionGate, GateDecision
from environment_provider import ActionIntent
from execution_permission import ExecutionPermission, consume_execution_permission, validate_execution_permission
from perception_models import Observation


class ActionBoundaryError(ValueError):
    """Raised for malformed, stale, or mismatched boundary evidence."""


@dataclass(frozen=True, slots=True)
class FreshObservationRequirement:
    observation_id: str
    frame_id: str
    capture_timestamp: str
    screenshot_digest: str
    expires_at_monotonic: float

    @classmethod
    def from_observation(cls, observation: Observation, *, ttl_seconds: float = 5.0) -> "FreshObservationRequirement":
        metadata = observation.frame_metadata
        values = {
            "observation_id": observation.observation_id,
            "frame_id": metadata.get("frame_id"),
            "capture_timestamp": observation.captured_at,
            "screenshot_digest": metadata.get("screenshot_digest"),
        }
        missing = [name for name, value in values.items() if not isinstance(value, str) or not value.strip()]
        if missing:
            raise ActionBoundaryError("fresh observation missing " + ", ".join(missing))
        if ttl_seconds <= 0:
            raise ActionBoundaryError("ttl_seconds must be positive")
        return cls(**values, expires_at_monotonic=time.monotonic() + float(ttl_seconds))

    def validate(self, observation: Observation, *, consumed_ids: set[str] | None = None,
                 now: float | None = None) -> None:
        if observation.observation_id != self.observation_id:
            raise ActionBoundaryError("observation_id mismatch")
        if consumed_ids is not None and self.observation_id in consumed_ids:
            raise ActionBoundaryError("observation_id already used")
        metadata = observation.frame_metadata
        if metadata.get("frame_id") != self.frame_id:
            raise ActionBoundaryError("frame_id mismatch")
        if observation.captured_at != self.capture_timestamp:
            raise ActionBoundaryError("capture_timestamp mismatch")
        if metadata.get("screenshot_digest") != self.screenshot_digest:
            raise ActionBoundaryError("screenshot integrity mismatch")
        if (time.monotonic() if now is None else float(now)) >= self.expires_at_monotonic:
            raise ActionBoundaryError("observation requirement expired")


@dataclass(frozen=True, slots=True)
class ActionRequest:
    action_id: str
    intent: ActionIntent
    target: str
    source_observation_id: str
    target_evidence: str
    scope: str

    def __post_init__(self) -> None:
        for field in ("action_id", "target", "source_observation_id", "target_evidence", "scope"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ActionBoundaryError(f"{field} is required")


@dataclass(frozen=True, slots=True)
class BoundaryExecutionResult:
    approved: bool
    verification: Mapping[str, Any]
    after_observation: Observation | None = None
    reason: str | None = None


class PermissionProvider(Protocol):
    def execute(self, permission: ExecutionPermission) -> Any:
        """Execute only a valid, single-use permission."""


class ActionBoundary:
    """Validate a request/permission pair before handing it to a provider."""

    def __init__(self, *, gate: ActionGate, provider: PermissionProvider,
                 consumed_observation_ids: set[str] | None = None) -> None:
        self.gate = gate
        self.provider = provider
        self._consumed_observation_ids = consumed_observation_ids if consumed_observation_ids is not None else set()

    def authorize(self, request: ActionRequest, observation: Observation) -> ExecutionPermission | None:
        requirement = FreshObservationRequirement.from_observation(observation)
        requirement.validate(observation, consumed_ids=self._consumed_observation_ids)
        if request.source_observation_id != observation.observation_id:
            raise ActionBoundaryError("request observation_id mismatch")
        gate_result = self.gate.evaluate(observation, request.intent)
        if gate_result.decision is not GateDecision.APPROVED or gate_result.permission is None:
            return None
        permission = gate_result.permission
        if permission.target_identity != request.target or permission.scope != request.scope:
            raise ActionBoundaryError("gate permission does not match request target/scope")
        return permission

    def execute(self, request: ActionRequest, observation: Observation,
                permission: ExecutionPermission | None) -> BoundaryExecutionResult:
        if permission is None:
            return BoundaryExecutionResult(False, {"verified": False}, reason="MISSING_PERMISSION")
        try:
            requirement = FreshObservationRequirement.from_observation(observation)
            requirement.validate(observation, consumed_ids=self._consumed_observation_ids)
            if request.source_observation_id != observation.observation_id:
                raise ActionBoundaryError("request observation_id mismatch")
            validation = validate_execution_permission(permission)
            if not validation.valid:
                return BoundaryExecutionResult(False, {"verified": False}, reason=validation.reason)
            if (permission.observation_id != request.source_observation_id
                    or permission.action_intent_id != request.intent.action_intent_id
                    or permission.target_identity != request.target
                    or permission.scope != request.scope):
                return BoundaryExecutionResult(False, {"verified": False}, reason="PERMISSION_BINDING_MISMATCH")
            consumed = consume_execution_permission(permission)
            if not consumed.valid:
                return BoundaryExecutionResult(False, {"verified": False}, reason=consumed.reason)
            raw_result = self.provider.execute(permission)
            after = getattr(raw_result, "after_observation", None)
            if after is None or after.observation_id == observation.observation_id:
                return BoundaryExecutionResult(False, {"verified": False, "new_observation": False}, after,
                                               "POST_ACTION_OBSERVATION_INVALID")
            self._consumed_observation_ids.add(observation.observation_id)
            return BoundaryExecutionResult(True, {"verified": True, "new_observation": True}, after)
        except ActionBoundaryError as error:
            return BoundaryExecutionResult(False, {"verified": False}, reason=str(error))


__all__ = [
    "ActionBoundaryError", "FreshObservationRequirement", "ActionRequest",
    "BoundaryExecutionResult", "PermissionProvider", "ActionBoundary",
]
