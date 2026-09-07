"""Regression tests for raw OCR and visual-grounding fusion."""
from __future__ import annotations

import json
import unittest

from perception_fusion import FusionProvenanceError, fused_artifact_digest, fuse_perception
from vision_observation_schema import VisionObservation


MODEL = "gemini-3.8-flash-medium"
SKILL = "gemini_vision_v1"


def gemini_fixture() -> dict:
    return {
        "metadata": {"provider": "Gemini"},
        "observation_id": "VOBS_FUSION_001",
        "capture": {
            "timestamp": "2026-09-03T00:00:00Z",
            "frame_id": "frame-1",
            "screenshot_digest": "sha256:fixture",
        },
        "viewport": {"width": 1280, "height": 720},
        "text_regions": [
            {"id": "t21", "text": "次へ", "bbox": [1145, 643, 73, 39], "confidence": 0.99}
        ],
        "interaction_candidates": [{
            "id": "e14",
            "bbox": [1092, 623, 166, 78],
            "appearance": {"shape": "rounded_rect", "color_hint": "pink"},
            "linked_text_ids": ["t21"],
            "interaction_confidence": 0.99,
        }],
        "numeric_regions": [],
        "overlay_regions": [],
        "uncertainties": [],
    }


class PerceptionFusionRegression(unittest.TestCase):
    def test_paddle_text_and_gemini_interaction_keep_distinct_provenance(self):
        paddle = {
            "source_image": "screen.png",
            "method": "PaddleOCR",
            "text_regions": [{
                "id": "paddle_001",
                "text": "次へ",
                "bbox": [1142, 640, 76, 42],
                "confidence": 0.99,
            }],
        }

        fused = fuse_perception(paddle, gemini_fixture(), {"text_regions": []})

        self.assertEqual(fused["text_regions"], [{
            "id": "paddle_001",
            "text": "次へ",
            "bbox": [1142, 640, 76, 42],
            "confidence": 0.99,
            "source": "paddle",
        }])
        self.assertEqual(fused["interaction_candidates"][0]["source"], "gemini")
        self.assertEqual(
            fused["interaction_candidates"][0]["linked_text_ids"],
            ["paddle_001"],
        )
        self.assertEqual(VisionObservation.validate(fused), [])

    def test_tesseract_is_used_only_when_paddle_has_no_text(self):
        tesseract = {"text_regions": [{
            "id": "ocr_001",
            "text": "次へ",
            "bbox": [1140, 640, 80, 44],
            "confidence": 0.95,
        }]}
        fused = fuse_perception({"text_regions": []}, gemini_fixture(), tesseract)
        self.assertEqual(fused["text_regions"][0]["source"], "tesseract")
        self.assertEqual(fused["interaction_candidates"][0]["source"], "gemini")

    def test_low_confidence_raw_text_is_preserved_with_uncertainty(self):
        paddle = {"text_regions": [{
            "id": "paddle_001",
            "text": "3",
            "bbox": [77, 402, 43, 53],
            "confidence": 0.543792,
        }]}
        fused = fuse_perception(paddle, gemini_fixture())
        self.assertEqual(fused["text_regions"][0]["text"], "3")
        self.assertEqual(fused["text_regions"][0]["confidence"], 0.543792)
        self.assertEqual(fused["uncertainties"], [{
            "bbox": [77, 402, 43, 53],
            "reason": "low_confidence_text_region",
            "source": "paddle",
        }])
        self.assertEqual(VisionObservation.validate(fused), [])

    def test_agy_visual_regions_preserve_provider_provenance(self):
        visual = gemini_fixture()
        visual["metadata"] = {"provider": "AGY"}
        visual["numeric_regions"] = [{
            "id": "n1", "raw_text": "10/20", "value": 10, "max_value": 20,
            "bbox": [100, 100, 40, 20], "confidence": 0.99,
        }]
        visual["overlay_regions"] = [{
            "id": "o1", "bbox": [0, 0, 100, 100],
            "blocked_element_ids": [], "linked_text_ids": [],
        }]
        visual["uncertainties"] = [{
            "bbox": [200, 200, 20, 20], "reason": "unreadable",
        }]

        fused = fuse_perception({"text_regions": []}, visual)

        for collection in (
            "interaction_candidates", "numeric_regions", "overlay_regions", "uncertainties"
        ):
            with self.subTest(collection=collection):
                self.assertTrue(fused[collection])
                self.assertTrue(all(item["source"] == "agy" for item in fused[collection]))
        self.assertNotIn("gemini", {
            item["source"]
            for collection in (
                "interaction_candidates", "numeric_regions", "overlay_regions", "uncertainties"
            )
            for item in fused[collection]
        })

    def test_missing_metadata_provider_fails_closed(self):
        visual = gemini_fixture()
        del visual["metadata"]
        with self.assertRaises(FusionProvenanceError):
            fuse_perception({"text_regions": []}, visual)

    def test_empty_metadata_provider_fails_closed(self):
        visual = gemini_fixture()
        visual["metadata"] = {"provider": "   "}
        with self.assertRaises(FusionProvenanceError):
            fuse_perception({"text_regions": []}, visual)

    def test_unknown_metadata_provider_fails_closed(self):
        visual = gemini_fixture()
        visual["metadata"] = {"provider": "ZCode"}
        with self.assertRaises(FusionProvenanceError):
            fuse_perception({"text_regions": []}, visual)

    def test_paddle_ocr_empty_is_recorded_as_sensor_provenance(self):
        visual = gemini_fixture()
        visual["metadata"] = {"provider": "AGY", "model": MODEL, "skill_version": SKILL}
        fused = fuse_perception({"text_regions": []}, visual)
        status = fused["sensor_status"]
        self.assertEqual(status["text_sensor"], "none")
        self.assertTrue(status["paddle_ocr_empty"])
        self.assertEqual(status["paddle_region_count"], 0)
        self.assertEqual(status["visual_provider"], "agy")
        self.assertEqual(VisionObservation.validate(fused), [])  # SUCCESS path 不受影响

    def test_tesseract_fallback_is_recorded_in_sensor_status(self):
        tesseract = {"text_regions": [{
            "id": "ocr_001", "text": "次へ", "bbox": [1140, 640, 80, 44], "confidence": 0.95,
        }]}
        fused = fuse_perception({"text_regions": []}, gemini_fixture(), tesseract)
        status = fused["sensor_status"]
        self.assertEqual(status["text_sensor"], "tesseract")
        self.assertTrue(status["paddle_ocr_empty"])

    def test_visual_detection_failures_survive_fusion(self):
        visual = gemini_fixture()
        visual["metadata"] = {"provider": "AGY", "model": MODEL, "skill_version": SKILL}
        visual["detection_failures"] = [{
            "id": "df1", "bbox": [10, 10, 20, 20], "reason": "unreadable_low_contrast",
        }]
        fused = fuse_perception({"text_regions": []}, visual)
        self.assertEqual(len(fused["detection_failures"]), 1)
        self.assertEqual(fused["detection_failures"][0]["source"], "agy")
        self.assertEqual(fused["detection_failures"][0]["reason"], "unreadable_low_contrast")

    def test_detection_failures_key_is_always_present(self):
        fused = fuse_perception({"text_regions": []}, gemini_fixture())
        self.assertEqual(fused["detection_failures"], [])

    def test_fused_artifact_is_self_describing(self):
        visual = gemini_fixture()
        visual["metadata"] = {"provider": "AGY", "model": MODEL,
                              "skill_version": SKILL}
        fused = fuse_perception({"text_regions": []}, visual)
        metadata = fused["metadata"]
        self.assertEqual(metadata["provider"], "AGY")
        self.assertEqual(metadata["model"], MODEL)
        self.assertEqual(metadata["skill_version"], SKILL)
        self.assertEqual(metadata["screenshot_sha256"], "fixture")  # capture digest 去前缀
        self.assertNotIn("artifact_sha256", metadata)  # 封印是发布方职责

    def test_fused_artifact_digest_is_self_verifiable(self):
        fused = fuse_perception({"text_regions": []}, gemini_fixture())
        digest = fused_artifact_digest(fused)
        again = fused_artifact_digest(fused)
        self.assertEqual(digest, again)  # 确定性
        tampered = json.loads(json.dumps(fused))
        tampered["text_regions"] = [{
            "id": "x", "text": "tampered", "bbox": [1, 1, 1, 1], "confidence": 0.99,
        }]
        self.assertNotEqual(fused_artifact_digest(tampered), digest)  # 内容敏感
        # 消费者验签路径：去掉 artifact_sha256 后重算必须复现
        sealed = json.loads(json.dumps(fused))
        sealed.setdefault("metadata", {})["artifact_sha256"] = digest
        body = json.loads(json.dumps(sealed))
        body["metadata"].pop("artifact_sha256")
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        import hashlib
        self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), digest)

    def test_legacy_explicit_provider_fixture_stays_schema_valid(self):
        visual = gemini_fixture()
        del visual["metadata"]
        visual["metadata"] = {"provider": "Gemini"}  # 无 model/skill_version
        fused = fuse_perception({"text_regions": []}, visual)
        self.assertEqual(fused["metadata"]["provider"], "Gemini")
        self.assertIsNone(fused["metadata"]["model"])
        self.assertEqual(VisionObservation.validate(fused), [])

    def test_missing_metadata_never_silently_becomes_gemini(self):
        visual = gemini_fixture()
        del visual["metadata"]
        try:
            fused = fuse_perception({"text_regions": []}, visual)
        except FusionProvenanceError:
            return
        sources = {
            item["source"]
            for collection in ("interaction_candidates", "numeric_regions")
            for item in fused.get(collection, [])
        }
        self.assertNotIn("gemini", sources)


if __name__ == "__main__":
    unittest.main()
