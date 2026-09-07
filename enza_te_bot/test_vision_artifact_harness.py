"""Regression tests for observation-first Vision artifact output routing."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from vision_agent.artifact_harness import (
    VisionArtifactHarness,
    VisionArtifactRoutingError,
)


CASE_ID = "OBS_ROUTING_FIXTURE"


def observation(version: str) -> dict:
    return {
        "observation_id": f"{CASE_ID}_{version}",
        "capture": {
            "timestamp": "2026-09-04T00:00:00Z",
            "frame_id": CASE_ID,
            "screenshot_digest": "sha256:fixture",
        },
        "viewport": {"width": 1280, "height": 720},
        "text_regions": [],
        "interaction_candidates": [],
        "numeric_regions": [],
        "overlay_regions": [],
        "uncertainties": [],
        "detection_failures": [],
    }


class VisionArtifactHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "test_data"
        self.case = self.root / "ob003" / CASE_ID
        self.case.mkdir(parents=True)
        (self.case / "source_screenshot.png").write_bytes(b"same screenshot")
        self.harness = VisionArtifactHarness(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_v1_v1_1_and_v2_route_below_same_observation_without_collision(self):
        expected_directories = {
            "gemini_vision_v1": "gemini_vision_v1",
            "gemini_vision_v1_1": "gemini_vision_v1_1",
            "gemini_vision_v2": "gemini_vision_v2",
        }
        paths = []
        for index, (skill_version, directory) in enumerate(expected_directories.items()):
            path = self.harness.persist(
                observation(directory),
                case_id=CASE_ID,
                provider="AGY",
                model="shared-model",
                skill_version=skill_version,
                created_at=f"2026-09-04T00:00:0{index}Z",
            )
            self.assertEqual(
                path,
                self.case / "providers" / "agy" / directory / "vision_output.json",
            )
            paths.append(path)

        self.assertEqual(len(set(paths)), 3)
        self.assertFalse((self.root / "gemini_v1_1").exists())
        manifest = json.loads((self.case / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["providers"]), 3)

    def test_persist_binds_metadata_and_manifest_to_case_screenshot(self):
        path = self.harness.persist(
            observation("v1_1"),
            case_id=CASE_ID,
            provider="AGY",
            model="gemini-test-model",
            skill_version="gemini_vision_v1_1",
            created_at="2026-09-04T00:00:00Z",
            provenance={"session_reference": "staffer-test"},
        )
        digest = hashlib.sha256(b"same screenshot").hexdigest()
        metadata = json.loads(path.read_text(encoding="utf-8"))["metadata"]
        self.assertEqual(metadata, {
            "provider": "AGY",
            "model": "gemini-test-model",
            "skill_version": "gemini_vision_v1_1",
            "case_id": CASE_ID,
            "source_image": "source_screenshot.png",
            "screenshot_sha256": digest,
            "created_at": "2026-09-04T00:00:00Z",
        })
        manifest = json.loads((self.case / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source"]["sha256"], digest)
        entry = manifest["providers"][0]
        self.assertEqual(entry["name"], "AGY")
        self.assertEqual(entry["artifact"], "providers/agy/gemini_vision_v1_1/vision_output.json")
        self.assertEqual(entry["provider"], "AGY")
        self.assertEqual(entry["model"], "gemini-test-model")
        self.assertEqual(entry["skill_version"], "gemini_vision_v1_1")
        self.assertEqual(entry["screenshot_sha256"], digest)
        self.assertEqual(entry["provenance"], {"session_reference": "staffer-test"})
        self.assertEqual(
            entry["artifact_sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
        )

    def test_exact_provider_skill_output_cannot_be_overwritten(self):
        kwargs = {
            "case_id": CASE_ID,
            "provider": "AGY",
            "model": "gemini-test-model",
            "skill_version": "gemini_vision_v1_1",
            "created_at": "2026-09-04T00:00:00Z",
        }
        self.harness.persist(observation("first"), **kwargs)
        with self.assertRaises(VisionArtifactRoutingError):
            self.harness.persist(observation("second"), **kwargs)

    def test_agy_provider_routes_each_skill_to_its_own_subdirectory(self):
        path = self.harness.persist(
            observation("agy"),
            case_id=CASE_ID,
            provider="AGY",
            model="gemini-test-model",
            skill_version="gemini_vision_v1_1",
            created_at="2026-09-04T00:00:00Z",
        )
        self.assertEqual(
            path,
            self.case / "providers" / "agy" / "gemini_vision_v1_1" / "vision_output.json",
        )
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))["metadata"]["skill_version"],
            "gemini_vision_v1_1",
        )

    def test_path_traversal_is_rejected(self):
        with self.assertRaises(VisionArtifactRoutingError):
            self.harness.output_path("../outside", "Gemini", "gemini_vision_v1")


if __name__ == "__main__":
    unittest.main()
