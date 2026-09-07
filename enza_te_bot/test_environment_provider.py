"""Offline contract tests for the EnvironmentProvider boundary."""
from __future__ import annotations

import json
import unittest

from environment_provider import ActionIntent, EnvironmentProvider, MockEnvironmentProvider
from perception_models import Observation


def observation(state: str, *, status: str = "VERIFIED") -> Observation:
    return Observation.fresh(
        game_window={"left": 0, "top": 0, "width": 100, "height": 100},
        business_state={"state": state, "confidence": 0.99},
        candidate_actions=("rest_start",), confidence=0.99, observation_status=status,
    )


class EnvironmentProviderTests(unittest.TestCase):
    def test_observation_action_verification_closed_loop(self) -> None:
        provider = MockEnvironmentProvider(
            observation("HOME"),
            transitions={"rest_start": observation("HOME")},
        )
        self.assertIsInstance(provider, EnvironmentProvider)
        before = provider.observe()
        action = ActionIntent("rest_start", coordinate=(0.5, 0.5), expected_state="HOME")
        result = provider.execute(action)
        verification = provider.verify(result)

        self.assertEqual(result.requested_action, "rest_start")
        self.assertEqual(result.executed_action, "rest_start")
        self.assertIs(result.before_observation, before)
        self.assertIsNotNone(result.after_observation)
        self.assertTrue(verification.verified)
        self.assertEqual(verification.observation.business_state["state"], "HOME")
        json.dumps(result.as_dict())

    def test_unknown_post_observation_is_not_verified(self) -> None:
        provider = MockEnvironmentProvider(
            observation("HOME"),
            transitions={"continue": observation("UNKNOWN", status="UNKNOWN")},
        )
        result = provider.execute(ActionIntent("continue"))
        verification = provider.verify(result)
        self.assertFalse(verification.verified)
        self.assertEqual(verification.failure.value, "CONFIRMED_UNKNOWN")

    def test_missing_action_is_safe_and_does_not_inject(self) -> None:
        provider = MockEnvironmentProvider(observation("HOME"))
        result = provider.execute(ActionIntent("unconfigured"))
        self.assertFalse(result.issued)
        self.assertEqual(result.failure.value, "TARGET_NOT_FOUND")
        self.assertEqual(provider.executed_intents[0].action_name, "unconfigured")
        self.assertEqual(provider.observation_history, [provider.observe()])

    def test_wrong_expected_destination_is_rejected(self) -> None:
        provider = MockEnvironmentProvider(
            observation("HOME"),
            transitions={"rest_start": observation("REST")},
        )
        result = provider.execute(ActionIntent("rest_start", expected_state="HOME"))
        verification = provider.verify(result)
        self.assertFalse(verification.verified)
        self.assertEqual(verification.failure.value, "STATE_UNEXPECTED")


if __name__ == "__main__":
    unittest.main()
