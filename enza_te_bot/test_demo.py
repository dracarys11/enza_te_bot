import json
import tempfile
import unittest
from collections import deque
from io import StringIO
from pathlib import Path
from queue import Queue
from unittest.mock import patch

from PIL import Image

from demo_recorder import (DemoSnapshot, RawMouseEvent, _inside, _latest_before,
                           build_demo_step, build_interaction_record, group_raw_events,
                           make_mouse_callback, match_named_action)
from demo_compiler import review_demo, validate_demo_metadata


class DemoInfrastructureTest(unittest.TestCase):
    def test_normalized_click_inside_window(self):
        window = {"left": 10, "top": 20, "width": 100, "height": 80}
        self.assertTrue(_inside((50, 60), window))
        self.assertFalse(_inside((5, 60), window))

    def test_recorder_never_exposes_injection_api(self):
        import demo_recorder
        self.assertFalse(hasattr(demo_recorder, "click"))

    def test_listener_callback_only_enqueues_left_press(self):
        events = Queue()
        callback = make_mouse_callback(events, left_button="left", monotonic=lambda: 10.0,
                                       wall_time=lambda: 20.0)
        callback(12, 34, "right", True)
        callback(12, 34, "left", False)
        self.assertTrue(events.empty())
        callback(12, 34, "left", True)
        self.assertEqual(events.get_nowait(), RawMouseEvent(10.0, 20.0, 12, 34, "left"))

    def test_latest_pre_observation_actually_precedes_click(self):
        snapshots = deque([
            DemoSnapshot(1.0, 1.0, Image.new("RGB", (10, 10)), {}, "HOME", 1.0, None),
            DemoSnapshot(2.0, 2.0, Image.new("RGB", (10, 10)), {}, "HOME", 1.0, None),
            DemoSnapshot(4.0, 4.0, Image.new("RGB", (10, 10)), {}, "PRODUCE_MENU", 1.0, None),
        ])
        self.assertEqual(_latest_before(snapshots, 3.0).captured_at, 2.0)

    def test_contiguous_clicks_are_grouped_but_not_dropped(self):
        events = [
            RawMouseEvent(1.0, 1.0, 1, 1, "left"),
            RawMouseEvent(1.2, 1.2, 2, 2, "left"),
            RawMouseEvent(2.0, 2.0, 3, 3, "left"),
        ]
        groups = group_raw_events(events, quiet_seconds=0.5)
        self.assertEqual([[event.x for event in group] for group in groups], [[1, 2], [3]])

    def test_click_maps_only_to_current_state_named_action(self):
        config = {"states": {
            "HOME": {"allowed_actions": [
                {"name": "produce_start", "type": "click", "box": [0.1, 0.1, 0.3, 0.3],
                 "expected_next_states": ["PRODUCE_MENU"]},
            ]},
            "PRODUCE_MENU": {"allowed_actions": [
                {"name": "vocal_lesson", "type": "click", "box": [0.1, 0.1, 0.3, 0.3],
                 "expected_next_states": ["VOCAL_RESULT"]},
            ]},
        }}
        match = match_named_action(config, "HOME", [0.2, 0.2])
        self.assertEqual((match["classification"], match["name"]), ("NAMED_ACTION", "produce_start"))
        self.assertEqual(match_named_action(config, "HOME", [0.8, 0.8])["classification"], "UNKNOWN_CLICK")

    def test_demo_step_records_observations_action_result_and_human_query(self):
        config = {"states": {"HOME": {"allowed_actions": []}, "UNKNOWN": {"allowed_actions": []}}}
        window = {"left": 100, "top": 200, "width": 100, "height": 100}
        pre = DemoSnapshot(1.0, 1.0, Image.new("RGB", (20, 20), "white"), window, "HOME", 1.0, "home.png")
        post = DemoSnapshot(2.0, 2.0, Image.new("RGB", (20, 20), "black"), window, "UNKNOWN", 0.0, None)
        event = RawMouseEvent(1.5, 1.5, 150, 250, "left")
        with tempfile.TemporaryDirectory() as temp:
            record, need = build_demo_step(0, event, pre, post, config, Path(temp))
            self.assertEqual(record["human_action"]["classification"], "UNKNOWN_CLICK")
            self.assertEqual(record["after_observation"]["state"], "UNKNOWN")
            self.assertEqual(record["transition_result"]["classification"], "POST_STATE_UNKNOWN")
            self.assertIsNotNone(need)
            self.assertTrue(Path(record["observation"]["screenshot"]).exists())
            json.dumps(record)

    def test_interaction_record_contains_one_aggregated_action(self):
        config = {"states": {"HOME": {"allowed_actions": []}}}
        window = {"left": 0, "top": 0, "width": 100, "height": 100}
        pre = DemoSnapshot(1.0, 1.0, Image.new("RGB", (20, 20), "white"), window, "HOME", 1.0, None)
        post = DemoSnapshot(2.0, 2.0, Image.new("RGB", (20, 20), "black"), window, "HOME", 1.0, None)
        events = [RawMouseEvent(1.0, 1.0, 50, 50, "left"), RawMouseEvent(1.2, 1.2, 51, 51, "left")]
        with tempfile.TemporaryDirectory() as temp:
            record, _ = build_interaction_record(0, events, pre, post, config, Path(temp))
        self.assertEqual(record["kind"], "normalized_interaction")
        self.assertEqual(record["raw_event_count"], 2)
        self.assertEqual(record["human_action"]["click_count"], 2)

    def test_review_demo_replays_completed_raw_steps(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            root = base / "logs" / "demos" / "WEEK_001"
            root.mkdir(parents=True)
            (root / "metadata.json").write_text(json.dumps({
                "demo_id": "WEEK_001", "name": "WEEK", "status": "COMPLETED", "steps": 1,
            }), encoding="utf-8")
            record = {
                "kind": "demo_step", "step": 0,
                "observation": {"state": "HOME", "screenshot": "pre.png", "numeric": {"parsed": {"weeks_remaining": 3}}},
                "human_action": {"name": "produce_start", "normalized_point": [0.5, 0.5]},
                "after_observation": {"state": "PRODUCE_MENU"},
                "transition_result": {"classification": "EXPECTED_TRANSITION"},
            }
            (root / "episode.jsonl").write_text(json.dumps(record) + "\n", encoding="utf-8")
            with patch("demo_compiler.BASE_DIR", base), patch("sys.stdout", new_callable=StringIO) as output:
                self.assertEqual(review_demo("WEEK"), 0)
            rendered = output.getvalue()
            self.assertIn("Step 0 / Week 3", rendered)
            self.assertIn("produce_start", rendered)
            self.assertIn("EXPECTED_TRANSITION", rendered)

    def test_incomplete_demo_refused(self):
        with self.assertRaises(ValueError):
            validate_demo_metadata({"status": "RECORDING"})
        with self.assertRaises(ValueError):
            validate_demo_metadata({"status": "FAILED"})
        validate_demo_metadata({"status": "COMPLETED"})


if __name__ == "__main__":
    unittest.main()
