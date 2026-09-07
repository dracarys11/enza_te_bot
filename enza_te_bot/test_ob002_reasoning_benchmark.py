"""Regression tests for the OB-002 Agent Reasoning Benchmark."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from ob002_reasoning_benchmark import (
    DECISION_GROUNDED,
    DECISION_NO_TARGET,
    DECISION_UNKNOWN,
    REPORT_PATH,
    ReasoningBenchmarkError,
    run_benchmark,
    validate_result,
)

FUSED_OB001 = Path(__file__).parent / "test_data" / "ob001" / "fused_observation.json"


class Ob002ReasoningBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_benchmark(FUSED_OB001)
        cls.cases = {case["case_id"]: case for case in cls.report["cases"]}

    def test_benchmark_runs_screenshot_free_from_fused_json(self):
        self.assertEqual(self.report["source_observation_id"], "VOBS_20260903052210")
        self.assertIn("no screenshot access", self.report["input_scope"])
        self.assertEqual(len(self.cases), 5)

    def test_screen_understanding_enumerates_only_evidenced_facts(self):
        case = self.cases["C1_screen_understanding"]
        texts = {item["text"] for item in case["grounded_elements"]}
        self.assertIn("次へ", texts)
        self.assertIn("研修設定", texts)
        self.assertEqual(case["selected_element_id"], None)
        screen_identity = [u for u in case["unresolved_uncertainty"]
                           if u["kind"] == "screen_identity"]
        self.assertTrue(screen_identity, "screen identity must stay unresolved")

    def test_target_selection_returns_grounded_candidate_with_confidence(self):
        case = self.cases["C2_target_selection_proceed"]
        self.assertEqual(case["decision_status"], DECISION_GROUNDED)
        self.assertEqual(case["selected_element_id"], "e14")
        self.assertEqual(case["confidence"], 0.99)
        self.assertTrue(any("e14" in item for item in case["reasoning_evidence"]))
        self.assertEqual(case["unresolved_uncertainty"], [])

    def test_training_settings_selection(self):
        case = self.cases["C3_target_selection_training"]
        self.assertEqual(case["selected_element_id"], "e13")

    def test_textless_navigation_stays_unknown(self):
        case = self.cases["C4_uncertainty_textless_navigation"]
        self.assertEqual(case["decision_status"], DECISION_UNKNOWN)
        self.assertIsNone(case["selected_element_id"])
        self.assertEqual(case["confidence"], 0.0)
        unknown_ids = case["unresolved_uncertainty"][0]["element_ids"]
        self.assertEqual(set(unknown_ids), {"e04", "e05", "e11"})

    def test_gemini_link_fusion_dropped_is_not_recovered_by_guessing(self):
        case = self.cases["C5_uncertainty_no_text_binding"]
        self.assertEqual(case["decision_status"], DECISION_UNKNOWN)
        self.assertEqual(case["unresolved_uncertainty"][0]["element_ids"], ["e12"])

    def test_every_case_passes_output_contract(self):
        for case in self.report["cases"]:
            self.assertEqual(validate_result(case), [], case["case_id"])

    def test_report_artifact_is_frozen_and_consistent(self):
        self.assertTrue(REPORT_PATH.is_file(), "run ob002_reasoning_benchmark.main()")
        frozen = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(frozen, self.report)


class Ob002ContractTests(unittest.TestCase):
    def test_unknown_decision_with_selection_is_rejected(self):
        result = {"case_id": "x", "decision_status": DECISION_UNKNOWN,
                  "selected_element_id": "e11", "confidence": 0.0,
                  "reasoning_evidence": [], "unresolved_uncertainty": [{"kind": "k"}]}
        errors = validate_result(result)
        self.assertTrue(any("must not carry a selection" in e for e in errors))

    def test_grounded_decision_without_selection_is_rejected(self):
        result = {"case_id": "x", "decision_status": DECISION_GROUNDED,
                  "selected_element_id": None, "confidence": 0.5,
                  "reasoning_evidence": [], "unresolved_uncertainty": []}
        self.assertTrue(validate_result(result))

    def test_grounded_decision_without_uncertainty_is_rejected(self):
        result = {"case_id": "x", "decision_status": DECISION_UNKNOWN,
                  "selected_element_id": None, "confidence": 0.0,
                  "reasoning_evidence": [], "unresolved_uncertainty": []}
        errors = validate_result(result)
        self.assertTrue(any("unresolved uncertainty" in e for e in errors))

    def test_action_and_screen_name_fields_are_forbidden(self):
        result = {"case_id": "x", "decision_status": DECISION_GROUNDED,
                  "selected_element_id": "e14", "confidence": 0.9,
                  "reasoning_evidence": [],
                  "unresolved_uncertainty": [],
                  "screen_name": "produce_selection"}
        errors = validate_result(result)
        self.assertTrue(any("screen_name" in e for e in errors))

    def test_coordinate_embedding_is_forbidden(self):
        result = {"case_id": "x", "decision_status": DECISION_GROUNDED,
                  "selected_element_id": "e14", "confidence": 0.9,
                  "reasoning_evidence": [],
                  "unresolved_uncertainty": [],
                  "click_target": {"bbox": [1092, 623, 166, 78]}}
        errors = validate_result(result)
        self.assertTrue(any("coordinates" in e for e in errors))

    def test_no_target_decision_reports_no_selection(self):
        fused = json.loads(FUSED_OB001.read_text(encoding="utf-8"))
        from ob002_reasoning_benchmark import reason_target_selection
        case = reason_target_selection("t", "impossible goal", "存在しないボタン", fused)
        self.assertEqual(case["decision_status"], DECISION_NO_TARGET)
        self.assertEqual(validate_result(case), [])


if __name__ == "__main__":
    unittest.main()
