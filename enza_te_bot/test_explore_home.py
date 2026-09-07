"""Phase A regression: read-only HOME exploration driver end to end.

Covers the ten acceptance behaviours for the exploration entry point:
AGY success path, timeout / invalid-JSON / paddle failure fail-closed with no
native-vision fallback, missing and ambiguous HOME fields as
UNKNOWN_DEPENDENCY, screenshot-free projection, import safety, two-frame
stability, and the absence of any input injection.
"""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from explore_home import run_exploration
from observer.trajectory_recorder import TrajectoryRecorder
from vision_agent.agy_vision_bridge import AgyRunnerRequest, AgyRunnerResult


REPO_ROOT = Path(__file__).resolve().parent

SEASON_ROI = [0.25, 0.02, 0.34, 0.05]
WEEKS_ROI = [0.37, 0.02, 0.43, 0.10]
FAN_GAP_ROI = [0.54, 0.02, 0.74, 0.11]
ANCHORS = {
    "season": {"roi": SEASON_ROI, "range": [1, 4]},
    "weeks_remaining": {"roi": WEEKS_ROI, "range": [0, 99]},
    "fan_gap_to_target": {"roi": FAN_GAP_ROI},
}

FORBIDDEN_IMPORTS = {
    "executor",
    "action_boundary",
    "actions",
    "goal_execution",
    "mvp_runtime_runner",
    "home_tick",
    "pyautogui",
}
GUARDED_SOURCES = [
    "explore_home.py",
    "exploration/__init__.py",
    "exploration/home_projection.py",
    "vision_agent/agy_cli_runner.py",
    "vision_agent/agy_vision_bridge.py",
]
FORBIDDEN_CALLS = {".click(", ".press(", ".typewrite(", ".moveTo(", ".hotkey(", ".dragTo("}


def paddle_regions() -> list[dict]:
    return [
        {"id": "paddle_001", "text": "3", "bbox": [340, 17, 30, 20], "confidence": 0.99},
        {"id": "paddle_002", "text": "5", "bbox": [500, 20, 30, 22], "confidence": 0.99},
        {"id": "paddle_003", "text": "12,345", "bbox": [700, 22, 90, 24], "confidence": 0.99},
    ]


class ExploreHomePhaseATests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_root = self.root / "test_data"
        self.trajectory_root = self.root / "trajectories"
        # Offline isolation: the real AGY CLI runner must never be constructed
        # by the offline suite, even if a fixture/override is forgotten.
        patcher = mock.patch(
            "vision_agent.agy_cli_runner.build_agy_cli_runner",
            side_effect=AssertionError(
                "offline suite attempted to build the real AGY CLI runner"
            ),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.digests: list[str] = []
        self.screenshots: list[Path] = []
        for index in range(2):
            screenshot = self.root / f"screen_{index}.png"
            try:
                from PIL import Image

                Image.new("RGB", (1280, 720), (240 + index, 240, 240)).save(screenshot)
            except ImportError:  # pragma: no cover - PIL is a repo dependency
                screenshot.write_bytes(f"\x89PNG\r\n\x1a\nfixture{index}".encode())
            self.screenshots.append(screenshot)
            self.digests.append(hashlib.sha256(screenshot.read_bytes()).hexdigest())
        self.base = "OBS_EXPLORE_FIXTURE"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    # -- fixture builders ------------------------------------------------
    def paddle_payload(self, regions: list[dict] | None = None) -> dict:
        return {
            "source_image": "screen.png",
            "method": "PaddleOCR",
            "text_regions": paddle_regions() if regions is None else regions,
        }

    def agy_fixture_for(self, case_id: str, digest: str) -> str:
        return json.dumps(
            {
                "metadata": {
                    "provider": "AGY",
                    "model": "gemini-3.8-flash-medium",
                    "skill_version": "gemini_vision_v1",
                    "case_id": case_id,
                    "source_image": "source_screenshot.png",
                    "screenshot_sha256": digest,
                    "created_at": "2026-09-05T00:00:00",
                },
                "observation_id": case_id,
                "capture": {
                    "timestamp": "2026-09-05T00:00:00",
                    "frame_id": case_id,
                    "screenshot_digest": f"sha256:{digest}",
                },
                "viewport": {"width": 1280, "height": 720},
                "text_regions": [],
                "interaction_candidates": [],
                "numeric_regions": [],
                "overlay_regions": [],
                "uncertainties": [],
            }
        )

    def runner(self, case_id_base: str, **overrides) -> dict:
        """Build run_exploration kwargs with case-bound offline fixtures."""
        frames = int(overrides.get("frames", 1))
        fixtures: dict[str, str] = {}
        for index in range(1, frames + 1):
            case_id = f"{case_id_base}_f{index:02d}"
            digest = self.digests[min(index - 1, len(self.digests) - 1)]
            fixtures[case_id] = self.agy_fixture_for(case_id, digest)
        observed_requests: list[AgyRunnerRequest] = []
        state = {"index": 0}

        def per_case_agy(request: AgyRunnerRequest) -> AgyRunnerResult:
            # The fake runner validates the real request contract, exactly as
            # a live runner must: no looser shapes allowed.
            self.assertEqual(
                Path(request.output_artifact_path).name, "vision_output.json"
            )
            self.assertTrue(request.case_id.startswith(case_id_base))
            self.assertEqual(len(request.source_sha256), 64)
            self.assertTrue(request.skill_path.endswith("SKILL.md"))
            self.assertGreater(request.timeout_seconds, 0)
            observed_requests.append(request)
            state["index"] += 1
            case_id = f"{case_id_base}_f{state['index']:02d}"
            output = Path(request.output_artifact_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(fixtures[case_id], encoding="utf-8")
            return AgyRunnerResult(
                exit_status=0,
                artifact_path=str(output),
                job_id="fixture-job",
                conversation_id=f"fixture-conversation-{state['index']}",
            )

        def paddle(_screenshot_path: str) -> dict:
            return self.paddle_payload()

        defaults: dict = {
            "frames": frames,
            "case_id_base": case_id_base,
            "data_root": self.data_root,
            "suite": "ob003",
            "trajectory_root": self.trajectory_root,
            "screenshot_sources": self.screenshots[:frames],
            "cdp_url": None,
            "agy_fixture": None,
            "paddle_fixture": None,
            "fake_paddle": False,
            "agy_timeout_seconds": 1500,
            "skill_version": "gemini_vision_v1",
            "resume_conversation_id": None,
            "clarify": None,
            "config_path": None,
            "identity_spec": {
                "contract": "home_identity_spec@1",
                "min_anchor_confidence": 0.6,
                "positive_anchors": [
                    {"anchor_id": "home.field.season", "kind": "field_value",
                     "field": "season", "roi": SEASON_ROI, "range": [1, 4], "required": True},
                    {"anchor_id": "home.field.weeks_remaining", "kind": "field_value",
                     "field": "weeks_remaining", "roi": WEEKS_ROI, "required": True},
                    {"anchor_id": "home.field.fan_gap_to_target", "kind": "field_value",
                     "field": "fan_gap_to_target", "roi": FAN_GAP_ROI, "required": True},
                ],
                "negative_anchors": [],
            },
            "agy_runner_override": per_case_agy,
            "paddle_runner_override": paddle,
        }
        defaults.update(overrides)
        return defaults


class ExploreHomeSuccessTests(ExploreHomePhaseATests):
    def test_two_frame_stable_home_succeeds_with_zero_actions(self):
        summary = run_exploration(**self.runner(self.base, frames=2, clarify="stamina=ok"))
        self.assertEqual(summary["status"], "SUCCESS")
        self.assertEqual(summary["frames_collected"], 2)
        self.assertEqual(summary["human_actions_recorded"], 0)
        hashes = {frame["screenshot_sha256"] for frame in summary["frame_results"]}
        self.assertEqual(len(hashes), 2)
        for frame in summary["frame_results"]:
            fields = frame["home_projection"]["fields"]
            self.assertEqual(fields["season"]["value"], 3)
            self.assertEqual(fields["weeks_remaining"]["value"], 5)
            self.assertEqual(fields["fan_gap_to_target"]["value"], 12345)
            # stamina 保持 human provenance / conf 0.5
            self.assertEqual(fields["stamina"]["source"], "human_clarification")
            self.assertEqual(fields["stamina"]["confidence"], 0.5)
            # 视觉 required 锚齐 ⇒ 身份 CONFIRMED（provenance 无循环）
            identity = frame["home_projection"]["home_identity"]
            self.assertEqual(identity["verdict"], "HOME_CONFIRMED")
        trajectory_id = Path(summary["trajectory_dir"]).name
        recorder = TrajectoryRecorder(trajectory_id=trajectory_id, root=self.trajectory_root)
        self.assertEqual(len(recorder.replay()), 2)
        self.assertEqual(recorder.human_actions(), [])

    def test_single_clean_frame_reports_incomplete_frames(self):
        summary = run_exploration(**self.runner(self.base, frames=1, clarify="stamina=ok"))
        self.assertEqual(summary["status"], "INCOMPLETE_FRAMES")
        self.assertEqual(summary["frames_collected"], 1)


class ExploreHomeFailClosedTests(ExploreHomePhaseATests):
    def test_agy_timeout_is_unknown_perception_without_native_fallback(self):
        def timed_out(request: AgyRunnerRequest) -> AgyRunnerResult:
            self.assertEqual(
                Path(request.output_artifact_path).name, "vision_output.json"
            )
            return AgyRunnerResult(
                exit_status=None,
                artifact_path=None,
                conversation_id="stalled-conversation",
                diagnostic="AGY CLI exceeded 1500s",
                timed_out=True,
            )

        summary = run_exploration(
            **self.runner(self.base, agy_runner_override=timed_out, clarify="stamina=ok")
        )
        self.assertEqual(summary["status"], "UNKNOWN_PERCEPTION")
        self.assertEqual(summary["frame_results"][0]["reason_code"], "AGY_TIMEOUT")
        case_dir = self.data_root / "ob003" / f"{self.base}_f01"
        self.assertFalse((case_dir / "fused_observation.json").exists())
        self.assertFalse((case_dir / "providers" / "zcode").exists())

    def test_invalid_agy_json_is_unknown_perception(self):
        def invalid(request: AgyRunnerRequest) -> AgyRunnerResult:
            output = Path(request.output_artifact_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("{not json", encoding="utf-8")
            return AgyRunnerResult(exit_status=0, artifact_path=str(output))

        summary = run_exploration(
            **self.runner(self.base, agy_runner_override=invalid, clarify="stamina=ok")
        )
        self.assertEqual(summary["status"], "UNKNOWN_PERCEPTION")
        self.assertEqual(summary["frame_results"][0]["reason_code"], "INVALID_JSON")

    def test_missing_paddle_artifact_is_unknown_perception(self):
        def broken_paddle(_screenshot_path: str):
            raise RuntimeError("PaddleOCR unavailable")

        summary = run_exploration(
            **self.runner(
                self.base,
                paddle_runner_override=broken_paddle,
                clarify="stamina=ok",
            )
        )
        self.assertEqual(summary["status"], "UNKNOWN_PERCEPTION")
        self.assertEqual(
            summary["frame_results"][0]["reason_code"], "PADDLE_PROCESS_FAILURE"
        )

    def test_missing_home_field_is_unknown_dependency_with_recorded_question(self):
        summary = run_exploration(**self.runner(self.base, frames=2))
        self.assertEqual(summary["status"], "UNKNOWN_DEPENDENCY")
        frame = summary["frame_results"][0]
        self.assertEqual(frame["missing_fields"], ["stamina"])
        self.assertIn("observation_id", frame)
        trajectory_id = Path(summary["trajectory_dir"]).name
        recorder = TrajectoryRecorder(trajectory_id=trajectory_id, root=self.trajectory_root)
        questions = recorder.clarifications()
        self.assertTrue(questions, "open clarification question must be persisted")
        self.assertTrue(all(q.get("answer") in (None, "") for q in questions))

    def test_ambiguous_home_field_is_unknown_dependency(self):
        regions = paddle_regions() + [
            {"id": "paddle_004", "text": "4", "bbox": [360, 19, 30, 20], "confidence": 0.97}
        ]

        def ambiguous_paddle(_screenshot_path: str) -> dict:
            return self.paddle_payload(regions)

        summary = run_exploration(
            **self.runner(
                self.base,
                frames=2,
                paddle_runner_override=ambiguous_paddle,
                clarify="stamina=ok",
            )
        )
        self.assertEqual(summary["status"], "UNKNOWN_DEPENDENCY")
        self.assertEqual(summary["frame_results"][0]["ambiguous_fields"], ["season"])

    def test_clarify_argument_resolves_ambiguous_and_missing_fields(self):
        regions = paddle_regions() + [
            {"id": "paddle_004", "text": "4", "bbox": [360, 19, 30, 20], "confidence": 0.97}
        ]

        def ambiguous_paddle(_screenshot_path: str) -> dict:
            return self.paddle_payload(regions)

        summary = run_exploration(
            **self.runner(
                self.base,
                frames=2,
                paddle_runner_override=ambiguous_paddle,
                clarify="stamina=ok;season=3",
            )
        )
        # 澄清补齐业务值（projection COMPLETE），但 season 的身份证据来自
        # human_clarification ⇒ 身份门保持 AMBIGUOUS，run 不判定 SUCCESS。
        self.assertEqual(summary["status"], "UNKNOWN_DEPENDENCY")
        frame = summary["frame_results"][0]
        self.assertEqual(frame["status"], "HOME_IDENTITY_UNCONFIRMED")
        self.assertTrue(any(r.startswith("identity_evidence_not_visual")
                            for r in frame["reasons"]))
        self.assertTrue(frame["projection_recorded"])


class ExploreHomeSafetyTests(ExploreHomePhaseATests):
    def test_projection_never_receives_screenshot_input(self):
        from exploration import home_projection

        for name in ("project_home_fields", "apply_clarification_answers"):
            parameters = inspect.signature(getattr(home_projection, name)).parameters
            for parameter in parameters:
                self.assertNotIn("screenshot", parameter)
                self.assertNotIn("image", parameter)

    def test_phase_a_imports_no_executor_or_injection_modules(self):
        for relative in GUARDED_SOURCES:
            tree = ast.parse((REPO_ROOT / relative).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_module = alias.name.split(".")[0]
                        self.assertNotIn(
                            root_module, FORBIDDEN_IMPORTS,
                            f"{relative} imports forbidden module {alias.name}",
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root_module = node.module.split(".")[0]
                    self.assertNotIn(
                        root_module, FORBIDDEN_IMPORTS,
                        f"{relative} imports forbidden module {node.module}",
                    )

    def test_phase_a_contains_no_input_injection_calls(self):
        for relative in GUARDED_SOURCES:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            for call in FORBIDDEN_CALLS:
                self.assertNotIn(call, source, f"{relative} references {call}")


if __name__ == "__main__":
    unittest.main()
