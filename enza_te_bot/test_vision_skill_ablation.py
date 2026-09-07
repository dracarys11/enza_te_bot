"""Regression tests for the canonical Training Settings skill ablation."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from evaluation.run_vision_skill_ablation import (
    DEFAULT_CASE,
    IntegrityError,
    SKILLS,
    build_report,
    run,
    validate_case,
)


class VisionSkillAblationTests(unittest.TestCase):
    def test_canonical_case_passes_integrity_before_comparison(self):
        integrity, artifacts = validate_case(DEFAULT_CASE)
        self.assertEqual(integrity["status"], "PASS")
        self.assertEqual(tuple(artifacts[skill]["metadata"]["skill_version"] for skill in SKILLS), SKILLS)

    def test_report_keeps_paddle_as_proxy_and_agy_skills_as_ablation(self):
        report = build_report(DEFAULT_CASE)
        roles = report["comparison_roles"]
        self.assertEqual(roles["text_reference_proxy"], "PaddleOCR")
        self.assertFalse(roles["text_reference_is_ground_truth"])
        self.assertEqual(roles["ablation_provider"], "AGY")
        self.assertEqual(roles["ablation_variable"], "skill_version")
        self.assertFalse(roles["zcode_included"])
        self.assertEqual(set(report["variants"]), set(SKILLS))

    def test_existing_metric_settings_are_preserved(self):
        settings = build_report(DEFAULT_CASE)["settings"]
        self.assertEqual(settings["interaction_iou_threshold"], 0.5)
        self.assertEqual(settings["text_normalization"], "Unicode NFKC plus whitespace removal")

    def test_required_structural_diagnostics_are_present(self):
        report = build_report(DEFAULT_CASE)
        for skill in SKILLS:
            metrics = report["variants"][skill]
            self.assertIn("text_region_count", metrics)
            self.assertIn("text_coverage_proxy", metrics["paddle_text_proxy"])
            self.assertIn("interaction_candidate_count", metrics)
            self.assertIn("interaction_link_coverage", metrics["grounding"])
            self.assertIn("dangling_link_count", metrics["grounding"])
            self.assertIn("viewport_area_coverage", metrics["uncertainty"])
            self.assertIn("count", metrics["out_of_viewport_bbox"])
            self.assertIn("count", metrics["suspicious_unsupported_extra"])
            self.assertIn("timeout_events", metrics["timing"])

    def test_assessment_is_derived_without_promoting_a_skill(self):
        assessment = build_report(DEFAULT_CASE)["assessment"]
        self.assertEqual(assessment["v1_to_v1_1"]["classification"], "REGRESSION")
        self.assertEqual(
            assessment["v1_1_to_v2"]["classification"],
            "RECOVERY_WITH_SIGNIFICANT_EXPANSION",
        )
        self.assertEqual(
            assessment["v2_vs_v1"]["classification"],
            "NO_DEMONSTRATED_NET_GAIN_ON_THIS_CASE",
        )
        self.assertEqual(assessment["recommended_default"], {
            "selection": "NO_PROMOTION",
            "retain_baseline": "gemini_vision_v1",
            "reason": (
                "One-case evidence shows v1.1 regression and v2 expansion without "
                "demonstrated net gain; successful latency is also unrecorded and v2 "
                "required a recorded 20-minute timeout continuation."
            ),
        })

    def test_hash_mismatch_fails_before_report_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / DEFAULT_CASE.name
            root.mkdir()
            source = DEFAULT_CASE / "source_screenshot.png"
            (root / "source_screenshot.png").write_bytes(source.read_bytes())
            manifest = copy.deepcopy(json.loads((DEFAULT_CASE / "manifest.json").read_text(encoding="utf-8")))
            manifest["source"]["sha256"] = "0" * 64
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(IntegrityError, "source screenshot SHA-256 mismatch"):
                validate_case(root)

    def test_runner_writes_both_reports_without_mutating_inputs(self):
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [DEFAULT_CASE / "manifest.json", *DEFAULT_CASE.glob("providers/**/vision_output.json")]
        }
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / "vision_skill_ablation.json"
            markdown_path = Path(directory) / "vision_skill_ablation.md"
            report = run(DEFAULT_CASE, json_path, markdown_path)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), report)
            self.assertIn("Integrity gate: **PASS**", markdown_path.read_text(encoding="utf-8"))
        after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
