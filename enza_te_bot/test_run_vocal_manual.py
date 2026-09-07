from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from harness.run_vocal_manual import load_observation, run_manual
from harness.vocal_harness import VocalHarness
from test_mvp_runtime_runner import payload


class ManualRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, value, name):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return str(path)

    def test_session_starts_and_screenshot_payload_is_accepted(self):
        p = payload("HOME", "h")
        screenshot = self.root / "screen.png"
        screenshot.write_bytes(b"offline")
        path = self.write(p, "home.json")
        obs, _ = load_observation(screenshot_path=str(screenshot), payload_path=path)
        self.assertEqual(obs.observation_id, "h")

    def test_unknown_stops(self):
        p = payload("HOME", "u")
        p["text_regions"] = []
        path = self.write(p, "unknown.json")
        session = run_manual(first_payload=path, harness=VocalHarness(storage_dir=self.root),
                             input_fn=lambda _prompt: "approve")
        self.assertIsNone(session.decisions[0].proposed_action)

    def test_approval_records_only_and_verification_works(self):
        before = payload("TRAINING_SETTINGS", "b", 0)
        after = payload("TRAINING_SETTINGS", "a", 1)
        # Supply a proposal then verify manually; no execution is available.
        session = VocalHarness(storage_dir=self.root)
        record = session.submit_observation(before)
        self.assertEqual(record.status, "PROPOSED")
        session.approve_action(record.observation_id)
        verification = session.verify_transition(before, after)
        self.assertTrue(verification["passed"])
        self.assertFalse(hasattr(session, "execute"))

    def test_missing_observation_cannot_continue(self):
        with self.assertRaises(FileNotFoundError):
            load_observation(payload_path=str(self.root / "missing.json"))


if __name__ == "__main__":
    unittest.main()
