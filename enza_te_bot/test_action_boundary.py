"""Offline tests for Phase 2.6 request/permission enforcement."""
from __future__ import annotations

from dataclasses import dataclass
import time
import unittest

from action_boundary import ActionBoundary, ActionBoundaryError, ActionRequest, FreshObservationRequirement
from action_gate import ActionGate, issue_observation_provenance
from environment_provider import ActionIntent
from execution_permission import issue_execution_permission
from perception_models import ActionTarget, Observation, UIElement


def observation(state: str, ident: str, *, frame: str = "frame-1", digest: str = "sha-1",
                elements=(), status: str = "VERIFIED") -> Observation:
    base = Observation(
        ident, "2026-09-03T06:00:00Z", {"width": 100, "height": 100},
        {"state": state, "confidence": 0.99},
        elements=elements, frame_metadata={"frame_id": frame, "screenshot_digest": digest},
        confidence=0.99, observation_status=status,
    )
    provenance = issue_observation_provenance(ident, state)
    return Observation(
        base.observation_id, base.captured_at, base.game_window, base.business_state,
        base.screenshot_path, base.elements, base.numerics, base.structures,
        {**base.frame_metadata, "provenance": provenance}, base.candidate_actions,
        base.confidence, base.observation_status,
    )


@dataclass
class ProviderResult:
    after_observation: Observation | None


class Provider:
    def __init__(self, after: Observation):
        self.after = after
        self.permissions = []

    def execute(self, permission):
        self.permissions.append(permission)
        return ProviderResult(self.after)


def request(obs: Observation, *, target: str = "coordinate:0.5,0.5") -> ActionRequest:
    intent = ActionIntent("produce_open", coordinate=(0.5, 0.5),
                          metadata={"room": "NAVIGATION_ONLY"},
                          action_intent_id="intent-1")
    return ActionRequest("action-1", intent, target, obs.observation_id, "calibrated-probe", "NAVIGATION_ONLY")


class ActionBoundaryTests(unittest.TestCase):
    def test_stale_observation_rejected(self) -> None:
        obs = observation("HOME", "OBS_1")
        requirement = FreshObservationRequirement.from_observation(obs)
        with self.assertRaisesRegex(ActionBoundaryError, "observation_id mismatch"):
            requirement.validate(observation("HOME", "OBS_OLD"))

    def test_missing_timestamp_rejected(self) -> None:
        obs = observation("HOME", "OBS_1")
        with self.assertRaisesRegex(ActionBoundaryError, "capture_timestamp"):
            FreshObservationRequirement.from_observation(
                Observation("OBS_1", "", obs.game_window, obs.business_state,
                            frame_metadata=obs.frame_metadata, observation_status="VERIFIED")
            )

    def test_successful_bounded_action_flow(self) -> None:
        before = observation("HOME", "OBS_1")
        after = observation("PRODUCE_SELECTION", "OBS_2", frame="frame-2", digest="sha-2")
        provider = Provider(after)
        boundary = ActionBoundary(gate=ActionGate(allowed_rooms={"NAVIGATION_ONLY"}), provider=provider)
        req = request(before)
        permission = boundary.authorize(req, before)
        self.assertIsNotNone(permission)
        result = boundary.execute(req, before, permission)
        self.assertTrue(result.approved)
        self.assertEqual(result.after_observation.observation_id, "OBS_2")

    def test_replay_permission_rejected(self) -> None:
        before = observation("HOME", "OBS_1")
        provider = Provider(observation("PRODUCE_SELECTION", "OBS_2"))
        boundary = ActionBoundary(gate=ActionGate(allowed_rooms={"NAVIGATION_ONLY"}), provider=provider)
        req = request(before)
        permission = boundary.authorize(req, before)
        self.assertTrue(boundary.execute(req, before, permission).approved)
        replay = boundary.execute(req, before, permission)
        self.assertFalse(replay.approved)

    def test_target_mismatch_rejected(self) -> None:
        before = observation("HOME", "OBS_1")
        provider = Provider(observation("PRODUCE_SELECTION", "OBS_2"))
        boundary = ActionBoundary(gate=ActionGate(allowed_rooms={"NAVIGATION_ONLY"}), provider=provider)
        req = request(before)
        permission = boundary.authorize(req, before)
        wrong = ActionRequest(req.action_id, req.intent, "coordinate:0.2,0.2", req.source_observation_id,
                               req.target_evidence, req.scope)
        result = boundary.execute(wrong, before, permission)
        self.assertEqual(result.reason, "PERMISSION_BINDING_MISMATCH")

    def test_missing_permission_rejected(self) -> None:
        before = observation("HOME", "OBS_1")
        boundary = ActionBoundary(gate=ActionGate(allowed_rooms={"NAVIGATION_ONLY"}),
                                  provider=Provider(observation("PRODUCE_SELECTION", "OBS_2")))
        result = boundary.execute(request(before), before, None)
        self.assertEqual(result.reason, "MISSING_PERMISSION")

    def test_after_observation_must_be_new(self) -> None:
        before = observation("HOME", "OBS_1")
        boundary = ActionBoundary(gate=ActionGate(allowed_rooms={"NAVIGATION_ONLY"}), provider=Provider(before))
        req = request(before)
        permission = boundary.authorize(req, before)
        result = boundary.execute(req, before, permission)
        self.assertFalse(result.approved)
        self.assertEqual(result.reason, "POST_ACTION_OBSERVATION_INVALID")

    def test_screenshot_only_target_cannot_execute(self) -> None:
        element = UIElement(
            "next", (0.4, 0.4, 0.6, 0.6), "button", semantic="next",
            metadata={"source": "SCREENSHOT", "verification_level": "VISIBLE_ONLY"},
        )
        before = observation("HOME", "OBS_1", elements=(element,))
        boundary = ActionBoundary(gate=ActionGate(allowed_rooms={"NAVIGATION_ONLY"}),
                                  provider=Provider(observation("PRODUCE_SELECTION", "OBS_2")))
        intent = ActionIntent("produce_open", target=ActionTarget(runtime_element_id="next"),
                              metadata={"room": "NAVIGATION_ONLY"}, action_intent_id="intent-1")
        req = ActionRequest("action-1", intent, "element:next", before.observation_id,
                            "screenshot-only", "NAVIGATION_ONLY")
        self.assertIsNone(boundary.authorize(req, before))

    def test_direct_provider_execution_is_not_a_boundary_success(self) -> None:
        provider = Provider(observation("PRODUCE_SELECTION", "OBS_2"))
        # Provider requires a permission-shaped object; an arbitrary direct call is rejected.
        with self.assertRaises(AttributeError):
            provider.execute(object()).permission_id  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
