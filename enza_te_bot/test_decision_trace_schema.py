"""Offline tests for the non-authorizing DecisionTrace schema."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from decision_trace_schema import (
    NO_ACTION, DecisionTraceSchemaError, load_decision_trace,
    validate_decision_trace,
)


def valid_trace() -> dict:
    return {
        "decision_id": "DT_001",
        "observation_id": "OBS_001",
        "exploration_objective": "map the next bounded state",
        "candidate_actions": ["next", "stop"],
        "selected_action": "next",
        "evidence_supporting_selection": ["OBS_001", "screenshots/OBS_001.png"],
        "risk_level": "LOW",
        "expected_transition": "STATE_A -> STATE_B",
        "unknowns_at_decision": ["exact destination remains unverified"],
        "verification_criteria": ["fresh screenshot", "STATE_B visible"],
        "action_reference": "ACT_001",
        "transition_reference": "TRANSITION_001",
        "not_chain_of_thought": True,
        "executable": False,
        "facts": ["button is visible"],
        "inferences": ["button likely advances"],
        "unknowns": ["button effect before observation"],
    }


def valid_no_action_trace() -> dict:
    return {
        "decision_id": "DT_PASSIVE_001",
        "decision_type": "NO_ACTION",
        "observation_id": "OBS_001",
        "exploration_objective": "inspect a protected boundary",
        "candidate_actions": ["confirm", "cancel", "observe"],
        "selected_action": None,
        "evidence_supporting_selection": ["OBS_001", "screenshots/OBS_001.png"],
        "rejected_actions": ["confirm", "cancel"],
        "rejection_reasons": {
            "confirm": "resource effect is irreversible",
            "cancel": "destination is not yet verified",
        },
        "risk_assessment": "interaction exceeds the authorized exploration scope",
        "unknowns": ["confirm resource effect", "cancel destination"],
        "authorization_gap": "no approval for resource-affecting or unverified actions",
        "verification_status": "PASSIVE_OBSERVATION_VERIFIED",
        "not_chain_of_thought": True,
        "executable": False,
    }


class DecisionTraceSchemaTests(unittest.TestCase):
    def test_passive_no_action_decision_loads_and_preserves_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DT_PASSIVE_001.json"
            path.write_text(json.dumps(valid_no_action_trace()), encoding="utf-8")
            trace = load_decision_trace(path, observation_ids={"OBS_001"})

        self.assertEqual(trace.decision_type, NO_ACTION)
        self.assertIsNone(trace.selected_action)
        self.assertEqual(trace.rejected_actions, ("confirm", "cancel"))
        self.assertEqual(dict(trace.rejection_reasons), {
            "confirm": "resource effect is irreversible",
            "cancel": "destination is not yet verified",
        })
        self.assertEqual(trace.unknowns,
                         ("confirm resource effect", "cancel destination"))

    def test_no_action_missing_rejection_reason_is_rejected(self) -> None:
        data = valid_no_action_trace()
        del data["rejection_reasons"]["cancel"]
        with self.assertRaisesRegex(DecisionTraceSchemaError, "missing rejection reason"):
            validate_decision_trace(data, observation_ids={"OBS_001"})

    def test_no_action_cannot_generate_permission(self) -> None:
        trace = validate_decision_trace(
            valid_no_action_trace(), observation_ids={"OBS_001"})
        self.assertFalse(hasattr(trace, "to_action_intent"))
        self.assertFalse(hasattr(trace, "permission"))

        data = valid_no_action_trace()
        data["permission"] = {"permission_id": "forged"}
        with self.assertRaisesRegex(DecisionTraceSchemaError, "cannot authorize"):
            validate_decision_trace(data, observation_ids={"OBS_001"})

    def test_no_action_unknown_cannot_be_silently_resolved(self) -> None:
        data = valid_no_action_trace()
        data["resolved_unknowns"] = ["cancel destination"]
        with self.assertRaisesRegex(DecisionTraceSchemaError, "cannot be silently resolved"):
            validate_decision_trace(data, observation_ids={"OBS_001"})

    def test_valid_dt_loads_and_preserves_verification_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "DT_001.json"
            path.write_text(json.dumps(valid_trace()), encoding="utf-8")
            trace = load_decision_trace(path, observation_ids={"OBS_001"})

        self.assertEqual(trace.decision_id, "DT_001")
        self.assertEqual(trace.observation_id, "OBS_001")
        self.assertEqual(trace.verification_criteria,
                         ("fresh screenshot", "STATE_B visible"))
        self.assertFalse(trace.executable)

    def test_existing_legacy_dt_field_names_are_normalized(self) -> None:
        path = Path(__file__).parent / "enza_memory" / "decision_traces" / "DT_20260903060510_001.json"
        trace = load_decision_trace(path, observation_ids={"OBS_20260903060500"})
        self.assertEqual(trace.decision_id, "DT_20260903060510_001")
        self.assertIsInstance(trace.action_reference, dict)
        self.assertIsInstance(trace.transition_reference, dict)

    def test_dt_without_observation_is_rejected(self) -> None:
        data = valid_trace()
        del data["observation_id"]
        with self.assertRaisesRegex(DecisionTraceSchemaError, "observation_id is required"):
            validate_decision_trace(data, observation_ids={"OBS_001"})

    def test_dt_with_unknown_observation_reference_is_rejected(self) -> None:
        with self.assertRaisesRegex(DecisionTraceSchemaError, "does not exist"):
            validate_decision_trace(valid_trace(), observation_ids={"OBS_OTHER"})

    def test_dt_without_evidence_is_rejected(self) -> None:
        data = valid_trace()
        data["evidence_supporting_selection"] = []
        with self.assertRaisesRegex(DecisionTraceSchemaError, "cannot be empty"):
            validate_decision_trace(data, observation_ids={"OBS_001"})

    def test_dt_containing_chain_of_thought_is_rejected(self) -> None:
        data = valid_trace()
        data["chain_of_thought"] = "private reasoning"
        with self.assertRaisesRegex(DecisionTraceSchemaError, "chain-of-thought"):
            validate_decision_trace(data, observation_ids={"OBS_001"})

    def test_fact_inference_unknown_separation_is_preserved(self) -> None:
        data = valid_trace()
        data["facts"].append(data["inferences"][0])
        with self.assertRaisesRegex(DecisionTraceSchemaError, "cannot cross"):
            validate_decision_trace(data, observation_ids={"OBS_001"})

    def test_dt_cannot_generate_action_intent_or_permission(self) -> None:
        trace = validate_decision_trace(valid_trace(), observation_ids={"OBS_001"})
        self.assertFalse(hasattr(trace, "to_action_intent"))
        self.assertFalse(hasattr(trace, "permission"))

        data = copy.deepcopy(valid_trace())
        data["execution_permission"] = {"permission_id": "forged"}
        with self.assertRaisesRegex(DecisionTraceSchemaError, "cannot authorize"):
            validate_decision_trace(data, observation_ids={"OBS_001"})


if __name__ == "__main__":
    unittest.main()


class SplitDecisionTraceTests(unittest.TestCase):
    def test_home_decision_split_survives_schema_validation(self):
        from home_observation import HomeObservation
        from home_policy import decide_home
        for rate in (0, 4):
            decision = decide_home(HomeObservation(2, 6, 6721), {
                "vocal_failure_rate_observation": {"value": rate, "fresh": True, "status": "KNOWN"}}, {})
            data = valid_trace()
            data.update(decision.as_dict())
            trace = validate_decision_trace(data, observation_ids={"OBS_001"})
            self.assertEqual(trace.planner_objective, "VOCAL")
            self.assertEqual(trace.planner_reason, "season_2_default_vocal")
            self.assertEqual(trace.permitting_gates[0]["risk_decision"],
                             "ALLOW" if rate == 0 else "BLOCK")
            self.assertNotEqual(trace.planner_reason, trace.permitting_gates[0]["risk_reason"])
            self.assertFalse(trace.executable)

    def test_gate_cannot_replace_missing_planner_reason(self):
        data = valid_trace()
        data.update(planner_objective="VOCAL", permitting_gates=[])
        with self.assertRaisesRegex(DecisionTraceSchemaError, "planner_reason"):
            validate_decision_trace(data, observation_ids={"OBS_001"})

    def test_invalid_or_collapsed_gate_is_rejected(self):
        for gate in ({"reason": "safe"}, {"risk_gate": "VOCAL_FAILURE_RATE",
                     "risk_reason": "safe", "risk_decision": "MAYBE", "risk_observation": None}):
            data = valid_trace()
            data.update(planner_objective="VOCAL", planner_reason="route feasible",
                        permitting_gates=[gate])
            with self.assertRaises(DecisionTraceSchemaError):
                validate_decision_trace(data, observation_ids={"OBS_001"})
