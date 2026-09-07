import unittest
from audition_entry import bounded_navigation, confirm_destination, middle_choice_only, target_reward

class AuditionEntryTest(unittest.TestCase):
    def test_targets_and_bounded_navigation(self):
        self.assertEqual(target_reward({"season3": {}}), 40000)
        self.assertEqual(bounded_navigation(40000, 40000, 0), "TARGET_VERIFIED")
        self.assertEqual(bounded_navigation(3000, 40000, 8), "TARGET_NOT_FOUND")
    def test_confirm_and_middle_only(self):
        self.assertTrue(confirm_destination("PRE_AUDITION_CHOICE"))
        self.assertTrue(confirm_destination("AUDITION_CHOICE", expected="AUDITION_CHOICE"))
        self.assertFalse(confirm_destination("AUDITION_BATTLE"))
        self.assertTrue(middle_choice_only("middle"))
        self.assertFalse(middle_choice_only("left"))

if __name__ == "__main__": unittest.main()
