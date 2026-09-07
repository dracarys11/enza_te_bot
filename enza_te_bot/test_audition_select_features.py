import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from vision import detect_audition_target_reward, detect_state


def _fixture_config():
    return {
        "defaults": {"confidence": 0.88},
        "states": {
            "AUDITION_SELECT": {
                "templates": [], "roi": None, "confidence": 0.88,
                "allowed_actions": []
            },
            "AUDITION_TARGET_40000": {
                "templates": ["audition_target_40000_marker.png"],
                "feature_only": True, "roi": None, "confidence": 0.88
            },
            "AUDITION_TARGET_50000": {
                "templates": ["audition_target_50000_marker.png"],
                "feature_only": True, "roi": None, "confidence": 0.88
            }
        }
    }


class AuditionSelectFeatureTest(unittest.TestCase):
    def test_reward_marker_keeps_parent_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "templates").mkdir()
            pattern = np.arange(64, dtype=np.uint8).reshape(8, 8)
            cv2.imwrite(str(base / "templates" / "audition_target_40000_marker.png"), pattern)
            frame = np.zeros((32, 32), dtype=np.uint8)
            frame[12:20, 15:23] = pattern
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB))
            config = _fixture_config()
            detected = detect_state(image, config, base)
            self.assertEqual(detected.state.value, "AUDITION_SELECT")

    def test_reward_feature_is_available_to_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "templates").mkdir()
            pattern = np.arange(64, dtype=np.uint8).reshape(8, 8)
            cv2.imwrite(str(base / "templates" / "audition_target_40000_marker.png"), pattern)
            frame = np.zeros((32, 32), dtype=np.uint8)
            frame[12:20, 15:23] = pattern
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB))
            reward, score, template = detect_audition_target_reward(image, _fixture_config(), base)
            self.assertEqual(reward, 40000)
            self.assertGreaterEqual(score, 0.88)
            self.assertEqual(template, "audition_target_40000_marker.png")

    def test_50000_marker_uses_same_parent_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "templates").mkdir()
            pattern = np.flipud(np.arange(64, dtype=np.uint8).reshape(8, 8))
            cv2.imwrite(str(base / "templates" / "audition_target_50000_marker.png"), pattern)
            frame = np.zeros((32, 32), dtype=np.uint8)
            frame[10:18, 11:19] = pattern
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB))
            config = _fixture_config()
            self.assertEqual(detect_state(image, config, base).state.value, "AUDITION_SELECT")
            self.assertEqual(detect_audition_target_reward(image, config, base)[0], 50000)

    def test_unrelated_state_detection_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "templates").mkdir()
            pattern = np.arange(64, dtype=np.uint8).reshape(8, 8)
            cv2.imwrite(str(base / "templates" / "other.png"), pattern)
            config = _fixture_config()
            config["states"]["HOME"] = {"templates": ["other.png"], "roi": None,
                                           "confidence": 0.88, "allowed_actions": []}
            frame = np.zeros((32, 32), dtype=np.uint8)
            frame[2:10, 3:11] = pattern
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB))
            self.assertEqual(detect_state(image, config, base).state.value, "HOME")

    def test_produce_menu_not_misclassified_as_audition_select(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "templates").mkdir()
            prod_pattern = np.arange(64, dtype=np.uint8).reshape(8, 8)
            cv2.imwrite(str(base / "templates" / "produce_menu_marker.png"), prod_pattern)
            config = _fixture_config()
            config["states"]["AUDITION_SELECT"]["templates"] = ["audition_target_10000_marker.png"]
            config["states"]["PRODUCE_MENU"] = {
                "templates": ["produce_menu_marker.png"], "roi": None,
                "confidence": 0.85, "allowed_actions": []
            }
            frame = np.zeros((32, 32), dtype=np.uint8)
            frame[2:10, 3:11] = prod_pattern
            image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB))
            self.assertEqual(detect_state(image, config, base).state.value, "PRODUCE_MENU")


if __name__ == "__main__":
    unittest.main()

