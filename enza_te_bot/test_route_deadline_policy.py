import unittest

from goal_execution import GoalContext, execute_goal, validate_goal_deadline
from home_observation import HomeObservation
from home_policy import (HomeDecision, decide_home, resolve_policy_state,
                         route_capacity_from_state)


def route_plan(*, season: int, weeks: int, mandatory_steps: int,
               retry_budget: int = 0, transition_margin: int = 0,
               next_action: str = "AUDITION", pre_action: str = "VOCAL") -> dict:
    return {
        "fresh": True,
        "season": season,
        "as_of_weeks_remaining": weeks,
        "mandatory_steps": mandatory_steps,
        "retry_budget": retry_budget,
        "transition_margin": transition_margin,
        "next_route_action": next_action,
        "next_route_target_tier": 100000,
        "pre_deadline_action": pre_action,
    }


def decide_s4(weeks: int, mandatory_steps: int, *, retry_budget: int = 0,
              transition_margin: int = 0, plan_weeks: int | None = None,
              plan_season: int = 4):
    plan = route_plan(
        season=plan_season,
        weeks=weeks if plan_weeks is None else plan_weeks,
        mandatory_steps=mandatory_steps,
        retry_budget=retry_budget,
        transition_margin=transition_margin,
    )
    state = resolve_policy_state(season=4, weeks_remaining=weeks, route_plan=plan)
    state["vocal_failure_rate_observation"] = {"value": 0, "status": "KNOWN", "fresh": True}
    return decide_home(HomeObservation(4, weeks, 0), state, {})


class RouteDeadlinePolicyTests(unittest.TestCase):
    def test_before_deadline_normal_training_is_allowed(self):
        decision = decide_s4(8, 4, retry_budget=1, transition_margin=1)
        self.assertEqual((decision.action, decision.reason),
                         ("VOCAL", "season_4_pre_deadline_action"))
        self.assertEqual(decision.route_deadline["remaining_weeks"], 8)
        self.assertEqual(decision.route_deadline["remaining_required_route_steps"], 6)

    def test_latest_safe_start_week_forces_route(self):
        decision = decide_s4(6, 4, retry_budget=1, transition_margin=1)
        self.assertEqual(decision.action, "AUDITION")
        self.assertIn("ROUTE_DEADLINE_REACHED", decision.reason)

    def test_one_week_remaining_forbids_training(self):
        decision = decide_s4(1, 1)
        self.assertEqual(decision.action, "AUDITION")
        self.assertNotEqual(decision.action, "VOCAL")
        self.assertIn("LOW_PRIORITY_TRAINING_FORBIDDEN", decision.reason)

    def test_failed_route_step_requires_fresh_replan(self):
        stale_after_failure = decide_s4(
            4, 4, retry_budget=1, plan_weeks=5,
        )
        self.assertEqual(stale_after_failure.status, "NEED_MORE_OBSERVATION")
        self.assertEqual(stale_after_failure.reason,
                         "ROUTE_DEADLINE_WEEK_RECONCILIATION_REQUIRED")

        replanned = decide_s4(4, 4, retry_budget=0)
        self.assertEqual(replanned.action, "AUDITION")
        self.assertIn("ROUTE_DEADLINE_REACHED", replanned.reason)
        self.assertEqual(replanned.route_deadline["safe_required_steps"], 4)

    def test_season_transition_rejects_previous_season_route_state(self):
        decision = decide_s4(8, 1, plan_weeks=1, plan_season=3)
        self.assertEqual(decision.status, "NEED_MORE_OBSERVATION")
        self.assertEqual(decision.reason,
                         "SEASON_TRANSITION_RECONCILIATION_REQUIRED")

    def test_execution_boundary_rejects_forged_low_priority_goal(self):
        calls = []
        context = GoalContext(
            "VOCAL",
            parameters={
                "route_deadline": {
                    "remaining_weeks": 6,
                    "remaining_required_route_steps": 6,
                    "next_route_action": "AUDITION",
                }
            },
        )
        allowed, reason = validate_goal_deadline(context)
        self.assertFalse(allowed)
        self.assertEqual(reason, "LOW_PRIORITY_ACTION_FORBIDDEN_AT_ROUTE_DEADLINE")
        result = execute_goal(
            context,
            live=True,
            executor_name="VOCAL_ROOM",
            run_executor=lambda: calls.append("run") or 0,
            verify_terminal_boundary=lambda: calls.append("verify") or ("HOME", True),
        )
        self.assertEqual(result.status, "DEADLINE_GUARD_FAILURE")
        self.assertEqual(calls, [])

    def test_unknown_required_step_count_stays_unknown(self):
        plan = route_plan(season=4, weeks=6, mandatory_steps=4)
        plan["retry_budget"] = None
        state = resolve_policy_state(season=4, weeks_remaining=6, route_plan=plan)
        decision = decide_home(HomeObservation(4, 6, 0), state, {})
        self.assertEqual(decision.status, "NEED_MORE_OBSERVATION")
        self.assertEqual(decision.reason, "ROUTE_CAPACITY_COMPONENT_INVALID:retry_budget")

    def test_retry_budget_zero_is_explicit_capacity(self):
        capacity = route_capacity_from_state({
            "mandatory_steps": 4,
            "retry_budget": 0,
            "transition_margin": 1,
        })
        self.assertEqual(capacity["safe_required_steps"], 5)
        self.assertEqual(capacity["remaining_required_route_steps"], 5)

    def test_retry_budget_one_adds_one_explicit_step(self):
        capacity = route_capacity_from_state({
            "mandatory_steps": 4,
            "retry_budget": 1,
            "transition_margin": 1,
        })
        self.assertEqual(capacity["safe_required_steps"], 6)

    def test_manual_derived_step_input_is_rejected(self):
        plan = route_plan(season=4, weeks=6, mandatory_steps=4)
        plan["remaining_required_route_steps"] = 4
        state = resolve_policy_state(season=4, weeks_remaining=6, route_plan=plan)
        decision = decide_home(HomeObservation(4, 6, 0), state, {})
        self.assertEqual(decision.status, "NEED_MORE_OBSERVATION")
        self.assertEqual(decision.reason,
                         "ROUTE_CAPACITY_DERIVED_FIELD_MUST_NOT_BE_SUPPLIED")


if __name__ == "__main__":
    unittest.main()
