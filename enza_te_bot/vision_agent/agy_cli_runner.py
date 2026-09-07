"""Real AGY CLI implementation of the frozen bridge runner protocol.

This adapter performs one bounded provider invocation and writes only the
bridge-provided staging path.  Validation, fusion, and canonical publication
remain owned by :mod:`vision_agent.agy_vision_bridge`.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from typing import Sequence

from vision_agent.agy_vision_bridge import (
    AgyRunner,
    AgyRunnerRequest,
    AgyRunnerResult,
    DEFAULT_APPROVED_LIVE_MODEL,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AGY_EXECUTABLE = "agy"
CONVERSATION_ID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
JOB_ID_PATTERN = re.compile(r"\b(?:staffer|researcher|reviewer|implementer)-[a-z0-9]+\b", re.IGNORECASE)


class AgyCliError(RuntimeError):
    """Invalid local request that prevents CLI dispatch."""


def extract_conversation_id(text: str) -> str | None:
    match = CONVERSATION_ID_PATTERN.search(text or "")
    return match.group(0) if match else None


def extract_job_id(text: str) -> str | None:
    match = JOB_ID_PATTERN.search(text or "")
    return match.group(0) if match else None


def _image_viewport(path: Path) -> dict[str, int]:
    from PIL import Image

    with Image.open(path) as image:
        return {"width": int(image.width), "height": int(image.height)}


def build_prompt(
    *,
    request: AgyRunnerRequest,
    viewport: dict[str, int],
    timestamp: str,
    resume_conversation_id: str | None = None,
) -> str:
    """Build dispatch instructions; extraction method stays in the skill."""
    continuation = (
        f"Continue exactly conversation {resume_conversation_id}."
        if resume_conversation_id
        else "Start one AGY Vision Provider extraction."
    )
    return (
        f"{continuation}\n"
        f"Read and obey the exact vision skill file: {request.skill_path}\n"
        f"Observe only this screenshot: {request.screenshot_path}\n"
        f"Write JSON only to this staging artifact: {request.output_artifact_path}\n"
        "Do not write any canonical provider artifact or manifest.\n"
        "Do not read other provider artifacts, manifests, reports, planner state, or runtime state.\n"
        "Do not emit strategy, action, decision, intent, permission, or semantic state.\n"
        "Use this request identity exactly:\n"
        f"case_id={request.case_id}\n"
        f"source_image=source_screenshot.png\n"
        f"screenshot_sha256={request.source_sha256}\n"
        f"capture.screenshot_digest=sha256:{request.source_sha256}\n"
        f"capture.frame_id={request.case_id}\n"
        f"capture.timestamp={timestamp}\n"
        f"viewport={json.dumps(viewport, separators=(',', ':'))}\n"
        f"metadata.provider=AGY\n"
        f"metadata.model={DEFAULT_APPROVED_LIVE_MODEL}\n"
    )


def build_argv(
    *,
    executable: str,
    prompt: str,
    timeout_seconds: float,
    model: str,
    resume_conversation_id: str | None,
) -> list[str]:
    """Map one request to argv without shell parsing."""
    argv = [executable]
    if resume_conversation_id:
        argv.extend(["--conversation", resume_conversation_id])
    argv.extend(
        [
            "--print",
            prompt,
            "--model",
            model,
            "--print-timeout",
            f"{timeout_seconds:g}s",
            "--dangerously-skip-permissions",
        ]
    )
    return argv


def _stream_text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or ""


def _write_evidence(
    evidence_dir: Path,
    *,
    request: AgyRunnerRequest,
    argv: Sequence[str],
    prompt: str,
    resume_conversation_id: str | None,
) -> Path:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "request.json").write_text(
        json.dumps(
            {
                "case_id": request.case_id,
                "screenshot_path": request.screenshot_path,
                "source_sha256": request.source_sha256,
                "skill_path": request.skill_path,
                "staging_output_path": request.output_artifact_path,
                "timeout_seconds": request.timeout_seconds,
                "resume_conversation_id": resume_conversation_id,
                "argv": list(argv),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (evidence_dir / "request_prompt.txt").write_text(prompt, encoding="utf-8")
    return evidence_dir / "agy_job.log"


@dataclass
class RealAgyCliRunner:
    """Callable real runner. Each call dispatches AGY exactly once.

    Carries no frame-specific state: identity, screenshot, staging path and
    timeout all arrive per call on the AgyRunnerRequest.
    """

    executable: str = DEFAULT_AGY_EXECUTABLE
    model: str = DEFAULT_APPROVED_LIVE_MODEL
    resume_conversation_id: str | None = None
    log_root: Path | None = None
    invocation_count: int = 0

    def __call__(self, request: AgyRunnerRequest) -> AgyRunnerResult:
        image = Path(request.screenshot_path)
        output = Path(request.output_artifact_path)
        if not image.is_file():
            raise AgyCliError(f"screenshot not found: {image}")
        if not Path(request.skill_path).is_file():
            raise AgyCliError(f"vision skill not found: {request.skill_path}")
        if request.timeout_seconds <= 0:
            raise AgyCliError("timeout_seconds must be positive")
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        if digest != request.source_sha256:
            raise AgyCliError(
                "screenshot changed before AGY dispatch "
                f"({digest} != {request.source_sha256})"
            )
        if output.exists():
            raise AgyCliError(f"staging artifact already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)

        viewport = _image_viewport(image)
        prompt = build_prompt(
            request=request,
            viewport=viewport,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            resume_conversation_id=self.resume_conversation_id,
        )
        argv = build_argv(
            executable=self.executable,
            prompt=prompt,
            timeout_seconds=request.timeout_seconds,
            model=self.model,
            resume_conversation_id=self.resume_conversation_id,
        )
        evidence_dir = (
            self.log_root / request.case_id
            if self.log_root is not None
            else REPO_ROOT / "logs" / "agy_bridge" / request.case_id
        )
        log_path = _write_evidence(
            evidence_dir,
            request=request,
            argv=argv,
            prompt=prompt,
            resume_conversation_id=self.resume_conversation_id,
        )

        self.invocation_count += 1
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as error:
            stdout = _stream_text(error.stdout)
            stderr = _stream_text(error.stderr)
            combined = stdout + stderr
            log_path.write_text(
                stdout + ("\n--stderr--\n" + stderr if stderr else ""),
                encoding="utf-8",
            )
            return AgyRunnerResult(
                exit_status=None,
                artifact_path=None,
                job_id=extract_job_id(combined),
                conversation_id=(
                    extract_conversation_id(combined) or self.resume_conversation_id
                ),
                stderr=stderr,
                diagnostic=(
                    stdout
                    or f"AGY CLI exceeded {request.timeout_seconds:g}s; job log: {log_path}"
                ),
                timed_out=True,
            )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        combined = stdout + stderr
        log_path.write_text(
            stdout + ("\n--stderr--\n" + stderr if stderr else ""),
            encoding="utf-8",
        )
        conversation_id = extract_conversation_id(combined) or self.resume_conversation_id
        job_id = extract_job_id(combined)
        if completed.returncode != 0:
            return AgyRunnerResult(
                exit_status=completed.returncode,
                artifact_path=None,
                job_id=job_id,
                conversation_id=conversation_id,
                stderr=stderr,
                diagnostic=stdout or f"AGY CLI exited {completed.returncode}",
            )
        if not output.is_file():
            return AgyRunnerResult(
                exit_status=0,
                artifact_path=None,
                job_id=job_id,
                conversation_id=conversation_id,
                stderr=stderr,
                diagnostic=stdout or "AGY CLI exited successfully without a staging artifact",
            )
        return AgyRunnerResult(
            exit_status=0,
            artifact_path=str(output),
            job_id=job_id,
            conversation_id=conversation_id,
            stderr=stderr,
            diagnostic=stdout,
        )


def build_agy_cli_runner(
    *,
    executable: str | Path = DEFAULT_AGY_EXECUTABLE,
    model: str = DEFAULT_APPROVED_LIVE_MODEL,
    resume_conversation_id: str | None = None,
    log_root: str | Path | None = None,
) -> AgyRunner:
    """Build the real runner without dispatching AGY.

    Session-level knobs only (executable, pinned model, resume conversation,
    log location). Frame-specific data — screenshot, sha, case id, staging
    path, timeout — arrives exclusively on each AgyRunnerRequest.
    """
    if model != DEFAULT_APPROVED_LIVE_MODEL:
        raise ValueError(
            f"real AGY runner model must be pinned to {DEFAULT_APPROVED_LIVE_MODEL}"
        )
    return RealAgyCliRunner(
        executable=str(executable),
        model=model,
        resume_conversation_id=resume_conversation_id,
        log_root=Path(log_root) if log_root is not None else None,
    )


__all__ = [
    "AgyCliError",
    "DEFAULT_AGY_EXECUTABLE",
    "JOB_ID_PATTERN",
    "CONVERSATION_ID_PATTERN",
    "RealAgyCliRunner",
    "build_agy_cli_runner",
    "build_argv",
    "build_prompt",
    "extract_conversation_id",
    "extract_job_id",
]
