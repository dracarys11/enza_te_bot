"""Regression coverage for observation-first offline artifact isolation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from ob002_agent_vision_eval import run
from vision_observation_schema import VisionObservation


ROOT = Path(__file__).parent
OB003_ROOT = ROOT / "test_data" / "ob003"
CASE_ROOT = OB003_ROOT / "OBS_ARTIFACT_ISOLATION_FIXTURE"
REQUIRED_METADATA = {
    "provider", "model", "skill_version", "case_id", "source_image",
    "screenshot_sha256", "created_at",
}
ARTIFACT_PATHS = {
    "paddle": CASE_ROOT / "providers" / "paddle" / "vision_output.json",
    "agy": CASE_ROOT / "providers" / "agy" / "vision_output.json",
    "zcode": CASE_ROOT / "providers" / "zcode" / "vision_output.json",
    "gemini_v1": CASE_ROOT / "providers" / "gemini" / "v1" / "vision_output.json",
    "gemini_v1_1": CASE_ROOT / "providers" / "gemini" / "v1_1" / "vision_output.json",
    "gemini_v2": CASE_ROOT / "providers" / "gemini" / "v2" / "vision_output.json",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class VisionProviderArtifactIsolationTests(unittest.TestCase):
    def test_observation_can_store_multiple_provider_outputs(self):
        for key, path in ARTIFACT_PATHS.items():
            with self.subTest(artifact=key):
                self.assertTrue(path.is_file())
                metadata = _load(path).get("metadata")
                self.assertIsInstance(metadata, dict)
                self.assertEqual(set(metadata), REQUIRED_METADATA)
                for field in REQUIRED_METADATA:
                    self.assertIsInstance(metadata[field], str)
                    self.assertTrue(metadata[field])

    def test_observation_manifests_bind_artifacts_to_local_source_hash(self):
        manifests = sorted(OB003_ROOT.glob("OBS_*/manifest.json"))
        self.assertGreaterEqual(len(manifests), 5)
        for manifest_path in manifests:
            with self.subTest(case=manifest_path.parent.name):
                manifest = _load(manifest_path)
                self.assertEqual(manifest["case_id"], manifest_path.parent.name)
                source_path = manifest_path.parent / manifest["source"]["file"]
                source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
                self.assertEqual(source_digest, manifest["source"]["sha256"])

                artifact_paths = []
                for entry in manifest["providers"]:
                    artifact_path = manifest_path.parent / entry["artifact"]
                    artifact_paths.append(artifact_path)
                    metadata = _load(artifact_path)["metadata"]
                    self.assertEqual(entry["name"].casefold(), metadata["provider"].casefold())
                    provider_directory = Path(entry["artifact"]).parts[1]
                    self.assertEqual(provider_directory, metadata["provider"].casefold())
                    self.assertEqual(metadata["case_id"], manifest["case_id"])
                    self.assertEqual(metadata["source_image"], "source_screenshot.png")
                    self.assertEqual(metadata["screenshot_sha256"], source_digest)
                self.assertEqual(len(artifact_paths), len(set(artifact_paths)))

    def test_same_model_can_belong_to_different_providers(self):
        agy = _load(ARTIFACT_PATHS["agy"])["metadata"]
        gemini = _load(ARTIFACT_PATHS["gemini_v2"])["metadata"]
        self.assertEqual(agy["model"], gemini["model"])
        self.assertNotEqual(agy["provider"], gemini["provider"])

    def test_skill_version_does_not_determine_provider(self):
        agy = _load(ARTIFACT_PATHS["agy"])["metadata"]
        gemini = _load(ARTIFACT_PATHS["gemini_v2"])["metadata"]
        self.assertEqual(agy["skill_version"], "gemini_vision_v2")
        self.assertEqual(gemini["skill_version"], "gemini_vision_v2")
        self.assertEqual(agy["provider"], "AGY")
        self.assertEqual(gemini["provider"], "Gemini")

    def test_agy_with_gemini_v2_skill_is_not_stored_as_gemini_provider(self):
        path = ARTIFACT_PATHS["agy"]
        self.assertEqual(path.relative_to(CASE_ROOT).parts[:2], ("providers", "agy"))
        self.assertNotIn("gemini", path.relative_to(CASE_ROOT).parts)
        self.assertEqual(_load(path)["metadata"]["skill_version"], "gemini_vision_v2")

    def test_misclassified_historical_agy_artifact_has_observation_first_copy(self):
        case = "OBS_20260903065025_P2_s7_training_settings"
        historical = ROOT / "test_data" / "gemini_v1" / case / "vision_output.json"
        canonical = (
            OB003_ROOT / case / "providers" / "agy"
            / "gemini_vision_v1" / "vision_output.json"
        )
        self.assertTrue(historical.is_file())
        self.assertTrue(canonical.is_file())
        metadata = _load(canonical)["metadata"]
        self.assertEqual(metadata["provider"], "AGY")
        self.assertEqual(metadata["model"], "gemini-3.8-flash-medium")
        self.assertEqual(metadata["skill_version"], "gemini_vision_v1")
        self.assertFalse(
            (OB003_ROOT / case / "providers" / "gemini" / "v1" / "vision_output.json").exists()
        )

    def test_zcode_with_glm_is_not_stored_as_gemini_provider(self):
        path = ARTIFACT_PATHS["zcode"]
        metadata = _load(path)["metadata"]
        self.assertEqual(path.relative_to(CASE_ROOT).parts[:2], ("providers", "zcode"))
        self.assertEqual(metadata["provider"], "ZCode")
        self.assertEqual(metadata["model"], "GLM-fixture")

    def test_paddle_artifact_does_not_pollute_vision_provider_directories(self):
        paddle = ARTIFACT_PATHS["paddle"]
        self.assertEqual(paddle.relative_to(CASE_ROOT).parts[:2], ("providers", "paddle"))
        self.assertEqual(_load(paddle)["metadata"]["provider"], "Paddle")
        for provider_dir in ("agy", "zcode", "gemini"):
            for path in (CASE_ROOT / "providers" / provider_dir).rglob("*.json"):
                self.assertNotEqual(_load(path)["metadata"]["provider"], "Paddle")

    def test_gemini_skill_outputs_coexist_under_one_observation(self):
        expected = {
            "gemini_v1": "gemini_vision_v1",
            "gemini_v1_1": "gemini_vision_v1_1",
            "gemini_v2": "gemini_vision_v2",
        }
        paths = [ARTIFACT_PATHS[key] for key in expected]
        self.assertEqual({path.name for path in paths}, {"vision_output.json"})
        self.assertEqual(len({path.parent for path in paths}), 3)
        for key, skill_version in expected.items():
            payload = _load(ARTIFACT_PATHS[key])
            self.assertEqual(payload["metadata"]["skill_version"], skill_version)
            self.assertEqual(VisionObservation.validate(payload), [])

    def test_existing_benchmark_reads_explicit_observation_artifact_paths(self):
        v1_path = ARTIFACT_PATHS["gemini_v1"]
        v2_path = ARTIFACT_PATHS["gemini_v2"]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "comparison.json"
            report = run(v1_path, v2_path, output)
            self.assertEqual(report["reference"], str(v1_path))
            self.assertEqual(report["candidate"], str(v2_path))
            self.assertEqual(_load(output), report)


if __name__ == "__main__":
    unittest.main()
