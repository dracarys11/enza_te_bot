"""One bounded HOME decision coordinator; no policy or room implementation."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Mapping

from goal_execution import GoalContext, GoalResult, execute_goal, validate_goal_deadline
from home_policy import HomeDecision
from room_adapter import HomeProvenance, HOME_PROVENANCE_PARAMETER
from weekly_tools import RestRoomAdapter


@dataclass(frozen=True)
class HomeTickResult:
    status: str
    decision: HomeDecision
    room: str | None = None
    final_state: str | None = None
    detail: str | None = None
    goal_context: GoalContext | None = None


def goal_context_for_decision(decision: HomeDecision, *, home_verified: bool = False,
                              home_fresh: bool = False,
                              home_provenance: HomeProvenance | None = None) -> GoalContext | None:
    """Translate pure policy output into an execution contract."""
    allowed_events_by_goal = {
        "VOCAL": frozenset({
            "DIALOGUE_FAST_FORWARD_OFF",
            "AUDITION_RESULT_DIALOGUE",
            "AUDITION_BATTLE",
            "SEASON_CLEAR",
            "SEASON_RESULT",
        }),
        "REST": frozenset({
            "DIALOGUE_FAST_FORWARD_OFF",
            "SEASON_CLEAR",
            "SEASON_RESULT",
        }),
        "AUDITION": frozenset({
            "DIALOGUE_FAST_FORWARD_OFF",
            "AUDITION_RESULT_DIALOGUE",
            "AUDITION_BATTLE",
            "SEASON_CLEAR",
            "SEASON_RESULT",
        }),
    }
    allowed_events = allowed_events_by_goal.get(decision.action)
    if allowed_events is None:
        return None
    parameters: dict[str, object] = {
        "reason": decision.reason,
        "planner_objective": decision.planner_objective,
        "planner_reason": decision.planner_reason,
        "permitting_gates": [dict(gate) for gate in decision.permitting_gates],
        "home_verified": home_verified,
        "home_fresh": home_fresh,
    }
    if home_provenance is not None:
        parameters[HOME_PROVENANCE_PARAMETER] = home_provenance
    if decision.target_tier is not None:
        parameters["target_tier"] = decision.target_tier
    if decision.route_deadline is not None:
        parameters["route_deadline"] = dict(decision.route_deadline)
    return GoalContext(
        goal=decision.action,
        success_state="HOME",
        parameters=parameters,
        allowed_events=allowed_events,
    )


def season3_reflection_prephase_status(config: dict) -> tuple[bool, str]:
    """Validate the explicit REFLECTION bridge without inventing a return click."""
    home = config.get("states", {}).get("HOME", {})
    reflection = config.get("states", {}).get("REFLECTION", {})
    home_actions = {a.get("name"): a for a in home.get("allowed_actions", [])}
    reflection_actions = {a.get("name"): a for a in reflection.get("allowed_actions", [])}
    opening = home_actions.get("reflection_open")
    if not opening or "REFLECTION" not in opening.get("expected_next_states", []):
        return False, "REFLECTION_OPEN_PATH_UNCONFIGURED"
    returning = reflection_actions.get("reflection_return_home")
    if not returning or "HOME" not in returning.get("expected_next_states", []):
        return False, "REFLECTION_RETURN_HOME_UNCONFIGURED"
    return True, "REFLECTION_PREPHASE_READY"


def execute_reflection_prephase(*, live: bool, config: dict, open_reflection: Callable[[], bool],
                                spend_reflection: Callable[[bool], bool], return_home: Callable[[], bool]) -> HomeTickResult:
    """Run one bounded Season-3 reflection bridge using injected room operations."""
    decision = HomeDecision("REFLECTION_PREPHASE", "season_3_opening_reflection")
    ready, reason = season3_reflection_prephase_status(config)
    if not ready:
        return HomeTickResult("UNSUPPORTED_REFLECTION", decision, detail=reason)
    if not live:
        return HomeTickResult("DRY_RUN", decision, room="REFLECTION", detail="would open, spend, and return HOME")
    if not open_reflection():
        return HomeTickResult("REFLECTION_ENTRY_FAILURE", decision, room="REFLECTION")
    if not spend_reflection(True):
        return HomeTickResult("REFLECTION_SPENDING_FAILURE", decision, room="REFLECTION")
    if not return_home():
        return HomeTickResult("REFLECTION_EXIT_FAILURE", decision, room="REFLECTION")
    return HomeTickResult("REFLECTION_PREPHASE_SUCCESS", decision, room="REFLECTION", final_state="HOME")


def execute_home_tick(decision: HomeDecision, *, live: bool,
                      tool_registry: Mapping[str, Callable[[GoalContext, bool], GoalResult]] | None = None,
                      run_rest_room_once: Callable[[], int] | None = None,
                      run_audition_goal_once: Callable[[int | None], int] | None = None,
                      verify_home_boundary: Callable[[], tuple[str, bool]],
                      home_verified: bool = False,
                      home_fresh: bool = False,
                      home_provenance: HomeProvenance | None = None) -> HomeTickResult:
    """Adapt one policy decision to a bounded goal over a legacy executor."""
    # This is the sole planner-to-executor semantic mapping.  The planner
    # objective remains intact for traceability; only the executor intent is
    # normalized to the existing VOCAL room contract.
    vocal_fan_gain = decision.action == "NEEDS_VOCAL_FAN_GAIN"
    execution_decision = (replace(decision, action="VOCAL")
                          if vocal_fan_gain else decision)
    context = goal_context_for_decision(
        execution_decision,
        home_verified=home_verified,
        home_fresh=home_fresh,
        home_provenance=home_provenance,
    )
    if context is None:
        return HomeTickResult("UNSUPPORTED_DECISION", decision, detail="no supported goal executor")
    deadline_allowed, deadline_reason = validate_goal_deadline(context)
    if not deadline_allowed:
        return HomeTickResult(
            "DEADLINE_GUARD_FAILURE", decision,
            detail=deadline_reason, goal_context=context,
        )
    if execution_decision.action == "VOCAL":
        if live:
            # Live execution accepts VOCAL only from the Python planner and its
            # fresh risk gate.  Textual rationale and a bare action label have
            # no authority here.
            if decision.planner_objective not in {"VOCAL", "NEEDS_VOCAL_FAN_GAIN"}:
                return HomeTickResult("AUTHORITY_FAILURE", decision,
                                      detail="PLANNER_OBJECTIVE_REQUIRED", goal_context=context)
            gates = decision.permitting_gates
            vocal_gate = next((gate for gate in gates
                               if gate.get("risk_gate") == "VOCAL_FAILURE_RATE"), None)
            observation = vocal_gate.get("risk_observation") if vocal_gate else None
            if (not isinstance(observation, Mapping)
                    or observation.get("fresh") is not True
                    or observation.get("status") != "KNOWN"
                    or not isinstance(observation.get("value"), (int, float))
                    or isinstance(observation.get("value"), bool)):
                return HomeTickResult("NEED_MORE_OBSERVATION", decision,
                                      detail="VOCAL_FAILURE_RATE_FRESH_READ_REQUIRED", goal_context=context)
            if float(observation["value"]) > 2 or vocal_gate.get("risk_decision") != "ALLOW":
                recovery = replace(decision, action="REST", reason="VOCAL_FAILURE_RATE_EXCEEDED:BACK_TO_REST",
                                   planner_objective="REST", planner_reason="risk_gate_recovery")
                return HomeTickResult("RISK_GATE_BLOCKED", recovery,
                                      detail="VOCAL_FAILURE_RATE_EXCEEDED:BACK_TO_REST", goal_context=context)
        vocal_tool = (tool_registry or {}).get("VOCAL")
        if vocal_tool is None:
            return HomeTickResult("UNSUPPORTED_DECISION", decision, detail="VOCAL tool is not registered")
        goal_result = vocal_tool(context, live)
        status_map = {
            "GOAL_SUCCESS": "TICK_SUCCESS",
            "EXECUTOR_FAILURE": "ROOM_FAILURE",
        }
        return HomeTickResult(
            status_map.get(goal_result.status, goal_result.status),
            decision,
            room=goal_result.executor,
            final_state=goal_result.final_state,
            detail=goal_result.detail,
            goal_context=context,
        )
    runners: dict[str, tuple[str, Callable[[], int] | None]] = {
        "REST": ("REST_ROOM", run_rest_room_once),
        "AUDITION": (
            "AUDITION_GOAL",
            ((lambda: run_audition_goal_once(decision.target_tier))
             if run_audition_goal_once is not None else None),
        ),
    }
    selected = runners.get(decision.action)
    if selected is None or selected[1] is None:
        return HomeTickResult("UNSUPPORTED_DECISION", decision, detail="no supported goal executor")
    executor_name, runner = selected
    if decision.action == "REST":
        # REST is the first production dispatch through the canonical Room
        # adapter.  Preserve the existing dry-run status outside that
        # canonical contract; no legacy executor is called in dry-run mode.
        if not live:
            return HomeTickResult(
                "DRY_RUN", decision, room=executor_name,
                detail=f"would execute one bounded {executor_name}",
                goal_context=context,
            )
        goal_result = RestRoomAdapter(
            live=live,
            run_rest_room_once=runner,
            observe_home_boundary=verify_home_boundary,
        ).execute("REST", context)
        status_map = {
            "SUCCESS_HOME": "TICK_SUCCESS",
            "FAILED": "ROOM_FAILURE",
        }
        return HomeTickResult(
            status_map.get(goal_result.status, goal_result.status),
            decision,
            room=goal_result.executor or executor_name,
            final_state=goal_result.final_state,
            detail=goal_result.detail,
            goal_context=context,
        )
    goal_result = execute_goal(
        context,
        live=live,
        executor_name=executor_name,
        run_executor=runner,
        verify_terminal_boundary=verify_home_boundary,
    )
    status_map = {
        "GOAL_SUCCESS": "TICK_SUCCESS",
        "EXECUTOR_FAILURE": "ROOM_FAILURE",
    }
    return HomeTickResult(
        status_map.get(goal_result.status, goal_result.status),
        decision,
        room=executor_name,
        final_state=goal_result.final_state,
        detail=goal_result.detail,
        goal_context=context,
    )
