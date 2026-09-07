"""OB-003 Vision Self-Extraction Benchmark on unseen screenshots.

For each of three new observations, compares the agent's direct vision
extraction (agent_vision_output.json) against an independent instrument
reference: the PaddleOCR raw sensor run over the same PNG
(paddle_reference.json), produced without modifying the perception pipeline.

Metrics per observation:
- text recall: PaddleOCR reference strings recovered by the agent
- grounding agreement: agent linked_text strings that appear in the
  independent OCR text set
- interaction inventory with UNKNOWN (no linked text) preservation

Caveat recorded in every report: the current PaddleOCR baseline runs with
document preprocessing enabled, so its bboxes are in processed-image space.
Text recall and grounding agreement are string-level and unaffected; no
bbox-level comparison is claimed against this reference.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent
OBSERVATIONS = [
    "OBS_20260903064050_P2_s3_after_back1",
    "OBS_20260903064030_P2_s2_unit_formation",
    "OBS_20260903063000_1E_s5_dialog_full",
]


_WIDTH_FOLD = str.maketrans(
    "～（）！？：・0123456789ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "~()!?::0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")


def _norm(text: object) -> str:
    return (str(text).replace(" ", "").replace("\u3000", "")
            .translate(_WIDTH_FOLD).strip().lower())


def evaluate(observation_dir: Path) -> dict:
    agent = json.loads((observation_dir / "agent_vision_output.json").read_text(encoding="utf-8"))
    paddle = json.loads((observation_dir / "paddle_reference.json").read_text(encoding="utf-8"))
    ocr_texts = [_norm(t) for t in paddle.get("rec_texts", [])]
    # The baseline runner groups text_regions; recover raw strings either way.
    if not ocr_texts:
        ocr_texts = [_norm(r.get("text", "")) for r in paddle.get("text_regions", [])]
    ocr_set = set(t for t in ocr_texts if t)

    agent_texts = [_norm(t["text"]) for t in agent["text_regions"]]
    recovered = [t for t in ocr_set if any(t in a or a in t for a in agent_texts)]
    missed = sorted(ocr_set - set(recovered))

    grounding_total, grounding_hits, grounding_gaps = 0, 0, []
    unknown_candidates = 0
    for candidate in agent["interaction_candidates"]:
        links = [_norm(t) for t in candidate.get("linked_text", [])]
        if not links:
            unknown_candidates += 1
            continue
        for link in links:
            grounding_total += 1
            if any(link in ocr or ocr in link for ocr in ocr_set):
                grounding_hits += 1
            else:
                grounding_gaps.append(
                    {"linked_text": link,
                     "candidate_bbox": candidate["bbox"]})

    return {
        "observation_id": agent["observation_id"],
        "screenshot": observation_dir.name,
        "reference_instrument": "PaddleOCR raw sensor (paddle_reference.json)",
        "reference_caveat": "reference bboxes are in processed-image space; "
                            "comparison is string-level only",
        "text_recall": {
            "reference_strings": len(ocr_set),
            "recovered": len(recovered),
            "recall": round(len(recovered) / len(ocr_set), 3) if ocr_set else None,
            "missed": missed,
        },
        "agent_text_regions": len(agent_texts),
        "grounding_agreement": {
            "linked_text_total": grounding_total,
            "supported_by_reference_ocr": grounding_hits,
            "ratio": round(grounding_hits / grounding_total, 3) if grounding_total else None,
            "unsupported_links": grounding_gaps,
        },
        "interaction_inventory": {
            "candidates": len(agent["interaction_candidates"]),
            "unknown_no_linked_text": unknown_candidates,
        },
        "uncertainties_declared": len(agent.get("uncertainties", [])),
    }


def main() -> None:
    reports = [evaluate(ROOT / "test_data" / "ob003" / name) for name in OBSERVATIONS]
    summary = {
        "benchmark": "OB-003 Vision Self-Extraction on Unseen Screenshots",
        "observations": reports,
    }
    out = ROOT / "test_data" / "ob003" / "comparison_report.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for report in reports:
        print(report["screenshot"],
              "text_recall=", report["text_recall"]["recall"],
              "grounding=", report["grounding_agreement"]["ratio"])


if __name__ == "__main__":
    main()
