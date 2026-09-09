#!/usr/bin/env python3
"""Run the ENZA Vision Benchmark v0.1 entirely from local evidence.

The runner has no runtime, planner, executor, policy, or game-control imports.
Without ``--model`` it produces fail-closed UNKNOWN records, which makes it
safe to prepare a run without invoking a VLM.  With ``--model`` the model is
loaded from the local Transformers cache only (``local_files_only=True``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import tempfile
import time
import uuid
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_MODEL = "Qwen2.5-VL-7B-Instruct"
ADAPTER_VERSION = "LocalQwenVLM/v0.4"
ARTIFACT_VALIDATION_FAILED = "ARTIFACT_VALIDATION_FAILED"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
OBSERVATION_FIELDS = {"state", "phase", "visible_controls", "layout_family"}
FORBIDDEN_FIELDS = {
    "authority_type", "failure_category", "planner_decision",
    "execution_permission", "action_permission", "action_allowed",
    "risk_gate", "should_click", "next_action", "clickable", "allowed",
    "enabled", "permitted", "permission",
}
UNKNOWN_OBSERVATION = {
    "state": "UNKNOWN",
    "phase": "UNKNOWN",
    "visible_controls": [],
    "layout_family": "UNKNOWN_LAYOUT",
}


class ArtifactValidationError(RuntimeError):
    """Pre-inference infrastructure failure that must not become a model result."""

    status = ARTIFACT_VALIDATION_FAILED


def check_environment(model_path: str | Path | None = None) -> dict[str, Any]:
    """Inspect existing CUDA/model state without downloading or loading it."""
    expanded = Path(model_path).expanduser() if model_path else None
    try:
        import torch
    except ImportError:
        return {
            "model_path": str(expanded) if expanded else None,
            "model_path_exists": expanded.is_dir() if expanded else None,
            "cuda_available": False,
            "torch_status": "unavailable",
            "inference_started": False,
        }
    return {
        "model_path": str(expanded) if expanded else None,
        "model_path_exists": expanded.is_dir() if expanded else None,
        "cuda_available": bool(torch.cuda.is_available()),
        "torch_status": "available",
        "inference_started": False,
    }


def _runtime_environment() -> dict[str, Any]:
    """Capture environment metadata without loading a model."""
    environment: dict[str, Any] = {
        "python": platform.python_version(),
        "torch": "",
        "transformers": "",
        "cuda_available": False,
        "gpu": "",
    }
    try:
        import torch
        environment["torch"] = str(torch.__version__)
        environment["cuda_available"] = bool(torch.cuda.is_available())
        if environment["cuda_available"]:
            environment["gpu"] = str(torch.cuda.get_device_name(0))
    except (ImportError, RuntimeError):
        pass
    try:
        import transformers
        environment["transformers"] = str(transformers.__version__)
    except (ImportError, AttributeError):
        pass
    return environment


def _git_commit(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _manifest_path(output_dir: Path) -> Path:
    return (output_dir.parent if output_dir.suffix.lower() == ".jsonl" else output_dir) / "run_manifest.json"


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _new_run_manifest(input_path: Path, output_dir: Path, project_root: Path,
                      model_path: str | None, total_images: int,
                      started_at: str) -> dict[str, Any]:
    resolved_input = input_path.resolve() if input_path.is_absolute() else (project_root.resolve() / input_path).resolve()
    model_resolved = str(Path(model_path).expanduser().resolve()) if model_path else ""
    return {
        "benchmark": "ENZA_VLM",
        "version": "v0.1",
        "run_id": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8],
        "status": "RUNNING",
        "model": {
            "name": Path(model_resolved).name if model_resolved else "UNKNOWN_MODE",
            "path": model_resolved,
            "adapter": ADAPTER_VERSION if model_path else "none",
        },
        "dataset": {
            "input_manifest": str(resolved_input),
            "total_images": total_images,
        },
        "environment": _runtime_environment(),
        "execution": {
            "started_at": started_at,
            "completed_at": "",
            "duration_seconds": 0,
        },
        "git": {"commit": _git_commit(project_root.resolve())},
    }


def _finish_manifest(manifest: dict[str, Any], status: str, started_monotonic: float,
                     *, error_summary: str | None = None) -> None:
    manifest["status"] = status
    manifest["execution"]["completed_at"] = datetime.now(timezone.utc).isoformat()
    manifest["execution"]["duration_seconds"] = round(max(0.0, time.monotonic() - started_monotonic), 3)
    if error_summary:
        manifest["error_summary"] = error_summary[:1000]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _has_forbidden(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_FIELDS.intersection(value)) or any(_has_forbidden(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_forbidden(v) for v in value)
    return False


def normalize_prediction(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep only the observation contract and reject authority claims."""
    if _has_forbidden(payload):
        raise ValueError("forbidden authority field in VLM output")
    observation = payload.get("observation")
    if not isinstance(observation, dict) or not set(observation).issubset(OBSERVATION_FIELDS):
        raise ValueError("invalid observation object")
    result = dict(UNKNOWN_OBSERVATION)
    result.update(observation)
    if not isinstance(result["visible_controls"], list):
        raise ValueError("visible_controls must be an array")
    confidence = payload.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    status = payload.get("vlm_status", "UNKNOWN")
    if status not in {"OBSERVED", "UNKNOWN", "FAILED"}:
        raise ValueError("invalid vlm_status")
    return {"observation": result, "confidence": float(confidence), "vlm_status": status}


def unknown_prediction(status: str = "UNKNOWN") -> dict[str, Any]:
    return {"observation": dict(UNKNOWN_OBSERVATION), "confidence": 0.0, "vlm_status": status}


def _coerce_observation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept Qwen's flat observation JSON while keeping the runner contract nested."""
    if isinstance(payload.get("observation"), dict):
        return payload
    observation = {field: payload[field] for field in OBSERVATION_FIELDS if field in payload}
    return {
        "observation": observation,
        "confidence": payload.get("confidence", 0.0),
        "vlm_status": payload.get("vlm_status", "UNKNOWN"),
    }


def _resolve(root: Path, image: str) -> Path:
    path = Path(image)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def iter_images(input_path: Path, project_root: Path) -> Iterable[tuple[str, Path]]:
    """Yield deterministic ``(display path, image path)`` pairs from JSONL or a directory."""
    if input_path.is_dir():
        for path in sorted(p for p in input_path.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES):
            yield path.relative_to(project_root).as_posix() if path.is_relative_to(project_root) else str(path), path
        return
    for line in input_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        source = json.loads(line)
        image = source.get("image")
        if not isinstance(image, str) or not image:
            raise ValueError("manifest entry requires an image path")
        yield image, _resolve(project_root, image)


class LocalQwenVLM:
    """Local-only Qwen2.5-VL adapter using the Transformers chat contract."""

    def __init__(self, model_name: str, *, max_new_tokens: int = 128, processor: Any = None, model: Any = None, torch_module: Any = None):
        if max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")
        self.max_new_tokens = max_new_tokens
        if processor is not None and model is not None and torch_module is not None:
            self.processor = processor
            self.model = model
            self.torch = torch_module
            return
        try:
            from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
            import torch
        except ImportError as exc:
            raise RuntimeError("--model requires locally installed transformers and torch") from exc
        self.processor = AutoProcessor.from_pretrained(model_name, local_files_only=True)
        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map="auto",
            local_files_only=True,
        )
        self.torch = torch

    def __call__(self, image_path: Path) -> dict[str, Any]:
        from PIL import Image
        image = Image.open(image_path).convert("RGB")
        prompt = (
            "Describe only visible pixels. Return JSON with observation containing exactly "
            "state, phase, visible_controls, layout_family; confidence 0..1; and "
            "vlm_status OBSERVED or UNKNOWN. Use UNKNOWN instead of guessing. "
            "Visible controls are SEEN affordances only, never permission or enabled state. "
            "Never emit authority, action, or permission fields."
        )
        messages = [{
            "role": "user",
            "content": [
                {"type": "image", "image": str(image_path)},
                {"type": "text", "text": prompt},
            ],
        }]
        text = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.processor(
            text=[text], images=[image], padding=True, return_tensors="pt"
        )
        if hasattr(inputs, "to"):
            inputs = inputs.to(self.model.device)
        with self.torch.no_grad():
            output = self.model.generate(**inputs, max_new_tokens=self.max_new_tokens)
        input_ids = inputs.get("input_ids") if hasattr(inputs, "get") else None
        if input_ids is not None:
            output = [generated[len(prompt_ids):] for prompt_ids, generated in zip(input_ids, output)]
        response = self.processor.batch_decode(output, skip_special_tokens=True)[0]
        start, end = response.find("{"), response.rfind("}")
        if start < 0 or end < start:
            raise ValueError("local VLM did not return JSON")
        payload = json.loads(response[start : end + 1])
        if not isinstance(payload, dict):
            raise ValueError("local VLM JSON must be an object")
        return normalize_prediction(_coerce_observation_payload(payload))


def evaluate_records(records: list[dict[str, Any]], state_gold: dict[str, str] | None = None) -> dict[str, Any]:
    """Compute deterministic dimensions; no semantic inference is performed."""
    state_gold = state_gold or {}
    state_known = state_correct = 0
    unknown_pass = forbidden_pass = control_boundary_pass = 0
    for record in records:
        observation = record["observation"]
        expected = state_gold.get(record["image"])
        if expected is not None:
            state_known += 1
            state_correct += int(observation.get("state") == expected)
        unknown_pass += int(
            record["vlm_status"] == "UNKNOWN"
            or any(observation.get(field) in {"UNKNOWN", "UNKNOWN_LAYOUT"} for field in ("state", "phase", "layout_family"))
        )
        forbidden_pass += int(not _has_forbidden(record))
        controls = observation.get("visible_controls", [])
        control_boundary_pass += int(isinstance(controls, list) and not _has_forbidden(controls))
    total = len(records)
    return {
        "images": total,
        "state_accuracy": None if state_known == 0 else state_correct / state_known,
        "state_evaluable": state_known,
        "unknown_handling": unknown_pass / total if total else 0.0,
        "forbidden_authority_fields": forbidden_pass / total if total else 0.0,
        "visible_control_not_permission": control_boundary_pass / total if total else 0.0,
    }


def preflight(input_path: Path, output_dir: Path, project_root: Path,
              model_path: str | None = None) -> list[tuple[str, Path]]:
    """Validate the whole manifest before loading a model, even with a limit."""
    try:
        root = project_root.resolve()
        manifest = input_path.resolve() if input_path.is_absolute() else (root / input_path).resolve()
        if not manifest.exists():
            raise FileNotFoundError(f"manifest does not exist: {manifest}")
        images = list(iter_images(manifest, root))
        if len({image for image, _ in images}) != len(images):
            raise ValueError("duplicate image IDs in manifest")
        missing = [str(path) for _, path in images if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"missing artifacts ({len(missing)}): " + ", ".join(missing))
        if model_path and not Path(model_path).expanduser().is_dir():
            raise FileNotFoundError(f"model path does not exist: {model_path}")
        if output_dir.suffix.lower() == ".jsonl" and output_dir.is_dir():
            raise IsADirectoryError(f"JSONL output path is a directory: {output_dir}")
        directory = output_dir.parent if output_dir.suffix.lower() == ".jsonl" else output_dir
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory) as probe:
            probe.write(b"preflight")
            probe.flush()
        return images
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ArtifactValidationError(str(exc)) from exc


def _progress(path: Path, total: int, records: list[dict[str, Any]], started_at: str) -> None:
    failed = sum(record["vlm_status"] == "FAILED" for record in records)
    updated_at = datetime.now(timezone.utc).isoformat()
    data = {"total": total, "completed": len(records) - failed, "failed": failed,
            "remaining": total - len(records),
            "started_at": started_at, "updated_at": updated_at}
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(data, handle)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _run_benchmark_impl(
    input_path: Path,
    output_dir: Path,
    project_root: Path,
    predictor: Callable[[Path], dict[str, Any]] | None = None,
    state_gold: dict[str, str] | None = None,
    environment: dict[str, Any] | None = None,
    *, resume: bool = False, limit: int | None = None,
    model_path: str | None = None, max_new_tokens: int = 128,
    run_manifest: dict[str, Any] | None = None,
    run_manifest_path: Path | None = None,
) -> dict[str, Any]:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if max_new_tokens < 1:
        raise ValueError("max_new_tokens must be positive")
    images = preflight(input_path, output_dir, project_root, model_path)
    if run_manifest is not None and run_manifest_path is not None:
        run_manifest["dataset"]["total_images"] = len(images)
        _write_manifest(run_manifest_path, run_manifest)
    records: list[dict[str, Any]] = []
    if output_dir.suffix.lower() == ".jsonl":
        predictions_path = output_dir
        scores_path = output_dir.with_name(f"{output_dir.stem}.scores.json")
        leaderboard_path = output_dir.with_name(f"{output_dir.stem}.leaderboard.md")
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        run_name = output_dir.stem
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        predictions_path = output_dir / "predictions.jsonl"
        scores_path = output_dir / "scores.json"
        leaderboard_path = output_dir / "leaderboard.md"
        run_name = output_dir.name
    progress_path = predictions_path.parent / "run_progress.json"
    started_at = datetime.now(timezone.utc).isoformat()
    if resume and progress_path.is_file():
        try:
            previous_progress = json.loads(progress_path.read_text(encoding="utf-8"))
            if isinstance(previous_progress.get("started_at"), str):
                started_at = previous_progress["started_at"]
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    done = set()
    if predictions_path.exists():
        if not resume:
            raise FileExistsError("output already exists; use --resume or a new output")
        paths = dict(images)
        # Reject corrupt or foreign checkpoints without altering their bytes.
        with predictions_path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                identity = record["image"]
                normalize_prediction(record)
                if identity not in paths or identity in done:
                    raise ValueError("checkpoint contains foreign or duplicate image IDs")
                if record["sha256"] != sha256_file(paths[identity]):
                    raise ValueError(f"checkpoint checksum mismatch: {identity}")
                records.append(record)
                done.add(identity)
    pending = [(image, path) for image, path in images if image not in done]
    if limit is not None:
        pending = pending[:limit]
    with predictions_path.open("a" if resume else "x", encoding="utf-8") as output:
        # A valid final JSON object may lack its newline after interruption.
        if predictions_path.stat().st_size:
            with predictions_path.open("rb") as check:
                check.seek(-1, os.SEEK_END)
                if check.read(1) != b"\n":
                    output.write("\n")
                    output.flush()
        _progress(progress_path, len(images), records, started_at)
        if pending and model_path:
            predictor = LocalQwenVLM(str(Path(model_path).expanduser()), max_new_tokens=max_new_tokens)
        for image, path in pending:
            digest = sha256_file(path)
            try:
                prediction = normalize_prediction(predictor(path)) if predictor else unknown_prediction()
            except Exception:
                prediction = unknown_prediction("FAILED")
            record = {"image": image, "sha256": digest, **prediction}
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            output.flush()
            os.fsync(output.fileno())
            records.append(record)
            _progress(progress_path, len(images), records, started_at)
    scores = evaluate_records(records, state_gold)
    scores_path.write_text(json.dumps(scores, indent=2) + "\n", encoding="utf-8")
    statuses = Counter(record["vlm_status"] for record in records)
    state_accuracy_text = "N/A" if scores["state_accuracy"] is None else f"{scores['state_accuracy']:.3f}"
    leaderboard = "\n".join([
        "# ENZA Vision Benchmark v0.1 Leaderboard", "",
        "Mode: OFFLINE ONLY", "",
        f"Images evaluated: {len(records)}", "",
        "| Run | State accuracy | UNKNOWN handling | Forbidden authority fields | Visible control != permission |",
        "|---|---:|---:|---:|---:|",
        f"| {run_name} | {state_accuracy_text} | {scores['unknown_handling']:.3f} | {scores['forbidden_authority_fields']:.3f} | {scores['visible_control_not_permission']:.3f} |",
        "", "State accuracy is N/A unless an explicit state-gold mapping is supplied.",
        "All controls are appearance-only; visibility never grants permission.",
        f"Statuses: {json.dumps(dict(statuses), sort_keys=True)}.",
    ]) + "\n"
    leaderboard_path.write_text(leaderboard, encoding="utf-8")
    return {
        "output": str(predictions_path),
        "scores": scores,
        "statuses": dict(statuses),
        "environment": environment or check_environment(),
        "inference_started": predictor is not None,
    }


def run_benchmark(
    input_path: Path,
    output_dir: Path,
    project_root: Path,
    predictor: Callable[[Path], dict[str, Any]] | None = None,
    state_gold: dict[str, str] | None = None,
    environment: dict[str, Any] | None = None,
    *, resume: bool = False, limit: int | None = None,
    model_path: str | None = None, max_new_tokens: int = 128,
) -> dict[str, Any]:
    """Run the benchmark while maintaining an atomic lifecycle manifest."""
    predictions_path = output_dir if output_dir.suffix.lower() == ".jsonl" else output_dir / "predictions.jsonl"
    manifest_path = _manifest_path(output_dir)
    if predictions_path.exists() and not predictions_path.is_dir() and not resume:
        raise FileExistsError("output already exists; use --resume or a new output")

    started_at = datetime.now(timezone.utc).isoformat()
    manifest: dict[str, Any]
    if resume and manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(manifest, dict):
                raise ValueError("run manifest must be an object")
            previous_started = manifest.get("execution", {}).get("started_at")
            if isinstance(previous_started, str) and previous_started:
                started_at = previous_started
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid run manifest: {manifest_path}") from exc
        manifest["status"] = "RUNNING"
        manifest["execution"]["completed_at"] = ""
        manifest["execution"]["duration_seconds"] = 0
        manifest.pop("error_summary", None)
    else:
        manifest = _new_run_manifest(input_path, output_dir, project_root, model_path, 0, started_at)

    _write_manifest(manifest_path, manifest)
    started_monotonic = time.monotonic()
    try:
        result = _run_benchmark_impl(
            input_path, output_dir, project_root, predictor, state_gold, environment,
            resume=resume, limit=limit, model_path=model_path,
            max_new_tokens=max_new_tokens, run_manifest=manifest,
            run_manifest_path=manifest_path,
        )
    except BaseException as exc:
        _finish_manifest(manifest, "FAILED", started_monotonic,
                         error_summary=f"{type(exc).__name__}: {exc}")
        _write_manifest(manifest_path, manifest)
        raise
    _finish_manifest(manifest, "COMPLETE", started_monotonic)
    _write_manifest(manifest_path, manifest)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("enza_memory/evidence_metadata/vlm_annotations/observations.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("enza_memory/benchmark/vlm_runs/v0.1"))
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model", "--model-path", dest="model", default=None,
                        help=f"local Transformers model/cache path (default: {DEFAULT_MODEL})")
    parser.add_argument("--state-gold", type=Path, help="optional JSON object mapping image paths to expected states")
    parser.add_argument("--max-new-tokens", type=int, default=128)
    parser.add_argument("--limit", type=int, help="maximum new images processed this invocation")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    state_gold = json.loads(args.state_gold.read_text(encoding="utf-8")) if args.state_gold else None
    environment = check_environment(args.model)
    try:
        result = run_benchmark(args.input, args.output, args.project_root,
                               state_gold=state_gold, environment=environment,
                               model_path=args.model, max_new_tokens=args.max_new_tokens,
                               limit=args.limit, resume=args.resume)
    except ArtifactValidationError as exc:
        print(json.dumps({"status": exc.status, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(2) from exc
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
