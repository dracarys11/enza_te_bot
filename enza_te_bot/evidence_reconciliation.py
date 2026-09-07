"""Append-only validation for offline evidence reconciliation records.

Reconciliation records correct the usable classification of earlier memory
without editing the source observations, screenshots, decision traces, or
trajectories.  They are audit overlays only and never authorize execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
UNKNOWN = "UNKNOWN"
AUDIT_FAILED = "AUDIT_FAILED_REQUIRES_RECONCILIATION"

# Runtime observation failures are deliberately separate from evidence-audit
# records above.  These values are classifications, never click authority.
TIMEOUT_CLASSES = frozenset({
    "TOOL_LATENCY_BUDGET_EXCEEDED", "SCREENSHOT_TIMEOUT", "PAGE_STATE_TIMEOUT",
    "CONTROL_FAILURE", "SESSION_RELEASED",
})


class EvidenceReconciliationError(ValueError):
    """Raised when a reconciliation record violates the audit contract."""


def _text(data: Mapping[str, Any], field: str, context: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EvidenceReconciliationError(f"{context}.{field} is required")
    return value.strip()


def _items(data: Mapping[str, Any], field: str, context: str) -> tuple[Any, ...]:
    value = data.get(field)
    if not isinstance(value, list) or not value:
        raise EvidenceReconciliationError(f"{context}.{field} is required")
    return tuple(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class ObservationReconciliation:
    observation_id: str
    original_artifact: str
    original_artifact_sha256: str
    original_claim: Mapping[str, Any]
    supporting_evidence: tuple[Mapping[str, Any], ...]
    conflicting_evidence: tuple[Mapping[str, Any], ...]
    final_classification: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class TrajectoryAuditStatus:
    trajectory_id: str
    original_artifact: str
    original_artifact_sha256: str
    status: str


@dataclass(frozen=True, slots=True)
class EvidenceReconciliation:
    reconciliation_id: str
    observations: tuple[ObservationReconciliation, ...]
    added_observed_states: tuple[Mapping[str, Any], ...]
    affected_trajectories: tuple[TrajectoryAuditStatus, ...]
    executable: bool = False


@dataclass(frozen=True, slots=True)
class PendingAction:
    """An action whose postcondition has not yet been observed."""

    action: str
    target: Any
    observation_id: str
    stale: bool = False
    retry_eligible: bool = False


@dataclass(frozen=True, slots=True)
class RuntimeReconciliation:
    """Result of reconciling a timed-out action against fresh stable state."""

    status: str
    reason: str
    pending_action: PendingAction | None
    observation_fresh: bool
    screenshot_attempts: int


class ObservationReconciler:
    """Fail-closed timeout gate for one pending semantic action.

    A timeout invalidates the pre-timeout observation.  Only a caller-supplied
    fresh, stable state can clear the pending action or make it eligible again.
    This class has no I/O and cannot execute or authorize a click.
    """

    def __init__(self, *, max_screenshot_attempts: int = 1) -> None:
        if max_screenshot_attempts < 1:
            raise ValueError("max_screenshot_attempts must be positive")
        self._max_screenshot_attempts = max_screenshot_attempts
        self._pending: PendingAction | None = None
        self._screenshot_attempts = 0
        self._blocked = False
        self._session_released = False

    @property
    def pending_action(self) -> PendingAction | None:
        return self._pending

    def action_sent(self, action: str, target: Any, observation_id: str) -> None:
        if self._blocked:
            raise EvidenceReconciliationError("RECONCILIATION_REQUIRED")
        if not isinstance(action, str) or not action.strip() or not isinstance(observation_id, str) or not observation_id.strip():
            raise EvidenceReconciliationError("pending action identity is required")
        self._pending = PendingAction(action.strip(), target, observation_id.strip())
        self._screenshot_attempts = 0

    def timeout(self, failure_class: str) -> RuntimeReconciliation:
        if failure_class not in TIMEOUT_CLASSES:
            raise EvidenceReconciliationError(f"unknown timeout class: {failure_class}")
        if failure_class == "SESSION_RELEASED":
            self._blocked = True
            self._session_released = True
        if failure_class == "SCREENSHOT_TIMEOUT":
            self._screenshot_attempts += 1
            self._blocked = self._screenshot_attempts >= self._max_screenshot_attempts
        if self._pending is not None:
            self._pending = PendingAction(self._pending.action, self._pending.target,
                                          self._pending.observation_id, stale=True,
                                          retry_eligible=False)
        return RuntimeReconciliation(
            "RECONCILIATION_REQUIRED" if not self._blocked else "FAIL_CLOSED",
            failure_class, self._pending, False, self._screenshot_attempts,
        )

    def reconcile(self, *, state: str, stable: bool, observation_id: str,
                  transition_succeeded: bool = False) -> RuntimeReconciliation:
        if self._session_released:
            return RuntimeReconciliation("FAIL_CLOSED", "SESSION_RELEASED", self._pending,
                                         False, self._screenshot_attempts)
        if self._pending is None:
            return RuntimeReconciliation("NO_PENDING_ACTION", "NO_ACTION_PENDING", None,
                                         bool(stable), self._screenshot_attempts)
        if not stable or not isinstance(observation_id, str) or observation_id == self._pending.observation_id:
            return RuntimeReconciliation("RECONCILIATION_REQUIRED", "FRESH_STABLE_OBSERVATION_REQUIRED",
                                         self._pending, False, self._screenshot_attempts)
        pending = self._pending
        if transition_succeeded:
            self._pending = None
            self._blocked = False
            return RuntimeReconciliation("RECONCILED", "TRANSITION_SUCCEEDED", None, True,
                                         self._screenshot_attempts)
        self._pending = PendingAction(pending.action, pending.target, pending.observation_id,
                                      stale=False, retry_eligible=True)
        self._blocked = False
        return RuntimeReconciliation("RETRY_ELIGIBLE", "ORIGINAL_STATE_REOBSERVED", self._pending,
                                     True, self._screenshot_attempts)


def _verify_original(root: Path, artifact: str, expected_hash: str, context: str) -> None:
    path = root / artifact
    if not path.is_file():
        raise EvidenceReconciliationError(f"{context} original artifact is missing: {artifact}")
    actual_hash = _sha256(path)
    if actual_hash != expected_hash:
        raise EvidenceReconciliationError(
            f"{context} original artifact changed: expected {expected_hash}, got {actual_hash}")


def validate_evidence_reconciliation(
    data: Mapping[str, Any], *, repository_root: str | Path | None = None,
) -> EvidenceReconciliation:
    """Validate one non-executable, append-only reconciliation overlay."""
    if data.get("schema_version") != SCHEMA_VERSION:
        raise EvidenceReconciliationError("unsupported schema_version")
    if data.get("executable") is not False:
        raise EvidenceReconciliationError("reconciliation must declare executable=false")
    if data.get("original_artifacts_mutated") is not False:
        raise EvidenceReconciliationError("original_artifacts_mutated must be false")

    root = Path(repository_root) if repository_root is not None else None
    observations_value = _items(data, "observations", "reconciliation")
    observations: list[ObservationReconciliation] = []
    seen: set[str] = set()
    for index, item in enumerate(observations_value):
        context = f"observations[{index}]"
        if not isinstance(item, Mapping):
            raise EvidenceReconciliationError(f"{context} must be an object")
        observation_id = _text(item, "observation_id", context)
        if observation_id in seen:
            raise EvidenceReconciliationError(f"duplicate observation_id: {observation_id}")
        seen.add(observation_id)
        original_claim = item.get("original_claim")
        final = item.get("final_classification")
        if not isinstance(original_claim, Mapping) or not isinstance(final, Mapping):
            raise EvidenceReconciliationError(
                f"{context}.original_claim and final_classification are required")
        supporting = _items(item, "supporting_evidence", context)
        conflicting = _items(item, "conflicting_evidence", context)
        if not all(isinstance(entry, Mapping) for entry in supporting + conflicting):
            raise EvidenceReconciliationError(f"{context} evidence entries must be objects")
        if conflicting and _text(final, "classification", f"{context}.final_classification") != UNKNOWN:
            raise EvidenceReconciliationError(
                f"{context} contradictory evidence cannot remain VERIFIED/INFERENCE")
        artifact = _text(item, "original_artifact", context)
        artifact_hash = _text(item, "original_artifact_sha256", context)
        if root is not None:
            _verify_original(root, artifact, artifact_hash, context)
        observations.append(ObservationReconciliation(
            observation_id, artifact, artifact_hash, original_claim,
            tuple(supporting), tuple(conflicting), final,
        ))

    added_states = _items(data, "added_observed_states", "reconciliation")
    for index, state in enumerate(added_states):
        context = f"added_observed_states[{index}]"
        if not isinstance(state, Mapping):
            raise EvidenceReconciliationError(f"{context} must be an object")
        _text(state, "label", context)
        classification = _text(state, "classification", context)
        if classification not in {"FACT", "INFERENCE", UNKNOWN}:
            raise EvidenceReconciliationError(f"{context}.classification is invalid")
        _items(state, "evidence_refs", context)

    trajectories_value = _items(data, "affected_trajectories", "reconciliation")
    trajectories: list[TrajectoryAuditStatus] = []
    for index, item in enumerate(trajectories_value):
        context = f"affected_trajectories[{index}]"
        if not isinstance(item, Mapping):
            raise EvidenceReconciliationError(f"{context} must be an object")
        if _text(item, "status", context) != AUDIT_FAILED:
            raise EvidenceReconciliationError(f"{context}.status must preserve audit failure")
        artifact = _text(item, "original_artifact", context)
        artifact_hash = _text(item, "original_artifact_sha256", context)
        if root is not None:
            _verify_original(root, artifact, artifact_hash, context)
        trajectories.append(TrajectoryAuditStatus(
            _text(item, "trajectory_id", context), artifact, artifact_hash, AUDIT_FAILED,
        ))

    return EvidenceReconciliation(
        _text(data, "reconciliation_id", "reconciliation"),
        tuple(observations), tuple(added_states), tuple(trajectories), False,
    )


def load_evidence_reconciliation(
    path: str | Path, *, repository_root: str | Path | None = None,
) -> EvidenceReconciliation:
    """Load a reconciliation without modifying any referenced artifact."""
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise EvidenceReconciliationError("reconciliation root must be an object")
    return validate_evidence_reconciliation(data, repository_root=repository_root)


__all__ = [
    "SCHEMA_VERSION", "UNKNOWN", "AUDIT_FAILED", "TIMEOUT_CLASSES",
    "EvidenceReconciliationError", "PendingAction", "RuntimeReconciliation",
    "ObservationReconciler",
    "ObservationReconciliation", "TrajectoryAuditStatus", "EvidenceReconciliation",
    "validate_evidence_reconciliation", "load_evidence_reconciliation",
]
