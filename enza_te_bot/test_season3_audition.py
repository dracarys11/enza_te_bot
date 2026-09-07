import unittest
from season3_audition import (commit_named_result, commit_result, commit_success,
                               missing_audition_actions, required_reward, target_is_locked)

class Season3AuditionTest(unittest.TestCase):
    def test_required_reward_order(self):
        s = {"season3": {}}
        self.assertEqual(required_reward(s), 40000)
        s["season3"]["audition_40k_completed"] = True
        self.assertEqual(required_reward(s), 50000)
        s["season3"]["audition_50k_completed"] = True
        self.assertIsNone(required_reward(s))
    def test_lock_and_commit_require_evidence(self):
        self.assertTrue(target_is_locked(target_reward=50000, current_fans=18775))
        state = {"season3": {}}
        self.assertFalse(commit_success(state, 40000, success_evidence=False))
        self.assertTrue(commit_success(state, 40000, success_evidence=True))
    def test_missing_confirm_is_reported(self):
        self.assertEqual(missing_audition_actions({"AUDITION_SELECT": {"allowed_actions": []}}), ["audition_confirm"])

    def test_result_room_alone_cannot_commit(self):
        state = {"season3": {}}
        outcome = commit_result(state, 40000, evidence={"room": "AUDITION_RESULT"})
        self.assertEqual(outcome, "UNKNOWN")
        self.assertEqual(state["season3"], {})

    def test_explicit_fail_never_commits_success(self):
        state = {"season3": {}}
        self.assertEqual(commit_result(state, 40000, evidence={
            "outcome": "FAIL", "evidence_class": "EXPLICIT_FAIL",
        }), "FAIL_RECORDED")
        self.assertFalse(state["season3"].get("audition_40k_completed", False))

    def test_explicit_pass_persists_before_commit(self):
        state = {"season3": {}}
        calls = []
        def persist(evidence):
            calls.append((dict(evidence), state["season3"].copy()))
        result = commit_result(state, 40000, evidence={
            "outcome": "PASS", "evidence_class": "EXPLICIT_PASS",
            "result_ref": "result-frame-1",
        }, persist_evidence=persist, result_id="R1")
        self.assertEqual(result, "COMMITTED")
        self.assertFalse(calls[0][1].get("audition_40k_completed", False))
        self.assertTrue(state["season3"]["audition_40k_completed"])

    def test_persistence_failure_prevents_commit(self):
        state = {"season3": {}}
        def persist(_):
            raise OSError("durability unavailable")
        with self.assertRaises(OSError):
            commit_result(state, 40000, evidence={
                "outcome": "PASS", "evidence_class": "EXPLICIT_PASS",
            }, persist_evidence=persist)
        self.assertFalse(state["season3"].get("audition_40k_completed", False))

    def test_unknown_and_result_page_do_not_commit(self):
        state = {"season3": {}}
        for evidence in (None, {"outcome": "PASS", "evidence_class": "RESULT_ROOM"},
                         {"outcome": "UNKNOWN", "evidence_class": "EXPLICIT_PASS"}):
            self.assertEqual(commit_result(state, 40000, evidence=evidence), "UNKNOWN")
        self.assertFalse(state["season3"].get("audition_40k_completed", False))

    def test_replayed_pass_is_idempotent(self):
        state = {"season3": {}}
        evidence = {"outcome": "PASS", "evidence_class": "EXPLICIT_PASS"}
        self.assertEqual(commit_result(state, 40000, evidence=evidence, result_id="R1"), "COMMITTED")
        self.assertEqual(commit_result(state, 40000, evidence=evidence, result_id="R1"), "ALREADY_COMMITTED")

    def test_semifinal_continuation_without_result_stays_unknown(self):
        state = {}
        self.assertEqual(commit_named_result(state, "SEMIFINAL_RESULT", evidence={
            "room": "SEMIFINAL_BANNER", "continuation": True,
        }), "UNKNOWN")
        self.assertNotIn("SEMIFINAL_RESULT", state)

    def test_named_result_pass_is_idempotent(self):
        state = {}
        evidence = {"outcome": "PASS", "evidence_class": "EXPLICIT_PASS"}
        self.assertEqual(commit_named_result(state, "SEMIFINAL_RESULT", evidence=evidence,
                                             result_id="S1"), "COMMITTED")
        self.assertEqual(commit_named_result(state, "SEMIFINAL_RESULT", evidence=evidence,
                                             result_id="S1"), "ALREADY_COMMITTED")

if __name__ == "__main__": unittest.main()
