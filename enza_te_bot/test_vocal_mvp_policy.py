import unittest

from harness.policy import PolicyViolation, load_policy, validate_action, validate_state


class VocalMvpPolicyTests(unittest.TestCase):
    def test_allowed_values(self):
        policy = load_policy()
        self.assertEqual(policy["policy_id"], "VOCAL_MVP_001")
        self.assertTrue(validate_state("HOME", policy))
        self.assertTrue(validate_action("vocal_plus", policy))

    def test_unknown_and_unsupported_state_rejected(self):
        with self.assertRaises(PolicyViolation):
            validate_state("UNKNOWN")
        with self.assertRaises(PolicyViolation):
            validate_state("AUDITION")

    def test_forbidden_and_unsupported_actions_rejected(self):
        with self.assertRaises(PolicyViolation):
            validate_action("confirm")
        with self.assertRaises(PolicyViolation):
            validate_action("resource_consume")
        with self.assertRaises(PolicyViolation):
            validate_action("anything_else")


if __name__ == "__main__":
    unittest.main()
