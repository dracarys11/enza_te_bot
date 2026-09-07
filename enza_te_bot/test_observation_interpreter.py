"""Tests for Observation Interpreter v0.1.

PASS cases:
- title text creates a semantic candidate
- coordinate-only panel remains UNKNOWN
- missing text remains UNKNOWN
- vocal counter detection creates a possible increment action

FAIL-guard cases (behavior that must NOT happen):
- a screenshot alone never creates a verified state
- coordinates never create semantic identity
- the interpreter never emits execution permission or click coordinates
"""
from __future__ import annotations

import unittest

from observation_interpreter import interpret
from vision_observation_schema import VisionContractError

from test_vision_observation_schema import valid_base_payload


def training_settings_payload() -> dict:
    """研修設定 with Vocal 0/20 and two circle buttons in the vocal column."""
    payload = valid_base_payload()
    payload["text_regions"].append(
        {"id": "t3", "text": "0/20", "bbox": [410, 338, 60, 34], "confidence": 0.95}
    )
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


def payload_with_unidentified_overlay() -> dict:
    payload = training_settings_payload()
    payload["overlay_regions"] = [
        {
            "id": "o9",
            "bbox": [100, 100, 500, 400],
            "linked_text_ids": [],  # no title text evidence
            "blocked_element_ids": ["e1", "e3"],
        }
    ]
    return payload


class PassCases(unittest.TestCase):
    def test_pass_1_title_text_creates_semantic_candidate(self):
        result = interpret(training_settings_payload())
        labels = [c["label"] for c in result["semantic_candidates"]]
        self.assertIn("TRAINING_SETTINGS", labels)
        candidate = next(c for c in result["semantic_candidates"] if c["label"] == "TRAINING_SETTINGS")
        self.assertEqual(candidate["identity_source"], "title_text_read")
        self.assertTrue(candidate["evidence_refs"])

    def test_pass_2_coordinate_only_panel_remains_unknown(self):
        result = interpret(payload_with_unidentified_overlay())
        self.assertTrue(
            any("identity UNKNOWN" in u and "o9" in u for u in result["unknowns"])
        )
        # The panel produced no semantic candidate
        for candidate in result["semantic_candidates"]:
            self.assertNotIn("coordinate", candidate["identity_source"])

    def test_pass_3_missing_text_remains_unknown(self):
        payload = training_settings_payload()
        payload["text_regions"] = [
            r for r in payload["text_regions"] if r["text"] != "研修設定"
        ]
        result = interpret(payload)
        labels = [c["label"] for c in result["semantic_candidates"]]
        self.assertNotIn("TRAINING_SETTINGS", labels)

    def test_pass_4_vocal_counter_creates_increment_action(self):
        result = interpret(training_settings_payload())
        vocal_actions = [a for a in result["permitted_actions"] if a["action_type"] == "VOCAL_INCREMENT"]
        self.assertEqual(len(vocal_actions), 1)
        action = vocal_actions[0]
        self.assertIn("n1", " ".join(action["evidence_refs"]))
        self.assertIn("uncertainty_status", action)
        self.assertIn("ASSUMED", action["uncertainty_status"])

    def test_vocal_at_max_creates_no_increment_action(self):
        payload = training_settings_payload()
        payload["numeric_regions"][0]["value"] = 20
        result = interpret(payload)
        self.assertFalse(
            [a for a in result["permitted_actions"] if a["action_type"] == "VOCAL_INCREMENT"]
        )

    def test_open_training_settings_via_linked_text(self):
        # The 研修設定 button lives on the W.I.N.G. selection screen, not on
        # the TRAINING_SETTINGS screen itself: model that screen here.
        payload = training_settings_payload()
        payload["text_regions"].append(
            {"id": "t9", "text": "W.I.N.G.", "bbox": [600, 195, 300, 60], "confidence": 0.95}
        )
        payload["interaction_candidates"].append(
            {
                "id": "e9",
                "bbox": [900, 628, 160, 85],
                "appearance": {"shape": "rect_button", "color_hint": "white"},
                "linked_text_ids": ["t9x"],
                "interaction_confidence": 0.9,
            }
        )
        payload["text_regions"].append(
            {"id": "t9x", "text": "研修設定", "bbox": [920, 640, 120, 60], "confidence": 0.93}
        )
        result = interpret(payload)
        actions = [a for a in result["permitted_actions"] if a["action_type"] == "OPEN_TRAINING_SETTINGS"]
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["target_element_id"], "e9")


class FailGuards(unittest.TestCase):
    """These assert forbidden behaviors do NOT occur."""

    def _serialized(self, payload) -> str:
        import json

        return json.dumps(interpret(payload))

    def test_fail_1_screenshot_alone_does_not_create_verified_state(self):
        # A payload with rich elements but NO title text and no roundtrip memory
        payload = training_settings_payload()
        payload["text_regions"] = []
        payload["numeric_regions"] = []
        payload["overlay_regions"] = []
        result = interpret(payload)
        self.assertEqual(result["semantic_candidates"], [])

    def test_fail_2_coordinates_do_not_create_semantic_identity(self):
        payload = training_settings_payload()
        payload["text_regions"] = [
            r for r in payload["text_regions"] if r["text"] != "研修設定"
        ]
        result = interpret(payload)
        for candidate in result["semantic_candidates"]:
            self.assertNotEqual(candidate["identity_source"], "coordinate_only")
            self.assertNotEqual(candidate["identity_source"], "shape_only")

    def test_fail_3_no_execution_permission_or_click_coordinates(self):
        blob = self._serialized(training_settings_payload())
        self.assertNotIn("permission", blob)
        self.assertNotIn("authorized", blob)
        # target_element_id is an id reference, not a coordinate pair
        result = interpret(training_settings_payload())
        for action in result["permitted_actions"]:
            self.assertNotIn("coordinate", action)
            self.assertNotIn("bbox", action)
            self.assertNotIn("x", action)
            self.assertNotIn("y", action)
            self.assertNotIn("next_screen", action)
            self.assertNotIn("strategy", action)

    def test_non_contract_input_rejected(self):
        bad = training_settings_payload()
        bad["semantic_state"] = "TRAINING_SETTINGS"
        with self.assertRaises(VisionContractError):
            interpret(bad)


if __name__ == "__main__":
    unittest.main()
