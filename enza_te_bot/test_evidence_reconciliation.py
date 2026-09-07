"""Offline regressions for append-only Phase 1E evidence reconciliation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from evidence_reconciliation import (
    AUDIT_FAILED, EvidenceReconciliationError, load_evidence_reconciliation,
    ObservationReconciler, validate_evidence_reconciliation,
)


ROOT = Path(__file__).resolve().parent
REAL_RECORD = ROOT / "enza_memory/reconciliations/phase1e_r_evidence_reconciliation.json"


def valid_record() -> dict:
    return {
        "schema_version": 1,
        "reconciliation_id": "REC_TEST",
        "executable": False,
        "original_artifacts_mutated": False,
        "observations": [{
            "observation_id": "OBS_1",
            "original_artifact": "observations/OBS_1.json",
            "original_artifact_sha256": "digest",
            "original_claim": {"state": "ITEM_SELECTION", "classification": "INFERENCE"},
            "supporting_evidence": [{"reference": "observations/OBS_1.json"}],
            "conflicting_evidence": [{"reference": "screenshots/OBS_1.png"}],
            "final_classification": {"state": "UNKNOWN", "classification": "UNKNOWN"},
        }],
        "added_observed_states": [{
            "label": "LOADING_TRANSITION", "classification": "INFERENCE",
            "evidence_refs": ["screenshots/OBS_1.png"],
        }],
        "affected_trajectories": [{
            "trajectory_id": "TRAJ_1",
            "original_artifact": "trajectories/TRAJ_1.json",
            "original_artifact_sha256": "digest",
            "status": AUDIT_FAILED,
        }],
    }


class EvidenceReconciliationTests(unittest.TestCase):
    def test_contradictory_screenshot_cannot_remain_verified(self) -> None:
        data = valid_record()
        data["observations"][0]["final_classification"]["classification"] = "VERIFIED"
        with self.assertRaisesRegex(
            EvidenceReconciliationError, "contradictory evidence cannot remain",
        ):
            validate_evidence_reconciliation(data)

    def test_unknown_survives_reload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "record.json"
            path.write_text(json.dumps(valid_record()), encoding="utf-8")
            record = load_evidence_reconciliation(path)
        self.assertEqual(
            record.observations[0].final_classification["classification"], "UNKNOWN")

    def test_audit_failure_status_is_preserved(self) -> None:
        record = validate_evidence_reconciliation(valid_record())
        self.assertEqual(record.affected_trajectories[0].status, AUDIT_FAILED)

        changed = valid_record()
        changed["affected_trajectories"][0]["status"] = "PASS"
        with self.assertRaisesRegex(EvidenceReconciliationError, "preserve audit failure"):
            validate_evidence_reconciliation(changed)

    def test_loading_does_not_mutate_original_artifact(self) -> None:
        source = ROOT / "ai_decisions/observations/OBS_20260903060520.json"
        before = source.read_bytes()
        record = load_evidence_reconciliation(REAL_RECORD, repository_root=ROOT)
        after = source.read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(len(record.observations), 4)

    def test_real_reconciliation_validates_original_digests(self) -> None:
        record = load_evidence_reconciliation(REAL_RECORD, repository_root=ROOT)
        self.assertEqual(
            {item.observation_id for item in record.observations},
            {
                "OBS_20260903060520", "OBS_20260903060545",
                "OBS_20260903060610", "OBS_20260903063000",
            },
        )
        self.assertEqual(
            {item["label"] for item in record.added_observed_states},
            {"LOADING_TRANSITION", "UNIT_FORMATION_TUTORIAL_MODAL"},
        )


class RuntimeTimeoutReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.reconciler = ObservationReconciler()
        self.reconciler.action_sent("VOCAL", {"x": 1}, "OBS_BEFORE")

    def test_timeout_does_not_imply_failure_or_retry(self):
        result = self.reconciler.timeout("PAGE_STATE_TIMEOUT")
        self.assertEqual(result.status, "RECONCILIATION_REQUIRED")
        self.assertTrue(result.pending_action.stale)
        self.assertFalse(result.pending_action.retry_eligible)

    def test_transition_after_timeout_clears_pending_without_duplicate_action(self):
        self.reconciler.timeout("SCREENSHOT_TIMEOUT")
        result = self.reconciler.reconcile(
            state="HOME_AFTER_VOCAL", stable=True,
            observation_id="OBS_AFTER", transition_succeeded=True,
        )
        self.assertEqual(result.status, "RECONCILED")
        self.assertIsNone(self.reconciler.pending_action)

    def test_original_state_allows_retry_only_after_fresh_observation(self):
        self.reconciler.timeout("CONTROL_FAILURE")
        stale = self.reconciler.reconcile(state="HOME", stable=True,
                                           observation_id="OBS_BEFORE")
        self.assertEqual(stale.status, "RECONCILIATION_REQUIRED")
        fresh = self.reconciler.reconcile(state="HOME", stable=True,
                                          observation_id="OBS_AFTER")
        self.assertEqual(fresh.status, "RETRY_ELIGIBLE")
        self.assertTrue(fresh.pending_action.retry_eligible)

    def test_stale_control_target_cannot_authorize_retry(self):
        self.reconciler.timeout("TOOL_LATENCY_BUDGET_EXCEEDED")
        self.assertFalse(self.reconciler.pending_action.retry_eligible)
        self.assertEqual(self.reconciler.reconcile(
            state="HOME", stable=False, observation_id="OBS_AFTER").status,
            "RECONCILIATION_REQUIRED")

    def test_screenshot_timeout_is_bounded(self):
        first = self.reconciler.timeout("SCREENSHOT_TIMEOUT")
        second = self.reconciler.timeout("SCREENSHOT_TIMEOUT")
        self.assertEqual(first.screenshot_attempts, 1)
        self.assertEqual(second.status, "FAIL_CLOSED")
        self.assertEqual(second.screenshot_attempts, 2)

    def test_session_release_remains_fail_closed(self):
        self.reconciler.timeout("SESSION_RELEASED")
        result = self.reconciler.reconcile(state="HOME", stable=True,
                                           observation_id="OBS_AFTER",
                                           transition_succeeded=True)
        self.assertEqual(result.status, "FAIL_CLOSED")
        with self.assertRaisesRegex(EvidenceReconciliationError, "RECONCILIATION_REQUIRED"):
            self.reconciler.action_sent("VOCAL", "new-target", "OBS_NEW")


if __name__ == "__main__":
    unittest.main()
