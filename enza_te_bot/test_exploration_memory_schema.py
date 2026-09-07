"""Offline tests for non-executable exploration memory validation."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from exploration_memory_schema import (
    ExplorationMemorySchemaError, load_exploration_session,
    validate_exploration_session,
)


def valid_session() -> dict:
    return {
        "schema_version": 1,
        "executable": False,
        "session_id": "EXP_001",
        "objective": "map one bounded navigation transition",
        "scope": "PRODUCE_PREPARATION",
        "observations": [
            {
                "observation_id": "OBS_001",
                "evidence_refs": ["screenshots/OBS_001.png"],
                "state": "PRODUCE_SELECTION",
            },
            {
                "observation_id": "OBS_002",
                "evidence_refs": ["screenshots/OBS_002.png"],
                "state": "UNIT_FORMATION",
            },
        ],
        "decision_traces": [{
            "decision_id": "DT_001",
            "observation_id": "OBS_001",
            "candidate_actions": ["next", "stop"],
            "selected_action": "next",
            "evidence_refs": ["OBS_001", "screenshots/OBS_001.png"],
            "information_gain_category": "MAP_NEXT_STATE",
            "risk_level": "LOW",
            "expected_transition": "PRODUCE_SELECTION -> UNIT_FORMATION",
        }],
        "actions": [{"action_id": "ACT_001", "action": "next", "performed": True}],
        "transitions": [{
            "previous_state": "PRODUCE_SELECTION",
            "action": "next",
            "next_state": "UNIT_FORMATION",
            "evidence_refs": ["OBS_001", "OBS_002"],
            "verification_status": "VERIFIED",
            "unknowns": [],
        }],
        "verification_records": [{
            "verification_id": "VER_001", "status": "VERIFIED",
            "evidence_refs": ["OBS_002"],
        }],
        "facts": [{
            "claim_id": "FACT_001", "statement": "the URL remained unchanged",
            "classification": "FACT", "source": "SESSION_OBSERVED",
            "evidence_refs": ["OBS_001", "OBS_002"],
        }],
        "inferences": [{
            "claim_id": "INF_001", "statement": "next is likely navigation-only",
            "classification": "INFERENCE", "source": "DERIVED",
            "evidence_refs": ["VER_001"],
        }],
        "unknowns": [{
            "claim_id": "UNK_001", "statement": "later confirmation effect is unknown",
            "classification": "UNKNOWN", "source": "UNRESOLVED",
            "evidence_refs": ["OBS_002"],
        }],
        "stop_reason": "configured boundary reached",
    }


class ExplorationMemorySchemaTests(unittest.TestCase):
    def test_valid_exploration_session_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.json"
            path.write_text(json.dumps(valid_session()), encoding="utf-8")
            session = load_exploration_session(path)

        self.assertEqual(session.session_id, "EXP_001")
        self.assertFalse(session.executable)
        self.assertEqual(session.facts[0].classification, "FACT")
        self.assertEqual(session.inferences[0].classification, "INFERENCE")
        self.assertEqual(session.unknowns[0].classification, "UNKNOWN")

    def test_valid_decision_trace_references_observation(self) -> None:
        session = validate_exploration_session(valid_session())
        self.assertEqual(session.decision_traces[0].observation_id, "OBS_001")

    def test_transition_with_evidence_validates(self) -> None:
        session = validate_exploration_session(valid_session())
        transition = session.transitions[0]
        self.assertEqual(transition.verification_status, "VERIFIED")
        self.assertEqual(transition.evidence_refs, ("OBS_001", "OBS_002"))

    def test_decision_without_observation_is_rejected(self) -> None:
        data = valid_session()
        data["decision_traces"][0]["observation_id"] = "OBS_MISSING"
        with self.assertRaisesRegex(ExplorationMemorySchemaError, "missing observation"):
            validate_exploration_session(data)

    def test_missing_evidence_is_rejected(self) -> None:
        data = valid_session()
        data["transitions"][0]["evidence_refs"] = []
        with self.assertRaisesRegex(ExplorationMemorySchemaError, "evidence_refs is required"):
            validate_exploration_session(data)

    def test_inference_promoted_to_fact_is_rejected(self) -> None:
        data = valid_session()
        promoted = copy.deepcopy(data["inferences"][0])
        promoted["classification"] = "FACT"
        data["facts"].append(promoted)
        with self.assertRaisesRegex(ExplorationMemorySchemaError, "claim identity"):
            validate_exploration_session(data)

    def test_user_reported_claim_cannot_be_fact(self) -> None:
        data = valid_session()
        data["facts"][0]["source"] = "USER_REPORTED"
        with self.assertRaisesRegex(ExplorationMemorySchemaError, "user-reported"):
            validate_exploration_session(data)

    def test_exploration_memory_cannot_create_action_authorization(self) -> None:
        data = valid_session()
        data["actions"][0]["execution_permission"] = {"permission_id": "forged"}
        with self.assertRaisesRegex(ExplorationMemorySchemaError, "cannot contain action authorization"):
            validate_exploration_session(data)

        executable = valid_session()
        executable["executable"] = True
        with self.assertRaisesRegex(ExplorationMemorySchemaError, "executable=false"):
            validate_exploration_session(executable)


if __name__ == "__main__":
    unittest.main()
