"""Regression coverage for the OB002 Decision Benchmark Suite."""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from evaluation.run_ob002_benchmark import DEFAULT_CASES, run_benchmark


FORBIDDEN_OUTPUT_FIELDS = {
    "coordinates", "hidden_state", "strategy", "executor_command",
}


class Ob002DecisionBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_benchmark()
        cls.results = {
            result["case_name"]: result for result in cls.report["cases"]
        }

    def test_all_four_required_cases_exist_and_pass(self):
        self.assertEqual(set(self.results), {
            "grounded click candidate",
            "insufficient evidence",
            "ambiguous decision",
            "invalid grounding",
        })
        self.assertEqual(self.report["summary"], {"passed": 4, "failed": 0})

    def test_grounded_click_references_e14(self):
        actual = self.results["grounded click candidate"]["actual"]
        self.assertEqual(actual["target_element_id"], "e14")
        self.assertEqual(actual["action_type"], "CLICK")

    def test_insufficient_and_ambiguous_cases_are_unknown_with_missing_evidence(self):
        for name in ("insufficient evidence", "ambiguous decision"):
            actual = self.results[name]["actual"]
            self.assertEqual(actual["action_type"], "UNKNOWN")
            self.assertIsNone(actual["target_element_id"])
            self.assertTrue(actual["evidence"][0].startswith("missing evidence:"))

    def test_invalid_grounding_is_rejected(self):
        actual = self.results["invalid grounding"]["actual"]
        self.assertEqual(actual["outcome"], "REJECTED")
        self.assertIn("does not reference an existing GroundedElement", actual["reason"])

    def test_decision_outputs_keep_exact_schema_and_no_execution_fields(self):
        expected_fields = {
            "candidate_id", "target_element_id", "action_type", "evidence", "confidence",
        }
        for result in self.report["cases"]:
            if "action_type" not in result["actual"]:
                continue
            self.assertEqual(set(result["actual"]), expected_fields)
            self.assertFalse(FORBIDDEN_OUTPUT_FIELDS & set(result["actual"]))

    def test_case_files_are_valid_json(self):
        case_files = sorted(DEFAULT_CASES.glob("*.json"))
        self.assertEqual(len(case_files), 4)
        for path in case_files:
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main()
