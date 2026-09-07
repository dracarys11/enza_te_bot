"""Offline regression checks for room-to-shared-transition lookup."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from main import (BASE_DIR, Detection, classify_local_transition, dialogue_outcome,
                  configured_action,
                  known_control_capability,
                  post_vocal_deadline, post_vocal_outcome, room_step_action,
                  synthetic_dialogue_outcome, synthetic_local_interruption_outcome,
                  synthetic_accelerated_post_vocal_outcome,
                  synthetic_audition_battle_outcome,
                  synthetic_battle_speed_target,
                  synthetic_capability_dispatch_outcome,
                  synthetic_safe_unknown_prior_outcome,
                  synthetic_post_vocal_outcome, synthetic_promise_transition_outcome,
                  synthetic_post_audition_cleanup_outcome,
                  post_audition_entry_allowed,
                  observe_post_vocal_transition,
                  synthetic_post_audition_drain_outcome,
                  synthetic_short_unknown_outcome, synthetic_unknown_outcome,
                  synthetic_vocal_pending_path, transition_accelerator_points,
                  run_transition_accelerator_burst)
from vision import detect_safe_pink_cta


class RoomRegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.config = json.loads((Path(BASE_DIR) / "config.json").read_text(encoding="utf-8"))
        self.steps = self.config["rooms"]["VOCAL_ROOM"]["local_steps"]

    def test_vocal_room_steps_resolve_from_shared_state_actions(self) -> None:
        first, second = (room_step_action(self.config, step) for step in self.steps)
        self.assertEqual(first["name"], "produce_start")
        self.assertEqual(first, self.config["states"]["HOME"]["allowed_actions"][0])
        self.assertEqual(second["name"], "vocal_lesson")
        self.assertEqual(second, self.config["states"]["PRODUCE_MENU"]["allowed_actions"][0])

    def test_named_room_lookup_remains_unambiguous_with_multiple_menu_actions(self) -> None:
        config = json.loads(json.dumps(self.config))
        config["states"]["AUDITION_SELECT"] = {"templates": [], "allowed_actions": []}
        config["states"]["PRODUCE_MENU"]["allowed_actions"].append({
            "name": "audition_start", "type": "click", "box": [0.4, 0.4, 0.5, 0.5],
            "expected_next_states": ["AUDITION_SELECT"],
        })
        self.assertEqual(configured_action(config, "PRODUCE_MENU", "vocal_lesson")["name"], "vocal_lesson")
        self.assertEqual(configured_action(config, "PRODUCE_MENU", "audition_start")["name"], "audition_start")
        with self.assertRaises(ValueError):
            configured_action(config, "PRODUCE_MENU")
        with self.assertRaises(ValueError):
            configured_action(config, "PRODUCE_MENU", "missing_action")
        config["states"]["PRODUCE_MENU"]["allowed_actions"].append(
            dict(config["states"]["PRODUCE_MENU"]["allowed_actions"][0])
        )
        with self.assertRaises(ValueError):
            configured_action(config, "PRODUCE_MENU", "vocal_lesson")

    def test_audition_battle_plan_targets_speed_then_toggles_auto_once(self) -> None:
        room = self.config["rooms"]["AUDITION_BATTLE_HANDLER"]
        self.assertEqual(room["completion"], {"type": "passive_wait", "expected_next_states": ["AUDITION_RESULT"]})
        speed, auto = room["local_steps"]
        self.assertEqual(speed["action"], "battle_speed_cycle")
        self.assertEqual((speed["target_speed"], speed["max_clicks"]), (3, 2))
        self.assertEqual(auto["action"], "battle_auto_on")
        self.assertEqual(auto["repeat"], "once")
        self.assertEqual(room_step_action(self.config, auto)["repeat"], "once")

    def test_speed_3x_entry_needs_no_click(self) -> None:
        self.assertEqual(synthetic_battle_speed_target([3]), ("SPEED_TARGET_REACHED", 0))

    def test_speed_2x_entry_needs_one_click(self) -> None:
        self.assertEqual(synthetic_battle_speed_target([2, 3], effects=[True]), ("SPEED_TARGET_REACHED", 1))

    def test_speed_1x_entry_needs_at_most_two_clicks(self) -> None:
        self.assertEqual(synthetic_battle_speed_target([1, 2, 3], effects=[True, True]),
                         ("SPEED_TARGET_REACHED", 2))

    def test_unknown_speed_stops_without_click(self) -> None:
        self.assertEqual(synthetic_battle_speed_target([None]), ("SPEED_UNKNOWN", 0))

    def test_speed_no_effect_stops_bounded(self) -> None:
        self.assertEqual(synthetic_battle_speed_target([2, 2], effects=[False]),
                         ("SPEED_EFFECT_NOT_VERIFIED", 1))

    def test_audition_battle_speed_and_auto_execute_once_then_reach_result(self) -> None:
        outcome, used = synthetic_audition_battle_outcome(
            ["AUDITION_BATTLE", "AUDITION_BATTLE"], "AUDITION_RESULT"
        )
        self.assertEqual(outcome, "AUDITION_RESULT")
        self.assertEqual(used, ["battle_speed_cycle", "battle_auto_on"])
        self.assertEqual(len(used), len(set(used)))

    def test_audition_battle_completion_stable_unknown_stops_safely(self) -> None:
        outcome, used = synthetic_audition_battle_outcome(
            ["AUDITION_BATTLE", "AUDITION_BATTLE"], "CONFIRMED_UNKNOWN"
        )
        self.assertEqual(outcome, "CONFIRMED_UNKNOWN")
        self.assertEqual(used, ["battle_speed_cycle", "battle_auto_on"])

    def test_audition_battle_completion_timeout_stops_safely(self) -> None:
        outcome, used = synthetic_audition_battle_outcome(
            ["AUDITION_BATTLE", "AUDITION_BATTLE"], "TRANSITION_TIMEOUT"
        )
        self.assertEqual(outcome, "TRANSITION_TIMEOUT")
        self.assertEqual(used, ["battle_speed_cycle", "battle_auto_on"])

    def test_audition_battle_toggle_that_leaves_battle_is_not_accepted(self) -> None:
        outcome, used = synthetic_audition_battle_outcome(
            ["AUDITION_RESULT"], "AUDITION_RESULT"
        )
        self.assertEqual(outcome, "UNEXPECTED_TRANSITION")
        self.assertEqual(used, ["battle_speed_cycle"])

    def test_unknown_confirmation_uses_a_consecutive_stable_tail(self) -> None:
        observations = [(value, None) for value in (0.94, 0.93, 0.63, 0.9999, 0.9999, 0.9999)]
        self.assertEqual(synthetic_unknown_outcome(observations, 0.995, 3), "CONFIRMED_UNKNOWN")

    def test_unknown_confirmation_times_out_when_never_stable(self) -> None:
        observations = [(value, None) for value in (0.80, 0.91, 0.75, 0.89, 0.70)]
        self.assertEqual(synthetic_unknown_outcome(observations, 0.995, 3), "TRANSITION_TIMEOUT")

    def test_known_state_cancels_unknown_confirmation(self) -> None:
        observations = [(0.80, None), (0.91, None), (None, "HOME")]
        self.assertEqual(synthetic_unknown_outcome(observations, 0.995, 3), "KNOWN:HOME")

    def test_post_vocal_fast_path_needs_no_fallback(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertEqual(synthetic_post_vocal_outcome("VOCAL_RESULT", [], room), "FAST_PATH")

    def test_post_vocal_timeout_can_confirm_stable_unknown(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        observations = [(value, None) for value in (0.80, 0.91, 0.70, 0.9999, 0.9999, 0.9999)]
        self.assertEqual(synthetic_post_vocal_outcome("TIMEOUT", observations, room), "CONFIRMED_UNKNOWN")

    def test_post_vocal_timeout_later_reaches_result(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertEqual(synthetic_post_vocal_outcome("TIMEOUT", [(0.8, None), (None, "VOCAL_RESULT")], room), "VOCAL_RESULT")

    def test_post_vocal_timeout_later_reaches_interruption(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertEqual(synthetic_post_vocal_outcome("TIMEOUT", [(0.8, None), (None, "DIALOGUE_FAST_FORWARD_OFF")], room), "ROOM_INTERRUPTED")

    def test_post_vocal_timeout_later_reaches_audition_battle(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertEqual(synthetic_post_vocal_outcome("TIMEOUT", [(0.8, None), (None, "AUDITION_BATTLE")], room), "ROOM_INTERRUPTED")

    def test_post_vocal_timeout_never_settles(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        observations = [(value, None) for value in (0.80, 0.91, 0.75, 0.89, 0.70)]
        self.assertEqual(synthetic_post_vocal_outcome("TIMEOUT", observations, room), "TRANSITION_TIMEOUT")

    def test_motion_continues_past_soft_transition_milestone_until_overall_deadline(self) -> None:
        deadline, milestone = post_vocal_deadline(now=21, transition_deadline=20, overall_deadline=60, loading_deadline=None)
        self.assertTrue(milestone)
        self.assertEqual(deadline, 60)

    def test_overall_post_vocal_deadline_remains_hard_without_loading(self) -> None:
        deadline, _ = post_vocal_deadline(now=60, transition_deadline=20, overall_deadline=60, loading_deadline=None)
        self.assertEqual(deadline, 60)

    def test_choice_required_is_a_room_interruption_boundary(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertEqual(post_vocal_outcome(Detection("CHOICE_REQUIRED"), room), "ROOM_INTERRUPTED")

    def test_audition_battle_is_a_room_interruption_boundary(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertEqual(post_vocal_outcome(Detection("AUDITION_BATTLE"), room), "ROOM_INTERRUPTED")

    def test_generic_dialogue_off_marker_is_not_support_event(self) -> None:
        dialogue = self.config["states"]["DIALOGUE_FAST_FORWARD_OFF"]
        support = self.config["states"]["SUPPORT_EVENT"]
        self.assertEqual(dialogue["templates"], ["support_event_marker.png"])
        self.assertEqual(support["templates"], [])
        self.assertEqual(support["allowed_actions"], [])

    def test_generic_dialogue_transient_playback_can_complete_at_home(self) -> None:
        observations = [(0.80, None), (0.70, None), (0.90, None), (None, "HOME")]
        self.assertEqual(synthetic_dialogue_outcome("TIMEOUT", observations), "EVENT_COMPLETED")

    def test_generic_dialogue_fast_unknown_also_enters_no_click_observation(self) -> None:
        observations = [(0.80, None), (0.70, None), (None, "HOME")]
        self.assertEqual(synthetic_dialogue_outcome("UNKNOWN", observations), "EVENT_COMPLETED")

    def test_generic_dialogue_choice_required_is_safe_boundary(self) -> None:
        self.assertEqual(synthetic_dialogue_outcome("TIMEOUT", [(0.8, None), (None, "CHOICE_REQUIRED")]), "CHOICE_REQUIRED")

    def test_generic_dialogue_stable_unknown_is_confirmed(self) -> None:
        observations = [(value, None) for value in (0.8, 0.9999, 0.9999, 0.9999)]
        self.assertEqual(synthetic_dialogue_outcome("TIMEOUT", observations), "CONFIRMED_UNKNOWN")

    def test_generic_dialogue_hard_deadline_has_distinct_reason(self) -> None:
        observations = [(value, None) for value in (0.8, 0.7, 0.9, 0.6)]
        self.assertEqual(synthetic_dialogue_outcome("TIMEOUT", observations), "EVENT_TRANSITION_TIMEOUT")

    def test_generic_dialogue_recognizes_season_boundaries(self) -> None:
        self.assertEqual(dialogue_outcome(Detection("SEASON_CLEAR")), "SEASON_CLEAR")
        self.assertEqual(dialogue_outcome(Detection("SEASON_RESULT")), "SEASON_RESULT")

    def test_vocal_transient_unknown_enters_fallback_and_later_exits_home(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        short_frames = [(value, None) for value in (0.93, 0.63, 0.90)]
        # Two separate changing fallback windows precede the eventual HOME exit.
        fallback_frames = [(0.80, None), (0.72, None), (0.91, None), (0.68, None), (None, "HOME")]
        outcome, fallback_entered = synthetic_vocal_pending_path(short_frames, fallback_frames, room)
        self.assertTrue(fallback_entered)
        self.assertEqual(outcome, "ROOM_EXIT")

    def test_short_vocal_classifier_returns_in_progress_not_final_timeout(self) -> None:
        changing_frames = [(value, None) for value in (0.93, 0.63, 0.90)]
        self.assertEqual(synthetic_short_unknown_outcome(changing_frames, allow_transition_continue=True), "TRANSITION_IN_PROGRESS")

    def test_short_vocal_classifier_keeps_confirmed_unknown_final(self) -> None:
        stable_frames = [(value, None) for value in (0.9999, 0.9999, 0.9999)]
        self.assertEqual(synthetic_short_unknown_outcome(stable_frames, allow_transition_continue=True), "CONFIRMED_UNKNOWN")

    def test_local_dialogue_interruption_can_exit_at_home(self) -> None:
        self.assertEqual(synthetic_local_interruption_outcome(
            "DIALOGUE_FAST_FORWARD_OFF", ["VOCAL_RESULT"], self.config["rooms"]["VOCAL_ROOM"]["interruptions"], ["HOME"]
        ), "ROOM_EXIT")

    def test_dialogue_then_promise_chain_can_exit_at_home(self) -> None:
        self.assertEqual(synthetic_local_interruption_outcome(
            "DIALOGUE_FAST_FORWARD_OFF", ["VOCAL_RESULT"], self.config["rooms"]["VOCAL_ROOM"]["interruptions"], ["PROMISE_CHOICE", "HOME"]
        ), "ROOM_EXIT")

    def test_expected_vocal_result_remains_normal_local_flow(self) -> None:
        self.assertEqual(classify_local_transition("VOCAL_RESULT", ["VOCAL_RESULT"], self.config["rooms"]["VOCAL_ROOM"]["interruptions"]), "EXPECTED")

    def test_vocal_local_action_can_exit_directly_to_home(self) -> None:
        """Changing post-Vocal frames may resolve at HOME without VOCAL_RESULT."""
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertEqual(
            classify_local_transition("HOME", ["VOCAL_RESULT"], room["interruptions"], room["exit_states"]),
            "ROOM_EXIT",
        )

    def test_vocal_local_interruption_still_precedes_expected_state_validation(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertEqual(
            classify_local_transition("DIALOGUE_FAST_FORWARD_OFF", ["VOCAL_RESULT"], room["interruptions"], room["exit_states"]),
            "INTERRUPTION",
        )

    def test_choice_required_remains_safe_interruption(self) -> None:
        self.assertEqual(synthetic_local_interruption_outcome(
            "CHOICE_REQUIRED", ["VOCAL_RESULT"], self.config["rooms"]["VOCAL_ROOM"]["interruptions"], []
        ), "ROOM_INTERRUPTED")

    def test_audition_battle_remains_safe_interruption(self) -> None:
        self.assertEqual(synthetic_local_interruption_outcome(
            "AUDITION_BATTLE", ["VOCAL_RESULT"], self.config["rooms"]["VOCAL_ROOM"]["interruptions"], []
        ), "ROOM_INTERRUPTED")

    def test_unrelated_known_state_is_unexpected_transition(self) -> None:
        self.assertEqual(classify_local_transition("SEASON_CLEAR", ["VOCAL_RESULT"], self.config["rooms"]["VOCAL_ROOM"]["interruptions"]), "UNEXPECTED_TRANSITION")

    def test_promise_transition_allows_transient_unknown_before_home(self) -> None:
        self.assertEqual(synthetic_promise_transition_outcome([(0.70, None), (0.91, None), (None, "HOME")]), "ROOM_EXIT")

    def test_accelerator_transition_burst_then_home_exits(self) -> None:
        outcome, planned, actual = synthetic_accelerated_post_vocal_outcome(
            ["TRANSITION_IN_PROGRESS", "HOME"], self.config["rooms"]["VOCAL_ROOM"], action_sent=True,
        )
        self.assertEqual((outcome, planned, actual), ("ROOM_EXIT", 1, 1))

    def test_accelerator_transition_burst_then_vocal_result(self) -> None:
        outcome, planned, actual = synthetic_accelerated_post_vocal_outcome(
            ["TRANSITION_IN_PROGRESS", "VOCAL_RESULT"], self.config["rooms"]["VOCAL_ROOM"], action_sent=True,
        )
        self.assertEqual((outcome, planned, actual), ("VOCAL_RESULT", 1, 1))

    def test_accelerator_stops_when_promise_choice_is_seen(self) -> None:
        outcome, planned, actual = synthetic_accelerated_post_vocal_outcome(
            ["TRANSITION_IN_PROGRESS", "PROMISE_CHOICE"], self.config["rooms"]["VOCAL_ROOM"], action_sent=True,
        )
        self.assertEqual((outcome, planned, actual), ("ROOM_INTERRUPTED", 1, 1))

    def test_accelerator_stops_before_choice_required(self) -> None:
        outcome, planned, actual = synthetic_accelerated_post_vocal_outcome(
            ["TRANSITION_IN_PROGRESS", "CHOICE_REQUIRED"], self.config["rooms"]["VOCAL_ROOM"], action_sent=True,
        )
        self.assertEqual((outcome, planned, actual), ("ROOM_INTERRUPTED", 1, 1))

    def test_accelerator_stops_before_audition_battle(self) -> None:
        outcome, planned, actual = synthetic_accelerated_post_vocal_outcome(
            ["TRANSITION_IN_PROGRESS", "AUDITION_BATTLE"], self.config["rooms"]["VOCAL_ROOM"], action_sent=True,
        )
        self.assertEqual((outcome, planned, actual), ("ROOM_INTERRUPTED", 1, 1))

    def test_post_vocal_unknown_requests_bounded_bursts_until_destination(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        for destination, expected in (
            ("HOME", "ROOM_EXIT"),
            ("VOCAL_RESULT", "VOCAL_RESULT"),
            ("AUDITION_BATTLE", "ROOM_INTERRUPTED"),
        ):
            with self.subTest(destination=destination):
                outcome, planned, actual = synthetic_accelerated_post_vocal_outcome(
                    ["UNKNOWN", "CONFIRMED_UNKNOWN", destination], room, action_sent=True,
                )
                self.assertEqual((outcome, planned, actual), (expected, 2, 2))

    def test_post_vocal_observer_drains_unknown_before_confirming_it(self) -> None:
        class Target:
            pass

        unknown_image = Image.new("RGB", (10, 10), "black")
        home_image = Image.new("RGB", (10, 10), "white")
        burst = {"status": "CLICKED", "click_count": 3, "normalized_points": [(0.5, 0.5)] * 3,
                 "elapsed_ms": 1.0}
        target = Target()
        with patch("main.target_screenshot", side_effect=[unknown_image, home_image]), \
             patch("main.detect_state", side_effect=[Detection("UNKNOWN"), Detection("HOME")]), \
             patch("main.run_transition_accelerator_burst", return_value=burst) as accelerate, \
             patch("main.confirm_room_unknown") as confirm:
            detected, _, outcome, details = observe_post_vocal_transition(
                target, self.config, self.config["rooms"]["VOCAL_ROOM"], action_sent=True,
            )
        confirm.assert_not_called()
        accelerate.assert_called_once_with(target, self.config, action_sent=True, dry_run=False)
        self.assertEqual(detected.state.value, "HOME")
        self.assertEqual(outcome, "ROOM_EXIT")
        self.assertEqual(details["last_accelerator_burst"]["click_count"], 3)

    def test_overall_timeout_does_not_request_accelerator(self) -> None:
        outcome, planned, actual = synthetic_accelerated_post_vocal_outcome(
            ["TRANSITION_TIMEOUT"], self.config["rooms"]["VOCAL_ROOM"], action_sent=True,
        )
        self.assertEqual((outcome, planned, actual), ("TRANSITION_TIMEOUT", 0, 0))

    def test_unarmed_accelerator_never_clicks(self) -> None:
        outcome, planned, actual = synthetic_accelerated_post_vocal_outcome(
            ["TRANSITION_IN_PROGRESS", "HOME"], self.config["rooms"]["VOCAL_ROOM"], action_sent=False,
        )
        self.assertEqual((outcome, planned, actual), ("ROOM_EXIT", 0, 0))

    def test_accelerator_dry_run_records_deterministic_points_without_clicking(self) -> None:
        settings = self.config["transition_accelerator"]
        normalized, points = transition_accelerator_points(settings, {"left": 10, "top": 20, "width": 1000, "height": 800})
        self.assertEqual(normalized, [(0.5, 0.5)] * 3)
        self.assertEqual(points, [(510, 420)] * 3)

        class Target:
            def verify_and_focus(self) -> None:
                return None

        image = Image.new("RGB", (10, 10))
        config = dict(self.config)
        config["game_window"] = {"left": 10, "top": 20, "width": 1000, "height": 800}
        with patch("main.target_screenshot", return_value=image), patch("main.detect_state", return_value=Detection("UNKNOWN")), \
             patch("main.fast_transaction_click_points") as click_burst:
            result = run_transition_accelerator_burst(Target(), config, action_sent=True, dry_run=True)
        click_burst.assert_not_called()
        self.assertEqual(result["status"], "DRY_RUN")
        self.assertEqual(result["click_count"], 3)
        self.assertEqual(result["normalized_points"], [(0.5, 0.5)] * 3)

    def test_audition_unknown_prior_can_reach_a_known_state(self) -> None:
        outcome, attempts = synthetic_safe_unknown_prior_outcome(
            [("AUDITION_RESULT", 0.61)], audition_context=True,
        )
        self.assertEqual((outcome, attempts), ("KNOWN:AUDITION_RESULT", 1))

    def test_audition_unknown_prior_allows_only_bounded_changed_unknown_retries(self) -> None:
        outcome, attempts = synthetic_safe_unknown_prior_outcome(
            [("UNKNOWN", 0.71), ("UNKNOWN", 0.62), ("AUDITION_RESULT", 0.58)],
            audition_context=True,
        )
        self.assertEqual((outcome, attempts), ("KNOWN:AUDITION_RESULT", 3))

    def test_audition_unknown_prior_stable_unknown_stops(self) -> None:
        outcome, attempts = synthetic_safe_unknown_prior_outcome(
            [("UNKNOWN", 0.99)], audition_context=True,
        )
        self.assertEqual((outcome, attempts), ("CONFIRMED_UNKNOWN", 1))

    def test_audition_unknown_prior_stops_when_choice_appears(self) -> None:
        outcome, attempts = synthetic_safe_unknown_prior_outcome(
            [("UNKNOWN", 0.72), ("CHOICE_REQUIRED", 0.60), ("AUDITION_RESULT", 0.50)],
            audition_context=True,
        )
        self.assertEqual((outcome, attempts), ("RISKY_STATE", 2))

    def test_unknown_prior_is_not_available_outside_audition_context(self) -> None:
        outcome, attempts = synthetic_safe_unknown_prior_outcome(
            [("AUDITION_RESULT", 0.50)], audition_context=False,
        )
        self.assertEqual((outcome, attempts), ("NO_PRIOR", 0))

    def test_audition_unknown_prior_never_exceeds_configured_attempt_limit(self) -> None:
        outcome, attempts = synthetic_safe_unknown_prior_outcome(
            [("UNKNOWN", 0.70), ("UNKNOWN", 0.70), ("UNKNOWN", 0.70), ("UNKNOWN", 0.70)],
            audition_context=True, max_attempts=3,
        )
        self.assertEqual((outcome, attempts), ("PRIOR_ATTEMPTS_EXHAUSTED", 3))

    def test_fast_forward_capability_is_independent_of_dialogue_artwork(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        first = known_control_capability(
            self.config, Detection("DIALOGUE_FAST_FORWARD_OFF", template="portrait_a.png"), room,
        )
        second = known_control_capability(
            self.config, Detection("DIALOGUE_FAST_FORWARD_OFF", template="portrait_b.png"), room,
        )
        self.assertEqual(first["action_name"], "dialogue_fast_forward_on")
        self.assertEqual(second["action_name"], "dialogue_fast_forward_on")
        self.assertEqual(first["mode"], "dialogue_fast_forward_once")

    def test_known_continue_control_can_advance_without_a_new_dialogue_identity(self) -> None:
        room = {"interruptions": ["AUDITION_RESULT_DIALOGUE"]}
        capability = known_control_capability(self.config, Detection("AUDITION_RESULT_DIALOGUE"), room)
        self.assertEqual(capability["action_name"], "audition_result_dialogue_continue")
        self.assertEqual(
            synthetic_capability_dispatch_outcome("AUDITION_RESULT_DIALOGUE", capability_available=True,
                                                  immediate_state="AUDITION_RESULT_DIALOGUE"),
            "CONTROL_EXECUTED:AUDITION_RESULT_DIALOGUE",
        )

    def test_choice_screen_never_falls_into_generic_continue(self) -> None:
        room = {"interruptions": ["CHOICE_REQUIRED"]}
        self.assertIsNone(known_control_capability(self.config, Detection("CHOICE_REQUIRED"), room))
        self.assertEqual(
            synthetic_capability_dispatch_outcome("CHOICE_REQUIRED", capability_available=True),
            "NO_GENERIC_CONTROL",
        )

    def test_stable_unknown_has_no_generic_control(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertIsNone(known_control_capability(self.config, Detection("UNKNOWN"), room))
        self.assertEqual(
            synthetic_capability_dispatch_outcome("UNKNOWN", capability_available=True),
            "NO_GENERIC_CONTROL",
        )

    def test_post_audition_season_clear_and_story_pages_drain_to_home(self) -> None:
        self.assertEqual(
            synthetic_post_audition_drain_outcome([
                ("SEASON_CLEAR", 0.7), ("UNKNOWN", 0.6), ("HOME", None),
            ]),
            ("CLEANUP_COMPLETE", 2),
        )

    def test_post_audition_fast_forward_can_complete_at_home(self) -> None:
        outcome, used = synthetic_post_audition_cleanup_outcome([
            "AUDITION_RESULT", "DIALOGUE_FAST_FORWARD_OFF", "HOME",
        ])
        self.assertEqual(outcome, "CLEANUP_COMPLETE")
        self.assertEqual(used, ["dialogue_fast_forward_on"])

    def test_post_audition_risky_choice_stops_without_capability_click(self) -> None:
        outcome, used = synthetic_post_audition_cleanup_outcome([
            "AUDITION_RESULT", "CHOICE_REQUIRED",
        ])
        self.assertEqual(outcome, "ROOM_INTERRUPTED")
        self.assertEqual(used, [])

    def test_post_audition_stable_unknown_stops(self) -> None:
        outcome, used = synthetic_post_audition_cleanup_outcome([
            "AUDITION_RESULT", "CONFIRMED_UNKNOWN",
        ])
        self.assertEqual(outcome, "CONFIRMED_UNKNOWN")
        self.assertEqual(used, [])

    def test_post_audition_capabilities_are_once_only(self) -> None:
        outcome, used = synthetic_post_audition_cleanup_outcome([
            "AUDITION_RESULT", "DIALOGUE_FAST_FORWARD_OFF", "DIALOGUE_FAST_FORWARD_OFF", "HOME",
        ])
        self.assertEqual(outcome, "CLEANUP_COMPLETE")
        self.assertEqual(used, ["dialogue_fast_forward_on"])

    def test_post_audition_timeout_stops(self) -> None:
        outcome, used = synthetic_post_audition_cleanup_outcome(["AUDITION_RESULT", "TIMEOUT"])
        self.assertEqual(outcome, "CLEANUP_TIMEOUT")
        self.assertEqual(used, [])

    def test_post_audition_generic_advance_handles_intermediate_states(self) -> None:
        outcome, used = synthetic_post_audition_cleanup_outcome([
            "AUDITION_RESULT", "STORY_PAGE", "AUDITION_BATTLE", "HOME",
        ])
        self.assertEqual(outcome, "CLEANUP_COMPLETE")
        self.assertEqual(used, [])

    def test_post_audition_season_clear_advances_without_specific_action(self) -> None:
        outcome, used = synthetic_post_audition_cleanup_outcome([
            "AUDITION_RESULT", "SEASON_CLEAR", "HOME",
        ])
        self.assertEqual(outcome, "CLEANUP_COMPLETE")
        self.assertEqual(used, [])

    def test_post_audition_known_cleanup_resume_states_are_allowed(self) -> None:
        cleanup = self.config["post_audition_cleanup"]
        for state in (
            "AUDITION_RESULT", "AUDITION_RESULT_DIALOGUE", "DIALOGUE_FAST_FORWARD_OFF",
            "SEASON_CLEAR", "SEASON_RESULT",
        ):
            self.assertTrue(post_audition_entry_allowed(cleanup, state))

    def test_post_audition_season_result_resume_advances_cta_before_terminal(self) -> None:
        cleanup = self.config["post_audition_cleanup"]
        self.assertTrue(post_audition_entry_allowed(cleanup, "SEASON_RESULT"))
        self.assertEqual(
            synthetic_post_audition_drain_outcome([("SEASON_RESULT", 0.6), ("HOME", None)]),
            ("CLEANUP_COMPLETE", 1),
        )

    def test_post_audition_season_clear_resume_uses_safe_drain(self) -> None:
        cleanup = self.config["post_audition_cleanup"]
        self.assertTrue(post_audition_entry_allowed(cleanup, "SEASON_CLEAR"))
        self.assertEqual(
            synthetic_post_audition_drain_outcome([("SEASON_CLEAR", 0.7), ("HOME", None)]),
            ("CLEANUP_COMPLETE", 1),
        )

    def test_post_audition_unrelated_and_unknown_entries_are_rejected(self) -> None:
        cleanup = self.config["post_audition_cleanup"]
        self.assertFalse(post_audition_entry_allowed(cleanup, "HOME"))
        self.assertFalse(post_audition_entry_allowed(cleanup, "UNKNOWN"))

    def test_post_audition_result_dialogue_self_loop_allows_bounded_progress(self) -> None:
        self.assertEqual(
            synthetic_post_audition_drain_outcome([
                ("AUDITION_RESULT_DIALOGUE", 0.70),
                ("AUDITION_RESULT_DIALOGUE", 0.65),
                ("HOME", None),
            ]),
            ("CLEANUP_COMPLETE", 2),
        )

    def test_post_audition_dialogue_no_effect_and_max_clicks_stop(self) -> None:
        self.assertEqual(
            synthetic_post_audition_drain_outcome([
                ("AUDITION_RESULT_DIALOGUE", 0.999),
                ("AUDITION_RESULT_DIALOGUE", 0.999),
            ]),
            ("NO_EFFECT", 2),
        )
        self.assertEqual(
            synthetic_post_audition_drain_outcome([("STORY_PAGE", 0.5)] * 13, max_clicks=12),
            ("CAPABILITY_LIMIT", 12),
        )

    def test_post_audition_generic_drain_reaches_home(self) -> None:
        self.assertEqual(
            synthetic_post_audition_drain_outcome([
                ("AUDITION_RESULT_DIALOGUE", 0.7),
                ("STORY_PAGE", 0.8),
                ("HOME", None),
            ]),
            ("CLEANUP_COMPLETE", 2),
        )

    def test_post_audition_generic_drain_protects_risky_states(self) -> None:
        self.assertEqual(synthetic_post_audition_drain_outcome([("CHOICE_REQUIRED", None)]), ("ROOM_INTERRUPTED", 0))

    def test_global_unknown_still_has_no_generic_capability(self) -> None:
        room = self.config["rooms"]["VOCAL_ROOM"]
        self.assertIsNone(known_control_capability(self.config, Detection("UNKNOWN"), room))

    def test_post_audition_generic_drain_bounds_no_effect(self) -> None:
        self.assertEqual(
            synthetic_post_audition_drain_outcome([
                ("STORY_PAGE", 0.999), ("STORY_PAGE", 0.999), ("STORY_PAGE", 0.999)
            ], no_effect_limit=2),
            ("NO_EFFECT", 2),
        )

    def test_safe_pink_cta_detects_only_large_lower_right_button(self) -> None:
        settings = self.config["post_audition_cleanup"]["safe_pink_cta"]
        frame = np.zeros((500, 1000, 3), dtype=np.uint8)
        frame[420:480, 840:970] = [255, 40, 180]
        detected = detect_safe_pink_cta(Image.fromarray(frame), settings)
        self.assertIsNotNone(detected)
        self.assertTrue(0.8 <= detected["center"][0] <= 0.99)
        frame = np.zeros((500, 1000, 3), dtype=np.uint8)
        frame[420:480, 100:230] = [255, 40, 180]
        self.assertIsNone(detect_safe_pink_cta(Image.fromarray(frame), settings))

    def test_real_ok_and_next_ctas_share_one_capability(self) -> None:
        settings = self.config["post_audition_cleanup"]["safe_pink_cta"]
        for filename in (
            "20260831_145932_764555_POST_AUDITION_SEASON_CLEAR.png",
            "20260831_155516_867885_POST_AUDITION_TERMINAL.png",
        ):
            path = Path(BASE_DIR) / "logs" / filename
            if not path.exists():
                continue
            self.assertIsNotNone(detect_safe_pink_cta(Image.open(path), settings), filename)

    def test_season_result_with_cta_advances_before_home(self) -> None:
        self.assertEqual(
            synthetic_post_audition_drain_outcome([("SEASON_RESULT", 0.6), ("HOME", None)]),
            ("CLEANUP_COMPLETE", 1),
        )

    def test_audition_choice_routes_middle_choice_reusing_pre_audition_box(self) -> None:
        pre_action = configured_action(self.config, "PRE_AUDITION_CHOICE")
        audition_action = configured_action(self.config, "AUDITION_CHOICE")
        self.assertEqual(pre_action["name"], "middle_choice")
        self.assertEqual(audition_action["name"], "middle_choice")
        self.assertEqual(audition_action["type"], "click")
        self.assertEqual(audition_action["box"], pre_action["box"])
        self.assertEqual(audition_action["box"], [0.581114, 0.243824, 0.626513, 0.292696])
        self.assertNotEqual(audition_action["expected_next_states"], pre_action["expected_next_states"])
        self.assertEqual(pre_action["expected_next_states"], ["AUDITION_BATTLE"])
        self.assertIn("AUDITION_RESULT_DIALOGUE", audition_action["expected_next_states"])
        self.assertIn("DIALOGUE_FAST_FORWARD_OFF", audition_action["expected_next_states"])
        self.assertIn("HOME", audition_action["expected_next_states"])

    def test_audition_choice_remains_protected_handoff(self) -> None:
        room = {"interruptions": ["AUDITION_CHOICE"]}
        self.assertIsNone(known_control_capability(self.config, Detection("AUDITION_CHOICE"), room))
        self.assertEqual(
            synthetic_capability_dispatch_outcome("AUDITION_CHOICE", capability_available=True),
            "NO_GENERIC_CONTROL",
        )
        outcome, used = synthetic_post_audition_cleanup_outcome(["AUDITION_RESULT", "AUDITION_CHOICE"])
        self.assertEqual(outcome, "ROOM_INTERRUPTED")
        self.assertEqual(used, [])

    def test_rest_room_schema_and_action_lookup(self) -> None:
        rest_room = self.config["rooms"]["REST_ROOM"]
        self.assertEqual(rest_room["entry_states"], ["HOME"])
        self.assertEqual(rest_room["exit_states"], ["HOME"])
        self.assertEqual(rest_room["local_anchors"], ["HOME"])
        self.assertEqual(len(rest_room["local_steps"]), 1)
        step = rest_room["local_steps"][0]
        self.assertEqual(step["source_state"], "HOME")
        self.assertEqual(step["action"], "rest")
        self.assertEqual(step["expected_next_states"], ["HOME"])
        action = configured_action(self.config, "HOME", "rest")
        self.assertEqual(action["name"], "rest")
        self.assertEqual(action["expected_next_states"], ["HOME"])

    def test_rest_room_transition_classification(self) -> None:
        rest_room = self.config["rooms"]["REST_ROOM"]
        self.assertEqual(
            classify_local_transition("HOME", ["HOME"], rest_room["interruptions"], rest_room["exit_states"]),
            "ROOM_EXIT",
        )
        self.assertEqual(
            classify_local_transition("DIALOGUE_FAST_FORWARD_OFF", ["HOME"], rest_room["interruptions"], rest_room["exit_states"]),
            "INTERRUPTION",
        )
        self.assertEqual(
            classify_local_transition("CHOICE_REQUIRED", ["HOME"], rest_room["interruptions"], rest_room["exit_states"]),
            "INTERRUPTION",
        )
        self.assertEqual(
            classify_local_transition("VOCAL_RESULT", ["HOME"], rest_room["interruptions"], rest_room["exit_states"]),
            "UNEXPECTED_TRANSITION",
        )


if __name__ == "__main__":
    unittest.main()
