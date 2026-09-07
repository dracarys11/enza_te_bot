from __future__ import annotations

import tempfile
import unittest

from harness.vocal_harness import VocalHarness
from test_mvp_runtime_runner import payload


class VocalHarnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.harness = VocalHarness(storage_dir=self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_home_proposes_produce(self):
        record = self.harness.submit_observation(payload("HOME", "h"))
        self.assertEqual(record.proposed_action, "produce_open")
        self.assertEqual(record.status, "PROPOSED")

    def test_wing_proposes_training(self):
        record = self.harness.submit_observation(payload("WING_SELECTION", "w"))
        self.assertEqual(record.proposed_action, "open_training_settings")

    def test_training_proposes_vocal_plus(self):
        record = self.harness.submit_observation(payload("TRAINING_SETTINGS", "t", 0))
        self.assertEqual(record.proposed_action, "vocal_plus")
        self.assertEqual(record.verification_rule["delta"], 1)

    def test_unknown_stops_without_action(self):
        p = payload("HOME", "u")
        p["text_regions"] = []
        record = self.harness.submit_observation(p)
        self.assertIsNone(record.proposed_action)
        self.assertEqual(record.status, "REJECTED")
        self.assertEqual(record.policy_id, "VOCAL_MVP_001")

    def test_approval_is_record_only(self):
        record = self.harness.submit_observation(payload("HOME", "a"))
        approved = self.harness.approve_action("a")
        self.assertEqual(approved.status, "APPROVED")
        self.assertTrue(self.harness.approvals[-1]["approved_by_human"])
        self.assertFalse(hasattr(self.harness, "execute"))

    def test_counter_verification(self):
        before = payload("TRAINING_SETTINGS", "b", 0)
        after = payload("TRAINING_SETTINGS", "c", 1)
        result = self.harness.verify_transition(before, after)
        self.assertTrue(result["passed"])
        self.assertEqual((result["old_value"], result["new_value"]), (0, 1))

    def test_screenshot_only_and_coordinate_only_do_not_propose(self):
        p = payload("TRAINING_SETTINGS", "x", 0)
        p["text_regions"] = []
        record = self.harness.submit_observation(p)
        self.assertIsNone(record.proposed_action)
        self.assertEqual(record.status, "REJECTED")


if __name__ == "__main__":
    unittest.main()
