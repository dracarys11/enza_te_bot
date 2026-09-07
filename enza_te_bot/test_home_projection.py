"""Phase A regression: HOME projection is a pure fused-JSON function."""
from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
import unittest

from exploration.home_projection import (
    FIELDS,
    numeric_tokens,
    STATUS_AMBIGUOUS,
    STATUS_KNOWN,
    STATUS_MISSING,
    SOURCE_HUMAN_CLARIFICATION,
    SOURCE_VISION_FUSION,
    apply_clarification_answers,
    parse_numeric_token,
    project_home_fields,
)


REPO_ROOT = Path(__file__).resolve().parent

SEASON_ROI = [0.25, 0.02, 0.34, 0.05]
WEEKS_ROI = [0.37, 0.02, 0.43, 0.10]
FAN_GAP_ROI = [0.54, 0.02, 0.74, 0.11]
ANCHORS = {
    "season": {"roi": SEASON_ROI, "range": [1, 4]},
    "weeks_remaining": {"roi": WEEKS_ROI, "range": [0, 99]},
    "fan_gap_to_target": {"roi": FAN_GAP_ROI},
}


def text_region(region_id: str, text: str, bbox: list[int], confidence: float = 0.99) -> dict:
    return {"id": region_id, "text": text, "bbox": bbox, "confidence": confidence}


def fused_payload(text_regions: list[dict]) -> dict:
    return {
        "observation_id": "OBS_PROJECTION_FIXTURE",
        "capture": {
            "timestamp": "2026-09-05T00:00:00",
            "frame_id": "OBS_PROJECTION_FIXTURE",
            "screenshot_digest": "sha256:fixture",
        },
        "viewport": {"width": 1280, "height": 720},
        "text_regions": text_regions,
        "interaction_candidates": [],
        "numeric_regions": [],
        "overlay_regions": [],
        "uncertainties": [],
    }


class HomeProjectionTests(unittest.TestCase):
    def test_fields_match_legacy_home_observation_vocabulary(self):
        """FIELDS must reuse home_observation.FIELDS without importing the
        legacy module (which drags in pyautogui)."""
        source = (REPO_ROOT / "home_observation.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        legacy_fields = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if getattr(target, "id", "") == "FIELDS":
                        legacy_fields = ast.literal_eval(node.value)
        self.assertEqual(legacy_fields, ("season", "weeks_remaining", "fan_gap_to_target", "stamina"))
        self.assertEqual(tuple(FIELDS), tuple(legacy_fields))

    def test_parse_numeric_token(self):
        self.assertEqual(parse_numeric_token("28,300"), 28300)
        self.assertEqual(parse_numeric_token("SP:40"), 40)
        self.assertEqual(parse_numeric_token("Week 5"), 5)
        self.assertIsNone(parse_numeric_token("stamina"))

    def test_full_width_digits_and_commas_normalize(self):
        self.assertEqual(numeric_tokens("１２３，４５６"), [123456])
        self.assertEqual(numeric_tokens("１２３４５"), [12345])
        self.assertEqual(parse_numeric_token("１２３４５"), 12345)

    def test_full_width_comma_folds_to_correct_value(self):
        # NFKC folds １２３，４５６ -> 123,456 -> 123456（正确值，非误解析）
        self.assertEqual(numeric_tokens("１２３，４５６"), [123456])
        self.assertEqual(numeric_tokens("１２３,４５６"), [123456])

    def test_unfoldable_separator_yields_multi_tokens_and_fails_closed(self):
        # 象形逗号不被 NFKC 折叠：分裂为两个 token，调用方必须 AMBIGUOUS
        self.assertEqual(numeric_tokens("１２３、４５６"), [123, 456])
        self.assertIsNone(parse_numeric_token("１２３、４５６"))

    def test_multi_number_text_never_yields_a_single_value(self):
        self.assertEqual(numeric_tokens("123,456 / 200,000"), [123456, 200000])
        self.assertIsNone(parse_numeric_token("123,456 / 200,000"))

    def test_known_fields_from_fused_json(self):
        payload = fused_payload(
            [
                text_region("p_001", "3", [340, 17, 30, 20]),
                text_region("p_002", "5", [500, 20, 30, 22]),
                text_region("p_003", "12,345", [700, 22, 90, 24]),
            ]
        )
        projection = project_home_fields(payload, None, ANCHORS)
        self.assertEqual(projection["status"], "INCOMPLETE")  # stamina not text-observable
        self.assertEqual(projection["fields"]["season"]["status"], STATUS_KNOWN)
        self.assertEqual(projection["fields"]["season"]["value"], 3)
        self.assertEqual(projection["fields"]["season"]["evidence_ids"], ["p_001"])
        self.assertEqual(projection["fields"]["season"]["source"], SOURCE_VISION_FUSION)
        self.assertEqual(projection["fields"]["weeks_remaining"]["value"], 5)
        self.assertEqual(projection["fields"]["fan_gap_to_target"]["value"], 12345)
        self.assertEqual(projection["missing_fields"], ["stamina"])

    def test_missing_field_when_anchor_has_no_text(self):
        payload = fused_payload([text_region("p_001", "3", [340, 17, 30, 20])])
        projection = project_home_fields(payload, None, ANCHORS)
        self.assertEqual(projection["fields"]["weeks_remaining"]["status"], STATUS_MISSING)
        self.assertIn("weeks_remaining", projection["missing_fields"])

    def test_multi_number_text_in_roi_is_ambiguous(self):
        payload = fused_payload([
            {"id": "t1", "text": "123,456 / 200,000", "bbox": [700, 22, 140, 24], "confidence": 0.99},
        ])
        projection = project_home_fields(payload, None, ANCHORS)
        gap = projection["fields"]["fan_gap_to_target"]
        self.assertEqual(gap["status"], "AMBIGUOUS")
        self.assertIn("refusing to pick one", gap["note"])

    def test_ambiguous_field_on_conflicting_readings(self):
        payload = fused_payload(
            [
                text_region("p_001", "3", [340, 17, 30, 20]),
                text_region("p_002", "4", [360, 19, 30, 20]),
            ]
        )
        projection = project_home_fields(payload, None, ANCHORS)
        season = projection["fields"]["season"]
        self.assertEqual(season["status"], STATUS_AMBIGUOUS)
        self.assertEqual(season["candidate_values"], [3, 4])
        self.assertIsNone(season["value"])

    def test_out_of_range_reading_is_ambiguous_not_known(self):
        payload = fused_payload([text_region("p_001", "9", [340, 17, 30, 20])])
        projection = project_home_fields(payload, None, ANCHORS)
        self.assertEqual(projection["fields"]["season"]["status"], STATUS_AMBIGUOUS)
        self.assertIn("outside taught range", projection["fields"]["season"]["note"])

    def test_projection_is_a_pure_json_function(self):
        signature = inspect.signature(project_home_fields)
        for parameter in signature.parameters:
            self.assertNotIn("screenshot", parameter)
            self.assertNotIn("image", parameter)
        payload = fused_payload([text_region("p_001", "3", [340, 17, 30, 20])])
        first = project_home_fields(payload, None, ANCHORS)
        second = project_home_fields(payload, None, ANCHORS)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_clarification_answers_resolve_missing_fields_with_human_provenance(self):
        payload = fused_payload([text_region("p_001", "3", [340, 17, 30, 20])])
        projection = project_home_fields(payload, None, ANCHORS)
        resolved = apply_clarification_answers(
            projection,
            {"weeks_remaining": "5", "fan_gap_to_target": "12,345", "stamina": "adequate"},
            question_ids={"weeks_remaining": "Q_001"},
        )
        self.assertEqual(resolved["status"], "COMPLETE")
        weeks = resolved["fields"]["weeks_remaining"]
        self.assertEqual(weeks["status"], STATUS_KNOWN)
        self.assertEqual(weeks["source"], SOURCE_HUMAN_CLARIFICATION)
        self.assertEqual(weeks["confidence"], 0.5)
        self.assertIn("Q_001", weeks["evidence_ids"])
        self.assertEqual(resolved["fields"]["fan_gap_to_target"]["value"], 12345)
        self.assertEqual(resolved["fields"]["stamina"]["value"], "adequate")

    def test_clarification_rejects_non_numeric_answer_for_numeric_field(self):
        payload = fused_payload([])
        projection = project_home_fields(payload, None, ANCHORS)
        resolved = apply_clarification_answers(projection, {"season": "third"})
        self.assertEqual(resolved["fields"]["season"]["status"], STATUS_MISSING)
        self.assertIn("rejected", resolved["fields"]["season"]["note"])


if __name__ == "__main__":
    unittest.main()
