"""CROSS_AGENT_INTEGRATION_GATE: digest-bound evidence for the converged
single runner contract across bridge x CLI runner x exploration driver.

Every check below is computed from a concrete offline two-frame integration
run (real bridge, structured fake runner, real fusion + harness persistence)
or from static source invariants. Evidence records embed the observed data so
the gate can never pass on naked caller booleans.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest

from vision_agent.agy_vision_bridge import (
    AgyRunnerRequest,
    AgyRunnerResult,
    AgyVisionConfig,
    CROSS_AGENT_INTEGRATION_GATE_CHECKS,
    REASON_AGY_COMMAND_FAILURE,
    REASON_AGY_TIMEOUT,
    REASON_RUNNER_PROTOCOL_FAILURE,
    STATUS_SUCCESS,
    STATUS_UNKNOWN,
    evaluate_cross_agent_integration_gate,
    make_gate_evidence,
    vision_request,
)
from vision_observation_schema import VisionObservation


REPO_ROOT = Path(__file__).resolve().parent
STR_RUNNER_DEF = re.compile(
    r"def \w+\(\s*_?[a-z_]*screenshot_path:\s*str\s*\)\s*->\s*(?:str|bytes)"
)


class CrossAgentIntegrationGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_root = self.root / "test_data"
        self.screenshots: list[Path] = []
        self.digests: list[str] = []
        for index in range(2):
            screenshot = self.root / f"frame{index}.png"
            try:
                from PIL import Image

                Image.new("RGB", (1280, 720), (200 + index, 220, 240)).save(screenshot)
            except ImportError:  # pragma: no cover - PIL is a repo dependency
                screenshot.write_bytes(f"\x89PNG\r\n\x1a\nframe{index}".encode())
            self.screenshots.append(screenshot)
            self.digests.append(hashlib.sha256(screenshot.read_bytes()).hexdigest())
        self.agy_calls = 0
        self.paddle_calls = 0
        self.structured_requests: list[AgyRunnerRequest] = []
        self.structured_results: list[AgyRunnerResult] = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    # -- offline structured runner (real contract, no looser shape) -------
    def paddle(self, _screenshot_path: str) -> dict:
        self.paddle_calls += 1
        return {
            "source_image": "screen.png",
            "method": "PaddleOCR",
            "text_regions": [{
                "id": "paddle_001", "text": "次へ",
                "bbox": [10, 20, 40, 20], "confidence": 0.99,
            }],
        }

    def structured_agy(self, request: AgyRunnerRequest) -> AgyRunnerResult:
        self.agy_calls += 1
        self.structured_requests.append(request)
        payload = {
            "metadata": {
                "provider": "AGY",
                "model": "gemini-3.8-flash-medium",
                "skill_version": "gemini_vision_v1",
                "case_id": request.case_id,
                "source_image": "source_screenshot.png",
                "screenshot_sha256": request.source_sha256,
                "created_at": "2026-09-05T00:00:00",
            },
            "observation_id": request.case_id,
            "capture": {
                "timestamp": "2026-09-05T00:00:00",
                "frame_id": request.case_id,
                "screenshot_digest": f"sha256:{request.source_sha256}",
            },
            "viewport": {"width": 1280, "height": 720},
            "text_regions": [],
            "interaction_candidates": [{
                "id": "agy_e1", "bbox": [5, 15, 60, 30],
                "appearance": {"shape": "rounded_rect"},
                "linked_text_ids": [], "interaction_confidence": 0.99,
            }],
            "numeric_regions": [], "overlay_regions": [], "uncertainties": [],
        }
        output = Path(request.output_artifact_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = AgyRunnerResult(
            exit_status=0,
            artifact_path=str(output),
            job_id=f"job-{request.case_id}",
            conversation_id=f"conversation-{request.case_id}",
            diagnostic="offline structured runner",
        )
        self.structured_results.append(result)
        return result

    def run_two_frame_integration(self) -> list:
        results = []
        for index, screenshot in enumerate(self.screenshots, start=1):
            results.append(vision_request(
                screenshot,
                f"OBS_CROSS_AGENT_f{index:02d}",
                test_data_root=self.data_root,
                agy_runner=self.structured_agy,
                paddle_runner=self.paddle,
                config=AgyVisionConfig(),
            ))
        return results

    # -- per-check evidence builders --------------------------------------
    def runner_protocol_observation(self) -> dict:
        findings = []
        for relative in (
            "vision_agent/agy_vision_bridge.py",
            "vision_agent/agy_cli_runner.py",
            "explore_home.py",
            "test_explore_home.py",
            "test_agy_vision_bridge.py",
        ):
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            findings.extend(STR_RUNNER_DEF.findall(source))
        return {
            "str_runner_definitions": findings,
            "runner_calls": self.agy_calls,
            "request_type": type(self.structured_requests[0]).__name__,
            "result_type": type(self.structured_results[0]).__name__,
        }

    def artifact_routing_observation(self, results: list) -> dict:
        from vision_agent.artifact_harness import VisionArtifactHarness

        harness = VisionArtifactHarness(self.data_root)
        checked = []
        for result in results:
            case_dir = self.data_root / "ob003" / result.case_id
            manifest = json.loads((case_dir / "manifest.json").read_text())
            for entry in manifest["providers"]:
                artifact = case_dir / entry["artifact"]
                checked.append({
                    "case_id": result.case_id,
                    "artifact": entry["artifact"],
                    "routed_correctly": str(
                        harness.output_path(
                            result.case_id, entry["provider"], entry["skill_version"]
                        )
                    ).endswith(entry["artifact"]),
                    "sha_matches": entry["artifact_sha256"]
                    == hashlib.sha256(artifact.read_bytes()).hexdigest(),
                })
        return {"artifacts": checked}

    def frame_identity_observation(self, results: list) -> dict:
        first, second = results
        manifests = [
            json.loads(
                (self.data_root / "ob003" / r.case_id / "manifest.json").read_text()
            )
            for r in results
        ]
        return {
            "case_ids": [r.case_id for r in results],
            "case_ids_distinct": first.case_id != second.case_id,
            "screenshot_shas": [r.screenshot_sha256 for r in results],
            "screenshot_shas_distinct": (
                first.screenshot_sha256 != second.screenshot_sha256
            ),
            "manifests_independent": manifests[0] != manifests[1],
        }

    def fusion_input_observation(self, results: list) -> dict:
        fused_reports = []
        for result in results:
            payload = json.loads(Path(result.fused_artifact).read_text())
            sources = {
                item["source"]
                for key in ("text_regions", "interaction_candidates")
                for item in payload.get(key, [])
            }
            fused_reports.append({
                "case_id": result.case_id,
                "schema_errors": VisionObservation.validate(payload),
                "sources": sorted(sources),
            })
        return {"fused": fused_reports}

    def exception_mapping_observation(self) -> dict:
        cases = {
            "timed_out_result": (
                lambda _r: AgyRunnerResult(
                    exit_status=None, artifact_path=None,
                    diagnostic="stalled", timed_out=True,
                ),
                "AGY_TIMEOUT",
            ),
            "command_failure_result": (
                lambda _r: AgyRunnerResult(
                    exit_status=3, artifact_path=None, diagnostic="boom"
                ),
                "AGY_COMMAND_FAILURE",
            ),
            "protocol_failure_result": (
                lambda _r: "legacy str payload",
                "RUNNER_PROTOCOL_FAILURE",
            ),
        }
        mapping = {}
        for name, (runner, expected_reason) in cases.items():
            result = vision_request(
                self.screenshots[0],
                f"OBS_CROSS_AGENT_{name}",
                test_data_root=self.data_root,
                agy_runner=runner,
                paddle_runner=self.paddle,
                config=AgyVisionConfig(),
            )
            mapping[name] = {
                "observed_reason": result.reason_code,
                "expected_reason": expected_reason,
                "matched": (
                    result.status == STATUS_UNKNOWN
                    and result.reason_code == expected_reason
                ),
            }
        return mapping

    def offline_isolation_observation(self) -> dict:
        findings = {}
        explore_tree = ast.parse(
            (REPO_ROOT / "explore_home.py").read_text(encoding="utf-8")
        )
        runner_import_nodes = [
            node
            for node in ast.walk(explore_tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "vision_agent.agy_cli_runner"
        ]
        # The real runner factory may only be imported lazily inside a
        # function body, never at module level.
        module_level = [
            node
            for node in explore_tree.body
            if isinstance(node, ast.ImportFrom)
            and node.module == "vision_agent.agy_cli_runner"
        ]
        findings["runner_import_is_lazy_inside_function"] = (
            bool(runner_import_nodes) and not module_level
        )
        findings["offline_suite_patches_real_runner"] = (
            "vision_agent.agy_cli_runner.build_agy_cli_runner"
            in (REPO_ROOT / "test_explore_home.py").read_text(encoding="utf-8")
        )
        subprocess_files = []
        for relative in (
            "vision_agent/agy_vision_bridge.py",
            "explore_home.py",
            "exploration/home_projection.py",
            "observer/observer_mode.py",
            "observer/trajectory_recorder.py",
            "observer/human_feedback.py",
        ):
            if "subprocess" in (REPO_ROOT / relative).read_text(encoding="utf-8"):
                subprocess_files.append(relative)
        findings["subprocess_outside_cli_runner"] = subprocess_files
        return findings

    def double_invocation_observation(self, frames: int, counts: dict) -> dict:
        return {
            "frames": frames,
            "agy_runner_calls": counts["agy"],
            "paddle_runner_calls": counts["paddle"],
            "agy_calls_match_frames": counts["agy"] == frames,
            "paddle_calls_match_frames": counts["paddle"] == frames,
        }

    # -- the gate ---------------------------------------------------------
    def test_cross_agent_integration_gate_passes_on_real_offline_evidence(self):
        test_id = "test_cross_agent_integration_gate_passes_on_real_offline_evidence"
        results = self.run_two_frame_integration()
        self.assertEqual([r.status for r in results], [STATUS_SUCCESS, STATUS_SUCCESS])
        # Snapshot immediately: later negative-path probes add extra calls and
        # must not contaminate the no-double-invocation evidence.
        two_frame_counts = {"agy": self.agy_calls, "paddle": self.paddle_calls}

        # ---- 1. observe the real world ------------------------------------
        observations = {
            "RUNNER_PROTOCOL_COMPATIBLE": self.runner_protocol_observation(),
            "ARTIFACT_ROUTING_COMPATIBLE": self.artifact_routing_observation(results),
            "FRAME_IDENTITY_COMPATIBLE": self.frame_identity_observation(results),
            "FUSION_INPUT_COMPATIBLE": self.fusion_input_observation(results),
            "EXCEPTION_MAPPING_COMPATIBLE": self.exception_mapping_observation(),
            "OFFLINE_TEST_ISOLATED": self.offline_isolation_observation(),
            "NO_DOUBLE_PROVIDER_INVOCATION": self.double_invocation_observation(
                frames=2, counts=two_frame_counts
            ),
        }

        # ---- 2. prove every invariant BEFORE any evidence is built --------
        self.assertEqual(observations["RUNNER_PROTOCOL_COMPATIBLE"]["str_runner_definitions"], [])
        routing = observations["ARTIFACT_ROUTING_COMPATIBLE"]["artifacts"]
        self.assertTrue(routing)
        self.assertTrue(all(a["routed_correctly"] and a["sha_matches"] for a in routing))
        identity = observations["FRAME_IDENTITY_COMPATIBLE"]
        self.assertTrue(identity["case_ids_distinct"])
        self.assertTrue(identity["screenshot_shas_distinct"])
        self.assertTrue(identity["manifests_independent"])
        for report in observations["FUSION_INPUT_COMPATIBLE"]["fused"]:
            self.assertEqual(report["schema_errors"], [])
            self.assertEqual(report["sources"], ["agy", "paddle"])
        mapping = observations["EXCEPTION_MAPPING_COMPATIBLE"]
        self.assertTrue(mapping and all(v["matched"] for v in mapping.values()))
        isolation = observations["OFFLINE_TEST_ISOLATED"]
        self.assertTrue(isolation["runner_import_is_lazy_inside_function"])
        self.assertTrue(isolation["offline_suite_patches_real_runner"])
        self.assertEqual(isolation["subprocess_outside_cli_runner"], [])
        counts = observations["NO_DOUBLE_PROVIDER_INVOCATION"]
        self.assertTrue(counts["agy_calls_match_frames"])
        self.assertTrue(counts["paddle_calls_match_frames"])

        # ---- 3. only now seal the proven facts into gate evidence ---------
        evidence = [
            make_gate_evidence(
                check_id, status="PASS",
                evidence_source="cross_agent_integration_test",
                test_identifier=test_id,
                observed=observed,
            )
            for check_id, observed in observations.items()
        ]

        # Hard assertions on the observed world first; the gate must reflect
        # reality, not the other way around.
        self.assertEqual(self.runner_protocol_observation()["str_runner_definitions"], [])
        routing = self.artifact_routing_observation(results)
        self.assertTrue(all(a["routed_correctly"] and a["sha_matches"] for a in routing["artifacts"]))
        identity = self.frame_identity_observation(results)
        self.assertTrue(identity["case_ids_distinct"])
        self.assertTrue(identity["screenshot_shas_distinct"])
        self.assertTrue(identity["manifests_independent"])
        for report in self.fusion_input_observation(results)["fused"]:
            self.assertEqual(report["schema_errors"], [])
            self.assertEqual(report["sources"], ["agy", "paddle"])
        mapping = self.exception_mapping_observation()
        self.assertTrue(all(v["matched"] for v in mapping.values()))
        isolation = self.offline_isolation_observation()
        self.assertTrue(isolation["runner_import_is_lazy_inside_function"])
        self.assertTrue(isolation["offline_suite_patches_real_runner"])
        self.assertEqual(isolation["subprocess_outside_cli_runner"], [])
        counts = two_frame_counts
        self.assertTrue(counts["agy_calls_match_frames"] if "agy_calls_match_frames" in counts else counts["agy"] == 2)
        self.assertEqual(counts["paddle"], 2)

        gate = evaluate_cross_agent_integration_gate(evidence)
        self.assertEqual(gate["gate"], "CROSS_AGENT_INTEGRATION_GATE")
        self.assertEqual(gate["status"], "PASS")
        self.assertEqual(sorted(gate["checks"]), sorted(CROSS_AGENT_INTEGRATION_GATE_CHECKS))

    def test_cross_agent_gate_rejects_bool_map_and_incomplete_evidence(self):
        checks = {name: True for name in CROSS_AGENT_INTEGRATION_GATE_CHECKS}
        self.assertEqual(evaluate_cross_agent_integration_gate(checks)["status"], "FAIL")

        results = self.run_two_frame_integration()
        partial = [
            make_gate_evidence(
                "FRAME_IDENTITY_COMPATIBLE", status="PASS",
                evidence_source="cross_agent_integration_test",
                test_identifier="partial",
                observed=self.frame_identity_observation(results),
            )
        ]
        gate = evaluate_cross_agent_integration_gate(partial)
        self.assertEqual(gate["status"], "FAIL")
        self.assertIn("RUNNER_PROTOCOL_COMPATIBLE", gate["failed_checks"])

        unknown_check = make_gate_evidence(
            "NOT_A_REAL_CHECK", status="PASS",
            evidence_source="cross_agent_integration_test",
            test_identifier="unknown", observed={},
        )
        gate = evaluate_cross_agent_integration_gate([unknown_check])
        self.assertEqual(gate["status"], "FAIL")
        self.assertTrue(any("unknown check_id" in item for item in gate["invalid_evidence"]))


if __name__ == "__main__":
    unittest.main()
