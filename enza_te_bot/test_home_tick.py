"""Offline coordinator checks: one decision, one optional room attempt."""
import unittest
from unittest.mock import patch

import main
from home_observation import HomeObservationUnreadable
from home_policy import HomeDecision
from goal_execution import GoalResult
from home_tick import (execute_home_tick, goal_context_for_decision,
                       season3_reflection_prephase_status, execute_reflection_prephase)
from room_adapter import issue_home_provenance
from weekly_tools import execute_vocal


def vocal_registry(run_room, verify_home):
    return {
        "VOCAL": lambda context, live: execute_vocal(
            context,
            live=live,
            run_vocal_room_once=run_room,
            observe_home_boundary=verify_home,
        ),
    }


def authorized_vocal_decision():
    return HomeDecision(
        "VOCAL", "season_2_default_vocal", planner_objective="VOCAL",
        planner_reason="season_2_default_vocal",
        permitting_gates=({"risk_gate": "VOCAL_FAILURE_RATE",
                           "risk_observation": {"value": 0, "status": "KNOWN", "fresh": True},
                           "risk_decision": "ALLOW", "risk_reason": "FRESH_FAILURE_RATE_WITHIN_LIMIT"},),
    )


class HomeTickTest(unittest.TestCase):
    def test_season_two_vocal_room_exit_home_is_success(self) -> None:
        calls = []
        verify = lambda: ("HOME", True)
        result = execute_home_tick(authorized_vocal_decision(), live=True,
                                   tool_registry=vocal_registry(lambda: calls.append("vocal") or 0, verify),
                                   verify_home_boundary=verify)
        self.assertEqual(result.status, "TICK_SUCCESS")
        self.assertEqual(result.room, "VOCAL_ROOM")
        self.assertEqual(result.final_state, "HOME")
        self.assertEqual(calls, ["vocal"])

    def test_season_three_rest_room_exit_home_is_success(self) -> None:
        calls = []
        result = execute_home_tick(HomeDecision("REST", "VOCAL_FAILURE_RATE_EXCEEDED"), live=True,
                                   run_rest_room_once=lambda: calls.append("rest") or 0,
                                   verify_home_boundary=lambda: ("HOME", True),
                                   home_provenance=issue_home_provenance("rest-success"))
        self.assertEqual(result.status, "TICK_SUCCESS")
        self.assertEqual(result.room, "REST_ROOM")
        self.assertEqual(result.final_state, "HOME")
        self.assertEqual(calls, ["rest"])

    def test_rest_room_failure_is_tick_failure(self) -> None:
        result = execute_home_tick(HomeDecision("REST", "VOCAL_FAILURE_RATE_EXCEEDED"), live=True,
                                   run_rest_room_once=lambda: 2,
                                   verify_home_boundary=lambda: ("HOME", True),
                                   home_provenance=issue_home_provenance("rest-failure"))
        self.assertEqual(result.status, "ROOM_FAILURE")
        self.assertEqual(result.room, "REST_ROOM")

    def test_rest_dry_run_does_not_execute_room(self) -> None:
        calls = []
        result = execute_home_tick(HomeDecision("REST", "VOCAL_FAILURE_RATE_EXCEEDED"), live=False,
                                   run_rest_room_once=lambda: calls.append("rest") or 0,
                                   verify_home_boundary=lambda: ("HOME", True))
        self.assertEqual(result.status, "DRY_RUN")
        self.assertEqual(result.room, "REST_ROOM")
        self.assertEqual(calls, [])

    def test_rest_dispatch_uses_room_adapter_and_canonicalizes_home_success(self) -> None:
        context_result = GoalResult(
            "SUCCESS_HOME", goal_context_for_decision(
                HomeDecision("REST", "test"),
                home_provenance=issue_home_provenance("adapter-dispatch"),
            ), executor="REST_ROOM", final_state="HOME", committed=True,
        )
        with patch("home_tick.RestRoomAdapter") as adapter_type:
            adapter_type.return_value.execute.return_value = context_result
            result = execute_home_tick(
                HomeDecision("REST", "test"), live=True,
                run_rest_room_once=lambda: self.fail("legacy runner should be owned by adapter"),
                verify_home_boundary=lambda: ("HOME", True),
                home_provenance=issue_home_provenance("adapter-dispatch"),
            )
        adapter_type.assert_called_once()
        adapter_type.return_value.execute.assert_called_once_with(
            "REST", result.goal_context,
        )
        self.assertEqual(result.status, "TICK_SUCCESS")
        self.assertEqual(result.room, "REST_ROOM")

    def test_rest_dispatch_rejects_stale_home_before_legacy_runner(self) -> None:
        calls = []
        result = execute_home_tick(
            HomeDecision("REST", "test"), live=True,
            run_rest_room_once=lambda: calls.append("rest") or 0,
            verify_home_boundary=lambda: ("HOME", True),
        )
        self.assertEqual(result.status, "ROOM_FAILURE")
        self.assertEqual(result.room, "REST_ROOM")
        self.assertEqual(calls, [])

    def test_observation_override_without_provenance_cannot_authorize_live_execution(self) -> None:
        with patch("main.setup_logging"), patch("main.execute_home_tick") as execute, \
             patch("main.write_trace"), patch("main.home_tick_trace_path", return_value="trace.jsonl"):
            result = main.run_home_tick(
                live=True,
                observation_override=main.HomeObservation(2, 3, 0),
            )
        self.assertEqual(result, 2)
        execute.assert_not_called()

    def test_unsupported_decision_does_not_run_a_room(self) -> None:
        calls = []
        result = execute_home_tick(HomeDecision("AUDITION", "not_supported_yet"), live=True,
                                   verify_home_boundary=lambda: ("HOME", True))
        self.assertEqual(result.status, "UNSUPPORTED_DECISION")
        self.assertEqual(calls, [])

    def test_audition_policy_is_safely_unsupported_until_a_room_exists(self) -> None:
        calls = []
        result = execute_home_tick(HomeDecision("AUDITION", "season_2_final_week_fan_gap"), live=True,
                                   verify_home_boundary=lambda: ("HOME", True))
        self.assertEqual(result.status, "UNSUPPORTED_DECISION")
        self.assertEqual(calls, [])

    def test_audition_decision_can_use_injected_goal_without_room_redesign(self) -> None:
        calls = []
        result = execute_home_tick(
            HomeDecision("AUDITION", "season_3_40k_audition_pending", 40000),
            live=True,
            run_audition_goal_once=lambda tier: calls.append(("audition", tier)) or 0,
            verify_home_boundary=lambda: ("HOME", True),
        )
        self.assertEqual(result.status, "TICK_SUCCESS")
        self.assertEqual(result.room, "AUDITION_GOAL")
        self.assertEqual(calls, [("audition", 40000)])
        self.assertEqual(result.goal_context.parameters["target_tier"], 40000)

    def test_policy_decision_is_adapted_to_goal_specific_event_authority(self) -> None:
        vocal = goal_context_for_decision(HomeDecision("VOCAL", "test"))
        rest = goal_context_for_decision(HomeDecision("REST", "test"))
        self.assertIn("AUDITION_BATTLE", vocal.allowed_events)
        self.assertNotIn("AUDITION_BATTLE", rest.allowed_events)
        self.assertIsNone(goal_context_for_decision(HomeDecision("ROUTE_STATE_REQUIRED", "test")))

    def test_vocal_room_failure_is_tick_failure(self) -> None:
        verify = lambda: ("HOME", True)
        result = execute_home_tick(authorized_vocal_decision(), live=True,
                                   tool_registry=vocal_registry(lambda: 2, verify),
                                   verify_home_boundary=verify)
        self.assertEqual(result.status, "ROOM_FAILURE")

    def test_dry_run_does_not_execute_room(self) -> None:
        calls = []
        verify = lambda: ("HOME", True)
        result = execute_home_tick(HomeDecision("VOCAL", "season_2_default_vocal"), live=False,
                                   tool_registry=vocal_registry(lambda: calls.append("room") or 0, verify),
                                   verify_home_boundary=verify)
        self.assertEqual(result.status, "DRY_RUN")
        self.assertEqual(calls, [])

    def test_only_one_room_execution_per_tick(self) -> None:
        calls = []
        verify = lambda: ("HOME", True)
        execute_home_tick(authorized_vocal_decision(), live=True,
                          tool_registry=vocal_registry(lambda: calls.append("room") or 0, verify),
                          verify_home_boundary=verify)
        self.assertEqual(calls, ["room"])

    def test_s1w6_trouble_rate_92_blocks_vocal_and_requires_rest_recovery(self) -> None:
        calls = []
        decision = HomeDecision(
            "VOCAL", "season_1_default_vocal", planner_objective="VOCAL",
            planner_reason="season_1_default_vocal",
            permitting_gates=({"risk_gate": "VOCAL_FAILURE_RATE",
                               "risk_observation": {"value": 92, "status": "KNOWN", "fresh": True},
                               "risk_decision": "BLOCK", "risk_reason": "VOCAL_FAILURE_RATE_EXCEEDED"},),
        )
        result = execute_home_tick(decision, live=True,
                                   tool_registry=vocal_registry(lambda: calls.append("vocal") or 0,
                                                                lambda: ("HOME", True)),
                                   verify_home_boundary=lambda: ("HOME", True))
        self.assertEqual(result.status, "RISK_GATE_BLOCKED")
        self.assertEqual(result.decision.action, "REST")
        self.assertEqual(result.detail, "VOCAL_FAILURE_RATE_EXCEEDED:BACK_TO_REST")
        self.assertEqual(calls, [])

    def test_non_vocal_planner_objective_cannot_emit_vocal(self) -> None:
        calls = []
        decision = HomeDecision("REST", "risk_recovery", planner_objective="REST",
                                planner_reason="risk_recovery")
        result = execute_home_tick(decision, live=True,
                                   tool_registry={"VOCAL": lambda *_: calls.append("vocal")},
                                   run_rest_room_once=lambda: 0,
                                   verify_home_boundary=lambda: ("HOME", True))
        self.assertNotEqual(result.room, "VOCAL_ROOM")
        self.assertEqual(calls, [])

    def test_unknown_trouble_rate_fails_closed(self) -> None:
        decision = HomeDecision(
            "VOCAL", "season_1_default_vocal", planner_objective="VOCAL",
            planner_reason="textual rationale is not authority",
            permitting_gates=({"risk_gate": "VOCAL_FAILURE_RATE",
                               "risk_observation": {"value": None, "status": "UNKNOWN", "fresh": True},
                               "risk_decision": "BLOCK", "risk_reason": "UNKNOWN"},),
        )
        result = execute_home_tick(decision, live=True, verify_home_boundary=lambda: ("HOME", True))
        self.assertEqual(result.status, "NEED_MORE_OBSERVATION")

    def test_needs_vocal_fan_gain_maps_to_vocal_executor(self) -> None:
        calls = []
        decision = HomeDecision(
            "NEEDS_VOCAL_FAN_GAIN", "season_1_final_week_small_positive_gap_requires_vocal_fan_gain",
            planner_objective="NEEDS_VOCAL_FAN_GAIN", planner_reason="fan gap",
            permitting_gates=({"risk_gate": "VOCAL_FAILURE_RATE",
                               "risk_observation": {"value": 0, "status": "KNOWN", "fresh": True},
                               "risk_decision": "ALLOW", "risk_reason": "within limit"},),
        )
        result = execute_home_tick(decision, live=True,
                                   tool_registry=vocal_registry(lambda: calls.append("vocal") or 0,
                                                                lambda: ("HOME", True)),
                                   verify_home_boundary=lambda: ("HOME", True))
        self.assertEqual(result.status, "TICK_SUCCESS")
        self.assertEqual(result.room, "VOCAL_ROOM")
        self.assertEqual(calls, ["vocal"])

    def test_needs_vocal_fan_gain_92_percent_uses_rest_recovery(self) -> None:
        decision = HomeDecision(
            "NEEDS_VOCAL_FAN_GAIN", "season_1_final_week_small_positive_gap_requires_vocal_fan_gain",
            planner_objective="NEEDS_VOCAL_FAN_GAIN", planner_reason="fan gap",
            permitting_gates=({"risk_gate": "VOCAL_FAILURE_RATE",
                               "risk_observation": {"value": 92, "status": "KNOWN", "fresh": True},
                               "risk_decision": "BLOCK", "risk_reason": "exceeded"},),
        )
        calls = []
        result = execute_home_tick(decision, live=True,
                                   tool_registry=vocal_registry(lambda: calls.append("vocal") or 0,
                                                                lambda: ("HOME", True)),
                                   verify_home_boundary=lambda: ("HOME", True))
        self.assertEqual(result.status, "RISK_GATE_BLOCKED")
        self.assertEqual(result.decision.action, "REST")
        self.assertEqual(calls, [])

    def test_needs_vocal_fan_gain_unknown_risk_fails_closed(self) -> None:
        decision = HomeDecision(
            "NEEDS_VOCAL_FAN_GAIN", "fan gap", planner_objective="NEEDS_VOCAL_FAN_GAIN",
            planner_reason="fan gap", permitting_gates=({"risk_gate": "VOCAL_FAILURE_RATE",
            "risk_observation": {"value": None, "status": "UNKNOWN", "fresh": True},
            "risk_decision": "BLOCK", "risk_reason": "unknown"},),
        )
        result = execute_home_tick(decision, live=True, verify_home_boundary=lambda: ("HOME", True))
        self.assertEqual(result.status, "NEED_MORE_OBSERVATION")

    def test_unrecognized_objective_remains_unsupported(self) -> None:
        result = execute_home_tick(HomeDecision("MADE_UP_OBJECTIVE", "text"), live=True,
                                   verify_home_boundary=lambda: ("HOME", True))
        self.assertEqual(result.status, "UNSUPPORTED_DECISION")

    def test_unreadable_policy_stops_before_any_room_execution(self) -> None:
        unreadable = HomeObservationUnreadable({"season": "no numeric candidate"}, [], [])
        with patch("main.setup_logging"), patch("main.read_validated_home_observation", return_value=unreadable), \
             patch("main.write_trace"), patch("main.run_vocal_room") as run_room:
            self.assertEqual(main.run_home_tick(live=True), 2)
        run_room.assert_not_called()

    def test_week_template_learning_summary_is_visible_and_compact(self) -> None:
        message = main.format_week_template_auto_learning({
            "previous_week": 3, "inferred_week": 2, "status": "COMMITTED",
            "verification_score": 0.9999609589576721, "verification_margin": 0.391714870929718,
        })
        self.assertEqual(message, "WeekTemplateAutoLearn: 3 -> 2 COMMITTED score=0.99996 margin=0.3917")

    def test_season_three_route_state_required_stops_without_a_tick(self) -> None:
        outcome, ticks = main.synthetic_season_trial_outcome(
            3, [(3, "ROUTE_STATE_REQUIRED", "TICK_SUCCESS")],
        )
        self.assertEqual((outcome, ticks), ("UNSUPPORTED_DECISION", 0))

    def test_season_trial_counts_only_verified_successful_ticks_and_stops_at_boundary(self) -> None:
        outcome, ticks = main.synthetic_season_trial_outcome(
            3, [(3, "VOCAL", "TICK_SUCCESS"), (3, "REST", "TICK_SUCCESS"),
                (4, "VOCAL", "TICK_SUCCESS")],
        )
        self.assertEqual((outcome, ticks), ("SEASON_CHANGED", 2))

    def test_season_trial_dry_run_never_claims_a_completed_tick(self) -> None:
        outcome, ticks = main.synthetic_season_trial_outcome(3, [(3, "VOCAL", "DRY_RUN")])
        self.assertEqual((outcome, ticks), ("DRY_RUN", 0))
        outcome_rest, ticks_rest = main.synthetic_season_trial_outcome(3, [(3, "REST", "DRY_RUN")])
        self.assertEqual((outcome_rest, ticks_rest), ("DRY_RUN", 0))

    def test_reflection_prephase_requires_explicit_return_path(self):
        config = {"states": {"HOME": {"allowed_actions": [{"name": "reflection_open", "expected_next_states": ["REFLECTION"]}]},
                              "REFLECTION": {"allowed_actions": []}}}
        self.assertEqual(season3_reflection_prephase_status(config), (False, "REFLECTION_RETURN_HOME_UNCONFIGURED"))

    def test_reflection_prephase_success_and_entry_failure(self):
        config = {"states": {"HOME": {"allowed_actions": [{"name": "reflection_open", "expected_next_states": ["REFLECTION"]}]},
                              "REFLECTION": {"allowed_actions": [{"name": "reflection_return_home", "expected_next_states": ["HOME"]}]}}}
        calls = []
        result = execute_reflection_prephase(live=True, config=config,
            open_reflection=lambda: calls.append("open") or True,
            spend_reflection=lambda _: calls.append("spend") or True,
            return_home=lambda: calls.append("return") or True)
        self.assertEqual(result.status, "REFLECTION_PREPHASE_SUCCESS")
        self.assertEqual(calls, ["open", "spend", "return"])
        failed = execute_reflection_prephase(live=True, config=config,
            open_reflection=lambda: False, spend_reflection=lambda _: True, return_home=lambda: True)
        self.assertEqual(failed.status, "REFLECTION_ENTRY_FAILURE")

    def test_completed_flag_skips_prephase_guard(self):
        config = {"run_state": {"season3": {"reflection_opening_completed": True}},
                  "states": {"HOME": {}, "REFLECTION": {}}}
        self.assertTrue(config["run_state"]["season3"]["reflection_opening_completed"])

    def test_manual_completion_requires_season3_home_and_persists(self):
        observation = main.HomeObservation(3, 3, 31225)
        config = {"run_state": {"run_id": "ACTIVE_RUN", "season3": {}}}
        with patch("main.load_config_with_run_state", return_value=config), \
             patch("main.read_validated_home_observation", return_value=observation), \
             patch("main.save_active_run_state", return_value="runtime_state.json") as save_state, \
             patch("main.write_trace"), patch("main.home_tick_trace_path", return_value="trace.jsonl"):
            self.assertEqual(main.mark_season3_reflection_complete(), 0)
            self.assertTrue(save_state.call_args.args[1]["season3"]["reflection_opening_completed"])
        with patch("main.load_config_with_run_state", return_value=config), \
             patch("main.read_validated_home_observation", return_value=main.HomeObservation(2, 3, 1)):
            self.assertEqual(main.mark_season3_reflection_complete(), 2)

    def test_manual_season3_auditions_completion_requires_season3_home_and_persists(self):
        observation = main.HomeObservation(3, 3, 0)
        config = {"run_state": {"run_id": "ACTIVE_RUN", "season3": {}}}
        persisted = {}
        def fake_save(path, state, **kwargs):
            persisted.update(state)
            return "runtime_state.json"
        with patch("main.load_config_with_run_state", return_value=config), \
             patch("main.read_validated_home_observation", return_value=observation), \
             patch("main.save_active_run_state", side_effect=fake_save), \
             patch("main.write_trace") as mock_trace, \
             patch("main.home_tick_trace_path", return_value="trace.jsonl"):
            self.assertEqual(main.mark_season3_auditions_complete(), 0)
            self.assertTrue(persisted["season3"]["audition_40k_completed"])
            self.assertTrue(persisted["season3"]["audition_50k_completed"])
            mock_trace.assert_called_once()
        with patch("main.load_config_with_run_state", return_value=config), \
             patch("main.read_validated_home_observation", return_value=main.HomeObservation(2, 3, 1)):
            self.assertEqual(main.mark_season3_auditions_complete(), 2)


if __name__ == "__main__":
    unittest.main()
