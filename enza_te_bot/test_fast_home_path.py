import time
import unittest
from PIL import Image

import fast_home_path as fast


class FastHomePathTests(unittest.TestCase):
    def setUp(self):
        self.image = Image.new("RGB", (100, 80), "white")
        self.config = {"states": {}, "perception": {"home_observation": {
            "season": {"roi": [0, 0, .2, .2], "range": [1, 4]},
            "weeks_remaining": {"roi": [0, 0, .2, .2], "range": [0, 99], "template_matching": {}},
            "fan_gap_to_target": {"roi": [0, 0, .2, .2], "clear_marker": {}},
            "stamina": {"roi": [0, 0, .2, .2]},
        }}}

    def test_known_home_partial_fields_and_expected_is_hint(self):
        original_state, original_ocr = fast.detect_state, fast.smoke_ocr
        fast.detect_state = lambda *args: type("D", (), {"state": type("S", (), {"value": "HOME"})()})()
        fast.smoke_ocr = lambda *args, **kwargs: ({"season": "2"}, {"season": {"method": "stub"}})
        try:
            result = fast.observe_home_fast(self.image, self.config,
                                            required_fields=("season",), expected_values={"season": 3})
        finally:
            fast.detect_state, fast.smoke_ocr = original_state, original_ocr
        self.assertTrue(result.escalation_required)
        self.assertEqual(result.fields["season"], 2)
        self.assertIn("expected_value_conflict:season", result.escalation_reasons)
        self.assertIn("action_gate_ms", result.timings)

    def test_stale_viewport_and_anchor_block(self):
        observation = fast.HomeFastObservation("KNOWN", "HOME", {}, {}, "sha256:x", "vp1", {}, False, ())
        binding = fast.ControlBinding("HOME.produce_start", "HOME", "vp2", "game_window_normalized", (0,0,1,1), ("PRODUCE_MENU",))
        self.assertEqual(fast.authorize_control(observation, binding, action_ttl_valid=True, bbox_in_bounds=True, local_anchor_valid=True)[1], "STALE_VIEWPORT")
        binding = fast.ControlBinding("HOME.produce_start", "HOME", "vp1", "game_window_normalized", (0,0,1,1), ("PRODUCE_MENU",))
        self.assertEqual(fast.authorize_control(observation, binding, action_ttl_valid=True, bbox_in_bounds=True, local_anchor_valid=False)[1], "LOCAL_ANCHOR_MISMATCH")

    def test_expected_next_state_mismatch_is_unknown(self):
        original = fast.detect_state
        fast.detect_state = lambda *args: type("D", (), {"state": type("S", (), {"value": "HOME"})()})()
        try:
            self.assertEqual(fast.verify_expected_next_state(self.image, self.config, ("PRODUCE_MENU",)), (False, "UNKNOWN"))
        finally:
            fast.detect_state = original


if __name__ == "__main__":
    unittest.main()
