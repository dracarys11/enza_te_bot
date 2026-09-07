"""Offline subprocess regression for Real AGY CLI Runner v0.1."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest import mock

from vision_agent.agy_cli_runner import (
    RealAgyCliRunner,
    build_agy_cli_runner,
)
from vision_agent.agy_vision_bridge import (
    AgyRunnerRequest,
    AgyVisionConfig,
    REASON_AGY_TIMEOUT,
    REASON_INVALID_JSON,
    REASON_PROVENANCE_MISMATCH,
    REASON_SCREENSHOT_HASH_MISMATCH,
    RUNNER_MODE_LIVE,
    STATUS_SUCCESS,
    STATUS_UNKNOWN,
    vision_request,
)


MODEL = "gemini-3.8-flash-medium"
SKILL = "gemini_vision_v1"
CONVERSATION_ID = "12345678-1234-1234-1234-123456789abc"
JOB_ID = "staffer-fixture123"


FAKE_AGY = r'''#!/usr/bin/env python3
import json
from pathlib import Path
import re
import sys
import time

program = Path(sys.argv[0])
mode_path = program.with_suffix(".mode")
calls_path = program.with_suffix(".calls")
mode = mode_path.read_text().strip() if mode_path.exists() else "success"
with calls_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\n")
args = sys.argv[1:]
prompt = args[args.index("--print") + 1]
conversation = (
    args[args.index("--conversation") + 1]
    if "--conversation" in args
    else "12345678-1234-1234-1234-123456789abc"
)
print("conversation " + conversation + " job staffer-fixture123", flush=True)
print("fake stderr preserved", file=sys.stderr, flush=True)
if mode == "timeout":
    time.sleep(2)
    raise SystemExit(0)
if mode == "nonzero":
    raise SystemExit(7)
if mode == "missing":
    raise SystemExit(0)

def value(name):
    match = re.search(r"^" + re.escape(name) + r"=(.*)$", prompt, re.MULTILINE)
    if not match:
        raise RuntimeError("missing prompt field: " + name)
    return match.group(1).strip()

output_match = re.search(r"^Write JSON only to this staging artifact: (.*)$", prompt, re.MULTILINE)
output = Path(output_match.group(1).strip())
output.parent.mkdir(parents=True, exist_ok=True)
if mode == "malformed":
    output.write_text("{not-json", encoding="utf-8")
    raise SystemExit(0)
case_id = value("case_id")
digest = value("screenshot_sha256")
model = "wrong-model" if mode == "wrong_model" else value("metadata.model")
artifact_digest = "wrong-digest" if mode == "wrong_digest" else digest
payload = {
    "metadata": {
        "provider": "AGY", "model": model, "skill_version": "gemini_vision_v1",
        "case_id": case_id, "source_image": "source_screenshot.png",
        "screenshot_sha256": artifact_digest, "created_at": "2026-09-05T00:00:00Z",
    },
    "observation_id": case_id,
    "capture": {
        "timestamp": "2026-09-05T00:00:00Z", "frame_id": case_id,
        "screenshot_digest": "sha256:" + artifact_digest,
    },
    "viewport": json.loads(value("viewport")),
    "text_regions": [], "interaction_candidates": [], "numeric_regions": [],
    "overlay_regions": [], "uncertainties": [], "detection_failures": [],
}
output.write_text(json.dumps(payload), encoding="utf-8")
'''


class RealAgyCliRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "workspace with spaces"
        self.root.mkdir(parents=True)
        self.executable = self.root / "bin with spaces" / "fake agy"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_text(textwrap.dedent(FAKE_AGY), encoding="utf-8")
        self.executable.chmod(0o755)
        self.mode_path = self.executable.with_suffix(".mode")
        self.calls_path = self.executable.with_suffix(".calls")
        self.screenshot = self.root / "screenshots with spaces" / "frame one.png"
        self.screenshot.parent.mkdir(parents=True)
        from PIL import Image

        Image.new("RGB", (64, 48), (10, 20, 30)).save(self.screenshot)
        self.digest = hashlib.sha256(self.screenshot.read_bytes()).hexdigest()
        self.skill = self.root / "skill files" / "SKILL.md"
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text("fixture skill", encoding="utf-8")
        self.staging = self.root / "staging output" / "vision_output.json"
        self.logs = self.root / "runner logs"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def set_mode(self, mode: str) -> None:
        self.mode_path.write_text(mode, encoding="utf-8")

    def request(self, *, case_id: str = "OBS_REAL_AGY_FIXTURE", timeout: float = 10.0):
        # 10s default: generous enough that interpreter startup can never
        # outrun the clock in normal-error tests; only the dedicated timeout
        # tests below shrink it on purpose.
        return AgyRunnerRequest(
            screenshot_path=str(self.screenshot),
            source_sha256=self.digest,
            case_id=case_id,
            skill_path=str(self.skill),
            output_artifact_path=str(self.staging),
            timeout_seconds=timeout,
        )

    def runner(self, *, resume: str | None = None) -> RealAgyCliRunner:
        return build_agy_cli_runner(
            executable=self.executable,
            resume_conversation_id=resume,
            log_root=self.logs,
        )

    def calls(self) -> list[list[str]]:
        if not self.calls_path.exists():
            return []
        return [json.loads(line) for line in self.calls_path.read_text().splitlines()]

    def paddle(self, _path: str) -> dict:
        return {"source_image": "screen.png", "method": "PaddleOCR", "text_regions": []}

    def bridge_request(self, mode: str):
        self.set_mode(mode)
        case_id = f"OBS_REAL_AGY_{mode.upper()}"
        runner = self.runner()
        result = vision_request(
            self.screenshot,
            case_id,
            test_data_root=self.root / "test_data",
            agy_runner=runner,
            paddle_runner=self.paddle,
            config=AgyVisionConfig(
                expected_model=MODEL,
                runner_mode=RUNNER_MODE_LIVE,
                # Timeout-semantic tests use 0.1s on purpose; every other
                # mode must never be time-limited by the harness itself -- a
                # loaded CI box can otherwise turn INVALID_JSON / hash /
                # provenance failures into spurious AGY_TIMEOUTs.
                timeout_seconds=0.1 if mode == "timeout" else 10.0,
            ),
        )
        return result, runner

    def test_success_maps_request_to_real_argv_and_result(self):
        self.set_mode("success")
        with mock.patch(
            "vision_agent.agy_cli_runner.subprocess.run", wraps=subprocess.run
        ) as run_spy:
            result = self.runner()(self.request())
        self.assertEqual(result.exit_status, 0)
        self.assertEqual(result.artifact_path, str(self.staging))
        self.assertEqual(result.conversation_id, CONVERSATION_ID)
        self.assertEqual(result.job_id, JOB_ID)
        self.assertIn("conversation", result.diagnostic)
        self.assertEqual(result.stderr.strip(), "fake stderr preserved")
        kwargs = run_spy.call_args.kwargs
        self.assertIs(kwargs["shell"], False)
        self.assertEqual(kwargs["timeout"], 10.0)
        argv = run_spy.call_args.args[0]
        self.assertIsInstance(argv, list)
        self.assertEqual(argv[0], str(self.executable))
        self.assertEqual(argv[argv.index("--model") + 1], MODEL)

    def test_timeout_is_structured_and_never_retried(self):
        self.set_mode("timeout")
        runner = self.runner()
        result = runner(self.request(timeout=0.1))
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_status)
        # A killed process yields no readable partial stdout on POSIX, so the
        # conversation id can only come from an explicit resume id.
        self.assertIsNone(result.conversation_id)
        # The 0.1s kill can land before the fake binary records its argv;
        # the runner-side counter is the reliable single-dispatch evidence.
        self.assertEqual(runner.invocation_count, 1)

    def test_nonzero_exit_preserves_stdout_stderr_and_exit_code(self):
        self.set_mode("nonzero")
        result = self.runner()(self.request())
        self.assertEqual(result.exit_status, 7)
        self.assertIsNone(result.artifact_path)
        self.assertIn(CONVERSATION_ID, result.diagnostic)
        self.assertEqual(result.stderr.strip(), "fake stderr preserved")

    def test_missing_artifact_is_reported_without_fabricating_path(self):
        self.set_mode("missing")
        result = self.runner()(self.request())
        self.assertEqual(result.exit_status, 0)
        self.assertIsNone(result.artifact_path)
        self.assertFalse(self.staging.exists())

    def test_malformed_json_is_left_for_bridge_validation(self):
        result, _runner = self.bridge_request("malformed")
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason_code, REASON_INVALID_JSON)
        self.assert_no_canonical_artifacts(result.case_id)

    def test_resume_uses_exact_conversation_id_without_new_dispatch(self):
        resume_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        self.set_mode("success")
        result = self.runner(resume=resume_id)(self.request())
        argv = self.calls()[0]
        self.assertEqual(argv[argv.index("--conversation") + 1], resume_id)
        self.assertEqual(result.conversation_id, resume_id)
        self.assertEqual(len(self.calls()), 1)

    def test_paths_with_spaces_are_single_argv_and_prompt_values(self):
        self.set_mode("success")
        self.runner()(self.request())
        argv = self.calls()[0]
        prompt = argv[argv.index("--print") + 1]
        self.assertIn(str(self.screenshot), prompt)
        self.assertIn(str(self.skill), prompt)
        self.assertIn(str(self.staging), prompt)
        self.assertTrue(self.staging.is_file())

    def test_wrong_model_fails_in_bridge_and_never_publishes(self):
        result, _runner = self.bridge_request("wrong_model")
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason_code, REASON_PROVENANCE_MISMATCH)
        self.assert_no_canonical_artifacts(result.case_id)

    def test_wrong_screenshot_digest_fails_and_never_publishes(self):
        result, _runner = self.bridge_request("wrong_digest")
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason_code, REASON_SCREENSHOT_HASH_MISMATCH)
        self.assert_no_canonical_artifacts(result.case_id)

    def test_success_stages_then_bridge_publishes_canonical_once(self):
        result, runner = self.bridge_request("success")
        self.assertEqual(result.status, STATUS_SUCCESS)
        self.assertEqual(len(self.calls()), 1)
        self.assertTrue(Path(result.agy_artifact).is_file())
        self.assertTrue(Path(result.fused_artifact).is_file())
        self.assertFalse(self.staging.exists(), "bridge staging directory must be transient")

    def test_timeout_maps_fail_closed_and_creates_no_canonical_artifact(self):
        result, runner = self.bridge_request("timeout")
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason_code, REASON_AGY_TIMEOUT)
        self.assertEqual(runner.invocation_count, 1)
        self.assert_no_canonical_artifacts(result.case_id)

    def test_runner_source_has_no_shell_true(self):
        source = Path(__import__("vision_agent.agy_cli_runner", fromlist=["x"]).__file__).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg == "shell":
                    self.assertIsInstance(keyword.value, ast.Constant)
                    self.assertIs(keyword.value.value, False)

    def assert_no_canonical_artifacts(self, case_id: str) -> None:
        case = self.root / "test_data" / "ob003" / case_id
        self.assertFalse((case / "providers").exists())
        self.assertFalse((case / "fused_observation.json").exists())


if __name__ == "__main__":
    unittest.main()
