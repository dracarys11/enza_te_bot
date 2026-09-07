import argparse
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from audition_target_teaching import (add_cli_argument,
                                      capture_audition_target_from_image,
                                      feature_name, template_filename)


def _config():
    return {
        "game_window": None,
        "capture_scale": {"x": 1.0, "y": 1.0},
        "defaults": {"confidence": 0.88},
        "states": {
            "HOME": {"templates": ["home.png"], "allowed_actions": []},
            "AUDITION_TARGET_40000": {
                "templates": ["audition_target_40000_marker.png"],
                "feature_only": True,
                "roi": None,
                "confidence": 0.88,
                "allowed_actions": [],
                "expected_next_states": [],
                "timeout_seconds": 5,
                "retries": 0,
            },
            "AUDITION_TARGET_50000": {
                "templates": [], "feature_only": True, "roi": None,
                "confidence": 0.88, "allowed_actions": [],
                "expected_next_states": [], "timeout_seconds": 5, "retries": 0,
            },
        },
    }


class AuditionTargetTeachingTest(unittest.TestCase):
    def test_cli_argument_parsing(self):
        parser = argparse.ArgumentParser()
        add_cli_argument(parser)
        self.assertEqual(parser.parse_args(["--teach-audition-target", "50000"]).teach_audition_target, 50000)
        with self.assertRaises(SystemExit):
            parser.parse_args(["--teach-audition-target", "12345"])

    def test_names_are_exact(self):
        self.assertEqual(feature_name(50000), "AUDITION_TARGET_50000")
        self.assertEqual(template_filename(50000), "audition_target_50000_marker.png")

    def test_capture_updates_only_matching_feature_and_never_clicks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "templates").mkdir()
            config = _config()
            (base / "config.json").write_text(json.dumps(config), encoding="utf-8")
            original_home = copy.deepcopy(config["states"]["HOME"])
            selection = ((20, 10, 30, 12), (20, 10, 30, 12), (100, 50), (100, 50), 1.0, (100, 50))
            with patch("capture_template.select_scaled_roi", return_value=selection), \
                 patch("pyautogui.click") as click:
                result = capture_audition_target_from_image(
                    Image.new("RGB", (100, 50), "white"),
                    {"left": 0, "top": 0, "width": 100, "height": 50},
                    config, 50000, base_dir=base,
                )
            self.assertIsNotNone(result)
            click.assert_not_called()
            written = json.loads((base / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(written["states"]["HOME"], original_home)
            feature = written["states"]["AUDITION_TARGET_50000"]
            self.assertTrue(feature["feature_only"])
            self.assertEqual(feature["templates"], ["audition_target_50000_marker.png"])
            self.assertTrue((base / "templates" / "audition_target_50000_marker.png").is_file())

    def test_missing_100000_feature_gets_inert_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "templates").mkdir()
            config = _config()
            (base / "config.json").write_text(json.dumps(config), encoding="utf-8")
            selection = ((20, 10, 30, 12), (20, 10, 30, 12), (100, 50), (100, 50), 1.0, (100, 50))
            with patch("capture_template.select_scaled_roi", return_value=selection):
                capture_audition_target_from_image(
                    Image.new("RGB", (100, 50), "white"),
                    {"left": 0, "top": 0, "width": 100, "height": 50},
                    config, 100000, base_dir=base,
                )
            feature = json.loads((base / "config.json").read_text(encoding="utf-8"))["states"]["AUDITION_TARGET_100000"]
            self.assertTrue(feature["feature_only"])
            self.assertEqual(feature["allowed_actions"], [])
            self.assertEqual(feature["templates"], ["audition_target_100000_marker.png"])

    def test_existing_40000_feature_and_template_remain_registered(self):
        config = _config()
        self.assertTrue(config["states"]["AUDITION_TARGET_40000"]["feature_only"])
        self.assertIn("audition_target_40000_marker.png", config["states"]["AUDITION_TARGET_40000"]["templates"])


if __name__ == "__main__":
    unittest.main()
