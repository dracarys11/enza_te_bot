"""Thin goal-execution boundary over existing verified room executors.

This module deliberately does not replace rooms or perception.  A room remains
an internal bounded executor; the goal layer owns the terminal contract and
commit decision.  Event resolution is a small, deterministic policy boundary
that existing handlers can adopt incrementally without adding more room-local
interruption lists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping


DEFAULT_PROTECTED_EVENTS = frozenset({
    "CHOICE_REQUIRED",
    "AUDITION_CHOICE",
    "CONFIRM",
    "PROMISE_CHOICE",
    "ERROR_POPUP",
})


@dataclass(frozen=True)
class GoalContext:
    """Execution contract for one bounded objective started from HOME."""

    goal: str
    success_state: str = "HOME"
    parameters: Mapping[str, object] = field(default_factory=dict)
    allowed_events: frozenset[str] = field(default_factory=frozenset)
    protected_events: frozenset[str] = DEFAULT_PROTECTED_EVENTS


@dataclass(frozen=True)
class GoalResult:
    """Outcome of a goal; success is committed only at its terminal boundary."""

    status: str
    context: GoalContext
    executor: str | None = None
    final_state: str | None = None
    committed: bool = False
    detail: str | None = None


@dataclass(frozen=True)
class EventResolution:
    """Goal-local interpretation of an observation, not a vision decision."""

    disposition: str
    state: str
    handler: str | None = None


def validate_goal_deadline(context: GoalContext) -> tuple[bool, str | None]:
    """Reject a goal that conflicts with an attached fresh route deadline."""
    deadline = context.parameters.get("route_deadline")
    if deadline is None:
        return True, None
    if not isinstance(deadline, Mapping):
        return False, "ROUTE_DEADLINE_STATE_INVALID"
    remaining_weeks = deadline.get("remaining_weeks")
    remaining_steps = deadline.get("remaining_required_route_steps")
    next_action = deadline.get("next_route_action")
    valid_count = (
        isinstance(remaining_weeks, int) and not isinstance(remaining_weeks, bool)
        and isinstance(remaining_steps, int) and not isinstance(remaining_steps, bool)
        and remaining_steps >= 0
    )
    if not valid_count:
        return False, "ROUTE_DEADLINE_STATE_INVALID"
    if remaining_steps > 0 and remaining_weeks <= remaining_steps:
        if not isinstance(next_action, str) or not next_action:
            return False, "NEXT_REQUIRED_ROUTE_ACTION_UNKNOWN"
        if context.goal != next_action:
            return False, "LOW_PRIORITY_ACTION_FORBIDDEN_AT_ROUTE_DEADLINE"
    return True, None


def resolve_goal_event(context: GoalContext, state: str) -> EventResolution:
    """Classify one observed state using goal safety/authorization policy.

    This function never clicks and never turns an arbitrary known or UNKNOWN
    state into permission to proceed.
    """
    if state == context.success_state:
        return EventResolution("TERMINAL", state)
    if state in context.protected_events:
        return EventResolution("PROTECTED_STOP", state)
    if state == "UNKNOWN":
        return EventResolution("UNKNOWN_STOP", state)
    if state in context.allowed_events:
        return EventResolution("DISPATCH", state, handler=state)
    return EventResolution("UNSUPPORTED_STOP", state)


def execute_goal(context: GoalContext, *, live: bool, executor_name: str,
                 run_executor: Callable[[], int],
                 verify_terminal_boundary: Callable[[], tuple[str, bool]]) -> GoalResult:
    """Run one legacy executor once and commit only at the verified terminal."""
    deadline_allowed, deadline_reason = validate_goal_deadline(context)
    if not deadline_allowed:
        return GoalResult(
            "DEADLINE_GUARD_FAILURE", context, executor=executor_name,
            detail=deadline_reason,
        )
    if not live:
        return GoalResult(
            "DRY_RUN", context, executor=executor_name,
            detail=f"would execute one bounded {executor_name}",
        )
    executor_code = run_executor()
    if executor_code != 0:
        return GoalResult(
            "EXECUTOR_FAILURE", context, executor=executor_name,
            detail=f"{executor_name} returned {executor_code}",
        )
    final_state, terminal_verified = verify_terminal_boundary()
    resolution = resolve_goal_event(context, final_state)
    if not terminal_verified or resolution.disposition != "TERMINAL":
        return GoalResult(
            "BOUNDARY_FAILURE", context, executor=executor_name,
            final_state=final_state,
            detail=(f"{executor_name} returned success but final "
                    f"{context.success_state} boundary was not reverified"),
        )
    return GoalResult(
        "GOAL_SUCCESS", context, executor=executor_name,
        final_state=final_state, committed=True,
        detail=f"{executor_name} completed at verified {context.success_state}",
    )
