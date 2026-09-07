"""Table tests for the live-finding fast handlers and the stamina guard."""
import unittest

from home_observation import HomeObservation
from home_policy import decide_home
from wing_fast_handlers import morning_three_choice, promise_dialogue


class StaminaGuardTest(unittest.TestCase):
    """Superseded semantics (2026-09-05): low stamina is warning-only; the
    VOCAL decision moved to the failure-rate gate (see VocalFailureGateDecisionTest)."""

    def decide(self, ratio, fresh=True):
        state = {"stamina_observation": {"ratio": ratio, "fresh": fresh}}
        return decide_home(HomeObservation(2, 6, 6721), state, {})

    def test_ratio_049_is_warning_requiring_failure_read(self) -> None:
        d = self.decide(0.49)
        self.assertEqual(d.action, "NEED_MORE_OBSERVATION")
        self.assertIn("LOW_STAMINA_WARNING", d.reason)

    def test_ratio_050_still_requires_failure_read_for_vocal(self) -> None:
        self.assertEqual(self.decide(0.50).action, "NEED_MORE_OBSERVATION")

    def test_stale_stamina_does_not_bypass_failure_read(self) -> None:
        self.assertEqual(self.decide(0.90, fresh=False).action, "NEED_MORE_OBSERVATION")

    def test_config_memory_cannot_create_stamina_warning(self) -> None:
        d = decide_home(HomeObservation(2, 6, 6721), {}, {"run_state": {"stamina_ratio": 0.1}})
        self.assertEqual(d.action, "NEED_MORE_OBSERVATION")
        self.assertNotIn("LOW_STAMINA_WARNING", d.reason)


class MorningThreeChoiceTest(unittest.TestCase):
    def base(self, **kw):
        facts = {"state_confirmed": True, "green_frames": 3, "options_visible": 3,
                 "middle_option_clickable": True, "taught_middle_coord_valid": True}
        facts.update(kw)
        return morning_three_choice(facts)

    def test_confirmed_three_choice_chooses_middle(self) -> None:
        d = self.base()
        self.assertEqual(d["decision"], "CHOOSE_MIDDLE")
        self.assertEqual(d["reason"], "MORNING_THREE_CHOICE_CONFIRMED")
        self.assertEqual(d["selection_index"], 2)

    def test_uncertain_state_never_blind_clicks(self) -> None:
        d = self.base(state_confirmed=False)
        self.assertEqual((d["decision"], d["reason"]), ("STOP", "MORNING_STATE_UNCERTAIN"))

    def test_green_frame_miss_allows_guarded_fallback(self) -> None:
        d = self.base(green_frames=None)
        self.assertEqual(d["decision"], "GUARDED_FALLBACK_CLICK")
        self.assertEqual(d["reason"], "GREEN_FRAME_MISS_GUARDED_FALLBACK")

    def test_green_frame_miss_without_valid_coord_stops(self) -> None:
        d = self.base(green_frames=None, taught_middle_coord_valid=False)
        self.assertEqual((d["decision"], d["reason"]), ("STOP", "MORNING_THREE_CHOICE_UNCONFIRMED"))


class PromiseMiokuriTest(unittest.TestCase):
    def test_miokuri_visible_wins_over_textbox_fallback(self) -> None:
        d = promise_dialogue({"dialogue_page_fresh": True, "miokuri_visible": True,
                              "miokuri_geometry_valid": True, "in_true_choice": False})
        self.assertEqual(d["decision"], "CLICK_MIOKURI")

    def test_true_choice_state_must_use_choice_policy(self) -> None:
        d = promise_dialogue({"dialogue_page_fresh": True, "miokuri_visible": True,
                              "miokuri_geometry_valid": True, "in_true_choice": True})
        self.assertEqual(d["decision"], "USE_BUSINESS_CHOICE_POLICY")

    def test_stale_evidence_stops(self) -> None:
        d = promise_dialogue({"dialogue_page_fresh": False, "miokuri_visible": True,
                              "miokuri_geometry_valid": True, "in_true_choice": False})
        self.assertEqual((d["decision"], d["reason"]), ("STOP", "STALE_DIALOGUE_EVIDENCE"))

    def test_no_miokuri_falls_back(self) -> None:
        d = promise_dialogue({"dialogue_page_fresh": True, "miokuri_visible": False,
                              "miokuri_geometry_valid": False, "in_true_choice": False})
        self.assertEqual(d["decision"], "FALLBACK_FAST_FORWARD_OR_TEXTBOX")


if __name__ == "__main__":
    unittest.main()


class VocalFailureRoiTest(unittest.TestCase):
    def test_parser_basic_values(self) -> None:
        from wing_fast_handlers import parse_failure_rate_percent
        for raw, expected in [("0", 0), ("1", 1), ("2", 2), ("3", 3), ("10", 10), ("100", 100)]:
            self.assertEqual(parse_failure_rate_percent([raw]), expected)

    def test_parser_conflict_and_garbage_fail_closed(self) -> None:
        from wing_fast_handlers import parse_failure_rate_percent
        self.assertIsNone(parse_failure_rate_percent(["2", "3"]))
        self.assertIsNone(parse_failure_rate_percent(["abc"]))
        self.assertIsNone(parse_failure_rate_percent([]))

    def test_roi_viewport_validation(self) -> None:
        from wing_fast_handlers import vocal_failure_roi_status
        self.assertEqual(vocal_failure_roi_status({"width": 1280, "height": 720}), "VALIDATED")
        self.assertEqual(vocal_failure_roi_status({"width": 1920, "height": 1080}), "UNVALIDATED")


class VocalFailureGateDecisionTest(unittest.TestCase):
    def decide(self, ratio, fr):
        state = {}
        if ratio is not None:
            state["stamina_observation"] = {"ratio": ratio, "fresh": True}
        if fr is not None:
            state["vocal_failure_rate_observation"] = fr
        return decide_home(HomeObservation(2, 6, 6721), state, {})

    def test_case1_low_stamina_fail1_vocal(self) -> None:
        self.assertEqual(self.decide(0.49, {"value": 1, "status": "KNOWN", "fresh": True}).action, "VOCAL")

    def test_case2_low_stamina_fail2_vocal(self) -> None:
        self.assertEqual(self.decide(0.49, {"value": 2, "status": "KNOWN", "fresh": True}).action, "VOCAL")

    def test_case3_low_stamina_fail3_back_rest(self) -> None:
        d = self.decide(0.49, {"value": 3, "status": "KNOWN", "fresh": True})
        self.assertEqual(d.action, "REST")
        self.assertIn("BACK_TO_REST", d.reason)

    def test_case4_good_stamina_fail4_back_rest(self) -> None:
        d = self.decide(0.70, {"value": 4, "status": "KNOWN", "fresh": True})
        self.assertEqual(d.action, "REST")

    def test_case5_unknown_rate_low_stamina_no_vocal(self) -> None:
        self.assertEqual(self.decide(0.49, {"value": None, "status": "UNKNOWN", "fresh": True}).action, "REST")

    def test_case6_unvalidated_viewport_blocks_gate(self) -> None:
        from wing_fast_handlers import vocal_failure_roi_status
        self.assertEqual(vocal_failure_roi_status({"width": 2560, "height": 1440}), "UNVALIDATED")
        # an observation sourced from an unvalidated ROI must be rejected by the
        # runtime before reaching the gate; simulate rejection as no observation
        # with low stamina → gate demands the read → no VOCAL.
        d = self.decide(0.49, None)
        self.assertEqual(d.action, "NEED_MORE_OBSERVATION")
        self.assertIn("FAILURE_RATE_READ_REQUIRED", d.reason)

    def test_case7_stale_observation_rejected(self) -> None:
        self.assertEqual(self.decide(0.49, {"value": 0, "status": "KNOWN", "fresh": False}).action, "REST")
