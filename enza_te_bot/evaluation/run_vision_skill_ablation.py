"""Training Settings vision-skill ablation over canonical case artifacts.

This is a read-only benchmark adapter.  It preserves the existing
``compare_vision`` formulas and adds only case integrity checks and structural
diagnostics required by the ablation report.  PaddleOCR is a directional text
reference/proxy, never ground truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ob002_agent_vision_eval import compare_vision  # noqa: E402
from vision_observation_schema import VisionObservation  # noqa: E402
from evaluation.run_three_way_vision_benchmark import _latency_ms  # noqa: E402


CASE_ID = "OBS_20260903065025_P2_s7_training_settings"
DEFAULT_CASE = PROJECT_ROOT / "test_data" / "ob003" / CASE_ID
SKILLS = (
    "gemini_vision_v1",
    "gemini_vision_v1_1",
    "gemini_vision_v2",
)
CANONICAL_PATHS = {
    "paddle": Path("providers/paddle/vision_output.json"),
    **{
        skill: Path("providers") / "agy" / skill / "vision_output.json"
        for skill in SKILLS
    },
}


class IntegrityError(RuntimeError):
    """Raised before comparison when canonical inputs fail integrity checks."""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IntegrityError(f"JSON artifact is not an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise IntegrityError(f"source is not a readable PNG: {path}")
    return struct.unpack(">II", header[16:24])


def validate_case(case_dir: str | Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Validate manifest, source, hashes, schema, and ablation provenance."""
    root = Path(case_dir).resolve()
    manifest_path = root / "manifest.json"
    manifest = _load(manifest_path)
    if manifest.get("case_id") != root.name:
        raise IntegrityError("manifest case_id does not match case directory")

    source_info = manifest.get("source")
    if not isinstance(source_info, dict) or source_info.get("file") != "source_screenshot.png":
        raise IntegrityError("manifest source must be source_screenshot.png")
    source_path = root / "source_screenshot.png"
    source_sha = _sha256(source_path)
    if source_info.get("sha256") != source_sha:
        raise IntegrityError("source screenshot SHA-256 mismatch")

    entries = manifest.get("providers")
    if not isinstance(entries, list):
        raise IntegrityError("manifest providers must be a list")
    by_artifact = {
        str(entry.get("artifact")): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("artifact"), str)
    }
    expected = {path.as_posix() for path in CANONICAL_PATHS.values()}
    if set(by_artifact) != expected:
        missing = sorted(expected - set(by_artifact))
        extra = sorted(set(by_artifact) - expected)
        raise IntegrityError(f"manifest canonical artifact set mismatch; missing={missing}, extra={extra}")

    artifacts: dict[str, dict[str, Any]] = {}
    for name, relative in CANONICAL_PATHS.items():
        path = root / relative
        entry = by_artifact[relative.as_posix()]
        if not path.is_file():
            raise IntegrityError(f"canonical artifact missing: {relative}")
        if entry.get("artifact_sha256") != _sha256(path):
            raise IntegrityError(f"artifact SHA-256 mismatch: {relative}")
        if entry.get("screenshot_sha256") != source_sha:
            raise IntegrityError(f"manifest screenshot binding mismatch: {relative}")

        payload = _load(path)
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise IntegrityError(f"metadata missing: {relative}")
        for field in ("provider", "model", "skill_version", "screenshot_sha256"):
            if entry.get(field) != metadata.get(field):
                raise IntegrityError(f"manifest/metadata {field} mismatch: {relative}")
        if metadata.get("case_id") != root.name:
            raise IntegrityError(f"metadata case_id mismatch: {relative}")
        if metadata.get("source_image") != "source_screenshot.png":
            raise IntegrityError(f"metadata source_image mismatch: {relative}")
        if metadata.get("screenshot_sha256") != source_sha:
            raise IntegrityError(f"artifact screenshot binding mismatch: {relative}")

        if name == "paddle":
            if metadata.get("provider") != "Paddle":
                raise IntegrityError("Paddle text proxy has incorrect provider")
        else:
            if metadata.get("provider") != "AGY":
                raise IntegrityError(f"AGY variant has incorrect provider: {name}")
            if metadata.get("model") != "gemini-3.8-flash-medium":
                raise IntegrityError(f"AGY variant model mismatch: {name}")
            if metadata.get("skill_version") != name:
                raise IntegrityError(f"AGY skill/version mismatch: {name}")
            schema_errors = VisionObservation.validate(payload)
            if schema_errors:
                raise IntegrityError(f"VisionObservation schema failure for {name}: {schema_errors}")
        artifacts[name] = payload

    width, height = _png_dimensions(source_path)
    for skill in SKILLS:
        viewport = artifacts[skill].get("viewport", {})
        if (viewport.get("width"), viewport.get("height")) != (width, height):
            raise IntegrityError(f"viewport/source dimensions mismatch: {skill}")

    integrity = {
        "status": "PASS",
        "manifest": str(manifest_path),
        "case_id": root.name,
        "source_screenshot": str(source_path),
        "source_screenshot_sha256": source_sha,
        "source_dimensions": {"width": width, "height": height},
        "artifact_hashes_verified": True,
        "manifest_filesystem_consistent": True,
        "agy_schema_valid": True,
        "provenance_consistent": True,
    }
    return integrity, artifacts


def _bbox(entry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    raw = entry.get("bbox")
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in raw):
        return None
    return tuple(float(value) for value in raw)  # type: ignore[return-value]


def _out_of_viewport(payload: dict[str, Any]) -> dict[str, Any]:
    viewport = payload["viewport"]
    width, height = float(viewport["width"]), float(viewport["height"])
    entries: list[dict[str, str]] = []
    for field in (
        "text_regions",
        "interaction_candidates",
        "numeric_regions",
        "overlay_regions",
        "uncertainties",
    ):
        for index, item in enumerate(payload.get(field, []) or []):
            box = _bbox(item)
            if box is None:
                continue
            x, y, box_width, box_height = box
            if x < 0 or y < 0 or box_width < 0 or box_height < 0 or x + box_width > width or y + box_height > height:
                entries.append({
                    "collection": field,
                    "id": str(item.get("id") or f"{field}[{index}]"),
                })
    return {"count": len(entries), "entries": entries}


def _rectangle_union_area(rectangles: list[tuple[float, float, float, float]]) -> float:
    x_values = sorted({x for x, _, width, _ in rectangles for x in (x, x + width)})
    area = 0.0
    for left, right in zip(x_values, x_values[1:]):
        intervals = sorted(
            (y, y + height)
            for x, y, width, height in rectangles
            if width > 0 and height > 0 and x < right and x + width > left
        )
        covered = 0.0
        if intervals:
            start, end = intervals[0]
            for next_start, next_end in intervals[1:]:
                if next_start > end:
                    covered += end - start
                    start, end = next_start, next_end
                else:
                    end = max(end, next_end)
            covered += end - start
        area += (right - left) * covered
    return area


def _uncertainty_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    viewport = payload["viewport"]
    width, height = float(viewport["width"]), float(viewport["height"])
    clipped: list[tuple[float, float, float, float]] = []
    for item in payload.get("uncertainties", []) or []:
        box = _bbox(item)
        if box is None:
            continue
        x, y, box_width, box_height = box
        left, top = max(0.0, x), max(0.0, y)
        right, bottom = min(width, x + box_width), min(height, y + box_height)
        if right > left and bottom > top:
            clipped.append((left, top, right - left, bottom - top))
    area = _rectangle_union_area(clipped)
    viewport_area = width * height
    return {
        "count": len(payload.get("uncertainties", []) or []),
        "viewport_union_area_pixels": round(area, 3),
        "viewport_area_coverage": round(area / viewport_area, 6) if viewport_area else None,
    }


def _grounding_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    text_ids = {str(item.get("id")) for item in payload.get("text_regions", []) if item.get("id")}
    interactions = list(payload.get("interaction_candidates", []) or [])
    linked = 0
    links = 0
    dangling: list[dict[str, str]] = []
    for index, item in enumerate(interactions):
        item_links = item.get("linked_text_ids", [])
        if not isinstance(item_links, list):
            continue
        if item_links:
            linked += 1
        item_id = str(item.get("id") or f"interaction_candidates[{index}]")
        for text_id in item_links:
            links += 1
            if str(text_id) not in text_ids:
                dangling.append({"interaction_id": item_id, "text_id": str(text_id)})
    return {
        "interaction_count": len(interactions),
        "interactions_with_text_links": linked,
        "interaction_link_coverage": round(linked / len(interactions), 6) if interactions else None,
        "linked_text_reference_count": links,
        "dangling_link_count": len(dangling),
        "dangling_links": dangling,
    }


def _timeout_evidence(manifest_entry: dict[str, Any]) -> dict[str, Any]:
    latency = None
    trajectory_ref = manifest_entry.get("provenance", {}).get("trajectory")
    trajectory_id = None
    if isinstance(trajectory_ref, str):
        trajectory_path = PROJECT_ROOT / trajectory_ref
        if trajectory_path.is_file():
            trajectory_id = _load(trajectory_path).get("artifact_id")

    events: list[dict[str, Any]] = []
    failures_dir = PROJECT_ROOT / "enza_memory" / "failures"
    for failure_path in sorted(failures_dir.glob("*.json")):
        failure = _load(failure_path)
        reference = str(failure.get("trajectory_reference", ""))
        classification = failure.get("unknown_cause", {}).get("classification")
        if not trajectory_id or not reference.startswith(str(trajectory_id)) or classification != "PROVIDER_TIMEOUT":
            continue
        effect = str(failure.get("observed_result", {}).get("effect", ""))
        match = re.search(
            r"(?:after\s+)?(\d+(?:\.\d+)?)\s*(?:-\s*)?minutes?",
            effect,
            re.IGNORECASE,
        )
        events.append({
            "failure_id": failure.get("failure_id"),
            "duration_minutes": float(match.group(1)) if match else None,
            "status": failure.get("state_now"),
            "evidence_path": str(failure_path.relative_to(PROJECT_ROOT)),
        })
    return {
        "successful_latency_ms": latency,
        "successful_latency_status": "not_recorded",
        "timeout_event_count": len(events),
        "timeout_events": events,
    }


def _manifest_entries(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(entry["skill_version"]): entry
        for entry in manifest["providers"]
        if entry.get("provider") == "AGY"
    }


def _variant_metrics(
    payload: dict[str, Any],
    paddle_comparison: dict[str, Any],
    manifest_entry: dict[str, Any],
) -> dict[str, Any]:
    exact = paddle_comparison["text_recall"]
    normalized = paddle_comparison["normalized_text_match"]
    extras = normalized["unmatched_candidate"]
    return {
        "provider": payload["metadata"]["provider"],
        "model": payload["metadata"]["model"],
        "skill_version": payload["metadata"]["skill_version"],
        "text_region_count": len(payload.get("text_regions", []) or []),
        "paddle_text_proxy": {
            "reference_count": exact["reference_count"],
            "exact_agreement_count": exact["exact_match_count"],
            "exact_agreement_rate": exact["recall_against_reference"],
            "normalized_agreement_count": normalized["match_count"],
            "text_coverage_proxy": normalized["match_rate_against_reference"],
            "note": "Directional agreement against PaddleOCR; PaddleOCR is not ground truth.",
        },
        "interaction_candidate_count": len(payload.get("interaction_candidates", []) or []),
        "grounding": _grounding_metrics(payload),
        "uncertainty": _uncertainty_metrics(payload),
        "out_of_viewport_bbox": _out_of_viewport(payload),
        "suspicious_unsupported_extra": {
            "count": len(extras),
            "items": extras,
            "definition": "Normalized candidate text with no one-to-one Paddle proxy match; diagnostic only, not a false-positive judgment.",
        },
        "timing": {
            "artifact_latency_ms": _latency_ms(payload),
            **_timeout_evidence(manifest_entry),
        },
    }


def _pairwise_summary(reference: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    comparison = compare_vision(reference, candidate)
    overlap = comparison["interaction_candidate_overlap"]
    return {
        "direction": "candidate against reference",
        "text": {
            "reference_count": comparison["text_recall"]["reference_count"],
            "candidate_count": comparison["text_recall"]["candidate_count"],
            "exact_agreement_count": comparison["text_recall"]["exact_match_count"],
            "exact_agreement_rate": comparison["text_recall"]["recall_against_reference"],
            "normalized_agreement_count": comparison["normalized_text_match"]["match_count"],
            "normalized_agreement_rate": comparison["normalized_text_match"]["match_rate_against_reference"],
        },
        "interaction_overlap": {
            "reference_count": overlap["reference_count"],
            "candidate_count": overlap["candidate_count"],
            "matched_count": overlap["matched_count"],
            "overlap_rate_against_reference": overlap["overlap_rate_against_reference"],
            "mean_matched_iou": overlap["mean_matched_iou"],
            "unmatched_reference_count": len(overlap["unmatched_reference_indices"]),
            "unmatched_candidate_count": len(overlap["unmatched_candidate_indices"]),
        },
        "grounding_agreement": comparison["grounding_agreement"],
    }


def _assessment(
    variants: dict[str, dict[str, Any]],
    pairwise: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    v1 = variants["gemini_vision_v1"]
    v1_1 = variants["gemini_vision_v1_1"]
    v2 = variants["gemini_vision_v2"]
    v1_v2 = pairwise["v1_to_v2"]
    return {
        "v1_to_v1_1": {
            "classification": "REGRESSION",
            "basis": [
                f"Paddle text coverage proxy {v1['paddle_text_proxy']['text_coverage_proxy']:.6f} -> {v1_1['paddle_text_proxy']['text_coverage_proxy']:.6f}",
                f"interaction candidates {v1['interaction_candidate_count']} -> {v1_1['interaction_candidate_count']}",
                f"out-of-viewport bboxes {v1['out_of_viewport_bbox']['count']} -> {v1_1['out_of_viewport_bbox']['count']}",
            ],
        },
        "v1_1_to_v2": {
            "classification": "RECOVERY_WITH_SIGNIFICANT_EXPANSION",
            "basis": [
                f"Paddle text coverage proxy {v1_1['paddle_text_proxy']['text_coverage_proxy']:.6f} -> {v2['paddle_text_proxy']['text_coverage_proxy']:.6f}",
                f"interaction candidates {v1_1['interaction_candidate_count']} -> {v2['interaction_candidate_count']}",
                f"unmatched candidate interactions {pairwise['v1_1_to_v2']['interaction_overlap']['unmatched_candidate_count']}",
                f"uncertainty records {v1_1['uncertainty']['count']} -> {v2['uncertainty']['count']}",
            ],
        },
        "v2_vs_v1": {
            "classification": "NO_DEMONSTRATED_NET_GAIN_ON_THIS_CASE",
            "basis": [
                f"Paddle text coverage proxy {v1['paddle_text_proxy']['text_coverage_proxy']:.6f} -> {v2['paddle_text_proxy']['text_coverage_proxy']:.6f}",
                f"normalized text agreement with v1 {v1_v2['text']['normalized_agreement_rate']:.6f}",
                f"interaction overlap with v1 {v1_v2['interaction_overlap']['overlap_rate_against_reference']:.6f}",
                f"grounding agreement on matched interactions {v1_v2['grounding_agreement']['agreement_rate']:.6f}",
                f"out-of-viewport bboxes {v1['out_of_viewport_bbox']['count']} -> {v2['out_of_viewport_bbox']['count']}",
            ],
            "observed_change": "Broader interaction and uncertainty enumeration, without a validated coverage or grounding gain.",
        },
        "recommended_default": {
            "selection": "NO_PROMOTION",
            "retain_baseline": "gemini_vision_v1",
            "reason": "One-case evidence shows v1.1 regression and v2 expansion without demonstrated net gain; successful latency is also unrecorded and v2 required a recorded 20-minute timeout continuation.",
        },
    }


def build_report(case_dir: str | Path) -> dict[str, Any]:
    root = Path(case_dir).resolve()
    integrity, artifacts = validate_case(root)
    manifest = _load(root / "manifest.json")
    entries = _manifest_entries(manifest)
    paddle = artifacts["paddle"]
    variants = {
        skill: _variant_metrics(
            artifacts[skill],
            compare_vision(paddle, artifacts[skill]),
            entries[skill],
        )
        for skill in SKILLS
    }
    pairwise = {
        "v1_to_v1_1": _pairwise_summary(
            artifacts["gemini_vision_v1"], artifacts["gemini_vision_v1_1"]),
        "v1_1_to_v2": _pairwise_summary(
            artifacts["gemini_vision_v1_1"], artifacts["gemini_vision_v2"]),
        "v1_to_v2": _pairwise_summary(
            artifacts["gemini_vision_v1"], artifacts["gemini_vision_v2"]),
    }
    return {
        "benchmark": "Training Settings Vision Skill Ablation",
        "case_id": root.name,
        "integrity_gate": integrity,
        "comparison_roles": {
            "text_reference_proxy": "PaddleOCR",
            "text_reference_is_ground_truth": False,
            "ablation_provider": "AGY",
            "ablation_model": "gemini-3.8-flash-medium",
            "ablation_variable": "skill_version",
            "zcode_included": False,
        },
        "settings": compare_vision(artifacts[SKILLS[0]], artifacts[SKILLS[1]])["settings"],
        "inputs": {name: str(root / relative) for name, relative in CANONICAL_PATHS.items()},
        "variants": variants,
        "pairwise": pairwise,
        "assessment": _assessment(variants, pairwise),
        "limitations": [
            "Single observation case; results do not establish general extraction quality.",
            "PaddleOCR is a text agreement proxy, not ground truth.",
            "Successful end-to-end latency was not recorded for these artifacts.",
            "Unmatched text is a suspicious-extra diagnostic, not proof of a false positive.",
        ],
    }


def _percent(value: Any) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.1f}%"


def render_markdown(report: dict[str, Any]) -> str:
    variants = report["variants"]
    rows = []
    for skill in SKILLS:
        item = variants[skill]
        proxy = item["paddle_text_proxy"]
        grounding = item["grounding"]
        uncertainty = item["uncertainty"]
        timing = item["timing"]
        rows.append(
            f"| {skill} | {item['text_region_count']} | "
            f"{proxy['exact_agreement_count']} / {_percent(proxy['exact_agreement_rate'])} | "
            f"{proxy['normalized_agreement_count']} / {_percent(proxy['text_coverage_proxy'])} | "
            f"{item['interaction_candidate_count']} | "
            f"{_percent(grounding['interaction_link_coverage'])} | "
            f"{grounding['dangling_link_count']} | "
            f"{uncertainty['count']} / {_percent(uncertainty['viewport_area_coverage'])} | "
            f"{item['out_of_viewport_bbox']['count']} | "
            f"{item['suspicious_unsupported_extra']['count']} | "
            f"{timing['artifact_latency_ms'] if timing['artifact_latency_ms'] is not None else 'not recorded'} | "
            f"{timing['timeout_event_count']} |"
        )

    pair_rows = []
    for name in ("v1_to_v1_1", "v1_1_to_v2", "v1_to_v2"):
        item = report["pairwise"][name]
        text = item["text"]
        interaction = item["interaction_overlap"]
        grounding = item["grounding_agreement"]
        pair_rows.append(
            f"| {name} | {text['normalized_agreement_count']} / {_percent(text['normalized_agreement_rate'])} | "
            f"{interaction['matched_count']} / {_percent(interaction['overlap_rate_against_reference'])} | "
            f"{interaction['mean_matched_iou'] if interaction['mean_matched_iou'] is not None else 'n/a'} | "
            f"{_percent(grounding['agreement_rate'])} | "
            f"{interaction['unmatched_candidate_count']} |"
        )

    timeout_lines = []
    for skill in SKILLS:
        timing = variants[skill]["timing"]
        if timing["timeout_events"]:
            details = ", ".join(
                (
                    f"{event['duration_minutes']:g} min ({event['failure_id']})"
                    if event["duration_minutes"] is not None
                    else f"duration not recorded ({event['failure_id']})"
                )
                for event in timing["timeout_events"]
            )
            timeout_lines.append(f"- `{skill}`: {details}; continuation completed. Successful total latency was not recorded.")
        else:
            timeout_lines.append(f"- `{skill}`: no timeout record found; successful total latency was not recorded.")

    assessment = report["assessment"]

    return "\n".join([
        "# Training Settings Vision Skill Ablation",
        "",
        f"Case: `{report['case_id']}`",
        "",
        "Integrity gate: **PASS**. Manifest, screenshot hash, artifact hashes, AGY schema, viewport binding, and provider/model/skill provenance were verified before comparison.",
        "",
        "PaddleOCR is used only as a directional text reference/proxy. It is not ground truth. All three ablation variants use provider `AGY` and model `gemini-3.8-flash-medium`; only `skill_version` changes.",
        "",
        "## Variant metrics",
        "",
        "| Skill | Text regions | Exact vs Paddle | Normalized / text coverage proxy | Interactions | Grounding link coverage | Dangling links | Uncertainty count / viewport coverage | OOV bbox | Suspicious unsupported text extra | Latency ms | Timeout events |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        "## Pairwise skill overlap",
        "",
        "The direction is the later skill as candidate against the earlier skill as reference. Existing comparison formulas are unchanged (interaction IoU threshold 0.5; Unicode NFKC plus whitespace removal).",
        "",
        "| Transition | Normalized text agreement | Interaction overlap | Mean matched IoU | Grounding agreement | Unmatched candidate interactions |",
        "|---|---:|---:|---:|---:|---:|",
        *pair_rows,
        "",
        "## Recorded timing evidence",
        "",
        *timeout_lines,
        "",
        "## Evidence-bounded assessment",
        "",
        f"- v1 -> v1.1: **{assessment['v1_to_v1_1']['classification']}**. "
        + "; ".join(assessment["v1_to_v1_1"]["basis"]) + ".",
        f"- v1.1 -> v2: **{assessment['v1_1_to_v2']['classification']}**. "
        + "; ".join(assessment["v1_1_to_v2"]["basis"]) + ".",
        f"- v2 vs v1: **{assessment['v2_vs_v1']['classification']}**. "
        + "; ".join(assessment["v2_vs_v1"]["basis"]) + ".",
        f"- Recommended default: **{assessment['recommended_default']['selection']}**; retain `{assessment['recommended_default']['retain_baseline']}` as the baseline. {assessment['recommended_default']['reason']}",
        "",
        "## Interpretation limits",
        "",
        "- This is one observation case and cannot establish general extraction quality.",
        "- Unmatched candidate text is reported as a suspicious unsupported extra, not classified as a false positive.",
        "- No successful end-to-end latency values exist in the artifacts or provenance records.",
        "",
    ])


def run(
    case_dir: str | Path = DEFAULT_CASE,
    json_output: str | Path | None = None,
    markdown_output: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(case_dir).resolve()
    report = build_report(root)
    json_path = Path(json_output) if json_output else root / "reports" / "vision_skill_ablation.json"
    markdown_path = Path(markdown_output) if markdown_output else root / "reports" / "vision_skill_ablation.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    report = run(args.case_dir, args.json_output, args.markdown_output)
    print(json.dumps({
        "case_id": report["case_id"],
        "integrity_gate": report["integrity_gate"]["status"],
        "json_report": str(args.json_output or args.case_dir / "reports" / "vision_skill_ablation.json"),
        "markdown_report": str(args.markdown_output or args.case_dir / "reports" / "vision_skill_ablation.md"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
