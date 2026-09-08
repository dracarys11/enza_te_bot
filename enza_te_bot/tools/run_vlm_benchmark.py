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
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable


DEFAULT_MODEL = "Qwen2.5-VL-7B-Instruct"
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
    return path if path.is_absolute() else root / path


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
            continue
        yield image, _resolve(project_root, image)


class LocalQwenVLM:
    """Local-only Qwen2.5-VL adapter using the Transformers chat contract."""

    def __init__(self, model_name: str, *, processor: Any = None, model: Any = None, torch_module: Any = None):
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
            output = self.model.generate(**inputs, max_new_tokens=256)
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


def run_benchmark(
    input_path: Path,
    output_dir: Path,
    project_root: Path,
    predictor: Callable[[Path], dict[str, Any]] | None = None,
    state_gold: dict[str, str] | None = None,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for image, path in iter_images(input_path, project_root):
        try:
            digest = sha256_file(path)
            prediction = normalize_prediction(predictor(path)) if predictor else unknown_prediction()
        except Exception:
            digest = sha256_file(path) if path.is_file() else None
            prediction = unknown_prediction("FAILED")
        records.append({"image": image, "sha256": digest, **prediction})
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
    predictions_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records), encoding="utf-8"
    )
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("enza_memory/evidence_metadata/vlm_annotations/observations.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("enza_memory/benchmark/vlm_runs/v0.1"))
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--model", "--model-path", dest="model", default=None,
                        help=f"local Transformers model/cache path (default: {DEFAULT_MODEL})")
    parser.add_argument("--state-gold", type=Path, help="optional JSON object mapping image paths to expected states")
    args = parser.parse_args()
    state_gold = json.loads(args.state_gold.read_text(encoding="utf-8")) if args.state_gold else None
    environment = check_environment(args.model)
    if args.model and not environment["model_path_exists"]:
        raise SystemExit(f"model path does not exist: {environment['model_path']}")
    predictor = LocalQwenVLM(args.model) if args.model else None
    print(json.dumps(run_benchmark(args.input, args.output, args.project_root, predictor,
                                   state_gold, environment), indent=2))


if __name__ == "__main__":
    main()
