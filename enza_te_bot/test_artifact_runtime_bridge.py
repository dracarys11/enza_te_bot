"""Offline tests for the read-only observation-artifact bridge."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from artifact_runtime_bridge import ArtifactValidationError, load_observation_artifact
from observation_artifact_schema import SCHEMA_VERSION


ROOT = Path(__file__).resolve().parent
REAL_ARTIFACT = ROOT / "ai_decisions" / "observations" / "OBS_20260903052210.json"


def versioned_artifact() -> dict:
    data = json.loads(REAL_ARTIFACT.read_text(encoding="utf-8"))
    data["schema_version"] = SCHEMA_VERSION
    data["capture_provenance"] = data.pop("provenance")
    data["capture_provenance"]["source"] = "ZCode"
    for item in data.get("visible_elements", []):
        item.setdefault("source", "SCREENSHOT")
        item.setdefault("verification_level", "VISIBLE_ONLY")
        item.setdefault("visual_evidence", item.get("name", "visual evidence"))
        item.setdefault("geometry_classification", "VISUAL_ONLY")
    return data


def write_versioned_artifact(directory: str, data: dict | None = None) -> Path:
    path = Path(directory) / "observation.json"
    path.write_text(json.dumps(data or versioned_artifact()), encoding="utf-8")
    return path


class ArtifactRuntimeBridgeTests(unittest.TestCase):
    def test_valid_artifact_loads_as_runtime_observation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observation = load_observation_artifact(write_versioned_artifact(directory))
        self.assertEqual(observation.observation_id, "OBS_20260903052210")
        self.assertEqual(observation.detected_state, "PRODUCE_SELECTION")
        self.assertEqual(observation.frame_metadata["authorization_provenance"], False)

    def test_missing_source_fails(self) -> None:
        data = versioned_artifact()
        data["capture_provenance"].pop("source", None)
        with tempfile.TemporaryDirectory() as directory:
            path = write_versioned_artifact(directory, data)
            with self.assertRaisesRegex(ArtifactValidationError, "source"):
                load_observation_artifact(path)

    def test_missing_verification_level_fails(self) -> None:
        data = versioned_artifact()
        data["visible_elements"][0].pop("verification_level", None)
        with tempfile.TemporaryDirectory() as directory:
            path = write_versioned_artifact(directory, data)
            with self.assertRaisesRegex(ArtifactValidationError, "verification_level"):
                load_observation_artifact(path)

    def test_inference_promoted_to_fact_fails(self) -> None:
        data = versioned_artifact()
        data["facts"].append(data["inferences"][0])
        with tempfile.TemporaryDirectory() as directory:
            path = write_versioned_artifact(directory, data)
            with self.assertRaisesRegex(ArtifactValidationError, "promoted to fact"):
                load_observation_artifact(path)

    def test_screenshot_promoted_to_clickable_fails(self) -> None:
        data = versioned_artifact()
        data["visible_elements"][0]["geometry_classification"] = "CLICKABLE"
        with tempfile.TemporaryDirectory() as directory:
            path = write_versioned_artifact(directory, data)
            with self.assertRaisesRegex(ArtifactValidationError, "promoted to clickable"):
                load_observation_artifact(path)

    def test_screenshot_only_elements_remain_visible_only(self) -> None:
        data = versioned_artifact()
        # This calibration artifact intentionally has no geometry; add only
        # bounded synthetic boxes so the evidence-level conversion can be
        # checked without treating screenshot claims as verified controls.
        for index, item in enumerate(data["visible_elements"]):
            item["bounds"] = f"~({10 + index},10,40,20)"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "screenshot-only.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            observation = load_observation_artifact(path)
        self.assertEqual(observation.observation_status, "VISIBLE_ONLY")
        self.assertTrue(all(item.metadata["source"] == "SCREENSHOT" for item in observation.elements))
        self.assertTrue(all(item.metadata["verification_level"] == "VISIBLE_ONLY" for item in observation.elements))
        self.assertTrue(all(item.metadata["geometry_classification"] == "VISUAL_ONLY" for item in observation.elements))

    def test_inference_is_never_promoted_to_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observation = load_observation_artifact(write_versioned_artifact(directory))
        self.assertEqual(observation.business_state["classification"], "INFERENCE")
        self.assertNotEqual(observation.observation_status, "VERIFIED")
        self.assertFalse(observation.frame_metadata["authorization_provenance"])

    def test_unknown_details_survive_conversion(self) -> None:
        data = versioned_artifact()
        data["unknowns"] = ["canvas internals"]
        data["blocking_unknowns"] = ["hitbox calibration"]
        data["uncertainty_reason"] = "screenshot-only evidence"
        with tempfile.TemporaryDirectory() as directory:
            observation = load_observation_artifact(write_versioned_artifact(directory, data))
        self.assertEqual(observation.frame_metadata["unknowns"], ["canvas internals"])
        self.assertEqual(observation.frame_metadata["blocking_unknowns"], ["hitbox calibration"])
        self.assertEqual(observation.frame_metadata["uncertainty_reason"], "screenshot-only evidence")
        self.assertEqual(observation.business_state["unknowns"], ["canvas internals"])
        self.assertEqual(observation.unknowns, ["canvas internals"])
        self.assertEqual(observation.blocking_unknowns, ["hitbox calibration"])
        self.assertEqual(observation.uncertainty_reason, "screenshot-only evidence")

    def test_inferred_state_is_not_verified_after_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            observation = load_observation_artifact(write_versioned_artifact(directory))
        self.assertEqual(observation.business_state["classification"], "INFERENCE")
        self.assertEqual(observation.observation_status, "VISIBLE_ONLY")


if __name__ == "__main__":
    unittest.main()
