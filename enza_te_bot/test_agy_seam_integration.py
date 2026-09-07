"""Seam integration: explore_home live path -> build_agy_cli_runner ->
RealAgyCliRunner -> subprocess(fake `agy` binary) -> bridge -> canonical.

The only substituted component is the external `agy` binary itself, provided
through PATH as a throwaway script. No runner override, no mock of the
factory: the driver's live branch constructs the real runner, the real
runner dispatches a real subprocess, and the real bridge validates and
publishes. Paddle is stubbed only because OCR is not the seam under test.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import textwrap
import unittest
from unittest import mock

from explore_home import run_exploration
from observer.trajectory_recorder import TrajectoryRecorder


REPO_ROOT = Path(__file__).resolve().parent
MODEL = "gemini-3.8-flash-medium"
SKILL = "gemini_vision_v1"
CONVERSATION_ID = "99999999-8888-7777-6666-555555555555"

SEASON_ROI = [0.25, 0.02, 0.34, 0.05]
WEEKS_ROI = [0.37, 0.02, 0.43, 0.10]
FAN_GAP_ROI = [0.54, 0.02, 0.74, 0.11]

FAKE_AGY = r'''#!/usr/bin/env python3
import json, os, re, sys, time
from pathlib import Path

argv = sys.argv[1:]
calls_path = Path(os.environ["FAKE_AGY_CALLS"])
expected_model = os.environ.get("FAKE_EXPECT_MODEL", "gemini-3.8-flash-medium")
expected_resume = os.environ.get("FAKE_EXPECT_RESUME", "")

missing = []
def flag(name):
    return name in argv and argv[argv.index(name) + 1]

if "--model" not in argv or flag("--model") != expected_model:
    missing.append("--model=" + expected_model)
if "--print" not in argv:
    missing.append("--print")
if "--print-timeout" not in argv or not re.match(r"^\d+(\.\d+)?s$", flag("--print-timeout")):
    missing.append("--print-timeout")
if expected_resume:
    if flag("--conversation") != expected_resume:
        missing.append("--conversation=" + expected_resume)
elif "--conversation" in argv:
    missing.append("no --conversation expected")

record = {"argv": argv, "argv_ok": not missing, "missing": missing}
with calls_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, ensure_ascii=False) + "\n")

mode = os.environ.get("FAKE_MODE", "success")
if mode == "timeout":
    time.sleep(30)
    sys.exit(0)
if mode == "nonzero":
    sys.exit(7)

prompt = argv[argv.index("--print") + 1]
output = Path(re.search(r"Write JSON only to this staging artifact: (\S+)", prompt).group(1))
output.parent.mkdir(parents=True, exist_ok=True)
if mode == "malformed":
    output.write_text("{not-json", encoding="utf-8")
    sys.exit(0)

def value(name):
    return re.search(r"^" + re.escape(name) + r"=(.*)$", prompt, re.MULTILINE).group(1).strip()

case_id = value("case_id")
sha = value("screenshot_sha256")
payload = {
    "metadata": {
        "provider": "AGY", "model": expected_model, "skill_version": "gemini_vision_v1",
        "case_id": case_id, "source_image": "source_screenshot.png",
        "screenshot_sha256": sha, "created_at": "2026-09-05T00:00:00",
    },
    "observation_id": case_id,
    "capture": {"timestamp": "2026-09-05T00:00:00", "frame_id": case_id,
                "screenshot_digest": "sha256:" + sha},
    "viewport": json.loads(value("viewport")),
    "text_regions": [], "interaction_candidates": [], "numeric_regions": [],
    "overlay_regions": [], "uncertainties": [],
}
output.write_text(json.dumps(payload), encoding="utf-8")
'''

PADDLE_REGIONS = [
    {"id": "paddle_001", "text": "3", "bbox": [340, 17, 30, 20], "confidence": 0.99},
    {"id": "paddle_002", "text": "5", "bbox": [500, 20, 30, 22], "confidence": 0.99},
    {"id": "paddle_003", "text": "12,345", "bbox": [700, 22, 90, 24], "confidence": 0.99},
]


class ExploreHomeLiveSeamIntegrationTests(unittest.TestCase):
    """The driver's live branch, end to end, with only the agy binary faked."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_root = self.root / "test_data"
        self.trajectory_root = self.root / "trajectories"
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir(parents=True)
        self.calls_path = self.bin_dir / "agy.calls"
        self._calls_env = mock.patch.dict(os.environ, {"FAKE_AGY_CALLS": str(self.calls_path)})
        self._calls_env.start()
        self.addCleanup(self._calls_env.stop)
        self.executable = self.bin_dir / "agy"
        self.executable.write_text(textwrap.dedent(FAKE_AGY), encoding="utf-8")
        self.executable.chmod(0o755)
        self._path_patch = mock.patch.dict(
            os.environ, {"PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        )
        self._path_patch.start()
        self.addCleanup(self._path_patch.stop)

        self.screenshots: list[Path] = []
        self.digests: list[str] = []
        for index in range(2):
            screenshot = self.root / f"frame{index}.png"
            try:
                from PIL import Image

                Image.new("RGB", (1280, 720), (30 + index, 60, 90)).save(screenshot)
            except ImportError:  # pragma: no cover - PIL is a repo dependency
                screenshot.write_bytes(f"\x89PNG\r\n\x1a\nframe{index}".encode())
            self.screenshots.append(screenshot)
            self.digests.append(hashlib.sha256(screenshot.read_bytes()).hexdigest())

        self.config = self.root / "config.json"
        self.config.write_text(json.dumps({
            "perception": {
                "home_observation": {
                    "season": {"roi": SEASON_ROI, "range": [1, 4]},
                    "weeks_remaining": {"roi": WEEKS_ROI, "range": [0, 99]},
                    "fan_gap_to_target": {"roi": FAN_GAP_ROI},
                    "stamina": {"roi": [0.75, 0.02, 0.99, 0.06]},
                },
                "home_identity": {
                    "contract": "home_identity_spec@1",
                    "positive_anchors": [
                        {"anchor_id": "home.field.season", "kind": "field_value",
                         "field": "season", "roi": SEASON_ROI, "required": True},
                        {"anchor_id": "home.field.weeks_remaining", "kind": "field_value",
                         "field": "weeks_remaining", "roi": WEEKS_ROI, "required": True},
                        {"anchor_id": "home.field.fan_gap_to_target", "kind": "field_value",
                         "field": "fan_gap_to_target", "roi": FAN_GAP_ROI, "required": True},
                    ],
                    "negative_anchors": [],
                },
            }
        }), encoding="utf-8")
        self.base = "OBS_SEAM_LIVE"

    def tearDown(self) -> None:
        bridge_logs = REPO_ROOT / "logs" / "agy_bridge"
        if bridge_logs.exists():
            for case_dir in bridge_logs.iterdir():
                if case_dir.name.startswith(self.base):
                    shutil.rmtree(case_dir, ignore_errors=True)
        self.temporary.cleanup()

    def set_mode(self, mode: str) -> None:
        os.environ["FAKE_MODE"] = mode

    def cleanup_mode(self) -> None:
        os.environ.pop("FAKE_MODE", None)

    def paddle(self, _screenshot_path: str) -> dict:
        return {"source_image": "screen.png", "method": "PaddleOCR",
                "text_regions": PADDLE_REGIONS}

    def calls(self) -> list[dict]:
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text().splitlines() if line.strip()]

    def run_live(self, *, frames: int = 1, mode: str = "success",
                 timeout: float = 10.0, resume: str | None = None) -> dict:
        self.set_mode(mode)
        if resume:
            os.environ["FAKE_EXPECT_RESUME"] = resume
        try:
            return run_exploration(
                frames=frames,
                case_id_base=self.base,
                data_root=self.data_root,
                suite="ob003",
                trajectory_root=self.trajectory_root,
                screenshot_sources=self.screenshots[:frames],
                cdp_url=None,
                agy_fixture=None,
                paddle_fixture=None,
                fake_paddle=False,
                agy_timeout_seconds=timeout,
                skill_version=SKILL,
                resume_conversation_id=resume,
                clarify="stamina=ok",
                config_path=self.config,
                paddle_runner_override=self.paddle,
            )
        finally:
            self.cleanup_mode()
            os.environ.pop("FAKE_EXPECT_RESUME", None)

    def case_dir(self, suffix: str) -> Path:
        return self.data_root / "ob003" / f"{self.base}_{suffix}"

    # -- the seam ----------------------------------------------------------
    def test_success_two_frames_real_runner_publishes_canonical(self):
        summary = self.run_live(frames=2)
        self.assertEqual(summary["status"], "SUCCESS")
        self.assertEqual(summary["frames_collected"], 2)
        self.assertEqual(summary["human_actions_recorded"], 0)

        # canonical publish per frame, self-describing fused artifact
        for index in (1, 2):
            case = self.case_dir(f"f{index:02d}")
            canonical = case / "providers" / "agy" / SKILL / "vision_output.json"
            self.assertTrue(canonical.is_file())
            payload = json.loads(canonical.read_text())
            self.assertEqual(payload["metadata"]["provider"], "AGY")
            self.assertEqual(payload["metadata"]["model"], MODEL)
            self.assertTrue((case / "fused_observation.json").is_file())

        # request.output_artifact_path was a staging path, distinct per frame,
        # and never the canonical destination
        stagings = []
        for index in (1, 2):
            record = json.loads(
                (REPO_ROOT / "logs" / "agy_bridge" / f"{self.base}_f{index:02d}"
                 / "request.json").read_text()
            )
            staging = record["staging_output_path"]
            self.assertTrue(staging.endswith("vision_output.json"))
            self.assertNotIn(str(self.data_root), staging)
            self.assertFalse(Path(staging).exists(), "bridge staging directory must be transient")
            stagings.append(staging)
        self.assertNotEqual(stagings[0], stagings[1])

        # argv contract observed by the fake binary
        records = self.calls()
        self.assertEqual(len(records), 2, "exactly one AGY dispatch per frame")
        for record in records:
            self.assertTrue(record["argv_ok"], record["missing"])
            argv = record["argv"]
            self.assertEqual(argv[argv.index("--model") + 1], MODEL)
            self.assertIn("--print", argv)
            self.assertEqual(argv[argv.index("--print-timeout") + 1], "10s")
            self.assertNotIn("--conversation", argv)

        fields = summary["frame_results"][0]["home_projection"]["fields"]
        self.assertEqual(fields["season"]["value"], 3)
        self.assertEqual(fields["weeks_remaining"]["value"], 5)
        self.assertEqual(fields["fan_gap_to_target"]["value"], 12345)
        self.assertEqual(fields["stamina"]["source"], "human_clarification")

        trajectory_id = Path(summary["trajectory_dir"]).name
        recorder = TrajectoryRecorder(trajectory_id=trajectory_id, root=self.trajectory_root)
        self.assertEqual(len(recorder.replay()), 2)

    def test_resume_flag_is_forwarded_to_real_argv(self):
        resume = CONVERSATION_ID
        summary = self.run_live(frames=1, resume=resume)
        self.assertEqual(summary["status"], "INCOMPLETE_FRAMES")  # single frame by contract
        record = self.calls()[0]
        self.assertTrue(record["argv_ok"], record["missing"])
        argv = record["argv"]
        self.assertEqual(argv[argv.index("--conversation") + 1], resume)

    # -- failure modes leave no canonical artifact -------------------------
    def test_timeout_leaves_no_canonical(self):
        summary = self.run_live(frames=1, mode="timeout", timeout=0.4)
        self.assertEqual(summary["status"], "UNKNOWN_PERCEPTION")
        self.assertEqual(summary["frame_results"][0]["reason_code"], "AGY_TIMEOUT")
        case = self.case_dir("f01")
        self.assertFalse((case / "providers").exists())
        self.assertFalse((case / "fused_observation.json").exists())

    def test_nonzero_exit_leaves_no_canonical(self):
        summary = self.run_live(frames=1, mode="nonzero")
        self.assertEqual(summary["status"], "UNKNOWN_PERCEPTION")
        self.assertEqual(summary["frame_results"][0]["reason_code"], "AGY_COMMAND_FAILURE")
        self.assertFalse((self.case_dir("f01") / "providers").exists())

    def test_malformed_json_leaves_no_canonical(self):
        summary = self.run_live(frames=1, mode="malformed")
        self.assertEqual(summary["status"], "UNKNOWN_PERCEPTION")
        self.assertEqual(summary["frame_results"][0]["reason_code"], "INVALID_JSON")
        self.assertFalse((self.case_dir("f01") / "providers").exists())


if __name__ == "__main__":
    unittest.main()
