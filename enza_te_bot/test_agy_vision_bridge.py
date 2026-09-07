"""Fail-closed regression harness for AGY Vision Bridge v0.3."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from observer.observer_mode import ObserverMode
from vision_agent import agy_vision_bridge as bridge_module
from vision_agent.agy_vision_bridge import (
    AgyRunnerRequest,
    AgyRunnerResult,
    AgyVisionBridge,
    AgyVisionConfig,
    AgyVisionUnknown,
    STATUS_SUCCESS,
    STATUS_UNKNOWN,
    evaluate_agy_vision_bridge_gate,
    make_gate_evidence,
    vision_request,
)
from perception_fusion import fused_artifact_digest
from vision_observation_schema import VisionObservation


CASE_ID = "OBS_AGY_BRIDGE_FIXTURE"
MODEL = "gemini-3.8-flash-medium"
SKILL = "gemini_vision_v1"


class RecorderStub:
    def __init__(self):
        self.record: dict | None = None

    def record_observation(self, observation, _screenshot_path):
        self.record = observation
        return observation


class AgyVisionBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "test_data"
        self.screenshot = Path(self.temporary.name) / "screen.png"
        self.screenshot.write_bytes(b"AGY bridge screenshot fixture")
        self.digest = hashlib.sha256(self.screenshot.read_bytes()).hexdigest()
        self.paddle_calls = 0
        self.agy_calls = 0
        self.runner_requests: list[AgyRunnerRequest] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def paddle(self, _path: str, *, empty: bool = False):
        self.paddle_calls += 1
        regions = [] if empty else [{
            "id": "paddle_001", "text": "次へ", "bbox": [10, 20, 40, 20],
            "confidence": 0.99,
        }]
        return {"source_image": "screen.png", "method": "PaddleOCR", "text_regions": regions}

    def agy_payload(
        self, *, case_id: str = CASE_ID, digest: str | None = None, **metadata_overrides
    ):
        digest = digest or self.digest
        metadata = {
            "provider": "AGY", "model": MODEL, "skill_version": SKILL,
            "case_id": case_id, "source_image": "source_screenshot.png",
            "screenshot_sha256": digest, "created_at": "2026-09-05T00:00:00Z",
            "provenance": {"session_reference": "fake-agy"},
        }
        metadata.update(metadata_overrides)
        return {
            "metadata": metadata,
            "observation_id": case_id,
            "capture": {
                "timestamp": "2026-09-05T00:00:00Z", "frame_id": case_id,
                "screenshot_digest": f"sha256:{digest}",
            },
            "viewport": {"width": 1280, "height": 720},
            "text_regions": [{
                "id": "agy_t1", "text": "次へ", "bbox": [10, 20, 40, 20],
                "confidence": 0.99,
            }],
            "interaction_candidates": [{
                "id": "agy_e1", "bbox": [5, 15, 60, 30],
                "appearance": {"shape": "rounded_rect"},
                "linked_text_ids": ["agy_t1"], "interaction_confidence": 0.99,
            }],
            "numeric_regions": [], "overlay_regions": [], "uncertainties": [],
            "detection_failures": [],
        }

    def fixture_runner(self, payload_or_factory):
        def run(request: AgyRunnerRequest) -> AgyRunnerResult:
            self.agy_calls += 1
            self.runner_requests.append(request)
            payload = payload_or_factory(request) if callable(payload_or_factory) else payload_or_factory
            output = Path(request.output_artifact_path)
            output.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(payload, bytes):
                output.write_bytes(payload)
            elif isinstance(payload, str):
                output.write_text(payload, encoding="utf-8")
            else:
                output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return AgyRunnerResult(
                exit_status=0, artifact_path=str(output), job_id="fake-job",
                conversation_id="fake-conversation", diagnostic="offline fixture",
            )
        return run

    def agy(self, request: AgyRunnerRequest) -> AgyRunnerResult:
        return self.fixture_runner(self.agy_payload())(request)

    def request(self, *, agy_runner="default", paddle_runner=None, config=None,
                case_id=CASE_ID, suite="ob003"):
        runner = self.agy if agy_runner == "default" else agy_runner
        return vision_request(
            self.screenshot, case_id, test_data_root=self.root, suite=suite, agy_runner=runner,
            paddle_runner=paddle_runner or self.paddle, config=config,
        )

    def assert_unknown(self, result, reason_code):
        self.assertEqual(result.status, STATUS_UNKNOWN)
        self.assertEqual(result.reason_code, reason_code)
        self.assertIsNone(result.fused_artifact)

    def test_fake_agy_success_and_structured_runner_request(self):
        result = self.request()
        self.assertEqual(result.status, STATUS_SUCCESS)
        self.assertEqual(result.provider, "AGY")
        self.assertEqual(result.model, MODEL)
        self.assertEqual(VisionObservation.validate(json.loads(Path(result.fused_artifact).read_text())), [])
        self.assertIn(f"providers/agy/{SKILL}/vision_output.json", result.agy_artifact)
        request = self.runner_requests[0]
        self.assertEqual(request.case_id, CASE_ID)
        self.assertEqual(request.source_sha256, self.digest)
        self.assertEqual(Path(request.skill_path).name, "SKILL.md")
        self.assertEqual(Path(request.output_artifact_path).name, "vision_output.json")
        self.assertGreater(request.timeout_seconds, 0)
        manifest = json.loads((self.root / "ob003" / CASE_ID / "manifest.json").read_text())
        self.assertEqual(len(manifest["providers"]), 2)
        for entry in manifest["providers"]:
            artifact = self.root / "ob003" / CASE_ID / entry["artifact"]
            self.assertEqual(entry["artifact_sha256"], hashlib.sha256(artifact.read_bytes()).hexdigest())
            self.assertEqual(entry["screenshot_sha256"], self.digest)

    def test_missing_source_image_returns_unknown(self):
        result = vision_request(
            self.screenshot.with_name("missing.png"), CASE_ID,
            test_data_root=self.root, agy_runner=self.agy, paddle_runner=self.paddle,
        )
        self.assert_unknown(result, bridge_module.REASON_SOURCE_IMAGE_MISSING)
        self.assertEqual((self.paddle_calls, self.agy_calls), (0, 0))

    def test_agy_timeout_returns_unknown(self):
        def timeout(_request):
            raise TimeoutError("fixture timeout")
        self.assert_unknown(self.request(agy_runner=timeout), bridge_module.REASON_AGY_TIMEOUT)

    def test_timeout_result_returns_unknown(self):
        result = AgyRunnerResult(
            exit_status=None, artifact_path=None, timed_out=True, diagnostic="bounded timeout"
        )
        self.assert_unknown(
            self.request(agy_runner=lambda _request: result), bridge_module.REASON_AGY_TIMEOUT
        )

    def test_invalid_json_returns_unknown(self):
        self.assert_unknown(
            self.request(agy_runner=self.fixture_runner("{invalid")),
            bridge_module.REASON_INVALID_JSON,
        )

    def test_runner_none_is_unconfigured_and_paddle_is_not_run(self):
        result = self.request(agy_runner=None)
        self.assert_unknown(result, bridge_module.REASON_AGY_COMMAND_UNCONFIGURED)
        self.assertEqual(self.paddle_calls, 0)

    def _boundary_runner(self, operation: str):
        payload = self.agy_payload()
        def run(request: AgyRunnerRequest) -> AgyRunnerResult:
            if operation == "providers":
                target = self.temporary_path / "test_data" / "ob003" / CASE_ID / "providers" / "evil.json"
                target.parent.mkdir(parents=True, exist_ok=True); target.write_text("x")
            elif operation == "manifest":
                target = self.temporary_path / "test_data" / "ob003" / CASE_ID / "manifest.json"
                target.parent.mkdir(parents=True, exist_ok=True); target.write_text("x")
            elif operation == "py":
                (self.temporary_path / "touched.py").write_text("x")
            elif operation == "delete":
                (self.temporary_path / "delete.me").unlink()
            elif operation == "outside":
                (self.temporary_path.parent / "agy-outside.tmp").write_text("x")
            output = Path(request.output_artifact_path)
            output.write_text(json.dumps(payload), encoding="utf-8")
            return AgyRunnerResult(exit_status=0, artifact_path=str(output))
        return run

    def test_unexpected_writes_fail_closed_and_leave_forensic_report(self):
        self.temporary_path = Path(self.temporary.name) / "workspace"
        self.temporary_path.mkdir()
        for name in ("touched.py", "delete.me"):
            (self.temporary_path / name).write_text("baseline")
        for operation in ("providers", "manifest", "py", "delete"):
            if operation == "delete":
                (self.temporary_path / "delete.me").write_text("baseline")
            with mock.patch.object(bridge_module, "REPO_ROOT", self.temporary_path):
                result = self.request(agy_runner=self._boundary_runner(operation), case_id=f"{CASE_ID}_{operation}")
            self.assert_unknown(result, bridge_module.REASON_UNEXPECTED_ARTIFACT_WRITE)
            report = self.temporary_path / "logs" / "agy_bridge" / f"{CASE_ID}_{operation}" / "unexpected_write_report.json"
            self.assertTrue(report.is_file())

    def test_writes_to_explicit_log_allowlist_are_allowed(self):
        self.temporary_path = Path(self.temporary.name) / "workspace"
        self.temporary_path.mkdir()
        payload = self.agy_payload(case_id=CASE_ID)
        def runner(request):
            log = self.temporary_path / "logs" / "agy_bridge" / CASE_ID / "extra.log"
            log.parent.mkdir(parents=True, exist_ok=True); log.write_text("ok")
            output = Path(request.output_artifact_path); output.write_text(json.dumps(payload))
            return AgyRunnerResult(exit_status=0, artifact_path=str(output))
        with mock.patch.object(bridge_module, "REPO_ROOT", self.temporary_path):
            result = self.request(agy_runner=runner)
        self.assertEqual(result.status, STATUS_SUCCESS)

    def test_runner_must_return_structured_result(self):
        self.assert_unknown(
            self.request(agy_runner=lambda _request: json.dumps(self.agy_payload())),
            bridge_module.REASON_RUNNER_PROTOCOL_FAILURE,
        )

    def test_malformed_observation_returns_schema_failure(self):
        payload = self.agy_payload()
        payload["viewport"] = {"width": "invalid", "height": 720}
        self.assert_unknown(
            self.request(agy_runner=self.fixture_runner(payload)), bridge_module.REASON_SCHEMA_FAILURE
        )

    def test_invalid_bbox_returns_schema_failure(self):
        payload = self.agy_payload()
        payload["interaction_candidates"][0]["bbox"] = [1, 2, 3]
        self.assert_unknown(
            self.request(agy_runner=self.fixture_runner(payload)), bridge_module.REASON_SCHEMA_FAILURE
        )

    def test_confidence_out_of_range_returns_schema_failure(self):
        payload = self.agy_payload()
        payload["text_regions"][0]["confidence"] = 1.1
        self.assert_unknown(
            self.request(agy_runner=self.fixture_runner(payload)), bridge_module.REASON_SCHEMA_FAILURE
        )

    def test_low_confidence_without_uncertainty_returns_schema_failure(self):
        payload = self.agy_payload()
        payload["text_regions"][0]["confidence"] = 0.2
        self.assert_unknown(
            self.request(agy_runner=self.fixture_runner(payload)), bridge_module.REASON_SCHEMA_FAILURE
        )

    def test_wrong_and_missing_capture_digest_fail_closed(self):
        wrong = self.agy_payload()
        wrong["capture"]["screenshot_digest"] = "sha256:wrong"
        self.assert_unknown(
            self.request(agy_runner=self.fixture_runner(wrong)),
            bridge_module.REASON_SCREENSHOT_HASH_MISMATCH,
        )
        missing_case = f"{CASE_ID}_missing"
        missing = self.agy_payload(case_id=missing_case)
        missing["capture"].pop("screenshot_digest")
        self.assert_unknown(
            self.request(agy_runner=self.fixture_runner(missing), case_id=missing_case),
            bridge_module.REASON_SCHEMA_FAILURE,
        )

    def test_forbidden_semantic_field_returns_unknown(self):
        payload = self.agy_payload()
        payload["semantic_state"] = "FORBIDDEN"
        self.assert_unknown(
            self.request(agy_runner=self.fixture_runner(payload)),
            bridge_module.REASON_FORBIDDEN_SEMANTIC_FIELD,
        )

    def test_provider_model_and_skill_mismatch_return_unknown(self):
        cases = [
            (self.agy_payload(provider="Gemini"), AgyVisionConfig()),
            (self.agy_payload(model="other"), AgyVisionConfig(expected_model=MODEL)),
            (self.agy_payload(skill_version="gemini_vision_v2"), AgyVisionConfig()),
        ]
        for index, (payload, config) in enumerate(cases):
            with self.subTest(metadata=payload["metadata"]):
                result = self.request(agy_runner=self.fixture_runner(payload), config=config,
                                      case_id=f"{CASE_ID}_mismatch_{index}")
                self.assert_unknown(result, bridge_module.REASON_PROVENANCE_MISMATCH)

    def test_unsupported_agy_skill_fails_before_sensors(self):
        self.assert_unknown(
            self.request(config=AgyVisionConfig(skill_version="unknown_skill")),
            bridge_module.REASON_UNSUPPORTED_SKILL,
        )
        self.assertEqual((self.paddle_calls, self.agy_calls), (0, 0))

    def test_live_like_expected_model_none_is_rejected(self):
        config = AgyVisionConfig(runner_mode=bridge_module.RUNNER_MODE_LIVE)
        self.assert_unknown(self.request(config=config), bridge_module.REASON_LIVE_MODEL_REQUIRED)
        self.assertEqual((self.paddle_calls, self.agy_calls), (0, 0))

    def test_offline_fake_expected_model_none_is_allowed(self):
        self.assertEqual(self.request(config=AgyVisionConfig(expected_model=None)).status, STATUS_SUCCESS)

    def test_stale_artifact_returns_unknown(self):
        payload = self.agy_payload(case_id="OBS_OLD")
        self.assert_unknown(
            self.request(agy_runner=self.fixture_runner(payload)), bridge_module.REASON_ARTIFACT_STALE
        )

    def test_preexisting_source_hash_mismatch_fails_before_sensors(self):
        source = self.root / "ob003" / CASE_ID / "source_screenshot.png"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"different screenshot")
        self.assert_unknown(self.request(), bridge_module.REASON_SCREENSHOT_HASH_MISMATCH)
        self.assertEqual((self.paddle_calls, self.agy_calls), (0, 0))

    def test_same_frame_overwrite_conflict_remains_unknown(self):
        self.assertEqual(self.request().status, STATUS_SUCCESS)
        calls = (self.paddle_calls, self.agy_calls)
        self.assert_unknown(self.request(), bridge_module.REASON_OVERWRITE_CONFLICT)
        self.assertEqual((self.paddle_calls, self.agy_calls), calls)

    def test_paddle_process_failure_returns_unknown(self):
        def failed(_path):
            raise RuntimeError("paddle failed")
        self.assert_unknown(
            self.request(paddle_runner=failed), bridge_module.REASON_PADDLE_PROCESS_FAILURE
        )
        self.assertEqual(self.agy_calls, 0)

    def test_empty_paddle_with_valid_agy_still_fuses(self):
        result = self.request(paddle_runner=lambda path: self.paddle(path, empty=True))
        self.assertEqual(result.status, STATUS_SUCCESS)
        fused = json.loads(Path(result.fused_artifact).read_text())
        self.assertEqual(fused["text_regions"], [])
        self.assertEqual(fused["interaction_candidates"][0]["source"], "agy")
        self.assertEqual(VisionObservation.validate(fused), [])

    def test_agy_failure_creates_no_fused_or_provider_artifact_and_no_fallback(self):
        def failed(_request):
            raise RuntimeError("agy failed")
        self.assert_unknown(self.request(agy_runner=failed), bridge_module.REASON_AGY_COMMAND_FAILURE)
        case = self.root / "ob003" / CASE_ID
        self.assertFalse((case / "fused_observation.json").exists())
        self.assertTrue((case / "providers" / "paddle" / "vision_output.json").exists())
        self.assertFalse((case / "providers" / "zcode").exists())

    def test_two_frames_succeed_with_distinct_case_trees(self):
        screenshots = []
        for index in (1, 2):
            path = Path(self.temporary.name) / f"frame{index}.png"
            path.write_bytes(f"frame-{index}".encode())
            screenshots.append(path)
        case_ids = iter(("OBS_TEST_frame_0001", "OBS_TEST_frame_0002"))

        def per_frame_runner(request: AgyRunnerRequest):
            payload = self.agy_payload(case_id=request.case_id, digest=request.source_sha256)
            return self.fixture_runner(payload)(request)

        bridge = AgyVisionBridge(
            test_data_root=self.root, case_id_factory=lambda: next(case_ids),
            agy_runner=per_frame_runner, paddle_runner=self.paddle,
        )
        first = bridge.request(screenshots[0])
        second = bridge.request(screenshots[1])
        self.assertEqual((first.status, second.status), (STATUS_SUCCESS, STATUS_SUCCESS))
        self.assertNotEqual(first.case_id, second.case_id)
        for result in (first, second):
            case = self.root / "ob003" / result.case_id
            self.assertTrue((case / "source_screenshot.png").is_file())
            self.assertTrue((case / "manifest.json").is_file())
            self.assertTrue((case / "providers" / "paddle" / "vision_output.json").is_file())
            self.assertTrue((case / "providers" / "agy" / SKILL / "vision_output.json").is_file())
            self.assertTrue((case / "fused_observation.json").is_file())

    def test_bridge_requires_per_observation_case_identity(self):
        bridge = AgyVisionBridge(
            test_data_root=self.root, agy_runner=self.agy, paddle_runner=self.paddle
        )
        self.assert_unknown(bridge.request(self.screenshot), bridge_module.REASON_CASE_ID_REQUIRED)
        self.assertEqual(self.paddle_calls, 0)

    def test_observe_exposes_only_fused_observation(self):
        bridge = AgyVisionBridge(
            test_data_root=self.root, case_id_factory=lambda: CASE_ID,
            agy_runner=self.agy, paddle_runner=self.paddle,
        )
        payload = bridge.observe(str(self.screenshot))
        self.assertEqual(payload, json.loads(Path(bridge.last_result.fused_artifact).read_text()))
        # v0.3: the fused artifact is self-describing -- provenance metadata is
        # expected, artifact-management plumbing still is not.
        metadata = payload["metadata"]
        self.assertEqual(metadata["provider"], "AGY")
        self.assertEqual(metadata["model"], MODEL)
        self.assertEqual(metadata["skill_version"], SKILL)
        self.assertEqual(metadata["screenshot_sha256"], self.digest)
        self.assertEqual(metadata["artifact_sha256"], fused_artifact_digest(payload))
        self.assertNotIn("agy_artifact", payload)
        self.assertNotIn("paddle_artifact", payload)

    def test_observe_raises_unknown_instead_of_returning_raw_sensor(self):
        bridge = AgyVisionBridge(
            test_data_root=self.root, case_id_factory=lambda: CASE_ID,
            agy_runner=self.fixture_runner("invalid"), paddle_runner=self.paddle,
        )
        with self.assertRaises(AgyVisionUnknown) as captured:
            bridge.observe(str(self.screenshot))
        self.assertEqual(captured.exception.result.status, STATUS_UNKNOWN)

    def test_observer_mode_consumes_successful_fused_output(self):
        recorder = RecorderStub()
        bridge = AgyVisionBridge(
            test_data_root=self.root, case_id_factory=lambda: CASE_ID,
            agy_runner=self.agy, paddle_runner=self.paddle,
        )
        record = ObserverMode(bridge, recorder).observe(str(self.screenshot))
        self.assertIs(record, recorder.record)
        self.assertEqual(VisionObservation.validate(record["vision_observation"]), [])
        self.assertNotIn("candidate_actions", record)

    def test_bridge_has_no_execution_or_native_vision_dependency(self):
        tree = ast.parse(Path(bridge_module.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(imported.isdisjoint({
            "executor", "action_boundary", "action_gate", "pyautogui", "pynput",
            "zcode_observation_provider", "zcode_observation_loop",
        }))

    def test_gate_rejects_naked_bool_dictionary(self):
        checks = {name: True for name in bridge_module.AGY_VISION_BRIDGE_GATE_CHECKS}
        self.assertEqual(evaluate_agy_vision_bridge_gate(checks)["status"], "FAIL")

    def test_gate_requires_digest_bound_evidence_for_every_invariant(self):
        evidence = [
            make_gate_evidence(
                check_id, status="PASS", evidence_source="pytest",
                test_identifier=f"test_agy_vision_bridge::{check_id}",
                observed={"passed": True, "check_id": check_id},
            )
            for check_id in bridge_module.AGY_VISION_BRIDGE_GATE_CHECKS
        ]
        result = evaluate_agy_vision_bridge_gate(evidence)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["evidence"]), len(bridge_module.AGY_VISION_BRIDGE_GATE_CHECKS))
        failed = list(evidence)
        failed[0] = make_gate_evidence(
            failed[0].check_id, status="FAIL", evidence_source="pytest",
            test_identifier="negative-check", observed={"passed": False},
        )
        self.assertEqual(evaluate_agy_vision_bridge_gate(failed)["status"], "FAIL")

    def test_gate_evidence_records_carry_type_and_timestamp(self):
        record = make_gate_evidence(
            "SCHEMA_FAIL_CLOSED", status="PASS", evidence_source="pytest",
            test_identifier="test_agy_vision_bridge::timestamped",
            observed={"passed": True},
        )
        self.assertEqual(record.evidence_type, "test_result")
        self.assertTrue(record.captured_at)
        stale = make_gate_evidence(
            "SCHEMA_FAIL_CLOSED", status="PASS", evidence_source="pytest",
            test_identifier="stale", observed={"passed": True},
            captured_at="2026-01-01T00:00:00+00:00",
        )
        self.assertEqual(stale.captured_at, "2026-01-01T00:00:00+00:00")
        untyped = make_gate_evidence(
            "ARTIFACT_HASH_BOUND", status="PASS", evidence_source="pytest",
            test_identifier="untyped", observed={"passed": True}, evidence_type="   ",
        )
        result = evaluate_agy_vision_bridge_gate([untyped])
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("evidence type" in item for item in result["invalid_evidence"]))

    def test_same_case_rerun_conflicts_and_manifests_stay_independent(self):
        screenshots = []
        for index in (1, 2):
            path = Path(self.temporary.name) / f"rerun-frame{index}.png"
            path.write_bytes(f"rerun-frame-{index}".encode())
            screenshots.append(path)

        def per_frame_runner(request: AgyRunnerRequest):
            payload = self.agy_payload(case_id=request.case_id, digest=request.source_sha256)
            return self.fixture_runner(payload)(request)

        bridge = AgyVisionBridge(
            test_data_root=self.root, agy_runner=per_frame_runner, paddle_runner=self.paddle,
        )
        first = bridge.request(screenshots[0], case_id="OBS_TEST_rerun_a")
        second = bridge.request(screenshots[1], case_id="OBS_TEST_rerun_b")
        self.assertEqual((first.status, second.status), (STATUS_SUCCESS, STATUS_SUCCESS))

        manifest_a = json.loads(
            (self.root / "ob003" / "OBS_TEST_rerun_a" / "manifest.json").read_text()
        )
        manifest_b = json.loads(
            (self.root / "ob003" / "OBS_TEST_rerun_b" / "manifest.json").read_text()
        )
        self.assertNotEqual(manifest_a["source"]["sha256"], manifest_b["source"]["sha256"])
        self.assertEqual(len(manifest_a["providers"]), 2)

        conflict = bridge.request(screenshots[0], case_id="OBS_TEST_rerun_a")
        self.assertEqual(conflict.status, STATUS_UNKNOWN)
        self.assertEqual(conflict.reason_code, bridge_module.REASON_OVERWRITE_CONFLICT)
        manifest_after = json.loads(
            (self.root / "ob003" / "OBS_TEST_rerun_a" / "manifest.json").read_text()
        )
        self.assertEqual(manifest_after, manifest_a)

    def test_live_config_invalid_stops_before_runner_call(self):
        def exploding(_request):
            raise AssertionError("runner must not be called for an invalid live config")

        config = AgyVisionConfig(runner_mode=bridge_module.RUNNER_MODE_LIVE, expected_model=None)
        result = self.request(agy_runner=exploding, config=config)
        self.assert_unknown(result, bridge_module.REASON_LIVE_MODEL_REQUIRED)
        self.assertEqual(self.agy_calls, 0)

    def test_timeout_persists_failure_provenance_without_canonical(self):
        def timed_out(_request):
            return AgyRunnerResult(
                exit_status=None, artifact_path=None,
                diagnostic="AGY CLI exceeded 1500s", timed_out=True,
            )

        case_id = f"{CASE_ID}_prov_timeout"
        result = self.request(agy_runner=timed_out, case_id=case_id)
        self.assert_unknown(result, bridge_module.REASON_AGY_TIMEOUT)
        record = json.loads(
            (self.root / "ob003" / case_id / "perception_failure.json").read_text()
        )
        self.assertEqual(record["reason_code"], "AGY_TIMEOUT")
        self.assertEqual(record["case_id"], case_id)
        self.assertEqual(record["screenshot_sha256"], self.digest)
        self.assertTrue((self.root / "ob003" / case_id / "providers" / "paddle" / "vision_output.json").exists())

    def test_capture_evidence_survives_agy_timeout(self):
        case_id = f"{CASE_ID}_durable_timeout"
        result = self.request(
            agy_runner=lambda _request: AgyRunnerResult(
                exit_status=None, artifact_path=None, timed_out=True, diagnostic="timeout"
            ), case_id=case_id,
        )
        self.assertEqual(result.reason_code, bridge_module.REASON_AGY_TIMEOUT)
        case = self.root / "ob003" / case_id
        self.assertTrue((case / "source_screenshot.png").is_file())
        self.assertTrue((case / "providers" / "paddle" / "vision_output.json").is_file())
        status = json.loads((case / "case_status.json").read_text())
        self.assertEqual(status["terminal_state"], "UNKNOWN")

    def test_non_default_suite_routes_all_durable_artifacts(self):
        suite = "ob999"
        case_id = f"{CASE_ID}_custom_suite"
        result = self.request(
            case_id=case_id, suite=suite,
            agy_runner=self.fixture_runner(lambda request: self.agy_payload(case_id=request.case_id)),
        )
        self.assertEqual(result.status, STATUS_SUCCESS)
        self.assertTrue((self.root / suite / case_id / "case_status.json").is_file())
        self.assertFalse((self.root / "ob003" / case_id).exists())

    def test_paddle_process_failure_record_keeps_sensor_provenance(self):
        def broken_paddle(_path):
            return {"source_image": "screen.png", "method": "PaddleOCR",
                    "text_regions": [], "error": "PaddleOCR unavailable"}

        case_id = f"{CASE_ID}_prov_paddle"
        result = self.request(paddle_runner=broken_paddle, case_id=case_id)
        self.assert_unknown(result, bridge_module.REASON_PADDLE_PROCESS_FAILURE)
        record = json.loads(
            (self.root / "ob003" / case_id / "perception_failure.json").read_text()
        )
        self.assertEqual(record["reason_code"], "PADDLE_PROCESS_FAILURE")

    def test_success_writes_no_failure_record(self):
        result = self.request()
        self.assertEqual(result.status, STATUS_SUCCESS)
        self.assertFalse(
            (self.root / "ob003" / CASE_ID / "perception_failure.json").exists()
        )

    def test_conversation_id_survives_into_request_result(self):
        result = self.request()
        self.assertEqual(result.status, STATUS_SUCCESS)
        self.assertEqual(result.conversation_id, "fake-conversation")

        def timed_out(_request):
            return AgyRunnerResult(
                exit_status=None, artifact_path=None,
                conversation_id="stalled-conversation",
                diagnostic="AGY CLI exceeded timeout", timed_out=True,
            )

        timeout_result = self.request(agy_runner=timed_out, case_id=f"{CASE_ID}_timeout")
        self.assertEqual(timeout_result.reason_code, bridge_module.REASON_AGY_TIMEOUT)
        self.assertEqual(timeout_result.conversation_id, "stalled-conversation")


if __name__ == "__main__":
    unittest.main()
