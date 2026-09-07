"""Tests for MVP-001 ActionRequest Adapter (no execution, no permissions)."""
from __future__ import annotations

import unittest

from mvp001_action_request import ActionRequest, AdapterRejection, build_action_request
from observation_interpreter import interpret
from test_vision_observation_schema import valid_base_payload


def vision_payload(observation_id: str, *, texts, elements, numerics=(), overlays=()) -> dict:
    return {
        "observation_id": observation_id,
        "capture": {
            "timestamp": "2026-09-03T10:00:00Z",
            "frame_id": observation_id,
            "screenshot_digest": f"sha256:{observation_id}",
        },
        "viewport": {"width": 1280, "height": 720},
        "text_regions": texts,
        "interaction_candidates": elements,
        "numeric_regions": list(numerics),
        "overlay_regions": list(overlays),
        "uncertainties": [],
    }


HOME_PAYLOAD = vision_payload(
    "VOBS_HOME",
    texts=[{"id": "th", "text": "プロデュース", "bbox": [960, 610, 150, 90], "confidence": 0.95}],
    elements=[{
        "id": "eh",
        "bbox": [950, 600, 180, 110],
        "appearance": {"shape": "rounded_rect_button", "color_hint": "pink"},
        "linked_text_ids": ["th"],
        "interaction_confidence": 0.9,
    }],
)

WING_PAYLOAD = vision_payload(
    "VOBS_WING",
    texts=[
        {"id": "tw", "text": "W.I.N.G.", "bbox": [600, 195, 300, 60], "confidence": 0.95},
        {"id": "ts", "text": "研修設定", "bbox": [920, 640, 120, 60], "confidence": 0.93},
    ],
    elements=[{
        "id": "es",
        "bbox": [900, 628, 160, 85],
        "appearance": {"shape": "rect_button", "color_hint": "white"},
        "linked_text_ids": ["ts"],
        "interaction_confidence": 0.9,
    }],
)

TRAINING_PAYLOAD = vision_payload(
    "VOBS_TS",
    texts=[
        {"id": "tt", "text": "研修設定", "bbox": [560, 88, 180, 44], "confidence": 0.98},
        {"id": "tv", "text": "ボーカル", "bbox": [360, 200, 120, 32], "confidence": 0.96},
    ],
    elements=[
        {"id": "eplus", "bbox": [440, 330, 56, 56],
         "appearance": {"shape": "circle_button", "color_hint": "orange"},
         "linked_text_ids": [], "interaction_confidence": 0.88},
        {"id": "eminus", "bbox": [330, 330, 56, 56],
         "appearance": {"shape": "circle_button", "color_hint": "grey"},
         "linked_text_ids": [], "interaction_confidence": 0.88},
    ],
    numerics=[{"id": "n1", "raw_text": "0/20", "value": 0, "max_value": 20,
               "bbox": [410, 338, 60, 34], "confidence": 0.97}],
)


class PassCases(unittest.TestCase):
    def test_pass_home_creates_produce_open(self):
        interp = interpret(HOME_PAYLOAD, roundtrip_verified_labels=("HOME",))
        request = build_action_request(interp, HOME_PAYLOAD)
        self.assertEqual(request.intent, "PRODUCE_OPEN")
        self.assertEqual(request.target_element_id, "eh")
        self.assertEqual(request.source_observation_id, "VOBS_HOME")
        self.assertTrue(request.evidence_refs)
        self.assertIn("roundtrip_verified", " ".join(request.evidence_refs))

    def test_pass_wing_creates_open_training_settings(self):
        interp = interpret(WING_PAYLOAD)
        request = build_action_request(interp, WING_PAYLOAD)
        self.assertEqual(request.intent, "OPEN_TRAINING_SETTINGS")
        self.assertEqual(request.target_element_id, "es")

    def test_pass_training_settings_creates_increase_vocal(self):
        interp = interpret(TRAINING_PAYLOAD)
        request = build_action_request(interp, TRAINING_PAYLOAD)
        self.assertEqual(request.intent, "INCREASE_VOCAL")
        self.assertEqual(request.target_element_id, "eplus")  # column-right circle
        self.assertIn("n1", " ".join(request.evidence_refs))
        self.assertIn("ASSUMED", request.uncertainty_status)


class FailGuards(unittest.TestCase):
    def test_fail_unknown_screen_creates_no_request(self):
        payload = vision_payload("VOBS_UNK", texts=[], elements=HOME_PAYLOAD["interaction_candidates"])
        interp = interpret(payload)
        with self.assertRaises(AdapterRejection):
            build_action_request(interp, payload)

    def test_fail_coordinate_only_panel_creates_no_request(self):
        # Panel/elements present with bboxes but no identifying text at all.
        payload = vision_payload(
            "VOBS_COORD",
            texts=[{"id": "t9", "text": "???", "bbox": [500, 100, 200, 50], "confidence": 0.4}],
            elements=TRAINING_PAYLOAD["interaction_candidates"],
            numerics=TRAINING_PAYLOAD["numeric_regions"],
            overlays=[{"id": "o9", "bbox": [100, 100, 500, 400],
                       "linked_text_ids": [], "blocked_element_ids": []}],
        )
        # Low-confidence text must be covered by an uncertainty entry to pass
        # the vision contract; identity itself still cannot be established.
        payload["uncertainties"] = [{"bbox": [495, 95, 210, 60], "reason": "ocr_failed"}]
        interp = interpret(payload)
        self.assertEqual(interp["semantic_candidates"], [])
        with self.assertRaises(AdapterRejection):
            build_action_request(interp, payload)

    def test_fail_screenshot_only_target_rejected(self):
        # Correct state (title-read) but no element linked to the required label.
        payload = dict(WING_PAYLOAD)
        payload = vision_payload(
            "VOBS_WING2",
            texts=[t for t in WING_PAYLOAD["text_regions"] if t["text"] == "W.I.N.G."],
            elements=[{**WING_PAYLOAD["interaction_candidates"][0], "linked_text_ids": []}],
        )
        interp = interpret(payload)
        with self.assertRaises(AdapterRejection) as ctx:
            build_action_request(interp, payload)
        self.assertIn("screenshot-only", str(ctx.exception))

    def test_fail_request_does_not_execute(self):
        # ActionRequest is inert data: no execute, no permission anywhere.
        interp = interpret(TRAINING_PAYLOAD)
        request = build_action_request(interp, TRAINING_PAYLOAD)
        self.assertFalse(hasattr(request, "execute"))
        self.assertFalse(hasattr(request, "permission"))
        import mvp001_action_request as module
        self.assertFalse(hasattr(module, "execute"))
        self.assertFalse(hasattr(module.ActionRequest, "run"))

    def test_fail_observation_id_mismatch_rejected(self):
        interp = interpret(TRAINING_PAYLOAD)
        other = dict(TRAINING_PAYLOAD)
        other["observation_id"] = "VOBS_OTHER"
        with self.assertRaises(AdapterRejection):
            build_action_request(interp, other)

    def test_fail_home_without_roundtrip_rejected(self):
        # HOME title alone is NOT sufficient for PRODUCE_OPEN per intent table.
        payload = vision_payload(
            "VOBS_HOME2",
            texts=[{"id": "th2", "text": "ホーム", "bbox": [40, 30, 160, 60], "confidence": 0.97},
                   {"id": "tp2", "text": "プロデュース", "bbox": [960, 610, 150, 90], "confidence": 0.95}],
            elements=[{"id": "eh2", "bbox": [950, 600, 180, 110],
                       "appearance": {"shape": "rounded_rect_button", "color_hint": "pink"},
                       "linked_text_ids": ["tp2"], "interaction_confidence": 0.9}],
        )
        interp = interpret(payload)  # HOME via title_text_read only
        with self.assertRaises(AdapterRejection) as ctx:
            build_action_request(interp, payload)
        self.assertIn("roundtrip_verified", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
