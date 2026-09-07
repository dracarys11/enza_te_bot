"""Offline consistency regressions for visual-review v0.3 annotations."""
import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = (Path(__file__).parent / "enza_memory" / "migration" /
               "python_click_migration" / "review_batches" / "v0_3" /
               "build_review_batch.py")
SPEC = importlib.util.spec_from_file_location("visual_review_v03", MODULE_PATH)
visual_review = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(visual_review)
CASES = {case["review_id"]: case for case in visual_review.CASES}
CHOICE_IDS = ("VRB02_018", "VRB02_019", "VRB02_020", "VRB02_021")


class ChoiceTextboxAuthorityTests(unittest.TestCase):
    def test_visible_textbox_is_recorded_but_not_actionable(self) -> None:
        for review_id in CHOICE_IDS:
            case = CASES[review_id]
            textbox = next(region for region in case["regions"]
                           if region["region_id"] == "STORY:TEXTBOX")
            self.assertTrue(textbox["visible"], review_id)
            self.assertFalse(textbox["actionable"], review_id)
            self.assertEqual(textbox["textbox_authority"],
                             "SUPPRESSED_BY_CHOICE_OWNER", review_id)
            self.assertEqual(textbox["interaction_owner"], "CHOICE", review_id)

    def test_no_false_geometric_overlap_hazard_labels(self) -> None:
        labels = [region for case in visual_review.CASES for region in case["regions"]
                  if "OVERLAP_HAZARD" in region["type"]]
        self.assertEqual(labels, [])

    def test_three_choice_visible_control_inventory_is_consistent(self) -> None:
        inventories = [CASES[review_id]["visible_controls"] for review_id in CHOICE_IDS]
        self.assertTrue(all(inventory == inventories[0] for inventory in inventories[1:]))
        self.assertEqual(inventories[0], [
            "CHOICE:OPTION_LEFT", "CHOICE:OPTION_MIDDLE",
            "CHOICE:OPTION_RIGHT", "STORY:TEXTBOX",
        ])

    def test_020_021_keep_choice_as_primary_authority(self) -> None:
        for review_id in ("VRB02_020", "VRB02_021"):
            case = CASES[review_id]
            self.assertEqual(case["overlay"], "CHOICE")
            self.assertEqual(visual_review.interaction_owner(case), "CHOICE_OVERLAY")
            self.assertNotEqual(case["recommended_action"], "STORY:TEXTBOX")


class MinorMetadataTests(unittest.TestCase):
    def test_024_recommendation_matches_rendered_textbox(self) -> None:
        case = CASES["VRB02_024"]
        self.assertEqual(case["recommended_action"], "RESULT:TEXTBOX")
        self.assertIn("RESULT:TEXTBOX", {region["region_id"] for region in case["regions"]})

    def test_030_is_dialogue_overlay(self) -> None:
        self.assertEqual(CASES["VRB02_030"]["overlay"], "DIALOGUE")

    def test_033_records_fast_forward_without_result_ok(self) -> None:
        case = CASES["VRB02_033"]
        region_ids = {region["region_id"] for region in case["regions"]}
        self.assertIn("DIALOGUE:FAST_FORWARD", region_ids)
        self.assertNotIn("RESULT:OK", region_ids)


if __name__ == "__main__":
    unittest.main()
