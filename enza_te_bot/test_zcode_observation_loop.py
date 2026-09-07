"""Tests for the screenshot-to-observation adapter and the VOCAL MVP loop."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from vision_adapter import VisionAdapter, VisionAdapterError
from zcode_observation_loop import run_observation_loop

import mvp001_action_request
import vision_adapter
import zcode_observation_loop


def analyzer_returning(payload_template):
    def analyzer(screenshot_path: str):
        payload = json.loads(json.dumps(payload_template))  # deep copy
        # analyzers see the real file; simulate digest/frame being external
        return payload

    return analyzer


TRAINING_TEMPLATE = {
    "observation_id": "VOBS_TEST_TRAINING",
    "viewport": {"width": 1280, "height": 720},
    "text_regions": [
        {"id": "tt", "text": "研修設定", "bbox": [560, 88, 180, 44], "confidence": 0.98},
        {"id": "tv", "text": "ボーカル", "bbox": [360, 200, 120, 32], "confidence": 0.96},
    ],
    "interaction_candidates": [
        {"id": "eplus", "bbox": [440, 330, 56, 56],
         "appearance": {"shape": "circle_button", "color_hint": "orange"},
         "linked_text_ids": [], "interaction_confidence": 0.88},
        {"id": "eminus", "bbox": [330, 330, 56, 56],
         "appearance": {"shape": "circle_button", "color_hint": "grey"},
         "linked_text_ids": [], "interaction_confidence": 0.88},
    ],
    "numeric_regions": [
        {"id": "n1", "raw_text": "0/20", "value": 0, "max_value": 20,
         "bbox": [410, 338, 60, 34], "confidence": 0.97},
    ],
    "overlay_regions": [],
    "uncertainties": [],
}

UNKNOWN_TEMPLATE = {
    "observation_id": "VOBS_TEST_UNKNOWN",
    "viewport": {"width": 1280, "height": 720},
    "text_regions": [],
    "interaction_candidates": [
        {"id": "e1", "bbox": [100, 100, 50, 50],
         "appearance": {"shape": "circle_button", "color_hint": "grey"},
         "linked_text_ids": [], "interaction_confidence": 0.9},
    ],
    "numeric_regions": [],
    "overlay_regions": [],
    "uncertainties": [],
}


class LoopTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.screenshot = os.path.join(self.tmp.name, "frame_0001.png")
        with open(self.screenshot, "wb") as handle:
            handle.write(b"\x89PNG fake bytes for contract tests")
        self.sessions_dir = os.path.join(self.tmp.name, "harness_sessions")


class PassCases(LoopTestCase):
    def test_pass_screenshot_path_creates_observation(self):
        adapter = VisionAdapter(analyzer_returning(TRAINING_TEMPLATE))
        observation = adapter.analyze_screenshot(self.screenshot)
        self.assertEqual(observation.observation_id, "VOBS_TEST_TRAINING")
        self.assertIn("sha256:", observation.capture["screenshot_digest"])

    def test_pass_vision_response_accepted_end_to_end(self):
        adapter = VisionAdapter(analyzer_returning(TRAINING_TEMPLATE))
        record = run_observation_loop(
            self.screenshot, adapter, sessions_dir=self.sessions_dir
        )
        self.assertEqual(record.state_label, "TRAINING_SETTINGS")
        self.assertIsNotNone(record.action_request)
        self.assertEqual(record.action_request["intent"], "INCREASE_VOCAL")
        self.assertIn("0/20 -> 1/20", record.action_request["expected_result"])
        # stored record
        with open(record.record_path, encoding="utf-8") as handle:
            stored = json.load(handle)
        self.assertEqual(stored["screenshot_path"], os.path.abspath(self.screenshot))
        self.assertEqual(stored["observation_id"], "VOBS_TEST_TRAINING")
        self.assertIn("vision_response", stored)
        self.assertIn("decision", stored)
        self.assertFalse(stored["decision"]["executed"])

    def test_pass_missing_screenshot_rejected(self):
        adapter = VisionAdapter(analyzer_returning(TRAINING_TEMPLATE))
        with self.assertRaises(VisionAdapterError):
            adapter.analyze_screenshot(os.path.join(self.tmp.name, "does_not_exist.png"))

    def test_pass_invalid_semantic_fields_rejected(self):
        for forbidden in ("semantic_state", "action", "recommendation"):
            template = json.loads(json.dumps(TRAINING_TEMPLATE))
            template[forbidden] = "x"
            adapter = VisionAdapter(analyzer_returning(template))
            with self.assertRaises(VisionAdapterError) as ctx:
                adapter.analyze_screenshot(self.screenshot)
            self.assertIn("violates VisionObservation contract", str(ctx.exception))

    def test_pass_unknown_observation_stops(self):
        adapter = VisionAdapter(analyzer_returning(UNKNOWN_TEMPLATE))
        record = run_observation_loop(self.screenshot, adapter, sessions_dir=self.sessions_dir)
        self.assertEqual(record.state_label, "UNKNOWN")
        self.assertIsNone(record.action_request)
        self.assertTrue(any("UNKNOWN" in u for u in record.unknown))


class FailGuards(LoopTestCase):
    def test_fail_screenshot_does_not_directly_create_action(self):
        # An analyzer that sees the TRAINING template but the interpreter gets
        # no text: verify no request materializes without perception evidence.
        template = json.loads(json.dumps(TRAINING_TEMPLATE))
        template["text_regions"] = []
        template["numeric_regions"] = []
        adapter = VisionAdapter(analyzer_returning(template))
        record = run_observation_loop(self.screenshot, adapter, sessions_dir=self.sessions_dir)
        self.assertIsNone(record.action_request)

    def test_fail_screenshot_filename_does_not_create_state(self):
        # Name the file "home.png" but the vision payload carries no text:
        # the filename must never become state evidence.
        named = os.path.join(self.tmp.name, "home.png")
        os.replace(self.screenshot, named)
        self.screenshot = named
        adapter = VisionAdapter(analyzer_returning(UNKNOWN_TEMPLATE))
        record = run_observation_loop(self.screenshot, adapter, sessions_dir=self.sessions_dir)
        self.assertEqual(record.state_label, "UNKNOWN")

    def test_fail_vision_adapter_creates_no_permission(self):
        adapter = VisionAdapter(analyzer_returning(TRAINING_TEMPLATE))
        observation = adapter.analyze_screenshot(self.screenshot)
        blob = json.dumps(observation.__dict__)
        for forbidden in ("permission", "authorized", "execute"):
            self.assertNotIn(forbidden, blob)
        self.assertFalse(hasattr(observation, "execute"))
        self.assertFalse(hasattr(vision_adapter.VisionAdapter, "execute"))
        self.assertFalse(hasattr(zcode_observation_loop, "execute"))
        self.assertFalse(hasattr(mvp001_action_request, "execute"))


if __name__ == "__main__":
    unittest.main()
