"""OB-002 Agent Reasoning Benchmark: external-agent consumption of Vision JSON.

An offline, screenshot-free benchmark. A reasoning agent receives only the
fused VisionObservation payload (and optionally the raw Gemini envelope) and
must produce grounded decisions as structured results:

- reasoning evidence citing region ids only
- an optional selected grounded element id (a candidate, never an action)
- confidence taken from the frozen perception confidence chain
- explicitly unresolved uncertainty

Rules enforced by construction: no screenshot access, no hidden state, no
clicking, no executor. The agent cannot emit coordinates, screen names, or
action commands; selecting a GroundedElement whose text evidence is UNKNOWN is
refused and routed to human verification instead.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from grounded_element import (
    TEXT_EVIDENCE_MATCHED,
    TEXT_EVIDENCE_UNKNOWN,
    build_grounded_elements,
    elements_with_text,
)

ROOT = Path(__file__).parent
FUSED_OB001 = ROOT / "test_data" / "ob001" / "fused_observation.json"
GEMINI_RAW_OB001 = ROOT / "test_data" / "ob001" / "gemini_raw.json"
REPORT_PATH = ROOT / "test_data" / "ob002" / "agent_reasoning_report.json"

DECISION_GROUNDED = "GROUNDED_SELECTION"
DECISION_UNKNOWN = "UNKNOWN_REQUIRES_HUMAN"
DECISION_NO_TARGET = "NO_GROUNDED_TARGET"
DECISION_REPORT = "EVIDENCE_REPORT"

LOW_CONFIDENCE_THRESHOLD = 0.9


class ReasoningBenchmarkError(ValueError):
    """Raised when an agent result violates the OB-002 output contract."""


def _require_text_evidence(element: Mapping[str, Any]) -> str:
    evidence = element.get("text_evidence", [])
    if not evidence or element.get("text_evidence_status") != TEXT_EVIDENCE_MATCHED:
        raise ReasoningBenchmarkError(
            f"element {element.get('element_id')} has no grounded text evidence")
    return "/".join(str(item["text"]) for item in evidence)


def reason_screen_understanding(case_id: str, fused: Mapping[str, Any]) -> dict[str, Any]:
    """Enumerate only what the Vision JSON proves; no screen-name claims."""
    elements = build_grounded_elements(fused)
    grounded = [
        {
            "element_id": element["element_id"],
            "text": _require_text_evidence(element),
            "confidence": element["grounding_confidence"],
        }
        for element in elements
        if element["text_evidence_status"] == TEXT_EVIDENCE_MATCHED
    ]
    unknown = [element["element_id"] for element in elements
               if element["text_evidence_status"] == TEXT_EVIDENCE_UNKNOWN]
    low_confidence_texts = [
        {"text_region_id": region["id"], "text": region["text"],
         "confidence": region["confidence"]}
        for region in fused.get("text_regions", [])
        if region.get("confidence", 1.0) < LOW_CONFIDENCE_THRESHOLD
    ]
    return {
        "case_id": case_id,
        "decision_status": DECISION_REPORT,
        "selected_element_id": None,
        "confidence": 1.0,
        "reasoning_evidence": [
            f"{len(grounded)} interaction candidates have MATCHED text evidence",
            f"{len(unknown)} interaction candidates remain text-evidence UNKNOWN: "
            + ", ".join(unknown),
            f"{len(low_confidence_texts)} text regions fall below the "
            f"{LOW_CONFIDENCE_THRESHOLD} reporting threshold",
        ],
        "grounded_elements": grounded,
        "unresolved_uncertainty": [
            {"kind": "text_evidence_unknown", "element_ids": unknown},
            {"kind": "low_confidence_text", "regions": low_confidence_texts},
            {"kind": "screen_identity", "detail":
                "screen name is not claimable from text regions alone; repeated "
                "text does not prove a title"},
        ],
    }


def reason_target_selection(case_id: str, goal: str, target_text: str,
                            fused: Mapping[str, Any]) -> dict[str, Any]:
    """Select the grounded element whose text evidence matches the goal."""
    elements = build_grounded_elements(fused)
    matches = elements_with_text(elements, target_text)
    if not matches:
        return {
            "case_id": case_id,
            "goal": goal,
            "decision_status": DECISION_NO_TARGET,
            "selected_element_id": None,
            "confidence": 0.0,
            "reasoning_evidence": [
                f"no interaction candidate carries text evidence '{target_text}'"],
            "unresolved_uncertainty": [
                {"kind": "no_grounded_target", "goal": goal}],
        }
    if len(matches) > 1:
        raise ReasoningBenchmarkError(
            f"goal '{target_text}' is ambiguous across {len(matches)} elements")
    element = matches[0]
    evidence_text = _require_text_evidence(element)
    return {
        "case_id": case_id,
        "goal": goal,
        "decision_status": DECISION_GROUNDED,
        "selected_element_id": element["element_id"],
        "confidence": element["grounding_confidence"],
        "reasoning_evidence": [
            f"element {element['element_id']} has MATCHED text evidence '{evidence_text}'",
            f"provenance visual={element['provenance']['visual']}, "
            f"text={element['provenance']['text']}",
            f"grounding_confidence={element['grounding_confidence']} "
            f"(min of visual and text confidence)",
        ],
        "unresolved_uncertainty": [],
    }


def reason_uncertainty_case(case_id: str, goal: str, candidate_ids: Sequence[str],
                            fused: Mapping[str, Any]) -> dict[str, Any]:
    """Textless candidates must stay unresolved, never guessed into a selection."""
    elements = build_grounded_elements(fused)
    by_id = {element["element_id"]: element for element in elements}
    unknown_ids = [
        element_id for element_id in candidate_ids
        if element_id in by_id
        and by_id[element_id]["text_evidence_status"] == TEXT_EVIDENCE_UNKNOWN
    ]
    return {
        "case_id": case_id,
        "goal": goal,
        "decision_status": DECISION_UNKNOWN,
        "selected_element_id": None,
        "confidence": 0.0,
        "reasoning_evidence": [
            f"candidates {', '.join(candidate_ids)} exist visually but carry no "
            "MATCHED text evidence in the Vision JSON",
        ],
        "unresolved_uncertainty": [
            {"kind": "text_evidence_unknown", "element_ids": unknown_ids,
             "detail": "human verification required before any candidate can be "
                       "promoted"},
        ],
    }


def run_benchmark(fused_path: str | Path = FUSED_OB001) -> dict[str, Any]:
    fused = json.loads(Path(fused_path).read_text(encoding="utf-8"))
    cases = [
        reason_screen_understanding("C1_screen_understanding", fused),
        reason_target_selection(
            "C2_target_selection_proceed", "proceed to the next step", "次へ", fused),
        reason_target_selection(
            "C3_target_selection_training", "open training settings", "研修設定", fused),
        reason_uncertainty_case(
            "C4_uncertainty_textless_navigation", "navigate back", ["e11", "e04", "e05"], fused),
        reason_uncertainty_case(
            "C5_uncertainty_no_text_binding", "use the auto-produce control", ["e12"], fused),
    ]
    return {
        "benchmark": "OB-002 Agent Reasoning Benchmark v0.1",
        "source_observation_id": fused["observation_id"],
        "input": str(fused_path),
        "input_scope": "fused VisionObservation JSON only; no screenshot access",
        "cases": cases,
    }


def validate_result(result: Mapping[str, Any]) -> list[str]:
    """Contract checks: ids only, no coordinates/actions/screen names."""
    errors: list[str] = []
    for key in ("case_id", "decision_status", "reasoning_evidence", "unresolved_uncertainty"):
        if key not in result:
            errors.append(f"missing required field '{key}'")
    if result.get("decision_status") == DECISION_GROUNDED:
        if not result.get("selected_element_id"):
            errors.append("GROUNDED_SELECTION requires a selected_element_id")
        if not isinstance(result.get("confidence"), (int, float)) or result["confidence"] <= 0:
            errors.append("GROUNDED_SELECTION requires positive confidence")
    if result.get("decision_status") == DECISION_REPORT:
        if result.get("selected_element_id"):
            errors.append("EVIDENCE_REPORT must not carry a selection")
        if not result.get("unresolved_uncertainty"):
            errors.append("EVIDENCE_REPORT must list unresolved uncertainty")
    if result.get("decision_status") in (DECISION_UNKNOWN, DECISION_NO_TARGET):
        if result.get("selected_element_id"):
            errors.append("UNKNOWN decisions must not carry a selection")
        if not result.get("unresolved_uncertainty"):
            errors.append("UNKNOWN decisions must list unresolved uncertainty")
    serialized = json.dumps(result, ensure_ascii=False)
    if "[" in serialized and '"bbox"' in serialized:
        errors.append("agent results must not embed bbox coordinates")
    for forbidden in ("semantic_state", "screen_name", "action_command",
                      "mouse", "click_at", "state"):
        if f'"{forbidden}"' in serialized:
            errors.append(f"forbidden field '{forbidden}' in agent result")
    return errors


def main() -> None:
    report = run_benchmark()
    failures = [error for case in report["cases"] for error in validate_result(case)]
    if failures:
        raise ReasoningBenchmarkError("; ".join(failures))
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OB-002 report written to {REPORT_PATH}")


if __name__ == "__main__":
    main()
