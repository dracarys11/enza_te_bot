"""Offline tests for the MVP runtime adapter."""
from __future__ import annotations

import unittest

from action_boundary import ActionBoundary
from action_gate import ActionGate, issue_observation_provenance
from mvp_runtime_adapter import MvpRuntimeAdapter, build_action_request
from perception_models import ActionResult, Observation, UIElement


def obs(state: str, ident: str, *, element: UIElement | None = None,
        status: str = "VERIFIED") -> Observation:
    base = Observation(ident, f"2026-09-03T00:00:{ident[-1]}Z", {"width": 100, "height": 100},
                       {"state": state, "confidence": 0.99},
                       elements=(element,) if element else (),
                       frame_metadata={"frame_id": f"frame-{ident}", "screenshot_digest": f"digest-{ident}"},
                       confidence=0.99, observation_status=status)
    provenance = issue_observation_provenance(ident, state)
    return Observation(base.observation_id, base.captured_at, base.game_window, base.business_state,
                       base.screenshot_path, base.elements, base.numerics, base.structures,
                       {**base.frame_metadata, "provenance": provenance}, base.candidate_actions,
                       base.confidence, base.observation_status)


def element(element_id: str = "produce") -> UIElement:
    return UIElement(element_id, (0.4, 0.4, 0.6, 0.6), "button",
                     metadata={"source": "RUNTIME", "verification_level": "CALIBRATED"},
                     confidence=0.99)


class Provider:
    def __init__(self, after: Observation):
        self.after = after
        self.calls = 0

    def execute(self, permission):
        self.calls += 1
        return ActionResult("PRODUCE_OPEN", issued=True,
                            before_observation=None, after_observation=self.after)


def interpretation(observation_id: str, action: str = "PRODUCE_OPEN", target: str = "produce"):
    return {"observation_id": observation_id, "permitted_actions": [{
        "action_type": action, "target_element_id": target,
        "source_observation_id": observation_id,
        "evidence_refs": [f"source_observation:{observation_id}", "calibrated target"],
        "expected_verification": {},
    }]}


class MvpRuntimeAdapterTests(unittest.TestCase):
    def make_adapter(self, before, after):
        provider = Provider(after)
        boundary = ActionBoundary(gate=ActionGate(allowed_rooms={"MVP_WING"}), provider=provider)
        return MvpRuntimeAdapter(boundary), provider

    def test_home_creates_produce_request(self):
        before = obs("HOME", "1", element=element())
        request = build_action_request(before, interpretation("1"))
        self.assertEqual(request.intent.action_name, "PRODUCE_OPEN")
        self.assertEqual(request.source_observation_id, "1")

    def test_wing_and_training_actions_are_supported(self):
        for state, action, expected in [
            ("WING_SELECTION", "OPEN_TRAINING_SETTINGS", "TRAINING_SETTINGS"),
            ("TRAINING_SETTINGS", "VOCAL_INCREMENT", "TRAINING_SETTINGS"),
        ]:
            before = obs(state, action, element=element())
            request = build_action_request(before, interpretation(action, action))
            self.assertEqual(request.intent.expected_state, expected)

    def test_valid_request_uses_boundary_and_new_observation(self):
        before = obs("HOME", "2", element=element())
        after = obs("WING_SELECTION", "3")
        adapter, provider = self.make_adapter(before, after)
        result = adapter.execute(before, interpretation("2"))
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(provider.calls, 1)
        self.assertEqual(result.after_observation.observation_id, "3")

    def test_unknown_state_never_executes(self):
        before = obs("UNKNOWN", "4", element=element(), status="UNKNOWN")
        after = obs("WING_SELECTION", "5")
        adapter, provider = self.make_adapter(before, after)
        result = adapter.execute(before, interpretation("4"))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(provider.calls, 0)

    def test_missing_evidence_never_executes(self):
        before = obs("HOME", "6", element=element())
        bad = interpretation("6")
        bad["permitted_actions"][0]["evidence_refs"] = []
        adapter, provider = self.make_adapter(before, obs("WING_SELECTION", "7"))
        result = adapter.execute(before, bad)
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(provider.calls, 0)

    def test_coordinate_only_target_rejected(self):
        before = obs("HOME", "8")
        candidate = interpretation("8")
        candidate["permitted_actions"][0]["target_element_id"] = "missing"
        adapter, provider = self.make_adapter(before, obs("WING_SELECTION", "9"))
        result = adapter.execute(before, candidate)
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(provider.calls, 0)

    def test_reused_observation_after_action_is_rejected(self):
        before = obs("HOME", "0", element=element())
        adapter, provider = self.make_adapter(before, before)
        result = adapter.execute(before, interpretation("0"))
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(provider.calls, 1)  # provider was reached; boundary rejects stale effect


if __name__ == "__main__":
    unittest.main()
