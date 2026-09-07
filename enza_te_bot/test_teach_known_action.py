"""Known inert-state action teaching retains visual evidence and writes safely."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

import capture_action_box
from capture_action_box import capture_action_from_image
import teaching_console


class TeachKnownActionTest(unittest.TestCase):
    def test_known_inert_state_can_gain_action_without_losing_template(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            config = {
                "states": {
                    "HOME": {"templates": ["home_marker.png"], "allowed_actions": []},
                    "PROMISE_CHOICE": {"templates": ["promise_choice_marker.png"], "allowed_actions": []},
                },
                "game_window": None,
                "capture_scale": {"x": 2.0, "y": 2.0},
            }
            (base / "config.json").write_text(json.dumps(config), encoding="utf-8")
            image = Image.new("RGB", (200, 100))
            window = {"left": 0, "top": 0, "width": 100, "height": 50}
            selection = ((20, 10, 40, 20), (20, 10, 40, 20), (200, 100), (200, 100), 1.0, (200, 100))
            with patch.object(capture_action_box, "BASE_DIR", base), \
                 patch("capture_action_box.select_scaled_roi", return_value=selection):
                result = capture_action_from_image(image, window, config, "PROMISE_CHOICE", "promise_decline", ["HOME"])
            saved = json.loads((base / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["states"]["PROMISE_CHOICE"]["templates"], ["promise_choice_marker.png"])
            self.assertEqual(saved["states"]["PROMISE_CHOICE"]["allowed_actions"], [{
                "name": "promise_decline", "type": "click", "box": [0.1, 0.1, 0.3, 0.3], "expected_next_states": ["HOME"],
            }])
            self.assertIsNotNone(result)
            self.assertTrue(Path(result["backup"]).exists())

    def test_known_no_action_teaching_path_offers_explicit_action_capture(self) -> None:
        config = {"states": {
            "HOME": {"templates": [], "allowed_actions": []},
            "PROMISE_CHOICE": {"templates": ["promise_choice_marker.png"], "allowed_actions": []},
        }}
        with TemporaryDirectory() as directory, \
             patch("builtins.input", side_effect=["HOME", "promise_decline"]), \
             patch("teaching_console.capture_action_from_image", return_value={
                 "action": {"name": "promise_decline"}, "backup": "/tmp/config_backup.json"
             }) as capture:
            action = teaching_console._teach_action_for_known_state(
                config, Image.new("RGB", (10, 10)), {}, "PROMISE_CHOICE", Path(directory) / "teach.jsonl"
            )
        self.assertEqual(action, "promise_decline")
        capture.assert_called_once()
        self.assertEqual(config["states"]["PROMISE_CHOICE"]["templates"], ["promise_choice_marker.png"])

    def test_capture_appends_new_named_action_without_losing_existing_action(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            config = {
                "states": {
                    "PRODUCE_MENU": {"templates": ["produce_menu_marker.png"], "allowed_actions": [{
                        "name": "vocal_lesson", "type": "click", "box": [0.1, 0.1, 0.2, 0.2],
                        "expected_next_states": ["VOCAL_RESULT"],
                    }]},
                    "VOCAL_RESULT": {"templates": [], "allowed_actions": []},
                    "AUDITION_SELECT": {"templates": [], "allowed_actions": []},
                },
                "game_window": None,
                "capture_scale": {"x": 1.0, "y": 1.0},
            }
            (base / "config.json").write_text(json.dumps(config), encoding="utf-8")
            image = Image.new("RGB", (100, 50))
            window = {"left": 0, "top": 0, "width": 100, "height": 50}
            selection = ((40, 20, 20, 10), (40, 20, 20, 10), (100, 50), (100, 50), 1.0, (100, 50))
            with patch.object(capture_action_box, "BASE_DIR", base), \
                 patch("capture_action_box.select_scaled_roi", return_value=selection):
                capture_action_from_image(image, window, config, "PRODUCE_MENU", "audition_start", ["AUDITION_SELECT"])
            saved = json.loads((base / "config.json").read_text(encoding="utf-8"))
            self.assertEqual([action["name"] for action in saved["states"]["PRODUCE_MENU"]["allowed_actions"]],
                             ["vocal_lesson", "audition_start"])

    def test_battle_toggle_actions_coexist_with_same_state_completion_and_once_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            base = Path(directory)
            config = {
                "states": {"AUDITION_BATTLE": {"templates": ["audition_battle_marker.png"], "allowed_actions": []}},
                "game_window": None, "capture_scale": {"x": 1.0, "y": 1.0},
            }
            (base / "config.json").write_text(json.dumps(config), encoding="utf-8")
            image = Image.new("RGB", (100, 50))
            window = {"left": 0, "top": 0, "width": 100, "height": 50}
            selection = ((40, 20, 20, 10), (40, 20, 20, 10), (100, 50), (100, 50), 1.0, (100, 50))
            with patch.object(capture_action_box, "BASE_DIR", base), \
                 patch("capture_action_box.select_scaled_roi", return_value=selection):
                capture_action_from_image(image, window, config, "AUDITION_BATTLE", "battle_speed_on", ["AUDITION_BATTLE"], repeat="once")
            config = json.loads((base / "config.json").read_text(encoding="utf-8"))
            config["capture_scale"] = {"x": 1.0, "y": 1.0}
            with patch.object(capture_action_box, "BASE_DIR", base), \
                 patch("capture_action_box.select_scaled_roi", return_value=selection):
                capture_action_from_image(image, window, config, "AUDITION_BATTLE", "battle_auto_on", ["AUDITION_BATTLE"], repeat="once")
            saved = json.loads((base / "config.json").read_text(encoding="utf-8"))
            actions = saved["states"]["AUDITION_BATTLE"]["allowed_actions"]
            self.assertEqual([action["name"] for action in actions], ["battle_speed_on", "battle_auto_on"])
            self.assertTrue(all(action["expected_next_states"] == ["AUDITION_BATTLE"] for action in actions))
            self.assertTrue(all(action["repeat"] == "once" for action in actions))


if __name__ == "__main__":
    unittest.main()
