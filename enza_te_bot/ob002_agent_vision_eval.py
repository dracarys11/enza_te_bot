"""Vision extraction comparison benchmark.

This module reports measurable differences between two visual-fact artifacts.
It does not determine which artifact is correct and does not touch runtime code.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import unicodedata
from typing import Any, Callable


ROOT = Path(__file__).parent
REFERENCE = ROOT / "test_data" / "ob001" / "gemini_output.json"
CANDIDATE = ROOT / "test_data" / "ob002" / "agent_vision_output.json"
COMPARISON_REPORT = ROOT / "test_data" / "ob002" / "vision_comparison_report.json"
IOU_THRESHOLD = 0.5


def normalize_text(text: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(text))
    return "".join(character for character in normalized if not character.isspace())


def _bbox(entry: dict[str, Any]) -> tuple[float, float, float, float]:
    x, y, width, height = entry["bbox"]
    return float(x), float(y), float(width), float(height)


def _center_distance(left: dict[str, Any], right: dict[str, Any]) -> float:
    lx, ly, lw, lh = _bbox(left)
    rx, ry, rw, rh = _bbox(right)
    return math.hypot(lx + lw / 2 - rx - rw / 2, ly + lh / 2 - ry - rh / 2)


def _iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    lx, ly, lw, lh = _bbox(left)
    rx, ry, rw, rh = _bbox(right)
    intersection_width = max(0.0, min(lx + lw, rx + rw) - max(lx, rx))
    intersection_height = max(0.0, min(ly + lh, ry + rh) - max(ly, ry))
    intersection = intersection_width * intersection_height
    union = lw * lh + rw * rh - intersection
    return intersection / union if union else 0.0


def _text_id(region: dict[str, Any], index: int, side: str) -> str:
    return str(region.get("id") or f"{side}_text_{index + 1:03d}")


def _pair_text_regions(reference_regions: list[dict[str, Any]],
                       candidate_regions: list[dict[str, Any]],
                       key: Callable[[object], str]) -> tuple[list[dict[str, Any]], list[int], list[int]]:
    unused_candidates = set(range(len(candidate_regions)))
    matched_reference: set[int] = set()
    pairs: list[dict[str, Any]] = []
    for reference_index, reference_region in enumerate(reference_regions):
        reference_key = key(reference_region.get("text", ""))
        options = [
            candidate_index for candidate_index in unused_candidates
            if key(candidate_regions[candidate_index].get("text", "")) == reference_key
        ]
        if not options:
            continue
        candidate_index = min(
            options,
            key=lambda index: _center_distance(reference_region, candidate_regions[index]),
        )
        candidate_region = candidate_regions[candidate_index]
        unused_candidates.remove(candidate_index)
        matched_reference.add(reference_index)
        pairs.append({
            "reference_id": _text_id(reference_region, reference_index, "reference"),
            "candidate_id": _text_id(candidate_region, candidate_index, "candidate"),
            "reference_text": reference_region.get("text"),
            "candidate_text": candidate_region.get("text"),
            "normalized_text": normalize_text(reference_region.get("text", "")),
            "bbox_iou": round(_iou(reference_region, candidate_region), 6),
            "center_distance": round(
                _center_distance(reference_region, candidate_region), 6),
        })
    return (
        pairs,
        [index for index in range(len(reference_regions)) if index not in matched_reference],
        sorted(unused_candidates),
    )


def _pair_interactions(reference_regions: list[dict[str, Any]],
                       candidate_regions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[int], list[int]]:
    ranked = sorted(
        (
            (_iou(reference_region, candidate_region), reference_index, candidate_index)
            for reference_index, reference_region in enumerate(reference_regions)
            for candidate_index, candidate_region in enumerate(candidate_regions)
        ),
        reverse=True,
    )
    used_reference: set[int] = set()
    used_candidate: set[int] = set()
    pairs: list[dict[str, Any]] = []
    for overlap, reference_index, candidate_index in ranked:
        if overlap < IOU_THRESHOLD:
            break
        if reference_index in used_reference or candidate_index in used_candidate:
            continue
        used_reference.add(reference_index)
        used_candidate.add(candidate_index)
        pairs.append({
            "reference_index": reference_index,
            "reference_id": str(
                reference_regions[reference_index].get("id")
                or f"reference_interaction_{reference_index + 1:03d}"
            ),
            "candidate_index": candidate_index,
            "candidate_id": str(
                candidate_regions[candidate_index].get("id")
                or f"candidate_interaction_{candidate_index + 1:03d}"
            ),
            "iou": round(overlap, 6),
            "center_distance": round(_center_distance(
                reference_regions[reference_index], candidate_regions[candidate_index]), 6),
        })
    pairs.sort(key=lambda pair: pair["reference_index"])
    return (
        pairs,
        [index for index in range(len(reference_regions)) if index not in used_reference],
        [index for index in range(len(candidate_regions)) if index not in used_candidate],
    )


def _linked_texts(interaction: dict[str, Any], text_regions: list[dict[str, Any]]) -> set[str]:
    direct = interaction.get("linked_text", [])
    values = (
        {normalize_text(text) for text in direct if normalize_text(text)}
        if isinstance(direct, list) else set()
    )
    text_by_id = {
        str(region.get("id")): normalize_text(region.get("text", ""))
        for region in text_regions if region.get("id")
    }
    for text_id in interaction.get("linked_text_ids", []):
        normalized = text_by_id.get(str(text_id))
        if normalized:
            values.add(normalized)
    return values


def compare_vision(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    reference_texts = list(reference.get("text_regions", []))
    candidate_texts = list(candidate.get("text_regions", []))
    exact_pairs, exact_reference_gaps, exact_candidate_gaps = _pair_text_regions(
        reference_texts, candidate_texts, lambda value: str(value),
    )
    normalized_pairs, normalized_reference_gaps, normalized_candidate_gaps = _pair_text_regions(
        reference_texts, candidate_texts, normalize_text,
    )

    reference_interactions = list(reference.get("interaction_candidates", []))
    candidate_interactions = list(candidate.get("interaction_candidates", []))
    interaction_pairs, interaction_reference_gaps, interaction_candidate_gaps = (
        _pair_interactions(reference_interactions, candidate_interactions)
    )

    grounding_pairs: list[dict[str, Any]] = []
    for pair in interaction_pairs:
        reference_links = _linked_texts(
            reference_interactions[pair["reference_index"]], reference_texts)
        candidate_links = _linked_texts(
            candidate_interactions[pair["candidate_index"]], candidate_texts)
        grounding_pairs.append({
            "reference_id": pair["reference_id"],
            "candidate_id": pair["candidate_id"],
            "shared_normalized_text": sorted(reference_links & candidate_links),
            "reference_only_normalized_text": sorted(reference_links - candidate_links),
            "candidate_only_normalized_text": sorted(candidate_links - reference_links),
            "agreement": reference_links == candidate_links,
        })

    mean_iou = (
        sum(pair["iou"] for pair in interaction_pairs) / len(interaction_pairs)
        if interaction_pairs else None
    )
    exact_grounding = sum(pair["agreement"] for pair in grounding_pairs)
    return {
        "benchmark": "Vision Extraction Comparison",
        "reference": str(REFERENCE),
        "candidate": str(CANDIDATE),
        "settings": {
            "interaction_iou_threshold": IOU_THRESHOLD,
            "text_normalization": "Unicode NFKC plus whitespace removal",
        },
        "text_recall": {
            "reference_count": len(reference_texts),
            "candidate_count": len(candidate_texts),
            "exact_match_count": len(exact_pairs),
            "recall_against_reference": (
                round(len(exact_pairs) / len(reference_texts), 6)
                if reference_texts else None
            ),
            "matches": exact_pairs,
            "unmatched_reference": [
                {"id": _text_id(reference_texts[index], index, "reference"),
                 "text": reference_texts[index].get("text")}
                for index in exact_reference_gaps
            ],
            "unmatched_candidate": [
                {"id": _text_id(candidate_texts[index], index, "candidate"),
                 "text": candidate_texts[index].get("text")}
                for index in exact_candidate_gaps
            ],
        },
        "normalized_text_match": {
            "match_count": len(normalized_pairs),
            "match_rate_against_reference": (
                round(len(normalized_pairs) / len(reference_texts), 6)
                if reference_texts else None
            ),
            "normalized_only_matches": [
                pair for pair in normalized_pairs
                if pair["reference_text"] != pair["candidate_text"]
            ],
            "unmatched_reference": [
                {"id": _text_id(reference_texts[index], index, "reference"),
                 "text": reference_texts[index].get("text")}
                for index in normalized_reference_gaps
            ],
            "unmatched_candidate": [
                {"id": _text_id(candidate_texts[index], index, "candidate"),
                 "text": candidate_texts[index].get("text")}
                for index in normalized_candidate_gaps
            ],
        },
        "interaction_candidate_overlap": {
            "reference_count": len(reference_interactions),
            "candidate_count": len(candidate_interactions),
            "matched_count": len(interaction_pairs),
            "overlap_rate_against_reference": (
                round(len(interaction_pairs) / len(reference_interactions), 6)
                if reference_interactions else None
            ),
            "mean_matched_iou": round(mean_iou, 6) if mean_iou is not None else None,
            "matches": interaction_pairs,
            "unmatched_reference_indices": interaction_reference_gaps,
            "unmatched_candidate_indices": interaction_candidate_gaps,
        },
        "grounding_agreement": {
            "compared_interactions": len(grounding_pairs),
            "exact_agreement_count": exact_grounding,
            "agreement_rate": (
                round(exact_grounding / len(grounding_pairs), 6)
                if grounding_pairs else None
            ),
            "differences": [pair for pair in grounding_pairs if not pair["agreement"]],
        },
    }


def run(reference_path: str | Path = REFERENCE,
        candidate_path: str | Path = CANDIDATE,
        output_path: str | Path = COMPARISON_REPORT) -> dict[str, Any]:
    reference = json.loads(Path(reference_path).read_text(encoding="utf-8"))
    candidate = json.loads(Path(candidate_path).read_text(encoding="utf-8"))
    report = compare_vision(reference, candidate)
    report["reference"] = str(Path(reference_path))
    report["candidate"] = str(Path(candidate_path))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    report = run()
    print(json.dumps({
        "report": str(COMPARISON_REPORT),
        "text_recall": report["text_recall"]["recall_against_reference"],
        "normalized_text_match": report["normalized_text_match"]["match_rate_against_reference"],
        "interaction_candidate_overlap": report["interaction_candidate_overlap"]["overlap_rate_against_reference"],
        "grounding_agreement": report["grounding_agreement"]["agreement_rate"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
