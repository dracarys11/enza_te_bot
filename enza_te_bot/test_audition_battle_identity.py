import json
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from vision import detect_audition_battle_speed, detect_state


BASE = Path(__file__).resolve().parent


class AuditionBattleIdentityTest(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((BASE / "config.json").read_text())

    def test_page_layout_survives_mutable_control_contents(self):
        h, w = 100, 100
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        # Stable bright/outlined control containers in the configured top-right
        # regions; their interiors represent different Auto/speed states.
        for x1, x2 in ((79, 85), (86, 93), (93, 100)):
            frame[2:14, x1:x2] = 150
            frame[4:12, x1 + 1:x2 - 1] = 240
        off = detect_state(Image.fromarray(frame), self.config, BASE)
        self.assertEqual(off.state.value, "AUDITION_BATTLE")
        frame[4:12, 80:84] = 30
        frame[4:12, 87:92] = 30
        on = detect_state(Image.fromarray(frame), self.config, BASE)
        self.assertEqual(on.state.value, "AUDITION_BATTLE")

    def test_unrelated_blank_page_is_not_battle(self):
        frame = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
        self.assertNotEqual(detect_state(frame, self.config, BASE).state.value, "AUDITION_BATTLE")

    def test_real_invalid_entry_screenshot_is_battle(self):
        path = BASE / "logs" / "20260831_111719_117151_AUDITION_BATTLE_INVALID_ENTRY.png"
        if not path.exists():
            self.skipTest("real diagnostic fixture not present")
        detected = detect_state(Image.open(path), self.config, BASE)
        self.assertEqual(detected.state.value, "AUDITION_BATTLE")

    def test_real_speed_feature_samples(self):
        fixtures = {
            "20260831_224500_870120_AUDITION_BATTLE_LOCAL_STEP.png": 1,
            "20260831_111719_117151_AUDITION_BATTLE_INVALID_ENTRY.png": 2,
            "20260831_141330_087486_AUDITION_BATTLE_LOCAL_STEP.png": 3,
        }
        for filename, expected in fixtures.items():
            path = BASE / "logs" / filename
            if not path.exists():
                self.skipTest(f"real diagnostic fixture not present: {filename}")
            self.assertEqual(detect_audition_battle_speed(Image.open(path), self.config)["speed"], expected)


if __name__ == "__main__":
    unittest.main()
