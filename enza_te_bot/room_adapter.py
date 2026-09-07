"""Minimal room adapter contract for legacy room executors.

This module intentionally contains no strategy or room mechanics.  It only
defines the small interface that lets a caller supply an objective to a room
adapter and receive the existing :class:`goal_execution.GoalResult` shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Protocol, runtime_checkable

from goal_execution import GoalContext, GoalResult


SUCCESS_HOME = "SUCCESS_HOME"
FAILED = "FAILED"
UNKNOWN = "UNKNOWN"
LEGACY_SUCCESS = "GOAL_SUCCESS"
LEGACY_SUCCESS_STATUSES = frozenset({"GOAL_SUCCESS", "SUCCESS"})
HOME_VERIFIED_PARAMETER = "home_verified"
HOME_FRESH_PARAMETER = "home_fresh"
HOME_PROVENANCE_PARAMETER = "home_provenance"


# The seal is intentionally module-private.  Callers receive provenance only
# from the explicit issuer below; legacy boolean flags are never sufficient.
_HOME_PROVENANCE_SEAL = object()


@dataclass(frozen=True)
class HomeProvenance:
    """Opaque evidence that a fresh HOME observation was actually verified."""

    observation_id: str
    state: str = "HOME"
    fresh: bool = True
    verified_at_monotonic: float = field(default_factory=time.monotonic)
    _seal: object | None = field(default=None, repr=False, compare=False)


def issue_home_provenance(observation_id: str, *, state: str = "HOME",
                          fresh: bool = True) -> HomeProvenance:
    """Mint provenance for the trusted validated-HOME observation boundary."""
    return HomeProvenance(
        observation_id=str(observation_id),
        state=state,
        fresh=fresh,
        _seal=_HOME_PROVENANCE_SEAL,
    )


def valid_home_provenance(provenance: object) -> bool:
    """Validate sealed, fresh HOME evidence rather than caller booleans."""
    return (
        isinstance(provenance, HomeProvenance)
        and provenance._seal is _HOME_PROVENANCE_SEAL
        and provenance.state == "HOME"
        and provenance.fresh is True
        and bool(provenance.observation_id)
        and provenance.verified_at_monotonic > 0
    )


def home_provenance_metadata(provenance: object) -> dict[str, object] | None:
    """Return JSON-safe diagnostic metadata without exposing the provenance seal."""
    if not isinstance(provenance, HomeProvenance):
        return None
    return {
        "observation_id": provenance.observation_id,
        "state": provenance.state,
        "fresh": provenance.fresh,
        "verified_at_monotonic": provenance.verified_at_monotonic,
        "valid": valid_home_provenance(provenance),
    }


@runtime_checkable
class Room(Protocol):
    """Execution contract implemented by each thin room adapter."""

    def execute(self, objective: str, context: GoalContext) -> GoalResult:
        """Execute one supplied objective; never choose a different objective."""


def canonical_room_result(result: GoalResult) -> GoalResult:
    """Expose the room contract's three outcomes without changing legacy paths.

    Existing function-based adapters retain their historical status strings.
    Only the new ``Room.execute`` adapters use this narrow normalization.
    """
    unknown_outcome = (
        result.status in {"UNKNOWN", "CONFIRMED_UNKNOWN"}
        or result.final_state in {"UNKNOWN", "CONFIRMED_UNKNOWN"}
    )
    if unknown_outcome:
        return GoalResult(
            UNKNOWN,
            result.context,
            executor=result.executor,
            final_state=result.final_state,
            committed=False,
            detail=result.detail,
        )
    if not home_entry_verified(result.context):
        return GoalResult(
            FAILED,
            result.context,
            executor=result.executor,
            final_state=result.final_state,
            committed=False,
            detail="verified HOME entry context is required",
        )
    if result.status == "DRY_RUN":
        # Dry-run is legacy simulation metadata, not a canonical room result.
        return GoalResult(
            FAILED,
            result.context,
            executor=result.executor,
            final_state=result.final_state,
            committed=False,
            detail=result.detail or "dry-run is not a canonical room result",
        )
    if (result.status in LEGACY_SUCCESS_STATUSES and result.committed
            and result.final_state == "HOME"):
        status = SUCCESS_HOME
    else:
        status = FAILED
    return GoalResult(
        status,
        result.context,
        executor=result.executor,
        final_state=result.final_state,
        committed=(status == SUCCESS_HOME),
        detail=result.detail,
    )


__all__ = [
    "Room", "SUCCESS_HOME", "FAILED", "UNKNOWN", "LEGACY_SUCCESS",
    "LEGACY_SUCCESS_STATUSES",
    "HOME_VERIFIED_PARAMETER", "HOME_FRESH_PARAMETER",
    "HOME_PROVENANCE_PARAMETER", "HomeProvenance", "issue_home_provenance",
    "valid_home_provenance", "home_provenance_metadata", "canonical_room_result",
    "home_entry_verified",
]


def home_entry_verified(context: GoalContext) -> bool:
    """Return true only for sealed provenance from a validated HOME read.

    ``home_verified``/``home_fresh`` remain accepted as legacy diagnostic
    parameters, but they are deliberately ignored for authorization.
    """
    return valid_home_provenance(
        context.parameters.get(HOME_PROVENANCE_PARAMETER),
    )
