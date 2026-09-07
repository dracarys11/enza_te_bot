"""ZCode observation loop for the VOCAL MVP (perception only).

Flow implemented:

    screenshot (already captured by ZCode, path given)
        -> VisionAdapter.analyze_screenshot()          [external analyzer]
        -> ObservationInterpreter (observation_interpreter)
        -> Vocal MVP policy (mvp001_action_request)     [request only]
        -> HumanDecisionRecord (STATE / ACTION REQUEST blocks)

Hard boundaries:
- UNKNOWN state STOPS the loop: no action request is produced
- no execution, no clicks, no browser automation, no ActionBoundary
  integration, no Planner changes
- the screenshot filename is never used as state evidence

Every run stores a JSON record under enza_memory/harness_sessions/.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from mvp001_action_request import ActionRequest, AdapterRejection, build_action_request
from observation_interpreter import interpret
from vision_adapter import VisionAdapter

HARNESS_SESSIONS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "enza_memory", "harness_sessions"
)


@dataclass(frozen=True)
class HumanDecisionRecord:
    """The human-readable decision surface: state, then (maybe) an action request."""

    observation_id: str
    state_label: str
    fact: list[str]
    inference: list[str]
    unknown: list[str]
    action_request: dict[str, Any] | None  # None when the loop stopped on UNKNOWN
    record_path: str

    def render(self) -> str:
        lines = [
            f"STATE: {self.state_label}",
            "FACT:",
            *(f"  - {f}" for f in self.fact),
            "INFERENCE:",
            *(f"  - {i}" for i in self.inference),
            "UNKNOWN:",
            *(f"  - {u}" for u in self.unknown),
            "",
        ]
        if self.action_request is None:
            lines.append("ACTION REQUEST: NONE (loop stopped: state UNKNOWN or inadmissible)")
        else:
            request = self.action_request
            lines += [
                "ACTION REQUEST:",
                f"  INTENT: {request['intent']}",
                f"  TARGET: element_id={request['target_element_id']} (no coordinates in this record)",
                "  EVIDENCE:",
                *(f"    - {ref}" for ref in request["evidence_refs"]),
                f"  EXPECTED RESULT: {request['expected_result']}",
                f"  VERIFICATION: {request['verification']}",
                f"  UNCERTAINTY: {request['uncertainty_status']}",
            ]
        lines.append(f"\nRECORD: {self.record_path}")
        return "\n".join(lines)


def run_observation_loop(
    screenshot_path: str,
    adapter: VisionAdapter,
    *,
    roundtrip_verified_labels: tuple[str, ...] = (),
    sessions_dir: str = HARNESS_SESSIONS_DIR,
) -> HumanDecisionRecord:
    """One perception pass: screenshot -> observation -> interpretation -> request-or-stop."""
    observation = adapter.analyze_screenshot(screenshot_path)
    vision_payload = {
        "observation_id": observation.observation_id,
        "capture": observation.capture,
        "viewport": observation.viewport,
        "text_regions": observation.text_regions,
        "interaction_candidates": observation.interaction_candidates,
        "numeric_regions": observation.numeric_regions,
        "overlay_regions": observation.overlay_regions,
        "uncertainties": observation.uncertainties,
        "visual_changes": observation.visual_changes,
    }

    interpretation = interpret(vision_payload, roundtrip_verified_labels=roundtrip_verified_labels)

    fact = list(interpretation["visible_facts"])
    candidates = interpretation["semantic_candidates"]
    if candidates:
        state_label = candidates[0]["label"]
        inference = [
            f"state candidate '{c['label']}' via {c['identity_source']} "
            f"(confidence {c['confidence']}) — evidence: {', '.join(c['evidence_refs'])}"
            for c in candidates
        ]
    else:
        state_label = "UNKNOWN"
        inference = ["no admissible state candidate"]

    action_request: dict[str, Any] | None = None
    stopped_reason = None
    if not candidates:
        stopped_reason = "state UNKNOWN — no action request produced"
    else:
        try:
            request: ActionRequest = build_action_request(interpretation, vision_payload)
            action_request = {
                "request_id": request.request_id,
                "intent": request.intent,
                "target_element_id": request.target_element_id,
                "source_observation_id": request.source_observation_id,
                "evidence_refs": list(request.evidence_refs),
                "expected_result": (
                    "vocal counter increments by exactly 1 (0/20 -> 1/20) at the same location"
                    if request.intent == "INCREASE_VOCAL"
                    else "screen transition to the next MVP-loop state (verified by next observation)"
                ),
                "verification": (
                    "same-bbox counter delta +1 in the post-action observation; "
                    "identity of new screen requires title text — never coordinates"
                ),
                "uncertainty_status": request.uncertainty_status,
            }
        except AdapterRejection as error:
            stopped_reason = f"adapter refused: {error}"

    record = {
        "screenshot_path": os.path.abspath(screenshot_path),
        "observation_id": observation.observation_id,
        "vision_response": vision_payload,
        "interpretation": interpretation,
        "decision": {
            "state_label": state_label,
            "action_request": action_request,
            "stopped_reason": stopped_reason,
            "executed": False,  # perception only, always
        },
    }
    os.makedirs(sessions_dir, exist_ok=True)
    record_path = os.path.join(sessions_dir, f"{observation.observation_id}.json")
    with open(record_path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)

    unknown = list(interpretation["unknowns"])
    if stopped_reason:
        unknown.append(stopped_reason)

    return HumanDecisionRecord(
        observation_id=observation.observation_id,
        state_label=state_label,
        fact=fact,
        inference=inference,
        unknown=unknown,
        action_request=action_request,
        record_path=record_path,
    )
