"""Offline tests for the bounded MVP-001 runner."""
from __future__ import annotations

import unittest

from action_boundary import ActionBoundary
from action_gate import ActionGate, issue_observation_provenance
from mvp_runtime_runner import MvpObservationEnvelope, MvpRuntimeRunner
from perception_models import ActionResult, Observation, UIElement
from test_vision_observation_schema import valid_base_payload


def payload(state: str, ident: str, value: int = 0) -> dict:
    p = valid_base_payload()
    p["observation_id"] = ident
    p["capture"]["frame_id"] = f"frame-{ident}"
    p["capture"]["screenshot_digest"] = f"digest-{ident}"
    p["interaction_candidates"] = []
    p["overlay_regions"] = []
    if state == "HOME":
        p["text_regions"] = [{"id": "home", "text": "ホーム", "bbox": [40, 30, 160, 60], "confidence": 0.97},
                              {"id": "produce_label", "text": "プロデュース", "bbox": [200, 300, 140, 40], "confidence": 0.95}]
        p["interaction_candidates"] = [{"id": "produce", "bbox": [180, 290, 180, 70],
                                         "appearance": {"shape": "rect_button"}, "linked_text_ids": ["produce_label"],
                                         "interaction_confidence": 0.95}]
        p["numeric_regions"] = []
    elif state == "WING_SELECTION":
        p["text_regions"] = [{"id": "wing", "text": "W.I.N.G.", "bbox": [600, 195, 300, 60], "confidence": 0.95},
                              {"id": "training", "text": "研修設定", "bbox": [620, 340, 120, 40], "confidence": 0.93}]
        p["interaction_candidates"] = [{"id": "settings", "bbox": [900, 628, 160, 85],
                                         "appearance": {"shape": "rect_button"}, "linked_text_ids": ["training"],
                                         "interaction_confidence": 0.95}]
        p["numeric_regions"] = []
    else:
        p["text_regions"] = [{"id": "settings", "text": "研修設定", "bbox": [600, 195, 300, 60], "confidence": 0.95},
                              {"id": "vocal", "text": "ボーカル", "bbox": [300, 250, 100, 40], "confidence": 0.95}]
        p["numeric_regions"] = [{"id": "n1", "raw_text": f"{value}/20", "value": value, "max_value": 20,
                                  "bbox": [410, 338, 60, 34], "confidence": 0.95}]
        p["interaction_candidates"] = [{"id": "e1", "bbox": [380, 330, 56, 56],
                                         "appearance": {"shape": "circle_button"}, "linked_text_ids": [],
                                         "interaction_confidence": 0.95}]
    return p


def runtime(p: dict, state: str, element_id: str | None = None) -> Observation:
    element = UIElement(element_id, (0.5, 0.5, 0.6, 0.6), "button",
                        metadata={"source": "RUNTIME", "verification_level": "CALIBRATED"}) if element_id else None
    base = Observation(p["observation_id"], p["capture"]["timestamp"], p["viewport"],
                       {"state": state, "confidence": 0.99}, elements=(element,) if element else (),
                       frame_metadata={"frame_id": p["capture"]["frame_id"], "screenshot_digest": p["capture"]["screenshot_digest"]},
                       confidence=0.99, observation_status="VERIFIED")
    prov = issue_observation_provenance(base.observation_id, state)
    return Observation(base.observation_id, base.captured_at, base.game_window, base.business_state,
                       elements=base.elements, frame_metadata={**base.frame_metadata, "provenance": prov},
                       confidence=base.confidence, observation_status=base.observation_status)


class Provider:
    def __init__(self, envelopes):
        self.envelopes = list(envelopes)
        self.current = self.envelopes[0]
        self.calls = []

    def observe(self):
        return self.current

    def execute(self, permission):
        self.calls.append(permission)
        idx = next(i for i, e in enumerate(self.envelopes) if e.observation.observation_id == self.current.observation.observation_id)
        nxt = self.envelopes[min(idx + 1, len(self.envelopes) - 1)]
        self.current = nxt
        return ActionResult("action", issued=True, after_observation=nxt.observation)


class RunnerTests(unittest.TestCase):
    def make(self):
        ps = [payload("HOME", "1"), payload("WING_SELECTION", "2"), payload("TRAINING_SETTINGS", "3", 0),
              payload("TRAINING_SETTINGS", "4", 1)]
        envs = [MvpObservationEnvelope(ps[0], runtime(ps[0], "HOME", "produce")),
                MvpObservationEnvelope(ps[1], runtime(ps[1], "WING_SELECTION", "settings")),
                MvpObservationEnvelope(ps[2], runtime(ps[2], "TRAINING_SETTINGS", "e1")),
                MvpObservationEnvelope(ps[3], runtime(ps[3], "TRAINING_SETTINGS", "e1"))]
        provider = Provider(envs)
        boundary = ActionBoundary(gate=ActionGate(allowed_rooms={"MVP_WING"}), provider=provider)
        return MvpRuntimeRunner(provider, boundary, max_steps=3), provider

    def test_full_flow_and_boundary_for_every_action(self):
        runner, provider = self.make()
        result = runner.run()
        self.assertEqual(result.status, "SUCCESS")
        self.assertEqual(len(provider.calls), 3)

    def test_unknown_state_stops(self):
        p = payload("HOME", "u")
        p["text_regions"] = []
        env = MvpObservationEnvelope(p, runtime(p, "UNKNOWN", "produce"))
        provider = Provider([env])
        runner = MvpRuntimeRunner(provider, ActionBoundary(gate=ActionGate(allowed_rooms={"MVP_WING"}), provider=provider))
        self.assertEqual(runner.run().status, "UNKNOWN")
        self.assertEqual(provider.calls, [])

    def test_missing_evidence_stops(self):
        runner, provider = self.make()
        runner.provider.current = MvpObservationEnvelope(payload("HOME", "m"), runtime(payload("HOME", "m"), "HOME", "produce"))
        bad = runner.provider.current.vision_payload.copy()
        bad["observation_id"] = "m"
        bad["text_regions"] = []
        runner.provider.current = MvpObservationEnvelope(bad, runner.provider.current.observation)
        self.assertIn(runner.run().status, {"FAILED", "UNKNOWN"})
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
