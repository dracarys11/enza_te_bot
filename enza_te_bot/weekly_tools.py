"""Thin task adapters over existing verified weekly executors."""
from __future__ import annotations

from typing import Callable

from goal_execution import GoalContext, GoalResult, execute_goal
from room_adapter import Room, canonical_room_result, home_entry_verified


def execute_vocal(context: GoalContext, *, live: bool,
                  run_vocal_room_once: Callable[[], int],
                  observe_home_boundary: Callable[[], tuple[str, bool]]) -> GoalResult:
    """Execute the legacy VOCAL room and commit only after a fresh HOME check.

    The adapter intentionally owns no VOCAL clicks, state transitions, or
    interruption handlers.  Those remain in the verified legacy executor.
    """
    if context.goal != "VOCAL":
        return GoalResult(
            "INVALID_GOAL", context, executor="VOCAL_ROOM",
            detail=f"VOCAL tool cannot execute goal {context.goal!r}",
        )
    return execute_goal(
        context,
        live=live,
        executor_name="VOCAL_ROOM",
        run_executor=run_vocal_room_once,
        verify_terminal_boundary=observe_home_boundary,
    )


def execute_rest(context: GoalContext, *, live: bool,
                 run_rest_room_once: Callable[[], int],
                 observe_home_boundary: Callable[[], tuple[str, bool]]) -> GoalResult:
    """Execute the legacy REST room and verify its fresh HOME boundary."""
    if context.goal != "REST":
        return GoalResult(
            "INVALID_GOAL", context, executor="REST_ROOM",
            detail=f"REST tool cannot execute goal {context.goal!r}",
        )
    return execute_goal(
        context,
        live=live,
        executor_name="REST_ROOM",
        run_executor=run_rest_room_once,
        verify_terminal_boundary=observe_home_boundary,
    )


class VocalRoomAdapter:
    """Room contract wrapper around the existing VOCAL implementation."""

    def __init__(self, *, live: bool,
                 run_vocal_room_once: Callable[[], int],
                 observe_home_boundary: Callable[[], tuple[str, bool]]) -> None:
        self._live = live
        self._run_vocal_room_once = run_vocal_room_once
        self._observe_home_boundary = observe_home_boundary

    def execute(self, objective: str, context: GoalContext) -> GoalResult:
        if objective != "VOCAL" or context.goal != "VOCAL":
            return canonical_room_result(GoalResult(
                "INVALID_GOAL", context, executor="VOCAL_ROOM",
                detail=f"VOCAL room cannot execute objective {objective!r}",
            ))
        if not home_entry_verified(context):
            return canonical_room_result(GoalResult(
                "INVALID_GOAL", context, executor="VOCAL_ROOM",
                detail="verified HOME entry context is required",
            ))
        return canonical_room_result(execute_vocal(
            context,
            live=self._live,
            run_vocal_room_once=self._run_vocal_room_once,
            observe_home_boundary=self._observe_home_boundary,
        ))


class RestRoomAdapter:
    """Room contract wrapper around the existing REST implementation."""

    def __init__(self, *, live: bool,
                 run_rest_room_once: Callable[[], int],
                 observe_home_boundary: Callable[[], tuple[str, bool]]) -> None:
        self._live = live
        self._run_rest_room_once = run_rest_room_once
        self._observe_home_boundary = observe_home_boundary

    def execute(self, objective: str, context: GoalContext) -> GoalResult:
        if objective != "REST" or context.goal != "REST":
            return canonical_room_result(GoalResult(
                "INVALID_GOAL", context, executor="REST_ROOM",
                detail=f"REST room cannot execute objective {objective!r}",
            ))
        if not home_entry_verified(context):
            return canonical_room_result(GoalResult(
                "INVALID_GOAL", context, executor="REST_ROOM",
                detail="verified HOME entry context is required",
            ))
        return canonical_room_result(execute_rest(
            context,
            live=self._live,
            run_rest_room_once=self._run_rest_room_once,
            observe_home_boundary=self._observe_home_boundary,
        ))


__all__ = [
    "Room", "execute_vocal", "execute_rest", "VocalRoomAdapter", "RestRoomAdapter",
]
