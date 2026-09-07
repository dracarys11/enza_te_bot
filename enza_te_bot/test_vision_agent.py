"""Tests for the screenshot-only VisionAgent boundary."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from vision_adapter import VisionAdapterError
from vision_agent.gemini_adapter import (
    GEMINI_VISION_SKILL_CONTRACT,
    GeminiVisionAdapter,
)
from vision_observation_schema import VisionObservation


class VisionAgentInterfaceTests(unittest.TestCase):
    def test_gemini_adapter_reuses_skill_contract_and_returns_valid_json(self):
        self.assertTrue(GEMINI_VISION_SKILL_CONTRACT.is_file())

        def extractor(_path):
            return {
                "viewport": {"width": 1280, "height": 720},
                "text_regions": [{
                    "id": "t1", "text": "次へ", "bbox": [10, 20, 40, 20],
                    "confidence": 0.99,
                }],
                "interaction_candidates": [],
                "numeric_regions": [],
                "overlay_regions": [],
                "uncertainties": [],
            }

        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            screenshot.write_bytes(b"fixture")
            payload = GeminiVisionAdapter(extractor).observe(str(screenshot))

        self.assertEqual(VisionObservation.validate(payload), [])
        self.assertEqual(payload["text_regions"][0]["text"], "次へ")
        self.assertNotIn("action", payload)
        self.assertNotIn("intent", payload)
        self.assertNotIn("strategy", payload)

    def test_semantic_output_from_extractor_is_rejected(self):
        def extractor(_path):
            return {
                "viewport": {"width": 1, "height": 1},
                "text_regions": [],
                "interaction_candidates": [],
                "numeric_regions": [],
                "overlay_regions": [],
                "uncertainties": [],
                "semantic_state": "invented",
            }

        with tempfile.TemporaryDirectory() as directory:
            screenshot = Path(directory) / "screen.png"
            screenshot.write_bytes(b"fixture")
            with self.assertRaises(VisionAdapterError):
                GeminiVisionAdapter(extractor).observe(str(screenshot))


if __name__ == "__main__":
    unittest.main()
