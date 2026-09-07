"""Benchmark for the Human Demonstration Observer Mode v0.2.

Minimal compliance patch coverage:
  - observer never performs action execution (guard raises)
  - observations contain NO candidate_actions (action generation removed)
  - canonical observation identity: observation_id/frame_id/sequence_number/
    screenshot_sha256 strongly bound
  - human action full event schema (action_id, mouse_coordinate,
    coordinate_space, input_type, raw_event)
  - replay integrity: fails on wrong digest / unknown observation /
    duplicate action_id
  - clarification persistence to clarifications.jsonl
  - provider metadata preserved
  - no pollution of existing benchmark artifacts
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from observer import (
    HumanFeedbackChannel,
    ObserverMode,
    ObserverPermissionError,
    TrajectoryRecorder,
)
from observer.trajectory_recorder import ReplayIntegrityError

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000d49444154789c626001000000ffff030000060005"
    "57bfabd40000000049454e44ae426082"
)


class FakeVisionProvider:
    name = "fake_paddle_gemini_fusion"

    def __init__(self, text: str = "育成プロデュース"):
        self.text = text

    def observe(self, screenshot_path: str) -> dict:
        return {
            "observation_id": "OBS_TMP",
            "capture": {
                "timestamp": "2026-09-04T10:00:00Z",
                "frame_id": "frame_1",
                "screenshot_digest": "sha256:fake",
                "provider": self.name,
            },
            "viewport": {"width": 1280, "height": 720},
            "text_regions": [
                {"id": "e1", "text": self.text, "bbox": [10, 20, 200, 40], "confidence": 0.95}
            ],
            "interaction_candidates": [
                {
                    "id": "e1",
                    "bbox": [5, 15, 210, 50],
                    "appearance": {"shape": "rounded_rect"},
                    "linked_text_ids": ["e1"],
                    "interaction_confidence": 0.9,
                }
            ],
            "numeric_regions": [],
            "overlay_regions": [],
            "uncertainties": [],
        }


def make_screenshot(tmp: Path, n: int) -> Path:
    # append varying byte so digests differ between frames
    p = tmp / f"shot{n}.png"
    p.write_bytes(PNG + f"#{n}".encode())
    return p


def human_action(observation_id: str, action_id: str = "ACT_0001", **over) -> dict:
    action = {
        "action_id": action_id,
        "observation_id": observation_id,
        "timestamp": "2026-09-04T10:00:05Z",
        "input_type": "CLICK",
        "mouse_coordinate": [640, 360],
        "coordinate_space": "viewport",
        "target_text": "育成プロデュース",
        "target_element_id": "e1",
        "human_comment": "",
        "raw_event": {"event": "left_down", "button": 0, "pid": 4242},
    }
    action.update(over)
    return action


class ObserverModeBenchmark(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.traj_root = self.tmp / "trajectories"
        self.traj_root.mkdir(parents=True, exist_ok=True)
        self.legacy_file = self.traj_root / "enza_1e_environment_mapping_001.json"
        self.legacy_file.write_text("{}")
        self.recorder = TrajectoryRecorder(root=self.traj_root / "human_demonstrations")
        self.observer = ObserverMode(FakeVisionProvider(), self.recorder)

    def tearDown(self):
        self._tmp.cleanup()

    # 1. observer must not execute actions
    def test_no_action_execution(self):
        with self.assertRaises(ObserverPermissionError):
            self.observer.execute({"action_type": "CLICK"})
        with self.assertRaises(ObserverPermissionError):
            self.observer.request_action_boundary({})
        self.assertEqual(self.observer.executed_actions, [])

    # 2. v0.2: no candidate_actions anywhere in observations
    def test_no_candidate_actions(self):
        obs = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        self.assertNotIn("candidate_actions", obs)
        stored = json.loads(
            (self.recorder.dir / "observations.jsonl").read_text().splitlines()[0]
        )
        self.assertNotIn("candidate_actions", stored)
        # and the recorder actively rejects them
        with self.assertRaises(ValueError):
            self.recorder.record_observation(
                {"candidate_actions": [{"x": 1}], "vision_observation": {}},
                make_screenshot(self.tmp, 2),
            )

    # 3. canonical observation identity binding
    def test_observation_identity(self):
        obs1 = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        obs2 = self.observer.observe(str(make_screenshot(self.tmp, 2)))
        for i, obs in enumerate((obs1, obs2), start=1):
            self.assertEqual(obs["observation_id"], f"OBS_{i:04d}")
            self.assertEqual(obs["sequence_number"], i)
            self.assertEqual(obs["frame_id"], "frame_1")
            self.assertTrue(obs["screenshot_sha256"].startswith("sha256:"))
            # digest matches actual stored screenshot bytes
            shot = self.recorder.dir / obs["screenshot"]
            import hashlib
            self.assertEqual(
                obs["screenshot_sha256"],
                "sha256:" + hashlib.sha256(shot.read_bytes()).hexdigest(),
            )
        self.assertNotEqual(
            obs1["screenshot_sha256"], obs2["screenshot_sha256"]
        )

    # 4. human action full event schema + validation
    def test_human_action_schema(self):
        obs = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        record = self.recorder.record_human_action(human_action(obs["observation_id"]))
        for key in ("action_id", "observation_id", "timestamp", "mouse_coordinate",
                    "coordinate_space", "input_type", "raw_event"):
            self.assertIn(key, record)
        self.assertEqual(record["raw_event"]["event"], "left_down")
        with self.assertRaises(ValueError):
            self.recorder.record_human_action(
                human_action(obs["observation_id"], coordinate_space="galactic")
            )
        with self.assertRaises(ValueError):
            self.recorder.record_human_action(
                human_action(obs["observation_id"], input_type="TELEPORT")
            )

    # 5a. replay integrity case 1: wrong digest must fail
    def test_replay_fails_on_wrong_digest(self):
        obs = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        self.recorder.record_human_action(human_action(obs["observation_id"]))
        target = self.recorder.dir / obs["screenshot"]
        target.write_bytes(b"corrupted")
        with self.assertRaises(ReplayIntegrityError):
            self.recorder.replay()

    # 5b. replay integrity case 2: unknown observation reference must fail
    def test_replay_fails_on_unknown_observation(self):
        self.observer.observe(str(make_screenshot(self.tmp, 1)))
        self.recorder.record_human_action(human_action("OBS_9999"))
        with self.assertRaises(ReplayIntegrityError):
            self.recorder.replay()

    # 5c. replay integrity case 3: duplicate action_id must fail
    def test_replay_fails_on_duplicate_action_id(self):
        obs = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        self.recorder.record_human_action(human_action(obs["observation_id"], "ACT_0001"))
        self.recorder.record_human_action(human_action(obs["observation_id"], "ACT_0001"))
        with self.assertRaises(ReplayIntegrityError):
            self.recorder.replay()

    # clean replay still works end to end
    def test_replay_ok(self):
        obs1 = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        self.recorder.record_human_action(human_action(obs1["observation_id"]))
        self.observer.observe(str(make_screenshot(self.tmp, 2)))
        frames = self.recorder.replay()
        self.assertEqual(len(frames), 2)
        self.assertEqual(frames[0]["human_action"]["action_id"], "ACT_0001")
        self.assertIsNone(frames[1]["human_action"])

    # 6. clarification persistence to clarifications.jsonl
    def test_clarification_persisted(self):
        obs = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        feedback = HumanFeedbackChannel(self.recorder)
        feedback.ask_clarification(
            obs["observation_id"],
            options=[
                {"id": "e1", "label": "A", "target_text": "次へ"},
                {"id": "e2", "label": "B", "target_text": "研修設定"},
            ],
        )
        lines = (self.recorder.dir / "clarifications.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)  # question is on disk before the answer
        question = json.loads(lines[0])
        self.assertEqual(question["candidate_ids"], ["e1", "e2"])
        self.assertEqual(question["answer"], "")

        feedback.answer(obs["observation_id"], "e2", "先设置研修")
        lines = (self.recorder.dir / "clarifications.jsonl").read_text().splitlines()
        answered = json.loads(lines[1])
        self.assertEqual(answered["question_id"], question["question_id"])
        self.assertEqual(answered["answer"], "e2")

    # 7. provider metadata preserved
    def test_provider_metadata_preserved(self):
        obs = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        self.assertEqual(obs["provider_metadata"]["provider"], "fake_paddle_gemini_fusion")
        self.assertEqual(obs["vision_observation"]["capture"]["frame_id"], "frame_1")

    # 8. no pollution of existing benchmark artifacts
    def test_no_artifact_pollution(self):
        self.observer.observe(str(make_screenshot(self.tmp, 1)))
        self.assertEqual(self.legacy_file.read_text(), "{}")
        top_level = {
            p.name for p in self.traj_root.iterdir() if p.is_file() and p.suffix == ".json"
        }
        self.assertEqual(top_level, {"enza_1e_environment_mapping_001.json"})
        self.assertTrue(
            self.recorder.dir.is_relative_to(self.traj_root / "human_demonstrations")
        )

    # 9. feedback channel failure samples still recordable
    def test_feedback_channel(self):
        obs = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        feedback = HumanFeedbackChannel(self.recorder)
        feedback.record_semantic_mismatch(
            obs["observation_id"], agent_prediction="次へ", human_action_text="研修設定"
        )
        feedback.record_sensor_disagreement(
            obs["observation_id"],
            providers={"paddle": "text: 研修設定", "gemini": "button: unknown"},
            reason="sensor disagreement: OCR text not matched by vision button label",
        )
        corrections = self.recorder.corrections()
        self.assertEqual(len(corrections), 2)
        self.assertEqual(corrections[0]["agent_prediction"]["type"], "semantic_mismatch")
        self.assertEqual(corrections[1]["agent_prediction"]["type"], "sensor_disagreement")

    # 10. transition comparison still works without candidate_actions
    def test_transition_comparison(self):
        obs1 = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        action = human_action(obs1["observation_id"])
        self.observer.vision_provider = FakeVisionProvider(text="次へ")
        obs2 = self.observer.observe(str(make_screenshot(self.tmp, 2)))
        self.recorder.set_prediction(
            {"candidates": [{"target_text": "次へ"}, {"target_text": "育成プロデュース"}]}
        )
        result = self.recorder.compare_transition(obs1, action, obs2)
        self.assertIn("次へ", result["actual_changes"])
        self.assertTrue(result["matches_prediction"])

    # 11. observer output remains VisionObservation contract-compatible
    def test_vision_observation_compatibility(self):
        obs = self.observer.observe(str(make_screenshot(self.tmp, 1)))
        payload = obs["vision_observation"]
        self.assertEqual(payload["viewport"]["width"], 1280)
        self.assertEqual(payload["text_regions"][0]["text"], "育成プロデュース")


if __name__ == "__main__":
    unittest.main(verbosity=2)
