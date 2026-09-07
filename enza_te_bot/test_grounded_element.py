"""Regression tests for the GroundedElement layer on OB-001 fused evidence."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from grounded_element import (
    GEOMETRY_SPACE,
    TEXT_EVIDENCE_MATCHED,
    TEXT_EVIDENCE_UNKNOWN,
    GroundedElementError,
    build_grounded_elements,
    build_from_file,
    elements_with_text,
)

FUSED_OB001 = Path(__file__).parent / "test_data" / "ob001" / "fused_observation.json"


class GroundedElementOb001Regression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.elements = build_from_file(FUSED_OB001)

    def test_every_interaction_candidate_becomes_one_element(self):
        import json
        fused = json.loads(FUSED_OB001.read_text(encoding="utf-8"))
        self.assertEqual(len(self.elements), len(fused["interaction_candidates"]))

    def test_tsugi_he_is_grounded_with_text_evidence(self):
        elements = elements_with_text(self.elements, "次へ")
        self.assertEqual(len(elements), 1)
        element = elements[0]
        self.assertEqual(element["element_id"], "e14")
        self.assertEqual(element["text_evidence_status"], TEXT_EVIDENCE_MATCHED)
        self.assertEqual(element["text_evidence"][0]["text_region_id"], "paddle_025")
        self.assertEqual(element["text_evidence"][0]["text"], "次へ")
        self.assertEqual(element["text_evidence"][0]["source"], "paddle")
        self.assertEqual(element["provenance"], {"visual": "gemini", "text": "paddle"})

    def test_ken_shuu_settei_is_grounded_with_text_evidence(self):
        elements = elements_with_text(self.elements, "研修設定")
        self.assertEqual(len(elements), 1)
        element = elements[0]
        self.assertEqual(element["element_id"], "e13")
        self.assertEqual(element["text_evidence_status"], TEXT_EVIDENCE_MATCHED)
        self.assertEqual(element["text_evidence"][0]["text_region_id"], "paddle_024")
        self.assertEqual(element["provenance"]["text"], "paddle")

    def test_textless_gemini_regions_stay_unknown(self):
        unknown_ids = {
            element["element_id"]
            for element in self.elements
            if element["text_evidence_status"] == TEXT_EVIDENCE_UNKNOWN
        }
        self.assertTrue({"e01", "e04", "e11", "e12"} <= unknown_ids)
        for element in self.elements:
            if element["text_evidence_status"] == TEXT_EVIDENCE_UNKNOWN:
                self.assertEqual(element["text_evidence"], [])
                self.assertIsNone(element["provenance"]["text"])
                self.assertEqual(
                    element["grounding_confidence"], element["visual_confidence"])

    def test_geometry_and_confidence_contract(self):
        for element in self.elements:
            self.assertEqual(element["geometry_space"], GEOMETRY_SPACE)
            self.assertEqual(len(element["bbox"]), 4)
            self.assertGreater(element["bbox"][2], 0)
            self.assertGreater(element["bbox"][3], 0)
            self.assertTrue(0.0 <= element["visual_confidence"] <= 1.0)
            self.assertTrue(0.0 <= element["grounding_confidence"]
                            <= element["visual_confidence"])
            self.assertEqual(element["source_observation_id"], "VOBS_20260903052210")

    def test_grounding_confidence_is_min_of_visual_and_text(self):
        element = elements_with_text(self.elements, "次へ")[0]
        self.assertEqual(element["grounding_confidence"],
                         min(element["visual_confidence"],
                             element["text_evidence"][0]["confidence"]))


FREEZE_ARTIFACT = Path(__file__).parent / "test_data" / "ob001" / "grounded_elements.json"

FORBIDDEN_ACTION_KEYS = {"action", "intent", "strategy", "semantic_state",
                         "recommendation", "recommended_action", "next_step",
                         "button_purpose", "game_progress", "state"}


class PerceptionStackFreezeTests(unittest.TestCase):
    """Freeze-preparation regression: the v0.1 perception baseline must not drift."""

    @classmethod
    def setUpClass(cls):
        cls.artifact = json.loads(FREEZE_ARTIFACT.read_text(encoding="utf-8"))
        cls.rebuilt = build_from_file(FUSED_OB001)

    def test_freeze_artifact_matches_current_pipeline_output(self):
        self.assertEqual(self.artifact["elements"], self.rebuilt)
        self.assertEqual(self.artifact["geometry_space"], "original_viewport")
        self.assertEqual(self.artifact["schema"], "GroundedElement v0.1")

    def test_groundedelement_cannot_contain_action_fields(self):
        for element in self.rebuilt + self.artifact["elements"]:
            self.assertFalse(FORBIDDEN_ACTION_KEYS & set(element),
                             f"action-like key leaked into element {element['element_id']}")
            for evidence in element["text_evidence"]:
                self.assertFalse(FORBIDDEN_ACTION_KEYS & set(evidence))

    def test_geometry_space_is_always_explicit(self):
        for element in self.rebuilt:
            self.assertIn("geometry_space", element)
            self.assertEqual(element["geometry_space"], "original_viewport")

    def test_provenance_cannot_disappear(self):
        for element in self.rebuilt:
            self.assertIn("provenance", element)
            self.assertEqual(element["provenance"]["visual"], "gemini")
            self.assertIn(element["provenance"]["text"],
                          (None, "paddle", "gemini", "tesseract"))
            for evidence in element["text_evidence"]:
                self.assertIn("source", evidence)
                self.assertIn(evidence["source"], ("paddle", "gemini", "tesseract"))

    def test_unknown_elements_remain_unknown(self):
        unknown = [e for e in self.rebuilt
                   if e["text_evidence_status"] == TEXT_EVIDENCE_UNKNOWN]
        self.assertGreater(len(unknown), 0)
        for element in unknown:
            self.assertEqual(element["text_evidence"], [])
            self.assertIsNone(element["provenance"]["text"])

    def test_fused_observation_remains_compatible(self):
        from vision_observation_schema import VisionObservation
        fused = json.loads(FUSED_OB001.read_text(encoding="utf-8"))
        self.assertEqual(VisionObservation.validate(fused), [])
        self.assertEqual(len(self.rebuilt), len(fused["interaction_candidates"]))


class GroundedElementSchemaTests(unittest.TestCase):
    def _fused(self, **overrides):
        fused = {
            "observation_id": "VOBS_TEST",
            "text_regions": [{"id": "paddle_001", "text": "次へ",
                              "bbox": [10, 10, 50, 20], "confidence": 0.99,
                              "source": "paddle"}],
            "interaction_candidates": [{"id": "e01", "bbox": [5, 5, 60, 30],
                                        "interaction_confidence": 0.95,
                                        "linked_text_ids": ["paddle_001"],
                                        "source": "gemini"}],
        }
        fused.update(overrides)
        return fused

    def test_no_action_or_strategy_fields_allowed(self):
        fused = self._fused()
        fused["interaction_candidates"][0]["action"] = "click_next"
        with self.assertRaises(GroundedElementError):
            build_grounded_elements(fused)

        fused = self._fused()
        fused["interaction_candidates"][0]["recommendation"] = {"strategy": "skip"}
        with self.assertRaises(GroundedElementError):
            build_grounded_elements(fused)

    def test_malformed_inputs_rejected(self):
        self.assertEqual(build_grounded_elements(self._fused(interaction_candidates=[])), [])
        fused = self._fused()
        fused["interaction_candidates"][0]["bbox"] = [5, 5, 0, 30]
        with self.assertRaises(GroundedElementError):
            build_grounded_elements(fused)
        fused = self._fused()
        fused["interaction_candidates"][0]["interaction_confidence"] = 1.5
        with self.assertRaises(GroundedElementError):
            build_grounded_elements(fused)

    def test_dangling_linked_text_id_is_unknown_not_guessed(self):
        fused = self._fused()
        fused["interaction_candidates"][0]["linked_text_ids"] = ["paddle_404"]
        elements = build_grounded_elements(fused)
        self.assertEqual(elements[0]["text_evidence_status"], TEXT_EVIDENCE_UNKNOWN)
        self.assertEqual(elements[0]["text_evidence"], [])

    def test_output_carries_no_semantic_keys(self):
        forbidden = {"action", "intent", "strategy", "semantic_state",
                     "recommendation", "next_step", "button_purpose"}
        for element in build_grounded_elements(self._fused()):
            serialized = str(element)
            self.assertFalse(any(f"'{key}'" in serialized for key in forbidden))


if __name__ == "__main__":
    unittest.main()
