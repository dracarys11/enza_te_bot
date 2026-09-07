#!/usr/bin/env python3
"""Offline VLM observation inference runner.

The model adapter is deliberately isolated from the observation contract. A
model is loaded only from local Transformers cache; without ``--model`` the
runner produces UNKNOWN predictions, which is the required fail-closed mode.
No planner, executor, policy, or runtime module is imported.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable


OBSERVATION_FIELDS = {"state", "phase", "event_type", "visible_text", "visible_controls", "layout_family"}
FORBIDDEN_FIELDS = {
    "authority_type",
    "planner_decision",
    "execution_permission",
    "action_allowed",
    "risk_gate",
    "should_click",
    "next_action",
    "clickable",
    "allowed",
    "enabled",
    "permitted",
    "permission",
}
UNKNOWN_OBSERVATION = {
    "state": "UNKNOWN",
    "phase": "UNKNOWN",
    "event_type": "UNKNOWN",
    "visible_text": [],
    "visible_controls": [],
    "layout_family": "UNKNOWN",
}


def unknown_prediction() -> dict[str, Any]:
    return {"observation": dict(UNKNOWN_OBSERVATION), "confidence": 0.0, "vlm_status": "UNKNOWN"}


def _contains_forbidden(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_FIELDS.intersection(value)) or any(_contains_forbidden(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden(child) for child in value)
    return False


def normalize_prediction(prediction: dict[str, Any]) -> dict[str, Any]:
    """Validate a model payload and return only the observation contract."""
    if _contains_forbidden(prediction):
        raise ValueError("forbidden authority field in VLM output")
    observation = prediction.get("observation")
    if not isinstance(observation, dict) or not OBSERVATION_FIELDS.issuperset(observation):
        raise ValueError("invalid observation object")
    result = dict(UNKNOWN_OBSERVATION)
    result.update(observation)
    confidence = prediction.get("confidence", 0.0)
    if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    status = prediction.get("vlm_status", "UNKNOWN")
    if status not in {"OBSERVED", "UNKNOWN"}:
        raise ValueError("invalid vlm_status")
    return {"observation": result, "confidence": float(confidence), "vlm_status": status}


class LocalTransformersVLM:
    """Small generic local Transformers adapter; model-specific prompting stays here."""

    def __init__(self, model_name: str):
        try:
            from transformers import AutoProcessor
            try:
                from transformers import AutoModelForImageTextToText as ModelClass
            except ImportError:
                from transformers import AutoModelForVision2Seq as ModelClass
            import torch
        except ImportError as exc:
            raise RuntimeError("local VLM requires transformers and torch") from exc
        self.processor = AutoProcessor.from_pretrained(model_name, local_files_only=True)
        self.model = ModelClass.from_pretrained(model_name, local_files_only=True)
        self.torch = torch

    def __call__(self, image_path: Path) -> dict[str, Any]:
        from PIL import Image
        image = Image.open(image_path)
        prompt = ('Describe only visible pixels. Return JSON with exactly an observation object '
                   '(state, phase, event_type, visible_text, visible_controls, layout_family), '
                   'confidence 0..1, and vlm_status OBSERVED or UNKNOWN. Never emit authority or action fields.')
        inputs = self.processor(images=image, text=prompt, return_tensors="pt")
        with self.torch.no_grad():
            output = self.model.generate(**inputs, max_new_tokens=256)
        text = self.processor.batch_decode(output, skip_special_tokens=True)[0]
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("local VLM did not return JSON")
        return normalize_prediction(json.loads(text[start:end + 1]))


def _resolve_image(root: Path, image: str) -> Path:
    path = Path(image)
    return path if path.is_absolute() else root / path


def run_predictions(input_path: Path, output_path: Path, project_root: Path, predictor: Callable[[Path], dict[str, Any]] | None = None) -> dict[str, Any]:
    records = []
    for line in input_path.read_text().splitlines():
        if not line.strip():
            continue
        source = json.loads(line)
        try:
            prediction = normalize_prediction(predictor(_resolve_image(project_root, source["image"]))) if predictor else unknown_prediction()
        except (OSError, ValueError, json.JSONDecodeError):
            prediction = unknown_prediction()
        records.append({"image": source["image"], "sha256": source.get("sha256"), **prediction})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records))
    statuses = Counter(record["vlm_status"] for record in records)
    states = Counter(record["observation"]["state"] for record in records)
    phases = Counter(record["observation"]["phase"] for record in records)
    histogram = {"0.0-0.19": 0, "0.2-0.39": 0, "0.4-0.59": 0, "0.6-0.79": 0, "0.8-1.0": 0}
    for record in records:
        confidence = record["confidence"]
        key = "0.0-0.19" if confidence < 0.2 else "0.2-0.39" if confidence < 0.4 else "0.4-0.59" if confidence < 0.6 else "0.6-0.79" if confidence < 0.8 else "0.8-1.0"
        histogram[key] += 1
    report_path = output_path.with_name("vlm_predictions_report.md")
    unknown_rate = statuses.get("UNKNOWN", 0) / len(records) if records else 0.0
    report_path.write_text("\n".join([
        "# VLM Observation Inference Report v0.1", "",
        f"- Total predictions: {len(records)}",
        f"- UNKNOWN rate: {unknown_rate:.3f}",
        f"- State distribution: {json.dumps(dict(states), sort_keys=True)}",
        f"- Phase distribution: {json.dumps(dict(phases), sort_keys=True)}",
        f"- Confidence histogram: {json.dumps(histogram, sort_keys=True)}", "",
        "Only observation fields are emitted. No authority or action fields are produced.", "",
    ]))
    return {"total": len(records), "unknown_rate": unknown_rate, "states": dict(states), "phases": dict(phases), "confidence_histogram": histogram, "output": str(output_path), "report": str(report_path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("enza_memory/evidence_metadata/vlm_annotations/observations.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("enza_memory/evidence_metadata/vlm_annotations/vlm_predictions.jsonl"))
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument(
        "--model",
        "--model-path",
        dest="model",
        help="Local Transformers model path or cached identifier; no network is used",
    )
    args = parser.parse_args()
    predictor = LocalTransformersVLM(args.model) if args.model else None
    print(json.dumps(run_predictions(args.input, args.output, args.project_root, predictor), indent=2))


if __name__ == "__main__":
    main()
