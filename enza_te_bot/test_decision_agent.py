"""Regression tests for model-agnostic grounded decision output."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from decision_agent.base import ActionCandidateError, validate_action_candidate
from decision_agent.grounded_decision import GroundedDecisionAgent
from evaluation.run_ob001_decision_test import OB001_GOAL, run


def element(*, element_id="e14", text="次へ"):
    evidence = [] if text is None else [{
        "text_region_id": "paddle_025",
        "text": text,
        "confidence": 0.99,
        "source": "paddle",
    }]
    return {
        "element_id": element_id,
        "source_observation_id": "VOBS_TEST",
        "bbox": [1092.0, 623.0, 166.0, 78.0],
        "geometry_space": "original_viewport",
        "text_evidence_status": "MATCHED" if evidence else "UNKNOWN",
        "text_evidence": evidence,
        "visual_confidence": 0.99,
        "grounding_confidence": 0.99,
        "provenance": {"visual": "gemini", "text": "paddle" if evidence else None},
    }


class GroundedDecisionAgentTests(unittest.TestCase):
    def setUp(self):
        self.agent = GroundedDecisionAgent({OB001_GOAL: "次へ"})

    def test_known_element_is_referenced(self):
        candidate = self.agent.decide([element()], OB001_GOAL)
        self.assertEqual(candidate, {
            "candidate_id": "AC_001",
            "target_element_id": "e14",
            "action_type": "CLICK",
            "evidence": [
                "text evidence: 次へ",
                "visual evidence: interaction candidate e14",
            ],
            "confidence": 0.99,
        })

    def test_visual_element_without_text_returns_unknown(self):
        candidate = self.agent.decide([element(text=None)], OB001_GOAL)
        self.assertEqual(candidate["action_type"], "UNKNOWN")
        self.assertIsNone(candidate["target_element_id"])
        self.assertTrue(candidate["evidence"][0].startswith("missing evidence:"))

    def test_multiple_grounded_targets_return_unknown(self):
        agent = GroundedDecisionAgent({"goal": ["次へ", "研修設定"]})
        elements = [element(element_id="e14", text="次へ"),
                    element(element_id="e13", text="研修設定")]
        candidate = agent.decide(elements, "goal")
        self.assertEqual(candidate["action_type"], "UNKNOWN")
        self.assertIsNone(candidate["target_element_id"])
        self.assertIn("multiple GroundedElements", candidate["evidence"][0])

    def test_invalid_element_id_is_rejected(self):
        candidate = {
            "candidate_id": "AC_001",
            "target_element_id": "e404",
            "action_type": "CLICK",
            "evidence": ["visual evidence: interaction candidate e404"],
            "confidence": 0.9,
        }
        with self.assertRaises(ActionCandidateError):
            validate_action_candidate(candidate, [element()])

    def test_execution_or_authorization_fields_are_rejected(self):
        candidate = self.agent.decide([element()], OB001_GOAL)
        candidate["coordinates"] = [1175, 662]
        with self.assertRaises(ActionCandidateError):
            validate_action_candidate(candidate, [element()])

    def test_ob001_replay_writes_candidate_only(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate.json"
            candidate = run(output_path=output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), candidate)
        self.assertEqual(candidate["target_element_id"], "e14")
        self.assertEqual(candidate["action_type"], "CLICK")
        self.assertNotIn("coordinates", candidate)
        self.assertNotIn("authorization", candidate)

    def test_every_result_has_exact_action_candidate_fields(self):
        expected_fields = {
            "candidate_id", "target_element_id", "action_type", "evidence", "confidence",
        }
        known = self.agent.decide([element()], OB001_GOAL)
        unknown = self.agent.decide([element(text=None)], OB001_GOAL)
        self.assertEqual(set(known), expected_fields)
        self.assertEqual(set(unknown), expected_fields)


if __name__ == "__main__":
    unittest.main()
