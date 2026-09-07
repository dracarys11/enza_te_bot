"""Integrity regression for the Training Settings Vision artifacts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from vision_observation_schema import VisionObservation


ROOT = Path(__file__).parent
CASE_ID = "OBS_20260903065025_P2_s7_training_settings"
CASE = ROOT / "test_data" / "ob003" / CASE_ID
SOURCE_SHA256 = "900e260bccab2618ac29e3b499a046725d60c65ab87bb3c414669bc884819723"
MODEL = "gemini-3.8-flash-medium"
AGY_ARTIFACTS = {
    "gemini_vision_v1": CASE / "providers" / "agy" / "gemini_vision_v1" / "vision_output.json",
    "gemini_vision_v1_1": CASE / "providers" / "agy" / "gemini_vision_v1_1" / "vision_output.json",
    "gemini_vision_v2": CASE / "providers" / "agy" / "gemini_vision_v2" / "vision_output.json",
}
ORIGINALS = {
    "gemini_vision_v1": ROOT / "test_data" / "gemini_v1" / CASE_ID / "vision_output.json",
    "gemini_vision_v1_1": ROOT / "test_data" / "gemini_v1_1" / CASE_ID / "vision_outputv1.1.json",
    "gemini_vision_v2": (
        CASE / "legacy_artifacts" / "provider_routing_pre_integrity"
        / "gemini_v2_vision_output.json"
    ),
}
VISUAL_FIELDS = (
    "viewport",
    "text_regions",
    "interaction_candidates",
    "numeric_regions",
    "overlay_regions",
    "uncertainties",
    "detection_failures",
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TrainingSettingsVisionIntegrityTests(unittest.TestCase):
    def test_three_agy_skill_artifacts_coexist_without_collision(self):
        self.assertEqual(len(set(AGY_ARTIFACTS.values())), 3)
        for skill_version, path in AGY_ARTIFACTS.items():
            with self.subTest(skill=skill_version):
                self.assertTrue(path.is_file())
                self.assertEqual(path.name, "vision_output.json")
                self.assertEqual(path.parent.name, skill_version)

    def test_provider_model_skill_and_source_binding_are_consistent(self):
        for skill_version, path in AGY_ARTIFACTS.items():
            with self.subTest(skill=skill_version):
                metadata = load(path)["metadata"]
                self.assertEqual(metadata["provider"], "AGY")
                self.assertEqual(metadata["model"], MODEL)
                self.assertEqual(metadata["skill_version"], skill_version)
                self.assertEqual(metadata["case_id"], CASE_ID)
                self.assertEqual(metadata["source_image"], "source_screenshot.png")
                self.assertEqual(metadata["screenshot_sha256"], SOURCE_SHA256)

    def test_agy_artifacts_are_contract_valid(self):
        for skill_version, path in AGY_ARTIFACTS.items():
            with self.subTest(skill=skill_version):
                self.assertEqual(VisionObservation.validate(load(path)), [])

    def test_v1_and_v2_migration_changes_metadata_only(self):
        for skill_version in ("gemini_vision_v1", "gemini_vision_v2"):
            with self.subTest(skill=skill_version):
                original = load(ORIGINALS[skill_version])
                canonical = load(AGY_ARTIFACTS[skill_version])
                original.pop("metadata", None)
                canonical.pop("metadata", None)
                self.assertEqual(canonical, original)

    def test_v1_1_normalization_preserves_all_visual_extraction_fields(self):
        original = load(ORIGINALS["gemini_vision_v1_1"])
        canonical = load(AGY_ARTIFACTS["gemini_vision_v1_1"])
        for field in VISUAL_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(canonical.get(field), original.get(field))
        self.assertEqual(canonical["observation_id"], CASE_ID)
        self.assertEqual(canonical["capture"]["timestamp"], "UNKNOWN")
        self.assertEqual(canonical["capture"]["frame_id"], "UNKNOWN")
        self.assertEqual(
            canonical["capture"]["screenshot_digest"], f"sha256:{SOURCE_SHA256}"
        )
        self.assertEqual(canonical["metadata"]["normalization"], {
            "type": "contract_only",
            "extraction_payload_modified": False,
            "original_artifact": (
                "test_data/gemini_v1_1/"
                f"{CASE_ID}/vision_outputv1.1.json"
            ),
        })

    def test_manifest_matches_filesystem_hashes_and_provenance(self):
        manifest = load(CASE / "manifest.json")
        source_digest = hashlib.sha256((CASE / "source_screenshot.png").read_bytes()).hexdigest()
        self.assertEqual(source_digest, SOURCE_SHA256)
        self.assertEqual(manifest["source"]["sha256"], source_digest)
        entries = manifest["providers"]
        self.assertEqual(len(entries), 4)
        self.assertEqual([entry["provider"] for entry in entries], ["Paddle", "AGY", "AGY", "AGY"])
        self.assertFalse(any(entry["provider"] in {"Gemini", "ZCode"} for entry in entries))
        self.assertFalse((CASE / "providers" / "gemini").exists())
        self.assertFalse((CASE / "providers" / "zcode").exists())

        for entry in entries:
            with self.subTest(artifact=entry["artifact"]):
                path = CASE / entry["artifact"]
                self.assertTrue(path.is_file())
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["artifact_sha256"])
                self.assertEqual(entry["screenshot_sha256"], source_digest)
                metadata = load(path)["metadata"]
                self.assertEqual(entry["provider"], metadata["provider"])
                self.assertEqual(entry["model"], metadata["model"])
                self.assertEqual(entry["skill_version"], metadata["skill_version"])
                if entry["provider"] == "AGY":
                    trajectory = ROOT / entry["provenance"]["trajectory"]
                    self.assertTrue(trajectory.is_file())
                    producer = load(trajectory)["steps"][0]["provenance"]["producer"]
                    self.assertEqual(producer, f"AGY Vision Provider ({MODEL})")


if __name__ == "__main__":
    unittest.main()
