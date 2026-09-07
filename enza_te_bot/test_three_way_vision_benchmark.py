"""Regression tests for the three-way provider benchmark runner."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from evaluation.run_three_way_vision_benchmark import compare_three_way, run


def _text(identifier: str, value: str, x: int = 0) -> dict:
    return {
        "id": identifier,
        "text": value,
        "bbox": [x, 0, 10, 10],
        "confidence": 0.99,
    }


class ThreeWayVisionBenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.paddle = {
            "text_regions": [_text("p1", "次へ"), _text("p2", "メニュー", 20)],
            "latency_ms": 21.5,
        }
        self.gemini = {
            "text_regions": [_text("g1", "次へ"), _text("g2", "メニュー", 20)],
            "interaction_candidates": [{
                "id": "g_button",
                "bbox": [0, 0, 10, 10],
                "linked_text_ids": ["g1"],
            }],
        }
        self.agy = {
            "text_regions": [_text("a1", "次 へ")],
            "interaction_candidates": [{
                "id": "a_button",
                "bbox": [1, 0, 10, 10],
                "linked_text": ["次へ"],
            }, {
                "id": "a_extra",
                "bbox": [50, 50, 10, 10],
                "linked_text": [],
            }],
            "metadata": {"elapsed_ms": 42},
        }

    def test_metrics_cover_text_interactions_iou_and_grounding(self):
        report = compare_three_way(self.agy, self.gemini, self.paddle)
        metrics = report["metrics"]
        self.assertEqual(
            metrics["text_recall"]["agy_against_paddle"]["normalized_recall"],
            0.5,
        )
        self.assertEqual(metrics["interaction_recall"]["recall"], 1.0)
        self.assertAlmostEqual(metrics["iou"]["mean_matched_iou"], 0.818182)
        self.assertEqual(metrics["grounding_agreement"]["agreement_rate"], 1.0)
        self.assertEqual(
            metrics["extra_missed"]["agy_text_against_paddle"]["missed"],
            [{"id": "p2", "text": "メニュー"}],
        )
        self.assertEqual(
            metrics["extra_missed"]["agy_interactions_against_gemini"]["extra"],
            [{"index": 1, "id": "a_extra"}],
        )

    def test_latency_is_optional_and_only_uses_explicit_fields(self):
        latency = compare_three_way(self.agy, self.gemini, self.paddle)["metrics"]["latency_ms"]
        self.assertEqual(latency, {"agy": 42.0, "gemini": None, "paddle": 21.5})

    def test_runner_reads_named_inputs_and_writes_valid_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "agy": root / "agy_vision_output.json",
                "gemini": root / "gemini_output.json",
                "paddle": root / "paddle_reference.json",
            }
            for key, path in paths.items():
                path.write_text(
                    json.dumps(getattr(self, key), ensure_ascii=False),
                    encoding="utf-8",
                )
            output = root / "three_way_vision_report.json"
            report = run(paths["agy"], paths["gemini"], paths["paddle"], output)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), report)
            self.assertEqual(report["inputs"], {key: str(path) for key, path in paths.items()})

    def test_report_contains_no_provider_verdict(self):
        report = compare_three_way(self.agy, self.gemini, self.paddle)
        serialized = json.dumps(report).lower()
        for judgment in ("winner", "better", "correctness", "verdict"):
            self.assertNotIn(judgment, serialized)


if __name__ == "__main__":
    unittest.main()
