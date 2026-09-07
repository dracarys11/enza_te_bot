"""Fail-closed offline bridge from screenshots to fused visual evidence.

The bridge orchestrates perception sensors only. It has no state, policy,
decision, authorization, or input-injection responsibility.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable, Iterable, Mapping, Protocol

from perception_fusion import fused_artifact_digest, fuse_perception
from vision_observation_schema import VisionObservation

from .artifact_harness import VisionArtifactHarness, VisionArtifactRoutingError
from .base import VisionAgent


REPO_ROOT = Path(__file__).resolve().parents[1]


STATUS_SUCCESS = "SUCCESS"
STATUS_UNKNOWN = "UNKNOWN"

REASON_OK = "OK"
REASON_AGY_COMMAND_UNCONFIGURED = "AGY_COMMAND_UNCONFIGURED"
REASON_AGY_TIMEOUT = "AGY_TIMEOUT"
REASON_AGY_COMMAND_FAILURE = "AGY_COMMAND_FAILURE"
REASON_INVALID_JSON = "INVALID_JSON"
REASON_SCHEMA_FAILURE = "SCHEMA_FAILURE"
REASON_FORBIDDEN_SEMANTIC_FIELD = "FORBIDDEN_SEMANTIC_FIELD"
REASON_SCREENSHOT_HASH_MISMATCH = "SCREENSHOT_HASH_MISMATCH"
REASON_PROVENANCE_MISMATCH = "PROVENANCE_MISMATCH"
REASON_ARTIFACT_STALE = "ARTIFACT_STALE"
REASON_OVERWRITE_CONFLICT = "OVERWRITE_CONFLICT"
REASON_PADDLE_PROCESS_FAILURE = "PADDLE_PROCESS_FAILURE"
REASON_FUSION_FAILURE = "FUSION_FAILURE"
REASON_SOURCE_IMAGE_MISSING = "SOURCE_IMAGE_MISSING"
REASON_SOURCE_PREPARATION_FAILURE = "SOURCE_PREPARATION_FAILURE"
REASON_CASE_ID_REQUIRED = "CASE_ID_REQUIRED"
REASON_LIVE_MODEL_REQUIRED = "LIVE_MODEL_REQUIRED"
REASON_RUNNER_PROTOCOL_FAILURE = "RUNNER_PROTOCOL_FAILURE"
REASON_UNSUPPORTED_SKILL = "UNSUPPORTED_SKILL"
REASON_UNEXPECTED_ARTIFACT_WRITE = "UNEXPECTED_ARTIFACT_WRITE"
REASON_EVIDENCE_PERSISTENCE_FAILURE = "EVIDENCE_PERSISTENCE_FAILURE"

UNKNOWN_REASON_CODES = frozenset(
    {
        REASON_AGY_COMMAND_UNCONFIGURED,
        REASON_AGY_TIMEOUT,
        REASON_AGY_COMMAND_FAILURE,
        REASON_INVALID_JSON,
        REASON_SCHEMA_FAILURE,
        REASON_FORBIDDEN_SEMANTIC_FIELD,
        REASON_SCREENSHOT_HASH_MISMATCH,
        REASON_PROVENANCE_MISMATCH,
        REASON_ARTIFACT_STALE,
        REASON_OVERWRITE_CONFLICT,
        REASON_PADDLE_PROCESS_FAILURE,
        REASON_FUSION_FAILURE,
        REASON_SOURCE_IMAGE_MISSING,
        REASON_SOURCE_PREPARATION_FAILURE,
        REASON_CASE_ID_REQUIRED,
        REASON_LIVE_MODEL_REQUIRED,
        REASON_RUNNER_PROTOCOL_FAILURE,
        REASON_UNSUPPORTED_SKILL,
        REASON_UNEXPECTED_ARTIFACT_WRITE,
        REASON_EVIDENCE_PERSISTENCE_FAILURE,
    }
)

AGY_VISION_BRIDGE_GATE = "AGY_VISION_BRIDGE_GATE"
AGY_VISION_BRIDGE_GATE_CHECKS = frozenset(
    {
        "MULTIFRAME_ISOLATION",
        "FUSION_PROVIDER_PROVENANCE",
        "NO_NATIVE_FALLBACK",
        "NO_PADDLE_ONLY_FALLBACK",
        "LIVE_MODEL_PINNED",
        "ARTIFACT_HASH_BOUND",
        "SCHEMA_FAIL_CLOSED",
        "NO_EXECUTION_DEPENDENCY",
        "REAL_AGY_RUNNER_CONTRACT",
        "RUNNER_TIMEOUT_FAIL_CLOSED",
        "RUNNER_CONVERSATION_ID_PRESERVED",
        "RUNNER_ARTIFACT_STAGING_ONLY",
        "NO_PROVIDER_DOUBLE_CALL",
    }
)

CROSS_AGENT_INTEGRATION_GATE = "CROSS_AGENT_INTEGRATION_GATE"
CROSS_AGENT_INTEGRATION_GATE_CHECKS = frozenset(
    {
        "RUNNER_PROTOCOL_COMPATIBLE",
        "ARTIFACT_ROUTING_COMPATIBLE",
        "FRAME_IDENTITY_COMPATIBLE",
        "FUSION_INPUT_COMPATIBLE",
        "EXCEPTION_MAPPING_COMPATIBLE",
        "OFFLINE_TEST_ISOLATED",
        "NO_DOUBLE_PROVIDER_INVOCATION",
    }
)

RUNNER_MODE_OFFLINE_FAKE = "OFFLINE_FAKE"
RUNNER_MODE_LIVE = "LIVE"
DEFAULT_APPROVED_LIVE_MODEL = "gemini-3.8-flash-medium"


@dataclass(frozen=True)
class AgyRunnerRequest:
    """Stable request boundary for a future real AGY adapter."""

    screenshot_path: str
    source_sha256: str
    case_id: str
    skill_path: str
    output_artifact_path: str
    timeout_seconds: float


@dataclass(frozen=True)
class AgyRunnerResult:
    """Result boundary; the bridge, not the runner, validates the artifact."""

    exit_status: int | None
    artifact_path: str | None
    job_id: str | None = None
    conversation_id: str | None = None
    stderr: str = ""
    diagnostic: str = ""
    timed_out: bool = False


class AgyRunner(Protocol):
    def __call__(self, request: AgyRunnerRequest) -> AgyRunnerResult: ...


PaddleRunner = Callable[[str], Mapping[str, Any]]


@dataclass(frozen=True)
class AgyVisionConfig:
    """Bridge configuration; the real AGY command is intentionally unknown."""

    provider: str = "AGY"
    expected_model: str | None = None
    skill_version: str = "gemini_vision_v1"
    agy_command: tuple[str, ...] | None = None
    paddle_model: str = "PP-OCRv6_medium_det+PP-OCRv6_medium_rec"
    runner_mode: str = RUNNER_MODE_OFFLINE_FAKE
    approved_live_model: str = DEFAULT_APPROVED_LIVE_MODEL
    timeout_seconds: float = 120.0


@dataclass(frozen=True)
class VisionRequestResult:
    status: str
    reason_code: str
    case_id: str
    screenshot_sha256: str
    fused_artifact: str | None
    agy_artifact: str | None
    paddle_artifact: str | None
    provider: str
    model: str | None
    skill_version: str
    detail: str
    conversation_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class AgyVisionUnknown(RuntimeError):
    """Raised by ``observe`` when perception fails closed."""

    def __init__(self, result: VisionRequestResult):
        self.result = result
        super().__init__(f"{result.reason_code}: {result.detail}")


@dataclass(frozen=True)
class GateEvidence:
    check_id: str
    status: str
    evidence_type: str
    evidence_source: str
    evidence_digest: str
    test_identifier: str
    captured_at: str


def make_gate_evidence(
    check_id: str,
    *,
    status: str,
    evidence_source: str,
    test_identifier: str,
    observed: Mapping[str, Any],
    evidence_type: str = "test_result",
    captured_at: str | None = None,
) -> GateEvidence:
    """Create digest-bound evidence from a concrete check result.

    ``captured_at`` defaults to the current UTC time so every record is
    timestamped; naked booleans are never accepted as gate evidence.
    """
    encoded = json.dumps(dict(observed), sort_keys=True, separators=(",", ":"))
    return GateEvidence(
        check_id=check_id,
        status=status,
        evidence_type=evidence_type,
        evidence_source=evidence_source,
        evidence_digest=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        test_identifier=test_identifier,
        captured_at=captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


def _evaluate_gate_records(
    evidence: Iterable[GateEvidence], checks: frozenset[str], gate: str
) -> dict[str, Any]:
    """Shared digest-bound evaluation; naked booleans can never pass."""
    if isinstance(evidence, Mapping):
        return {
            "gate": gate,
            "status": "FAIL",
            "checks": {},
            "failed_checks": sorted(checks),
            "invalid_evidence": ["gate requires GateEvidence records, not a bool mapping"],
        }
    records: dict[str, GateEvidence] = {}
    invalid: list[str] = []
    for item in evidence:
        if not isinstance(item, GateEvidence):
            invalid.append(f"unsupported evidence record: {type(item).__name__}")
            continue
        if item.check_id in records:
            invalid.append(f"duplicate check_id: {item.check_id}")
            continue
        if item.check_id not in checks:
            invalid.append(f"unknown check_id: {item.check_id}")
            continue
        if not item.evidence_source or not item.test_identifier:
            invalid.append(f"missing evidence source/test identifier: {item.check_id}")
            continue
        if not item.evidence_type.strip():
            invalid.append(f"missing evidence type: {item.check_id}")
            continue
        if not item.captured_at.strip():
            invalid.append(f"missing captured_at timestamp: {item.check_id}")
            continue
        if len(item.evidence_digest) != 64 or any(c not in "0123456789abcdef" for c in item.evidence_digest):
            invalid.append(f"invalid evidence digest: {item.check_id}")
            continue
        records[item.check_id] = item
    normalized = {
        name: records.get(name).status == "PASS" if name in records else False
        for name in checks
    }
    failed = sorted(name for name, passed in normalized.items() if not passed)
    return {
        "gate": gate,
        "status": "PASS" if not failed and not invalid else "FAIL",
        "checks": normalized,
        "failed_checks": failed,
        "evidence": [asdict(records[name]) for name in sorted(records)],
        "invalid_evidence": invalid,
    }


def evaluate_agy_vision_bridge_gate(evidence: Iterable[GateEvidence]) -> dict[str, Any]:
    """Evaluate digest-bound check evidence; naked booleans can never pass."""
    return _evaluate_gate_records(evidence, AGY_VISION_BRIDGE_GATE_CHECKS, AGY_VISION_BRIDGE_GATE)


def evaluate_cross_agent_integration_gate(evidence: Iterable[GateEvidence]) -> dict[str, Any]:
    """Evaluate cross-agent integration evidence (bridge x runner x driver)."""
    return _evaluate_gate_records(
        evidence, CROSS_AGENT_INTEGRATION_GATE_CHECKS, CROSS_AGENT_INTEGRATION_GATE
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_boundary_snapshot(repo_root: Path, allowed: Iterable[Path]) -> dict[str, str]:
    """Return a digest snapshot of repo files outside explicit write roots."""
    root = repo_root.resolve()
    allowed_roots = [path.resolve() for path in allowed]
    ignored_dirs = {".git", ".venv", "__pycache__", "node_modules"}
    snapshot: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        relative_dir = current.relative_to(root)
        dirnames[:] = [name for name in dirnames if name not in ignored_dirs]
        if relative_dir.parts and relative_dir.parts[0] == "logs":
            if len(relative_dir.parts) <= 1:
                for name in list(dirnames):
                    child = current / name
                    resolved_child = child.resolve()
                    if any(resolved_child == allowed_path or resolved_child in allowed_path.parents
                           for allowed_path in allowed_roots):
                        # The allowlisted case directory itself is skipped, but
                        # sibling AGY log directories remain observable.
                        for nested in child.iterdir():
                            nested_resolved = nested.resolve()
                            if any(nested_resolved == allowed_path or nested_resolved in allowed_path.parents
                                   for allowed_path in allowed_roots):
                                continue
                            try:
                                snapshot[str(nested.relative_to(root)) + "/.dir_mtime"] = str(nested.stat().st_mtime_ns)
                            except OSError:
                                snapshot[str(nested.relative_to(root)) + "/.dir_mtime"] = "unreadable"
                        continue
                    try:
                        snapshot[str(child.relative_to(root)) + "/.dir_mtime"] = str(child.stat().st_mtime_ns)
                    except OSError:
                        snapshot[str(child.relative_to(root)) + "/.dir_mtime"] = "unreadable"
            dirnames[:] = []
            continue
        for name in filenames:
            path = current / name
            relative = path.relative_to(root)
            parts = relative.parts
            if any(part in ignored_dirs for part in parts):
                continue
            resolved = path.resolve() if path.is_symlink() else path
            if any(resolved == allowed_path or allowed_path in resolved.parents
                   for allowed_path in allowed_roots):
                continue
            rel = str(relative)
            try:
                if path.is_symlink():
                    snapshot[rel] = "symlink:" + str(path.readlink())
                elif path.is_file():
                    snapshot[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                snapshot[rel] = f"unreadable:{type(error).__name__}:{error}"
    return snapshot


def _write_boundary_diff(before: Mapping[str, str], after: Mapping[str, str]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for path in sorted(set(before) | set(after)):
        if path not in before:
            changes.append({"path": path, "operation": "create"})
        elif path not in after:
            changes.append({"path": path, "operation": "delete"})
        elif before[path] != after[path]:
            changes.append({"path": path, "operation": "modify"})
    return changes


def _default_paddle_runner(screenshot_path: str) -> Mapping[str, Any]:
    from paddleocr_baseline import run

    with tempfile.TemporaryDirectory() as directory:
        return run(screenshot_path, Path(directory) / "paddle_raw.json")


def _skill_path(skill_version: str) -> Path | None:
    paths = {
        "gemini_vision_v1": Path("skills/gemini_vision/SKILL.md"),
        "gemini_vision_v1_1": Path("skills/gemini_vision_v1_1/SKILL.md"),
        "gemini_vision_v2": Path("skills/gemini_vision_v2/SKILL.md"),
    }
    relative = paths.get(skill_version)
    return Path(__file__).resolve().parents[1] / relative if relative else None


def _live_model_policy_error(settings: AgyVisionConfig) -> str | None:
    if settings.runner_mode == RUNNER_MODE_OFFLINE_FAKE:
        return None
    if settings.runner_mode != RUNNER_MODE_LIVE:
        return f"unsupported runner_mode: {settings.runner_mode}"
    if not settings.expected_model:
        return "live-like mode requires a non-empty expected_model"
    if settings.expected_model != settings.approved_live_model:
        return (
            "live-like expected_model is not the explicitly approved pinned model: "
            f"{settings.expected_model}"
        )
    return None


def _decode_agy_payload(path: Path) -> dict[str, Any]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("AGY JSON root must be an object")
    return decoded


def _publish_fused(path: Path, payload: Mapping[str, Any]) -> None:
    """Publish the fused artifact with a self-hash seal.

    metadata.artifact_sha256 is the recomputable digest of the canonical
    serialization of the payload minus that key, so the file is
    self-describing and tamper-checkable without external state.
    """
    sealed = dict(payload)
    metadata = dict(sealed.get("metadata") or {})
    metadata["artifact_sha256"] = fused_artifact_digest(sealed)
    sealed["metadata"] = metadata
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(sealed, ensure_ascii=False, indent=2) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(encoded)


def persist_perception_failure(
    test_data_root: str | Path,
    case_id: str,
    *,
    reason_code: str,
    detail: str,
    screenshot_sha256: str,
    provider: str,
    model: str | None,
    skill_version: str,
    suite: str = "ob003",
    paddle_region_count: int | None = None,
) -> None:
    """Persist failure provenance next to (never inside) the canonical set.

    Gives every UNKNOWN a durable, inspectable cause at the exact case it
    belongs to. Best-effort by design: a bookkeeping error here must never
    mask the original failure reason. OVERWRITE_CONFLICT is skipped -- the
    case directory already holds published artifacts and must stay clean.
    """
    if reason_code == REASON_OVERWRITE_CONFLICT:
        return
    try:
        harness = VisionArtifactHarness(Path(test_data_root), suite=suite)
        case_directory = harness.case_directory(case_id)
        case_directory.mkdir(parents=True, exist_ok=True)
        record = {
            "reason_code": reason_code,
            "detail": detail,
            "case_id": case_id,
            "provider": provider,
            "model": model,
            "skill_version": skill_version,
            "screenshot_sha256": screenshot_sha256,
            "paddle_region_count": paddle_region_count,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        (case_directory / "perception_failure.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as error:
        raise RuntimeError(f"evidence persistence failed: {error}") from error


def _write_case_status(case_directory: Path, *, case_id: str, terminal_state: str,
                       stage: str, source_sha256: str, started_at: str,
                       reason_code: str = "", finished_at: str = "") -> None:
    payload = {
        "case_id": case_id, "terminal_state": terminal_state, "stage": stage,
        "reason_code": reason_code, "source_sha256": source_sha256,
        "started_at": started_at, "finished_at": finished_at,
    }
    case_directory.mkdir(parents=True, exist_ok=True)
    (case_directory / "case_status.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _quarantine_agy(path: Path, case_directory: Path, *, reason_code: str,
                    exit_status: int | None, conversation_id: str | None,
                    job_id: str | None) -> None:
    if not path.is_file():
        return
    quarantine = case_directory / "rejected"
    quarantine.mkdir(parents=True, exist_ok=True)
    target = quarantine / "agy_raw_output.json"
    shutil.copyfile(path, target)
    record = {
        "reason_code": reason_code,
        "artifact_sha256": _sha256(target),
        "runner_exit_status": exit_status,
        "conversation_id": conversation_id,
        "job_id": job_id,
    }
    (quarantine / "agy_rejection.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _quarantine_agy_bytes(raw: bytes, case_directory: Path, *, reason_code: str,
                          exit_status: int | None, conversation_id: str | None,
                          job_id: str | None) -> None:
    quarantine = case_directory / "rejected"
    quarantine.mkdir(parents=True, exist_ok=True)
    target = quarantine / "agy_raw_output.json"
    target.write_bytes(raw)
    (quarantine / "agy_rejection.json").write_text(json.dumps({
        "reason_code": reason_code, "artifact_sha256": _sha256(target),
        "runner_exit_status": exit_status, "conversation_id": conversation_id,
        "job_id": job_id,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def vision_request(
    screenshot_path: str | Path,
    case_id: str,
    *,
    test_data_root: str | Path,
    suite: str = "ob003",
    agy_runner: AgyRunner | None = None,
    paddle_runner: PaddleRunner | None = None,
    config: AgyVisionConfig | None = None,
) -> VisionRequestResult:
    """Run the bounded perception pipeline and return a fail-closed result."""
    settings = config or AgyVisionConfig()
    screenshot = Path(screenshot_path)
    model: str | None = settings.expected_model
    screenshot_sha256 = _sha256(screenshot) if screenshot.is_file() else ""
    runner_conversation_id: str | None = None
    paddle_region_count: int | None = None
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    case_directory: Path | None = None

    def unknown(reason_code: str, detail: str) -> VisionRequestResult:
        effective_reason = reason_code
        effective_detail = detail
        try:
            persist_perception_failure(
                test_data_root, case_id, reason_code=reason_code, detail=detail,
                screenshot_sha256=screenshot_sha256, provider=settings.provider,
                model=model, skill_version=settings.skill_version,
                paddle_region_count=paddle_region_count, suite=suite,
            )
            if case_directory is not None:
                _write_case_status(case_directory, case_id=case_id,
                                   terminal_state="UNKNOWN", stage=reason_code,
                                   source_sha256=screenshot_sha256,
                                   started_at=started_at, reason_code=reason_code,
                                   finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
        except Exception as error:
            effective_reason = REASON_EVIDENCE_PERSISTENCE_FAILURE
            effective_detail = f"{detail}; {error}"
        return VisionRequestResult(
            status=STATUS_UNKNOWN,
            reason_code=effective_reason,
            case_id=case_id,
            screenshot_sha256=screenshot_sha256,
            fused_artifact=None,
            agy_artifact=None,
            paddle_artifact=None,
            provider=settings.provider,
            model=model,
            skill_version=settings.skill_version,
            detail=effective_detail,
            conversation_id=runner_conversation_id,
        )

    if not screenshot.is_file():
        return unknown(REASON_SOURCE_IMAGE_MISSING, f"screenshot is missing: {screenshot}")
    if settings.provider != "AGY":
        return unknown(REASON_PROVENANCE_MISMATCH, "configured provider must be AGY")
    model_policy_error = _live_model_policy_error(settings)
    if model_policy_error:
        return unknown(REASON_LIVE_MODEL_REQUIRED, model_policy_error)
    skill_path = _skill_path(settings.skill_version)
    if skill_path is None or not skill_path.is_file():
        return unknown(
            REASON_UNSUPPORTED_SKILL,
            f"unsupported or missing AGY vision skill: {settings.skill_version}",
        )
    if agy_runner is None:
        return unknown(
            REASON_AGY_COMMAND_UNCONFIGURED,
            "real AGY CLI command contract is UNKNOWN; use an injected or fake runner",
        )

    harness = VisionArtifactHarness(Path(test_data_root), suite=suite)
    try:
        case_directory = harness.case_directory(case_id)
    except VisionArtifactRoutingError as error:
        return unknown(REASON_PROVENANCE_MISMATCH, str(error))
    case_source = case_directory / "source_screenshot.png"
    try:
        case_directory.mkdir(parents=True, exist_ok=True)
        if not case_source.exists():
            shutil.copyfile(screenshot, case_source)
        if _sha256(case_source) != screenshot_sha256:
            return unknown(REASON_SCREENSHOT_HASH_MISMATCH, "case source changed during request")
        _write_case_status(case_directory, case_id=case_id, terminal_state="STARTED",
                           stage="CAPTURED", source_sha256=screenshot_sha256,
                           started_at=started_at)
    except Exception as error:
        return unknown(REASON_EVIDENCE_PERSISTENCE_FAILURE, str(error))
    if case_source.exists() and _sha256(case_source) != screenshot_sha256:
        return unknown(
            REASON_SCREENSHOT_HASH_MISMATCH,
            "case source_screenshot.png does not match the requested screenshot",
        )
    manifest_path = case_directory / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return unknown(REASON_ARTIFACT_STALE, f"case manifest is unreadable: {error}")
        if manifest.get("case_id") != case_id or manifest.get("source") != {
            "file": "source_screenshot.png",
            "sha256": screenshot_sha256,
        }:
            return unknown(REASON_ARTIFACT_STALE, "case manifest source binding is stale")

    try:
        paddle_path = harness.output_path(case_id, "Paddle", "not_applicable")
        agy_path = harness.output_path(case_id, "AGY", settings.skill_version)
    except VisionArtifactRoutingError as error:
        return unknown(REASON_PROVENANCE_MISMATCH, str(error))
    fused_path = case_directory / "fused_observation.json"
    conflicts = [path for path in (paddle_path, agy_path, fused_path) if path.exists()]
    if conflicts:
        return unknown(
            REASON_OVERWRITE_CONFLICT,
            "existing artifact would be overwritten: " + ", ".join(map(str, conflicts)),
        )

    try:
        paddle = dict((paddle_runner or _default_paddle_runner)(str(screenshot)))
    except Exception as error:
        return unknown(REASON_PADDLE_PROCESS_FAILURE, str(error))
    if paddle.get("error"):
        return unknown(REASON_PADDLE_PROCESS_FAILURE, str(paddle["error"]))
    if not isinstance(paddle.get("text_regions"), list):
        return unknown(REASON_PADDLE_PROCESS_FAILURE, "Paddle text_regions is not a list")
    paddle_region_count = len(paddle["text_regions"])
    try:
        paddle_written_early = harness.persist_raw_sensor(
            paddle, case_id=case_id, provider="Paddle", model=settings.paddle_model,
            skill_version="not_applicable", created_at=started_at,
        )
    except Exception as error:
        return unknown(REASON_PADDLE_PROCESS_FAILURE, f"Paddle evidence persistence failed: {error}")

    with tempfile.TemporaryDirectory() as staging_directory:
        staging_path = Path(staging_directory) / "vision_output.json"
        configured_log_root = getattr(agy_runner, "log_root", None)
        log_root = (Path(configured_log_root) if configured_log_root is not None
                    else REPO_ROOT / "logs" / "agy_bridge")
        log_directory = log_root / case_id
        boundary_before = _write_boundary_snapshot(
            REPO_ROOT, [Path(staging_directory), log_directory]
        )
        def boundary_violation() -> list[dict[str, str]]:
            changes = _write_boundary_diff(
                boundary_before,
                _write_boundary_snapshot(REPO_ROOT, [Path(staging_directory), log_directory]),
            )
            if changes:
                log_directory.mkdir(parents=True, exist_ok=True)
                (log_directory / "unexpected_write_report.json").write_text(
                    json.dumps({
                        "case_id": case_id,
                        "reason_code": REASON_UNEXPECTED_ARTIFACT_WRITE,
                        "allowlist": [str(Path(staging_directory)), str(log_directory)],
                        "changes": changes,
                    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
            return changes
        runner_request = AgyRunnerRequest(
            screenshot_path=str(screenshot.resolve()),
            source_sha256=screenshot_sha256,
            case_id=case_id,
            skill_path=str(skill_path.resolve()),
            output_artifact_path=str(staging_path.resolve()),
            timeout_seconds=settings.timeout_seconds,
        )
        agy_staging_path: Path | None = None
        agy_raw_bytes: bytes | None = None
        try:
            runner_result = agy_runner(runner_request)
        except TimeoutError as error:
            if boundary_violation():
                return unknown(REASON_UNEXPECTED_ARTIFACT_WRITE, "AGY modified paths outside staging/log allowlist")
            return unknown(REASON_AGY_TIMEOUT, str(error) or "AGY runner timed out")
        except Exception as error:
            if boundary_violation():
                return unknown(REASON_UNEXPECTED_ARTIFACT_WRITE, "AGY modified paths outside staging/log allowlist")
            return unknown(REASON_AGY_COMMAND_FAILURE, str(error))
        unexpected_writes = boundary_violation()
        if unexpected_writes:
            return unknown(
                REASON_UNEXPECTED_ARTIFACT_WRITE,
                "AGY modified paths outside staging/log allowlist",
            )
        if not isinstance(runner_result, AgyRunnerResult):
            return unknown(
                REASON_RUNNER_PROTOCOL_FAILURE,
                f"AGY runner returned {type(runner_result).__name__}, expected AgyRunnerResult",
            )
        runner_conversation_id = runner_result.conversation_id
        if runner_result.artifact_path:
            agy_staging_path = Path(runner_result.artifact_path)
        def reject_agy(reason: str, detail: str) -> VisionRequestResult:
            try:
                if agy_staging_path is not None:
                    _quarantine_agy(
                        agy_staging_path, case_directory, reason_code=reason,
                        exit_status=runner_result.exit_status,
                        conversation_id=runner_result.conversation_id,
                        job_id=runner_result.job_id,
                    )
            except Exception as error:
                detail = f"{detail}; rejected artifact preservation failed: {error}"
            return unknown(reason, detail)
        if runner_result.timed_out:
            return reject_agy(
                REASON_AGY_TIMEOUT,
                runner_result.diagnostic or runner_result.stderr or "AGY runner timed out",
            )
        if runner_result.exit_status != 0:
            return reject_agy(
                REASON_AGY_COMMAND_FAILURE,
                runner_result.diagnostic
                or runner_result.stderr
                or f"AGY runner exited with status {runner_result.exit_status}",
            )
        if not runner_result.artifact_path:
            return unknown(REASON_RUNNER_PROTOCOL_FAILURE, "AGY runner returned no artifact path")
        returned_path = Path(runner_result.artifact_path)
        if returned_path.resolve() != staging_path.resolve():
            return reject_agy(
                REASON_RUNNER_PROTOCOL_FAILURE,
                "AGY runner artifact path does not match the requested output path",
            )
        if not returned_path.is_file():
            return reject_agy(REASON_AGY_COMMAND_FAILURE, "AGY runner wrote no output artifact")
        try:
            agy = _decode_agy_payload(returned_path)
            agy_raw_bytes = returned_path.read_bytes()
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            return reject_agy(REASON_INVALID_JSON, str(error))

    metadata = agy.get("metadata")
    if not isinstance(metadata, Mapping):
        return reject_agy(REASON_PROVENANCE_MISMATCH, "AGY artifact metadata is missing")
    artifact_provider = metadata.get("provider")
    artifact_model = metadata.get("model")
    artifact_skill = metadata.get("skill_version")
    if not isinstance(artifact_model, str) or not artifact_model:
        return reject_agy(REASON_PROVENANCE_MISMATCH, "AGY artifact model is missing")
    model = artifact_model
    if (
        artifact_provider != settings.provider
        or artifact_skill != settings.skill_version
        or (settings.expected_model is not None and artifact_model != settings.expected_model)
    ):
        return reject_agy(
            REASON_PROVENANCE_MISMATCH,
            "AGY artifact provider/model/skill does not match the request",
        )
    if metadata.get("case_id") != case_id or agy.get("observation_id") != case_id:
        return reject_agy(REASON_ARTIFACT_STALE, "AGY artifact identity does not match case_id")
    if metadata.get("source_image") != "source_screenshot.png":
        return reject_agy(REASON_PROVENANCE_MISMATCH, "AGY source_image is not case-local")
    created_at = metadata.get("created_at")
    if not isinstance(created_at, str) or not created_at:
        return reject_agy(REASON_PROVENANCE_MISMATCH, "AGY created_at is missing")

    schema_errors = VisionObservation.validate(agy)
    if schema_errors:
        reason = (
            REASON_FORBIDDEN_SEMANTIC_FIELD
            if any("forbidden semantic field" in error for error in schema_errors)
            else REASON_SCHEMA_FAILURE
        )
        return reject_agy(reason, "; ".join(schema_errors))

    expected_digest = f"sha256:{screenshot_sha256}"
    capture = agy["capture"]
    if (
        metadata.get("screenshot_sha256") != screenshot_sha256
        or capture.get("screenshot_digest") != expected_digest
    ):
        return reject_agy(
            REASON_SCREENSHOT_HASH_MISMATCH,
            "AGY artifact is not bound to the requested screenshot",
        )

    try:
        fused = fuse_perception(paddle, agy)
        VisionObservation.from_payload(fused)
    except Exception as error:
        if agy_raw_bytes is not None:
            try:
                _quarantine_agy_bytes(
                    agy_raw_bytes, case_directory, reason_code=REASON_FUSION_FAILURE,
                    exit_status=runner_result.exit_status,
                    conversation_id=runner_result.conversation_id,
                    job_id=runner_result.job_id,
                )
            except Exception:
                pass
        return unknown(REASON_FUSION_FAILURE, str(error))

    try:
        case_directory.mkdir(parents=True, exist_ok=True)
        if not case_source.exists():
            shutil.copyfile(screenshot, case_source)
    except OSError as error:
        return unknown(REASON_SOURCE_PREPARATION_FAILURE, str(error))
    if _sha256(case_source) != screenshot_sha256:
        return unknown(REASON_SCREENSHOT_HASH_MISMATCH, "case source changed during request")

    provenance = metadata.get("provenance")
    manifest_provenance = dict(provenance) if isinstance(provenance, Mapping) else None
    try:
        agy_written = harness.persist(
            agy,
            case_id=case_id,
            provider="AGY",
            model=artifact_model,
            skill_version=settings.skill_version,
            created_at=created_at,
            provenance=manifest_provenance,
        )
        _publish_fused(fused_path, fused)
    except (FileExistsError, VisionArtifactRoutingError) as error:
        return unknown(REASON_OVERWRITE_CONFLICT, str(error))
    except Exception as error:
        return unknown(REASON_FUSION_FAILURE, f"artifact publication failed: {error}")

    try:
        _write_case_status(case_directory, case_id=case_id, terminal_state="SUCCESS",
                           stage="PUBLISHED", source_sha256=screenshot_sha256,
                           started_at=started_at,
                           finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           reason_code=REASON_OK)
    except Exception as error:
        return unknown(REASON_EVIDENCE_PERSISTENCE_FAILURE, str(error))
    return VisionRequestResult(
        status=STATUS_SUCCESS,
        reason_code=REASON_OK,
        case_id=case_id,
        screenshot_sha256=screenshot_sha256,
        fused_artifact=str(fused_path),
        agy_artifact=str(agy_written),
        paddle_artifact=str(paddle_written_early),
        provider=settings.provider,
        model=artifact_model,
        skill_version=settings.skill_version,
        detail="validated fused VisionObservation is ready",
        conversation_id=runner_conversation_id,
    )


class AgyVisionBridge(VisionAgent):
    """Observer-compatible provider that exposes only validated fused output."""

    name = "AGY Vision Bridge v0.3"

    def __init__(
        self,
        *,
        test_data_root: str | Path,
        suite: str = "ob003",
        case_id_factory: Callable[[], str] | None = None,
        agy_runner: AgyRunner | None = None,
        paddle_runner: PaddleRunner | None = None,
        config: AgyVisionConfig | None = None,
    ):
        self.test_data_root = Path(test_data_root)
        self.suite = suite
        self.case_id_factory = case_id_factory
        self.agy_runner = agy_runner
        self.paddle_runner = paddle_runner
        self.config = config or AgyVisionConfig()
        self.last_result: VisionRequestResult | None = None

    def request(
        self,
        screenshot_path: str | Path,
        case_id: str | None = None,
    ) -> VisionRequestResult:
        resolved_case_id = case_id
        if resolved_case_id is None and self.case_id_factory is not None:
            resolved_case_id = self.case_id_factory()
        if not resolved_case_id:
            screenshot = Path(screenshot_path)
            digest = _sha256(screenshot) if screenshot.is_file() else ""
            self.last_result = VisionRequestResult(
                status=STATUS_UNKNOWN,
                reason_code=REASON_CASE_ID_REQUIRED,
                case_id="",
                screenshot_sha256=digest,
                fused_artifact=None,
                agy_artifact=None,
                paddle_artifact=None,
                provider=self.config.provider,
                model=self.config.expected_model,
                skill_version=self.config.skill_version,
                detail="each observation requires an explicit case_id or case_id_factory",
            )
            return self.last_result
        self.last_result = vision_request(
            screenshot_path,
            resolved_case_id,
            test_data_root=self.test_data_root,
            suite=self.suite,
            agy_runner=self.agy_runner,
            paddle_runner=self.paddle_runner,
            config=self.config,
        )
        return self.last_result

    def observe(self, screenshot_path: str, case_id: str | None = None) -> dict[str, Any]:
        result = self.request(screenshot_path, case_id)
        if result.status != STATUS_SUCCESS or result.fused_artifact is None:
            raise AgyVisionUnknown(result)
        payload = json.loads(Path(result.fused_artifact).read_text(encoding="utf-8"))
        VisionObservation.from_payload(payload)
        return payload


class FakeAgyRunner:
    """Offline fixture runner implementing the structured AGY protocol.

    Parity rule: the fake validates the same request contract a live runner
    must see — case identity, screenshot hash, skill path, staging output
    path, and a positive timeout — and never silently accepts a fixture that
    does not match the request.
    """

    def __init__(self, fixture_path: str | Path):
        self.fixture_path = Path(fixture_path)
        self.requests: list[AgyRunnerRequest] = []

    def _assert_request_contract(self, request: AgyRunnerRequest) -> None:
        fixture = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        metadata = fixture.get("metadata") if isinstance(fixture, dict) else None
        if not isinstance(metadata, dict):
            raise AssertionError("fake runner fixture has no metadata contract block")
        if request.case_id != metadata.get("case_id"):
            raise AssertionError(
                f"fixture case_id {metadata.get('case_id')!r} != request {request.case_id!r}"
            )
        if request.source_sha256 != metadata.get("screenshot_sha256"):
            raise AssertionError(
                f"fixture screenshot_sha256 {metadata.get('screenshot_sha256')!r} "
                f"!= request {request.source_sha256!r}"
            )
        if not request.skill_path.endswith("SKILL.md"):
            raise AssertionError(f"unexpected skill_path: {request.skill_path}")
        if Path(request.output_artifact_path).name != "vision_output.json":
            raise AssertionError(
                f"unexpected staging output name: {request.output_artifact_path}"
            )
        if request.timeout_seconds <= 0:
            raise AssertionError("timeout_seconds must be positive")

    def __call__(self, request: AgyRunnerRequest) -> AgyRunnerResult:
        self.requests.append(request)
        self._assert_request_contract(request)
        output = Path(request.output_artifact_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.fixture_path, output)
        return AgyRunnerResult(
            exit_status=0,
            artifact_path=str(output),
            diagnostic="offline fixture copied",
        )


def _fake_agy_runner(path: Path) -> AgyRunner:
    return FakeAgyRunner(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline AGY Vision Bridge v0.3")
    parser.add_argument("screenshot", type=Path)
    parser.add_argument("case_id")
    parser.add_argument("--test-data-root", type=Path, default=Path("test_data"))
    parser.add_argument("--fake-agy", action="store_true")
    parser.add_argument("--agy-fixture", type=Path)
    arguments = parser.parse_args()

    runner = None
    if arguments.fake_agy:
        if arguments.agy_fixture is None:
            parser.error("--fake-agy requires --agy-fixture")
        runner = _fake_agy_runner(arguments.agy_fixture)
    result = vision_request(
        arguments.screenshot,
        arguments.case_id,
        test_data_root=arguments.test_data_root,
        agy_runner=runner,
    )
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "AGY_VISION_BRIDGE_GATE",
    "AGY_VISION_BRIDGE_GATE_CHECKS",
    "AgyRunnerRequest",
    "AgyRunnerResult",
    "AgyVisionBridge",
    "AgyVisionConfig",
    "AgyVisionUnknown",
    "CROSS_AGENT_INTEGRATION_GATE",
    "CROSS_AGENT_INTEGRATION_GATE_CHECKS",
    "FakeAgyRunner",
    "GateEvidence",
    "VisionRequestResult",
    "UNKNOWN_REASON_CODES",
    "evaluate_agy_vision_bridge_gate",
    "evaluate_cross_agent_integration_gate",
    "make_gate_evidence",
    "vision_request",
]
