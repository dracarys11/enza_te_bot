"""Three-way, offline vision-provider comparison.

PaddleOCR is used as the text reference because it has no interaction
candidates. Gemini is used as the interaction reference for the AGY input.
The report is descriptive: it records directional recall, geometry overlap,
grounding agreement, and unmatched items without selecting a winner.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ob002_agent_vision_eval import compare_vision  # noqa: E402


DEFAULT_OUTPUT = PROJECT_ROOT / "three_way_vision_report.json"
_LATENCY_KEYS = ("latency_ms", "elapsed_ms", "duration_ms")


def _load(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"vision artifact must be a JSON object: {path}")
    return payload


def _latency_ms(payload: dict[str, Any]) -> float | None:
    """Return only explicitly recorded millisecond latency."""
    containers = [payload]
    for key in ("metadata", "metrics", "timing"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            containers.append(nested)
    for container in containers:
        for key in _LATENCY_KEYS:
            value = container.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _text_metrics(comparison: dict[str, Any]) -> dict[str, Any]:
    exact = comparison["text_recall"]
    normalized = comparison["normalized_text_match"]
    return {
        "reference_count": exact["reference_count"],
        "provider_count": exact["candidate_count"],
        "exact_match_count": exact["exact_match_count"],
        "exact_recall": exact["recall_against_reference"],
        "normalized_match_count": normalized["match_count"],
        "normalized_recall": normalized["match_rate_against_reference"],
    }


def _text_differences(comparison: dict[str, Any]) -> dict[str, Any]:
    normalized = comparison["normalized_text_match"]
    return {
        "missed": normalized["unmatched_reference"],
        "extra": normalized["unmatched_candidate"],
    }


def _interaction_id(entries: list[dict[str, Any]], index: int, prefix: str) -> str:
    return str(entries[index].get("id") or f"{prefix}_{index + 1:03d}")


def compare_three_way(
    agy: dict[str, Any],
    gemini: dict[str, Any],
    paddle: dict[str, Any],
) -> dict[str, Any]:
    """Compare one AGY/Gemini/Paddle artifact triplet."""
    agy_text = compare_vision(paddle, agy)
    gemini_text = compare_vision(paddle, gemini)
    agy_visual = compare_vision(gemini, agy)

    overlap = agy_visual["interaction_candidate_overlap"]
    grounding = agy_visual["grounding_agreement"]
    gemini_interactions = list(gemini.get("interaction_candidates", []))
    agy_interactions = list(agy.get("interaction_candidates", []))
    missed_indices = overlap["unmatched_reference_indices"]
    extra_indices = overlap["unmatched_candidate_indices"]

    return {
        "benchmark": "Three-way Vision Provider Comparison",
        "comparison_roles": {
            "text_reference": "paddle",
            "interaction_reference": "gemini",
            "interaction_candidate": "agy",
            "note": "Directional measurements only; no provider ranking is inferred.",
        },
        "settings": agy_visual["settings"],
        "metrics": {
            "text_recall": {
                "agy_against_paddle": _text_metrics(agy_text),
                "gemini_against_paddle": _text_metrics(gemini_text),
            },
            "interaction_recall": {
                "direction": "agy against gemini",
                "reference_count": overlap["reference_count"],
                "provider_count": overlap["candidate_count"],
                "matched_count": overlap["matched_count"],
                "recall": overlap["overlap_rate_against_reference"],
            },
            "iou": {
                "mean_matched_iou": overlap["mean_matched_iou"],
                "matches": overlap["matches"],
            },
            "grounding_agreement": grounding,
            "extra_missed": {
                "agy_text_against_paddle": _text_differences(agy_text),
                "gemini_text_against_paddle": _text_differences(gemini_text),
                "agy_interactions_against_gemini": {
                    "missed": [
                        {
                            "index": index,
                            "id": _interaction_id(gemini_interactions, index, "gemini_interaction"),
                        }
                        for index in missed_indices
                    ],
                    "extra": [
                        {
                            "index": index,
                            "id": _interaction_id(agy_interactions, index, "agy_interaction"),
                        }
                        for index in extra_indices
                    ],
                },
            },
            "latency_ms": {
                "agy": _latency_ms(agy),
                "gemini": _latency_ms(gemini),
                "paddle": _latency_ms(paddle),
            },
        },
    }


def run(
    agy_path: str | Path,
    gemini_path: str | Path,
    paddle_path: str | Path,
    output_path: str | Path = DEFAULT_OUTPUT,
) -> dict[str, Any]:
    report = compare_three_way(
        _load(agy_path),
        _load(gemini_path),
        _load(paddle_path),
    )
    report["inputs"] = {
        "agy": str(Path(agy_path)),
        "gemini": str(Path(gemini_path)),
        "paddle": str(Path(paddle_path)),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agy", type=Path, help="agy_vision_output.json")
    parser.add_argument("gemini", type=Path, help="gemini_output.json")
    parser.add_argument("paddle", type=Path, help="paddle_reference.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="output path (default: three_way_vision_report.json)",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    report = run(args.agy, args.gemini, args.paddle, args.output)
    print(json.dumps({
        "report": str(args.output),
        "text_recall": report["metrics"]["text_recall"],
        "interaction_recall": report["metrics"]["interaction_recall"]["recall"],
        "mean_iou": report["metrics"]["iou"]["mean_matched_iou"],
        "grounding_agreement": report["metrics"]["grounding_agreement"]["agreement_rate"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
