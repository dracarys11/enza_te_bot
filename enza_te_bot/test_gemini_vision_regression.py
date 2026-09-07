"""Regression checks for the Gemini raw-facts boundary."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from observation_interpreter import interpret
from vision_observation_schema import VisionContractError, VisionObservation


ROOT = Path(__file__).parent
GOOD = ROOT / "skills" / "gemini_vision" / "examples" / "good.json"
BAD = ROOT / "skills" / "gemini_vision" / "examples" / "bad.json"


class GeminiVisionRegression(unittest.TestCase):
    def test_good_raw_facts_enter_pipeline_with_text_identity(self):
        payload = json.loads(GOOD.read_text(encoding="utf-8"))
        # The fixture is intentionally generic; this regression exercises the
        # same raw-facts envelope with a W.I.N.G. title observation.
        payload["text_regions"] = [
            {"id": "title", "text": "W.I.N.G.", "bbox": [40, 30, 160, 60], "confidence": 0.96}
        ]
        # The raw example intentionally leaves capture identity blank; the
        # adapter supplies these fields before schema validation.
        payload["observation_id"] = "GEMINI_GOOD_001"
        payload["capture"] = {"timestamp": "2026-09-03T00:00:00Z", "frame_id": "frame-1",
                               "screenshot_digest": "sha256:fixture"}
        payload["interaction_candidates"][0]["shape"] = "rounded_rect"
        payload["interaction_candidates"][0]["appearance"]["shape"] = "rounded_rect"
        payload["interaction_candidates"][0]["interaction_confidence"] = 0.91
        observation = VisionObservation.from_payload(payload)
        self.assertEqual(VisionObservation.validate(payload), [])
        forbidden = {"semantic_state", "page_name", "screen_name", "current_state", "next_action",
                     "recommendation", "button_purpose", "intent", "strategy", "game_progress", "state", "action"}
        self.assertFalse(forbidden.intersection(payload))
        result = interpret(payload)
        candidate = next(c for c in result["semantic_candidates"] if c["label"] == "WING_SELECTION")
        self.assertEqual(candidate["identity_source"], "title_text_read")
        self.assertTrue(candidate["evidence_refs"])
        self.assertEqual(observation.observation_id, payload["observation_id"])

    def test_bad_semantic_payload_is_rejected(self):
        payload = json.loads(BAD.read_text(encoding="utf-8"))
        with self.assertRaises(VisionContractError):
            VisionObservation.from_payload(payload)


if __name__ == "__main__":
    unittest.main()
