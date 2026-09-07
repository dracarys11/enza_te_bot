"""Offline tests for the bounded navigation ActionProvider."""
from __future__ import annotations

import unittest

from action_gate import issue_observation_provenance
from action_provider import ActionProviderResult, MockActionProvider
from environment_provider import ActionIntent
from perception_models import Observation


def observation(state: str, ident: str) -> Observation:
    draft = Observation(
        ident, "2026-09-03T06:00:00Z", {"width": 100, "height": 100},
        {"state": state, "confidence": 0.99}, observation_status="VERIFIED",
    )
    provenance = issue_observation_provenance(ident, state)
    return Observation(
        draft.observation_id, draft.captured_at, draft.game_window,
        draft.business_state, draft.screenshot_path, draft.elements,
        draft.numerics, draft.structures, {"provenance": provenance},
        draft.candidate_actions, draft.confidence, draft.observation_status,
    )


class ActionProviderTests(unittest.TestCase):
    def test_mock_click_succeeds_and_writes_before_after_trajectory(self) -> None:
        before = observation("HOME", "OBS_1")
        after = observation("PRODUCE_SELECTION", "OBS_2")
        provider = MockActionProvider(
            before, {"produce_open": after}, calibrated_actions=("produce_open",),
        )
        result = provider.execute(ActionIntent("produce_open"))
        self.assertEqual(result.result, ActionProviderResult.SUCCESS)
        self.assertEqual(result.before_observation.observation_id, "OBS_1")
        self.assertEqual(result.after_observation.observation_id, "OBS_2")
        self.assertTrue(result.verification["verified"])
        self.assertEqual(provider.trajectory[0]["before_obs"]["observation_id"], "OBS_1")

    def test_stale_observation_is_rejected(self) -> None:
        before = observation("HOME", "OBS_1")
        stale = observation("HOME", "OBS_OLD")
        provider = MockActionProvider(
            before, {"produce_open": observation("PRODUCE_SELECTION", "OBS_2")},
            calibrated_actions=("produce_open",),
        )
        result = provider.execute(ActionIntent("produce_open"), stale)
        self.assertEqual(result.result, ActionProviderResult.FAILED)
        self.assertEqual(result.reason, "STALE_OR_UNVERIFIED_OBSERVATION")
        self.assertEqual(provider.trajectory[0]["verification"]["verified"], False)

    def test_confirm_or_other_resource_action_is_rejected(self) -> None:
        provider = MockActionProvider(observation("HOME", "OBS_1"), {})
        result = provider.execute(ActionIntent("production_confirm"))
        self.assertEqual(result.result, ActionProviderResult.FAILED)
        self.assertEqual(result.reason, "RESOURCE_OR_UNSUPPORTED_ACTION")

    def test_verification_failure_is_recorded(self) -> None:
        provider = MockActionProvider(
            observation("HOME", "OBS_1"),
            {"produce_open": observation("UNKNOWN", "OBS_2")},
            calibrated_actions=("produce_open",),
        )
        result = provider.execute(ActionIntent("produce_open"))
        self.assertEqual(result.result, ActionProviderResult.UNKNOWN)
        self.assertFalse(result.verification["verified"])
        self.assertEqual(result.reason, "POST_ACTION_UNKNOWN")
        self.assertEqual(provider.trajectory[0]["result"], "UNKNOWN")

    def test_uncalibrated_action_is_rejected(self) -> None:
        provider = MockActionProvider(
            observation("HOME", "OBS_1"),
            {"produce_open": observation("PRODUCE_SELECTION", "OBS_2")},
        )
        result = provider.execute(ActionIntent("produce_open"))
        self.assertEqual(result.reason, "UNCALIBRATED_TARGET")


if __name__ == "__main__":
    unittest.main()
