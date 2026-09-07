"""HOME identity gate regressions: JSON-only verdicts with evidence."""
from __future__ import annotations

import inspect
from pathlib import Path
import unittest

REPO_ROOT = Path(__file__).resolve().parent

from exploration.home_identity import (
    HOME_AMBIGUOUS,
    HOME_CONFIRMED,
    NOT_HOME,
    evaluate_home_identity,
)


SEASON_ROI = [0.25, 0.02, 0.34, 0.05]
WEEKS_ROI = [0.37, 0.02, 0.43, 0.10]
FAN_GAP_ROI = [0.54, 0.02, 0.74, 0.11]


def spec(positives=None, negatives=None) -> dict:
    return {
        "contract": "home_identity_spec@1",
        "min_anchor_confidence": 0.6,
        "positive_anchors": positives if positives is not None else [
            {"anchor_id": "home.field.season", "kind": "field_value", "field": "season",
             "roi": SEASON_ROI, "range": [1, 4], "required": True},
            {"anchor_id": "home.field.weeks_remaining", "kind": "field_value",
             "field": "weeks_remaining", "roi": WEEKS_ROI, "required": True},
            {"anchor_id": "home.field.fan_gap_to_target", "kind": "field_value",
             "field": "fan_gap_to_target", "roi": FAN_GAP_ROI, "required": True},
        ],
        "negative_anchors": negatives or [],
    }


def observation(texts=None, overlays=None, sensor=None) -> dict:
    return {
        "observation_id": "OBS_ID_FIXTURE",
        "capture": {"timestamp": "t", "frame_id": "f", "screenshot_digest": "sha256:x"},
        "viewport": {"width": 1280, "height": 720},
        "text_regions": texts if texts is not None else [
            {"id": "t1", "text": "3", "bbox": [340, 17, 30, 20], "confidence": 0.99},
            {"id": "t2", "text": "5", "bbox": [500, 20, 30, 22], "confidence": 0.99},
            {"id": "t3", "text": "12,345", "bbox": [700, 22, 90, 24], "confidence": 0.99},
        ],
        "interaction_candidates": [],
        "numeric_regions": [],
        "overlay_regions": overlays or [],
        "uncertainties": [],
        "sensor_status": sensor or {"text_sensor": "paddle", "paddle_ocr_empty": False},
    }


class HomeIdentityTests(unittest.TestCase):
    def test_confirmed_with_complete_required_anchors(self):
        verdict = evaluate_home_identity(observation(), [], spec())
        self.assertEqual(verdict["verdict"], HOME_CONFIRMED)
        positive = {p["anchor_id"] for p in verdict["positive_evidence"] if p["matched"]}
        self.assertIn("home.field.season", positive)
        self.assertEqual(verdict["observation_id"], "OBS_ID_FIXTURE")

    def test_partial_positive_evidence_is_ambiguous(self):
        texts = [  # weeks / fan_gap 无读数
            {"id": "t1", "text": "3", "bbox": [340, 17, 30, 20], "confidence": 0.99},
        ]
        verdict = evaluate_home_identity(observation(texts=texts), [], spec())
        self.assertEqual(verdict["verdict"], HOME_AMBIGUOUS)
        self.assertIn("partial_home_evidence", verdict["reasons"])

    def test_no_positive_evidence_is_ambiguous_not_not_home(self):
        verdict = evaluate_home_identity(observation(texts=[]), [], spec())
        self.assertEqual(verdict["verdict"], HOME_AMBIGUOUS)
        self.assertIn("no_positive_evidence", verdict["reasons"])
        self.assertNotEqual(verdict["verdict"], NOT_HOME)

    def test_affirmative_negative_evidence_is_not_home_even_with_fields(self):
        negatives = [{
            "anchor_id": "away.board_title", "kind": "text",
            "match": {"exact": "振り返り"}, "required": True,
        }]
        texts = observation()["text_regions"] + [
            {"id": "t9", "text": "振り返り", "bbox": [60, 30, 100, 36], "confidence": 0.99},
        ]
        verdict = evaluate_home_identity(observation(texts=texts), [], spec(negatives=negatives))
        self.assertEqual(verdict["verdict"], NOT_HOME)
        self.assertIn("contradicting_evidence", verdict["reasons"])

    def test_unknown_spec_kind_fails_closed(self):
        bad = spec(positives=[
            {"anchor_id": "x", "kind": "semantic_magic", "required": True},
        ])
        verdict = evaluate_home_identity(observation(), [], bad)
        self.assertEqual(verdict["verdict"], HOME_AMBIGUOUS)
        self.assertTrue(any(r.startswith("unknown_anchor_kind") for r in verdict["reasons"]))

    def test_sensor_blind_is_ambiguous_and_blocks_confirmation(self):
        sensor = {"text_sensor": "none", "paddle_ocr_empty": True}
        verdict = evaluate_home_identity(observation(sensor=sensor), [], spec())
        self.assertEqual(verdict["verdict"], HOME_AMBIGUOUS)
        self.assertIn("sensor_blind", verdict["reasons"])

    def test_overlay_contamination_blocks_confirmation(self):
        overlays = [{
            "id": "o1", "bbox": [300, 0, 500, 80],
            "linked_text_ids": [], "blocked_element_ids": [],
        }]
        verdict = evaluate_home_identity(observation(overlays=overlays), [], spec())
        self.assertEqual(verdict["verdict"], HOME_AMBIGUOUS)
        self.assertTrue(any(r.startswith("overlay_contaminated_required") for r in verdict["reasons"]))
        interference = verdict["overlay_interference"]
        self.assertTrue(any(entry["overlay_ids"] == ["o1"] for entry in interference))

    def test_low_confidence_text_negative_does_not_fire(self):
        negatives = [{
            "anchor_id": "away.board_title", "kind": "text",
            "match": {"exact": "振り返り"}, "required": True,
        }]
        texts = observation()["text_regions"] + [
            {"id": "t9", "text": "振り返り", "bbox": [60, 30, 100, 36], "confidence": 0.30},
        ]
        verdict = evaluate_home_identity(observation(texts=texts), [], spec(negatives=negatives))
        self.assertEqual(verdict["verdict"], HOME_CONFIRMED)  # 低置信反证不触发

    def test_visual_anchors_via_field_projection_confirm(self):
        visual = {
            "fields": {
                "season": {"status": "KNOWN", "value": 3, "evidence_ids": ["t1"],
                           "confidence": 0.99, "source": "vision_fusion"},
                "weeks_remaining": {"status": "KNOWN", "value": 5, "evidence_ids": ["t2"],
                                    "confidence": 0.99, "source": "vision_fusion"},
                "fan_gap_to_target": {"status": "KNOWN", "value": 12345, "evidence_ids": ["t3"],
                                      "confidence": 0.99, "source": "vision_fusion"},
            }
        }
        verdict = evaluate_home_identity(observation(), [], spec(), visual)
        self.assertEqual(verdict["verdict"], HOME_CONFIRMED)

    def test_human_clarified_fields_complete_business_but_identity_stays_ambiguous(self):
        # 三个 required anchor 全部来自 human_clarification：业务投影可以
        # COMPLETE，但身份证据非视觉 => identity_evidence_not_visual。
        human = {
            "fields": {
                "season": {"status": "KNOWN", "value": 3, "evidence_ids": ["Q1"],
                           "confidence": 0.5, "source": "human_clarification"},
                "weeks_remaining": {"status": "KNOWN", "value": 5, "evidence_ids": ["Q2"],
                                    "confidence": 0.5, "source": "human_clarification"},
                "fan_gap_to_target": {"status": "KNOWN", "value": 12345, "evidence_ids": ["Q3"],
                                      "confidence": 0.5, "source": "human_clarification"},
            },
            "status": "COMPLETE",
            "missing_fields": [],
            "ambiguous_fields": [],
        }
        verdict = evaluate_home_identity(observation(), [], spec(), human)
        self.assertEqual(verdict["verdict"], HOME_AMBIGUOUS)
        self.assertTrue(any(r.startswith("identity_evidence_not_visual")
                            for r in verdict["reasons"]))
        # 业务字段仍是 COMPLETE（投影完整性独立于身份门）
        self.assertEqual(human["status"], "COMPLETE")

    def test_all_fields_human_supplied_never_confirm(self):
        human = {
            "fields": {name: {"status": "KNOWN", "value": 1, "evidence_ids": ["Q"],
                              "confidence": 0.5, "source": "human_clarification"}
                       for name in ("season", "weeks_remaining", "fan_gap_to_target",
                                    "stamina")},
            "status": "COMPLETE", "missing_fields": [], "ambiguous_fields": [],
        }
        verdict = evaluate_home_identity(observation(), [], spec(), human)
        self.assertNotEqual(verdict["verdict"], HOME_CONFIRMED)
        self.assertEqual(verdict["verdict"], HOME_AMBIGUOUS)

    def test_visual_identity_with_human_stamina_keeps_provenance_split(self):
        # season/weeks/fan 来自视觉（可 CONFIRM）；stamina 不在身份 spec 内，
        # 其 human provenance (conf 0.5) 保持原样。
        projection = {
            "fields": {
                "season": {"status": "KNOWN", "value": 3, "evidence_ids": ["t1"],
                           "confidence": 0.99, "source": "vision_fusion"},
                "weeks_remaining": {"status": "KNOWN", "value": 5, "evidence_ids": ["t2"],
                                    "confidence": 0.99, "source": "vision_fusion"},
                "fan_gap_to_target": {"status": "KNOWN", "value": 12345, "evidence_ids": ["t3"],
                                      "confidence": 0.99, "source": "vision_fusion"},
                "stamina": {"status": "KNOWN", "value": "adequate", "evidence_ids": ["Q1"],
                            "confidence": 0.5, "source": "human_clarification"},
            }
        }
        verdict = evaluate_home_identity(observation(), [], spec(), projection)
        self.assertEqual(verdict["verdict"], HOME_CONFIRMED)
        # stamina 不进入身份证据（不在 spec 内）
        stamina_anchors = [p for p in verdict["positive_evidence"]
                           if "stamina" in p["anchor_id"]]
        self.assertEqual(stamina_anchors, [])
        self.assertEqual(projection["fields"]["stamina"]["source"], "human_clarification")
        self.assertEqual(projection["fields"]["stamina"]["confidence"], 0.5)

    def test_evaluation_is_a_pure_json_function(self):
        parameters = inspect.signature(evaluate_home_identity).parameters
        for parameter in parameters:
            self.assertNotIn("screenshot", parameter)
            self.assertNotIn("image", parameter)


class StartupPreflightTests(unittest.TestCase):
    def test_preflight_reports_missing_agy_binary(self):
        from exploration.preflight import run_preflight

        report = run_preflight(
            executable="definitely-not-a-real-binary-xyz",
            config_path=REPO_ROOT / "config.json",
            memory_root=REPO_ROOT / "enza_memory",
            cdp_url=None,
            include_paddle=False,
            include_cdp=False,
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("agy_executable", report["failed_checks"])

    def test_preflight_passes_offline_subset_on_healthy_repo(self):
        from exploration.preflight import run_preflight

        report = run_preflight(
            config_path=REPO_ROOT / "config.json",
            memory_root=REPO_ROOT / "enza_memory",
            cdp_url=None,
            include_paddle=False,
            include_cdp=False,
        )
        self.assertEqual(report["status"], "PASS")
        checks = {item["check"]: item["status"] for item in report["checks"]}
        self.assertEqual(checks["write_boundary_protection"], "ok")
        self.assertEqual(checks["staging_allowlist"], "ok")
        self.assertEqual(checks["unexpected_write_detection"], "ok")


if __name__ == "__main__":
    unittest.main()
