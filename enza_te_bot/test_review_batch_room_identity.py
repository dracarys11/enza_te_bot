from __future__ import annotations

import copy
import unittest

from enza_memory.migration.python_click_migration.review_batches.v0_2 import build_review_batch as batch


class RoomIdentityProjectionRegressionTests(unittest.TestCase):
    def test_HOME_FRAME_MUST_NOT_RENDER_SCHEDULE_ROOM_CONTROLS(self) -> None:
        case = copy.deepcopy(next(item for item in batch.CASES if item["review_id"] == "VRB02_012"))
        rendered = {region["region_id"] for region in case["regions"]}

        self.assertEqual(case["page"], "WING_HOME")
        self.assertEqual(case["room_identity"], "WING_HOME")
        self.assertEqual(case["overlay"], "NONE")
        self.assertNotIn("SCHEDULE:VOCAL", rendered)
        self.assertNotIn("SCHEDULE:DECIDE", rendered)
        batch.validate_room_inventory(case)

        case["recommended_action"] = "SCHEDULE:VOCAL"
        case["primary_action"] = "SCHEDULE:VOCAL"
        with self.assertRaisesRegex(ValueError, "recommended action belongs to another room"):
            batch.validate_room_inventory(case)

    def test_SCHEDULE_FRAME_MUST_NOT_RENDER_HOME_ROOM_CONTROLS(self) -> None:
        case = copy.deepcopy(next(item for item in batch.CASES if item["review_id"] == "VRB02_011"))
        case["regions"].append(batch.box("HOME:SCHEDULE", batch.HOME_SCHEDULE, "GREEN", "ACTIONABLE_CONTROL", .9))

        with self.assertRaisesRegex(ValueError, "CONTROL_REGION_REQUIRES_MATCHING_ROOM_IDENTITY"):
            batch.validate_room_inventory(case)

    def test_ROOM_TRANSITION_INVALIDATES_PREVIOUS_CONTROL_INVENTORY(self) -> None:
        schedule_inventory = batch.resolve_control_inventory("SCHEDULE")
        home_inventory = batch.resolve_control_inventory("WING_HOME")

        self.assertIn("SCHEDULE:VOCAL", schedule_inventory)
        self.assertNotIn("SCHEDULE:VOCAL", home_inventory)
        self.assertIn("HOME:SCHEDULE", home_inventory)
        self.assertNotIn("HOME:SCHEDULE", schedule_inventory)

    def test_all_review_frames_use_only_current_room_inventory(self) -> None:
        self.assertEqual(len(batch.CASES), 38)
        for case in batch.CASES:
            with self.subTest(review_id=case["review_id"]):
                batch.validate_room_inventory(case)

    def test_dialogue_priority_is_skip_then_fast_forward_then_textbox(self) -> None:
        self.assertEqual(
            batch.recommend_dialogue_action(["STORY:TEXTBOX", "DIALOGUE:FAST_FORWARD_RIGHT", "STORY:SKIP"]),
            "STORY:SKIP",
        )
        self.assertEqual(
            batch.recommend_dialogue_action(["STORY:TEXTBOX", "DIALOGUE:FAST_FORWARD_RIGHT"]),
            "DIALOGUE:FAST_FORWARD_RIGHT",
        )
        self.assertEqual(batch.recommend_dialogue_action(["STORY:TEXTBOX"]), "STORY:TEXTBOX")

    def test_choice_present_blocks_textbox_primary(self) -> None:
        self.assertEqual(
            batch.recommend_dialogue_action(["STORY:TEXTBOX"], choice_present=True),
            "HUMAN_REVIEW",
        )
        case = copy.deepcopy(next(item for item in batch.CASES if item["review_id"] == "VRB02_015"))
        case["recommended_action"] = "STORY:TEXTBOX"
        case["primary_action"] = "STORY:TEXTBOX"
        with self.assertRaisesRegex(ValueError, "CHOICE_PRESENT_BLOCKS_TEXTBOX_PRIMARY"):
            batch.validate_room_inventory(case)

    def test_VRB02_005_uses_skip_primary_and_textbox_fallback(self) -> None:
        case = next(item for item in batch.CASES if item["review_id"] == "VRB02_005")
        self.assertEqual(case["primary_action"], "STORY:SKIP")
        self.assertEqual(case["fallback_actions"], ["DIALOGUE:FAST_FORWARD_RIGHT", "STORY:TEXTBOX"])
        self.assertIn("STORY:TEXTBOX", case["visible_controls"])


if __name__ == "__main__":
    unittest.main()
