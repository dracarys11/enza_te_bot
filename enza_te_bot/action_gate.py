"""Side-effect-free authorization boundary for environment actions.

``ActionGate`` is intentionally narrower than a planner or executor.  It
checks that an already-selected action has sufficient observation evidence and
is inside its declared room scope.  It never clicks, chooses an objective, or
commits completion.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import time
from typing import Iterable, Mapping

from environment_provider import ActionIntent
from execution_permission import ExecutionPermission, issue_execution_permission
from perception_models import Observation
from room_adapter import HomeProvenance, valid_home_provenance
from grounding import TargetResolution, resolve_action_target


class GateDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


APPROVED = GateDecision.APPROVED
REJECTED = GateDecision.REJECTED
UNKNOWN = GateDecision.UNKNOWN


@dataclass(frozen=True)
class ObservationProvenance:
    """Sealed freshness/verification evidence for non-HOME observations."""

    observation_id: str
    state: str
    fresh: bool = True
    verified: bool = True
    issued_at_monotonic: float = field(default_factory=time.monotonic)
    _seal: object | None = None


_PROVENANCE_SEAL = object()


def issue_observation_provenance(observation_id: str, state: str, *, fresh: bool = True,
                                 verified: bool = True) -> ObservationProvenance:
    """Issue provider-owned provenance; the gate never mints it implicitly."""
    return ObservationProvenance(str(observation_id), str(state), fresh, verified,
                                 time.monotonic(), _PROVENANCE_SEAL)


def valid_observation_provenance(provenance: object, observation: Observation) -> bool:
    """Accept only sealed provenance bound to this exact observation."""
    if isinstance(provenance, HomeProvenance):
        return (valid_home_provenance(provenance)
                and provenance.observation_id == observation.observation_id)
    return (
        isinstance(provenance, ObservationProvenance)
        and provenance._seal is _PROVENANCE_SEAL
        and provenance.observation_id == observation.observation_id
        and provenance.state == (observation.detected_state or "")
        and provenance.fresh is True
        and provenance.verified is True
        and provenance.issued_at_monotonic > 0
    )


@dataclass(frozen=True)
class ActionGateResult:
    decision: GateDecision
    reason: str
    target: TargetResolution | None = None
    permission: ExecutionPermission | None = None

    @property
    def approved(self) -> bool:
        return self.decision is GateDecision.APPROVED

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision.value,
            "reason": self.reason,
            "target_source": self.target.source if self.target else None,
            "target_failure": self.target.failure.value if self.target and self.target.failure else None,
            "permission": self.permission.as_dict() if self.permission else None,
        }


def _provenance_identity(provenance: object) -> str:
    """Identify already-validated provenance without exposing its private seal."""
    if isinstance(provenance, HomeProvenance):
        payload = ("HOME", provenance.observation_id,
                   format(provenance.verified_at_monotonic, ".17g"))
    elif isinstance(provenance, ObservationProvenance):
        payload = ("OBSERVATION", provenance.observation_id, provenance.state,
                   format(provenance.issued_at_monotonic, ".17g"))
    else:
        raise ValueError("unsupported provenance type")
    digest = hashlib.sha256("\x1f".join(payload).encode("utf-8")).hexdigest()
    return f"provenance_{digest}"


def _target_identity(action: ActionIntent, target: TargetResolution | None) -> str:
    """Bind authorization to the concrete resolved element, box, or point."""
    if target is not None and target.element is not None:
        return f"element:{target.element.element_id}"
    if target is not None and target.bbox is not None:
        coordinates = ",".join(format(value, ".17g") for value in target.bbox)
        return f"{target.source or 'resolved'}:bbox:{coordinates}"
    if action.coordinate is not None:
        coordinates = ",".join(format(value, ".17g") for value in action.coordinate)
        return f"coordinate:{coordinates}"
    raise ValueError("approved action has no resolved target identity")


def _has_calibrated_target(target: TargetResolution | None) -> bool:
    """Return true only for independently calibrated runtime target evidence."""
    element = target.element if target is not None else None
    if element is None:
        return False
    metadata = element.metadata if isinstance(element.metadata, Mapping) else {}
    source = str(metadata.get("source", "")).upper()
    verification = str(metadata.get("verification_level", "")).upper()
    calibration = str(metadata.get("calibration_status", "")).upper()
    # Screenshot/artifact claims cannot authorize a click, even if a caller
    # supplies otherwise valid observation provenance.
    if source in {"SCREENSHOT", "ARTIFACT"}:
        return False
    return verification == "CALIBRATED" or calibration == "CALIBRATED"


def _is_screenshot_visible_only(target: TargetResolution | None) -> bool:
    element = target.element if target is not None else None
    if element is None or not isinstance(element.metadata, Mapping):
        return False
    return (
        str(element.metadata.get("source", "")).upper() == "SCREENSHOT"
        and str(element.metadata.get("verification_level", "")).upper() == "VISIBLE_ONLY"
    )


class ActionGate:
    """Evaluate action authorization without performing any environment I/O."""

    def __init__(self, *, confidence_threshold: float = 0.80,
                 allowed_rooms: Iterable[str] | None = None,
                 permission_ttl_seconds: float = 5.0) -> None:
        if not 0 <= float(confidence_threshold) <= 1:
            raise ValueError("confidence_threshold must be in [0, 1].")
        if float(permission_ttl_seconds) <= 0:
            raise ValueError("permission_ttl_seconds must be positive.")
        self.confidence_threshold = float(confidence_threshold)
        self.allowed_rooms = frozenset(str(room) for room in allowed_rooms) if allowed_rooms is not None else None
        self.permission_ttl_seconds = float(permission_ttl_seconds)

    def evaluate(self, observation: Observation, action: ActionIntent) -> ActionGateResult:
        """Return APPROVED, REJECTED, or UNKNOWN; this method has no side effects."""
        provenance = observation.frame_metadata.get("provenance")
        if provenance is None:
            provenance = observation.frame_metadata.get("home_provenance")
        if provenance is None:
            return ActionGateResult(REJECTED, "MISSING_PROVENANCE")
        if not valid_observation_provenance(provenance, observation):
            return ActionGateResult(REJECTED, "STALE_OR_INVALID_PROVENANCE")

        if observation.observation_status in {"UNKNOWN", "UNREADABLE"}:
            return ActionGateResult(UNKNOWN, "OBSERVATION_UNKNOWN")
        if observation.detected_state in {"UNKNOWN", "CONFIRMED_UNKNOWN"}:
            return ActionGateResult(UNKNOWN, "STATE_UNKNOWN")

        confidence = observation.confidence
        if confidence is None:
            confidence = observation.business_state.get("confidence")
        if confidence is None:
            return ActionGateResult(UNKNOWN, "CONFIDENCE_UNAVAILABLE")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            return ActionGateResult(UNKNOWN, "CONFIDENCE_UNREADABLE")
        if confidence < self.confidence_threshold:
            return ActionGateResult(REJECTED, "CONFIDENCE_BELOW_THRESHOLD")

        room = action.metadata.get("room") if isinstance(action.metadata, Mapping) else None
        if self.allowed_rooms is not None:
            if room is None or str(room) not in self.allowed_rooms:
                return ActionGateResult(REJECTED, "ACTION_OUTSIDE_ALLOWED_ROOM_SCOPE")

        target: TargetResolution | None = None
        if action.target is not None:
            target = resolve_action_target(observation, action.target)
            if target.failure is not None:
                return ActionGateResult(REJECTED, target.failure.value, target)
        elif action.coordinate is None:
            return ActionGateResult(REJECTED, "TARGET_NOT_FOUND")

        # Element-level evidence is authoritative over a caller's top-level
        # status flag. Screenshot-only bounds cannot authorize a click.
        if _is_screenshot_visible_only(target):
            return ActionGateResult(UNKNOWN, "SCREENSHOT_VISIBLE_ONLY_TARGET", target)
        if observation.observation_status in {"VISIBLE_ONLY", "ARTIFACT_UNVERIFIED"}:
            if not _has_calibrated_target(target):
                return ActionGateResult(
                    UNKNOWN, "NON_EXECUTABLE_OBSERVATION_EVIDENCE", target,
                )

        permission = issue_execution_permission(
            observation_id=observation.observation_id,
            action_intent_id=action.action_intent_id,
            target_identity=_target_identity(action, target),
            scope=str(room) if room is not None else "UNSCOPED",
            provenance_identity=_provenance_identity(provenance),
            ttl_seconds=self.permission_ttl_seconds,
        )
        return ActionGateResult(APPROVED, "EVIDENCE_AND_SCOPE_VALID", target, permission)

    __call__ = evaluate


__all__ = [
    "APPROVED", "REJECTED", "UNKNOWN", "GateDecision", "ActionGateResult",
    "ObservationProvenance", "issue_observation_provenance",
    "valid_observation_provenance", "ActionGate",
]
