"""Offline regressions for grounded semantic-state evidence."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from grounded_state import GroundedState, GroundedStateSchemaError, UNKNOWN_UNIDENTIFIED


def artifact(*, title_text=False, roundtrip=False) -> dict:
    return {
        "schema_version": 1, "observation_id": "OBS_1",
        "capture_provenance": {"source": "SCREENSHOT", "screenshot_reference": "shot.png"},
        "facts": ["panel visible"], "inferences": ["panel may be unit formation"], "unknowns": [],
        "state": {
            "label": "UNIT_FORMATION", "identity_source": "SCREENSHOT",
            "identity_evidence": {"title_text_read": title_text, "roundtrip_evidence": roundtrip},
        },
        "visible_elements": [],
    }


class GroundedStateTests(unittest.TestCase):
    def test_coordinate_only_panel_remains_unknown(self) -> None:
        grounded = GroundedState.from_artifact(artifact())
        self.assertEqual(grounded.label, UNKNOWN_UNIDENTIFIED)
        self.assertEqual(grounded.verification_level, "UNKNOWN")

    def test_screenshot_without_text_cannot_create_semantic_state(self) -> None:
        grounded = GroundedState.from_artifact(artifact())
        self.assertEqual(grounded.identity_source, "SCREENSHOT")
        self.assertNotEqual(grounded.verification_level, "VERIFIED")

    def test_title_text_creates_verified_candidate(self) -> None:
        grounded = GroundedState.from_artifact(artifact(title_text=True))
        self.assertEqual(grounded.label, "UNIT_FORMATION")
        self.assertEqual(grounded.verification_level, "VERIFIED")

    def test_unknown_survives_serialization(self) -> None:
        grounded = GroundedState.from_artifact(artifact())
        restored = GroundedState.from_dict(json.loads(json.dumps(grounded.as_dict())))
        self.assertEqual(restored.label, UNKNOWN_UNIDENTIFIED)
        self.assertEqual(restored.verification_level, "UNKNOWN")

    def test_verified_without_identity_evidence_is_rejected(self) -> None:
        with self.assertRaisesRegex(GroundedStateSchemaError, "requires title_text_read"):
            GroundedState("s", "UNIT_FORMATION", "OBS_1", "COORDINATE", verification_level="VERIFIED")

    def test_facts_and_inferences_remain_separate(self) -> None:
        grounded = GroundedState.from_artifact(artifact(title_text=True))
        self.assertEqual(grounded.facts, ("panel visible",))
        self.assertEqual(grounded.inferences, ("panel may be unit formation",))


if __name__ == "__main__":
    unittest.main()
