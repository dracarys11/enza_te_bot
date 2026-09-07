"""Tests for the VisionObservation contract v0.1.

Covers the required PASS cases (valid payloads load) and FAIL cases
(forbidden semantic fields / missing required fields / low-confidence
regions without an uncertainty entry are rejected).
"""
from __future__ import annotations

import unittest

from vision_observation_schema import VisionContractError, VisionObservation


def valid_base_payload() -> dict:
    """Minimal contract-compliant observation (研修設定, Vocal 0/20 style)."""
    return {
        "observation_id": "VOBS_20260903090000",
        "capture": {
            "timestamp": "2026-09-03T09:00:00Z",
            "frame_id": "frame_0001",
            "screenshot_digest": "sha256:abc123",
        },
        "viewport": {"width": 1280, "height": 720},
        "text_regions": [
            {"id": "t1", "text": "研修設定", "bbox": [560, 88, 180, 44], "confidence": 0.98},
            {"id": "t2", "text": "ボーカル", "bbox": [360, 200, 120, 32], "confidence": 0.96},
            {"id": "t5", "text": "決定", "bbox": [1010, 598, 120, 52], "confidence": 0.94},
        ],
        "interaction_candidates": [
            {
                "id": "e1",
                "bbox": [440, 330, 56, 56],
                "appearance": {"shape": "circle_button", "color_hint": "orange"},
                "linked_text_ids": [],
                "interaction_confidence": 0.88,
            },
            {
                "id": "e3",
                "bbox": [1000, 590, 150, 68],
                "appearance": {"shape": "rounded_rect_button", "color_hint": "red"},
                "linked_text_ids": ["t5"],
                "interaction_confidence": 0.93,
            },
        ],
        "numeric_regions": [
            {
                "id": "n1",
                "raw_text": "0/20",
                "value": 0,
                "max_value": 20,
                "bbox": [410, 338, 60, 34],
                "confidence": 0.97,
            }
        ],
        "overlay_regions": [
            {
                "id": "o1",
                "bbox": [220, 60, 840, 640],
                "linked_text_ids": ["t1"],
                "blocked_element_ids": [],
            }
        ],
        "uncertainties": [
            {"bbox": [480, 250, 400, 100], "reason": "small_description_text_not_requested"}
        ],
    }


class ValidPayloadsLoad(unittest.TestCase):
    def test_pass_1_minimal_observation_with_screenshot_viewport_text_bbox(self):
        obs = VisionObservation.from_payload(valid_base_payload())
        self.assertEqual(obs.observation_id, "VOBS_20260903090000")
        self.assertEqual(obs.viewport, {"width": 1280, "height": 720})
        self.assertEqual(obs.text_regions[0]["text"], "研修設定")

    def test_pass_2_overlay_with_blocked_elements_loads(self):
        payload = valid_base_payload()
        payload["overlay_regions"][0]["blocked_element_ids"] = ["e3"]
        obs = VisionObservation.from_payload(payload)
        self.assertEqual(obs.overlay_regions[0]["blocked_element_ids"], ["e3"])

    def test_pass_3_unreadable_region_is_preserved(self):
        payload = valid_base_payload()
        payload["uncertainties"].append({"bbox": [520, 200, 480, 40], "reason": "low_contrast"})
        obs = VisionObservation.from_payload(payload)
        self.assertEqual(len(obs.uncertainties), 2)

    def test_pass_4_numeric_change_0_to_20_then_1_to_20_accepted(self):
        before = valid_base_payload()
        after = valid_base_payload()
        after["numeric_regions"][0]["value"] = 1
        after["numeric_regions"][0]["raw_text"] = "1/20"
        after["visual_changes"] = [
            {"type": "number_changed", "ref": "n1", "from": 0, "to": 1}
        ]
        obs_before = VisionObservation.from_payload(before)
        obs_after = VisionObservation.from_payload(after)
        self.assertEqual(obs_before.numeric_regions[0]["value"], 0)
        self.assertEqual(obs_after.numeric_regions[0]["value"], 1)
        self.assertEqual(obs_after.visual_changes[0]["to"], 1)

    def test_visual_changes_field_is_optional(self):
        payload = valid_base_payload()
        self.assertNotIn("visual_changes", payload)
        VisionObservation.from_payload(payload)  # must not raise


class ForbiddenAndMissingRejected(unittest.TestCase):
    def assert_rejected(self, payload):
        with self.assertRaises(VisionContractError):
            VisionObservation.from_payload(payload)

    def test_fail_1_semantic_state_field_rejected(self):
        payload = valid_base_payload()
        payload["semantic_state"] = "TRAINING_SETTINGS"
        self.assert_rejected(payload)

    def test_fail_2_action_field_rejected(self):
        payload = valid_base_payload()
        payload["action"] = "click_plus"
        self.assert_rejected(payload)

    def test_fail_3_recommendation_field_rejected(self):
        payload = valid_base_payload()
        payload["recommendation"] = "allocate_vocal"
        self.assert_rejected(payload)

    def test_fail_3b_nested_forbidden_field_rejected(self):
        payload = valid_base_payload()
        payload["interaction_candidates"][0]["button_purpose"] = "increment"
        self.assert_rejected(payload)

    def test_fail_4_missing_viewport_rejected(self):
        payload = valid_base_payload()
        del payload["viewport"]
        self.assert_rejected(payload)

    def test_fail_4b_viewport_without_height_rejected(self):
        payload = valid_base_payload()
        payload["viewport"] = {"width": 1280}
        self.assert_rejected(payload)

    def test_fail_5_low_confidence_without_uncertainty_rejected(self):
        payload = valid_base_payload()
        payload["text_regions"][1]["confidence"] = 0.4  # low, nothing covers it
        errors = VisionObservation.validate(payload)
        self.assertTrue(any("no uncertainty entry covers" in e for e in errors))
        self.assert_rejected(payload)

    def test_fail_5b_low_confidence_with_covering_uncertainty_accepted(self):
        payload = valid_base_payload()
        payload["text_regions"][1]["confidence"] = 0.4
        payload["uncertainties"].append(
            {"bbox": [355, 195, 130, 42], "reason": "partial_occlusion_of_label"}
        )
        VisionObservation.from_payload(payload)  # reported unreadable -> acceptable

    def test_missing_capture_fields_rejected(self):
        payload = valid_base_payload()
        del payload["capture"]["screenshot_digest"]
        self.assert_rejected(payload)

    def test_text_region_without_bbox_rejected(self):
        payload = valid_base_payload()
        del payload["text_regions"][0]["bbox"]
        self.assert_rejected(payload)


if __name__ == "__main__":
    unittest.main()
