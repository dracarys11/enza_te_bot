"""Tests for the MVP closed-loop controller (no live automation)."""
from __future__ import annotations

import unittest

from mvp_loop import VerificationResult, classify, resolve, verify
from test_vision_observation_schema import valid_base_payload


def training_settings_payload(observation_id: str = "VOBS_A") -> dict:
    payload = valid_base_payload()
    payload["observation_id"] = observation_id
    payload["capture"]["frame_id"] = observation_id
    payload["interaction_candidates"].insert(
        0,
        {
            "id": "e0",
            "bbox": [330, 330, 56, 56],
            "appearance": {"shape": "circle_button", "color_hint": "grey"},
            "linked_text_ids": [],
            "interaction_confidence": 0.85,
        },
    )
    return payload


def after_plus_one_payload() -> dict:
    payload = training_settings_payload("VOBS_B")
    payload["numeric_regions"][0]["value"] = 1
    payload["numeric_regions"][0]["raw_text"] = "1/20"
    return payload


def home_payload() -> dict:
    payload = valid_base_payload()
    payload["observation_id"] = "VOBS_HOME"
    payload["text_regions"] = [
        {"id": "t1", "text": "ホーム", "bbox": [40, 30, 160, 60], "confidence": 0.97},
    ]
    payload["numeric_regions"] = []
    payload["overlay_regions"] = []
    payload["interaction_candidates"] = []
    payload["uncertainties"] = []
    return payload


def wing_payload() -> dict:
    payload = valid_base_payload()
    payload["observation_id"] = "VOBS_WING"
    payload["text_regions"] = [
        {"id": "t1", "text": "W.I.N.G.", "bbox": [600, 195, 300, 60], "confidence": 0.95},
        {"id": "t2", "text": "ビギナー", "bbox": [620, 340, 120, 40], "confidence": 0.93},
    ]
    payload["numeric_regions"] = []
    payload["overlay_regions"] = []
    return payload


class PassCases(unittest.TestCase):
    def test_pass_home_recognized_from_title(self):
        state = classify(home_payload())
        self.assertEqual(state.state, "HOME")
        self.assertTrue(state.evidence_refs)
        self.assertGreaterEqual(state.confidence, 0.9)
        self.assertEqual(state.unknowns, ())

    def test_pass_training_settings_recognized_from_title(self):
        state = classify(training_settings_payload())
        self.assertEqual(state.state, "TRAINING_SETTINGS")

    def test_pass_vocal_plus_target_found(self):
        payload = training_settings_payload()
        state = classify(payload)
        request = resolve(payload, state)
        self.assertIsNotNone(request)
        self.assertEqual(request.action_type, "VOCAL_PLUS")
        self.assertEqual(request.target_element_id, "e1")  # column-right circle
        self.assertIn("n1", " ".join(request.evidence_refs))
        self.assertIn("ASSUMED", request.uncertainty_status)
        self.assertEqual(request.expected_verification["old_value"], 0)
        self.assertEqual(request.expected_verification["new_value"], 1)

    def test_pass_zero_to_one_verification(self):
        result = verify(training_settings_payload(), after_plus_one_payload(), expected_counter_id="n1")
        self.assertTrue(result.passed)
        self.assertEqual((result.old_value, result.new_value), (0, 1))
        self.assertIn("same location", result.reason)


class FailGuards(unittest.TestCase):
    def test_fail_coordinate_only_does_not_create_state(self):
        payload = training_settings_payload()
        payload["text_regions"] = []  # only coordinates/shapes remain
        state = classify(payload)
        self.assertEqual(state.state, "UNKNOWN")
        self.assertEqual(state.confidence, 0.0)

    def test_fail_unknown_screen_does_not_create_action(self):
        payload = training_settings_payload()
        payload["text_regions"] = [r for r in payload["text_regions"] if r["text"] != "研修設定"]
        state = classify(payload)
        self.assertEqual(state.state, "UNKNOWN")
        self.assertIsNone(resolve(payload, state))  # no action from unknown state

    def test_fail_missing_title_does_not_create_verified_state(self):
        payload = home_payload()
        payload["text_regions"][0]["text"] = "???"  # OCR failed to a noise string
        state = classify(payload)
        self.assertEqual(state.state, "UNKNOWN")

    def test_verification_fails_when_counter_moves(self):
        after = after_plus_one_payload()
        after["numeric_regions"][0]["bbox"] = [700, 338, 60, 34]  # different counter
        result = verify(training_settings_payload(), after, expected_counter_id="n1")
        self.assertFalse(result.passed)
        self.assertIn("location changed", result.reason)

    def test_verification_fails_on_wrong_delta(self):
        after = after_plus_one_payload()
        after["numeric_regions"][0]["value"] = 2
        result = verify(training_settings_payload(), after, expected_counter_id="n1")
        self.assertFalse(result.passed)
        self.assertIn("delta != +1", result.reason)


if __name__ == "__main__":
    unittest.main()
