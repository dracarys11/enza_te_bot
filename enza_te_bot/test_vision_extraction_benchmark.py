"""Regression tests for the difference-only Vision Extraction Benchmark."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from ob002_agent_vision_eval import CANDIDATE, REFERENCE, compare_vision, run


class VisionExtractionBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
        cls.candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))

    def test_ob001_ob002_metrics_are_regression_stable(self):
        report = compare_vision(self.reference, self.candidate)
        self.assertEqual(report["text_recall"]["exact_match_count"], 21)
        self.assertEqual(report["normalized_text_match"]["match_count"], 21)
        self.assertEqual(report["interaction_candidate_overlap"]["matched_count"], 14)
        self.assertEqual(report["grounding_agreement"]["exact_agreement_count"], 14)
        self.assertEqual(
            report["interaction_candidate_overlap"]["unmatched_candidate_indices"],
            [10, 15],
        )

    def test_normalization_and_missing_text_are_reported_as_differences(self):
        reference = deepcopy(self.reference)
        candidate = deepcopy(self.candidate)
        reference["text_regions"] = [{
            "id": "r1", "text": "A B", "bbox": [0, 0, 10, 10], "confidence": 1.0,
        }, {
            "id": "r2", "text": "missing", "bbox": [20, 0, 10, 10], "confidence": 1.0,
        }]
        candidate["text_regions"] = [{
            "id": "c1", "text": "ＡＢ", "bbox": [0, 0, 10, 10], "confidence": 1.0,
        }]
        reference["interaction_candidates"] = []
        candidate["interaction_candidates"] = []
        report = compare_vision(reference, candidate)
        self.assertEqual(report["text_recall"]["exact_match_count"], 0)
        self.assertEqual(report["normalized_text_match"]["match_count"], 1)
        self.assertEqual(
            report["normalized_text_match"]["unmatched_reference"],
            [{"id": "r2", "text": "missing"}],
        )

    def test_grounding_link_differences_are_reported(self):
        reference = deepcopy(self.reference)
        candidate = deepcopy(self.candidate)
        candidate["interaction_candidates"][0]["linked_text"] = ["extra"]
        report = compare_vision(reference, candidate)
        self.assertTrue(report["grounding_agreement"]["differences"])
        difference = report["grounding_agreement"]["differences"][0]
        self.assertEqual(difference["candidate_only_normalized_text"], ["extra"])

    def test_runner_writes_valid_difference_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "vision_comparison_report.json"
            report = run(output_path=output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
        serialized = json.dumps(report).lower()
        for judgment in ("winner", "better", "correctness", "verdict"):
            self.assertNotIn(judgment, serialized)


if __name__ == "__main__":
    unittest.main()
