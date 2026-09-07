"""Interactive, human-controlled VOCAL MVP session.

The command observes supplied screenshot/payload evidence, proposes an action,
records human approval, and verifies a later operator-supplied observation. It
never invokes a click or execution API.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from vision_adapter import VisionAdapter, VisionAdapterError
from vision_observation_schema import VisionObservation
try:  # supports both `python -m harness.run_vocal_manual` and direct script use
    from .vocal_harness import HumanDecisionRecord, VocalHarness
except ImportError:  # pragma: no cover - direct CLI path
    from harness.vocal_harness import HumanDecisionRecord, VocalHarness


def _payload_analyzer(payload_path: str) -> Callable[[str], dict[str, Any]]:
    path = Path(payload_path)
    def analyze(_screenshot: str) -> dict[str, Any]:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise VisionAdapterError("observation payload must be an object")
        return value
    return analyze


def load_observation(*, screenshot_path: str | None = None,
                     payload_path: str | None = None) -> tuple[VisionObservation, dict[str, Any]]:
    """Load a contract observation from a payload, optionally bound to a screenshot."""
    if payload_path:
        if screenshot_path:
            observation = VisionAdapter(_payload_analyzer(payload_path)).analyze_screenshot(screenshot_path)
        else:
            with Path(payload_path).open(encoding="utf-8") as handle:
                raw = json.load(handle)
            observation = VisionObservation.from_payload(raw)
    else:
        raise VisionAdapterError("a contract payload is required (use --observation-json)")
    payload = {"observation_id": observation.observation_id, "capture": observation.capture,
               "viewport": observation.viewport, "text_regions": observation.text_regions,
               "interaction_candidates": observation.interaction_candidates,
               "numeric_regions": observation.numeric_regions, "overlay_regions": observation.overlay_regions,
               "uncertainties": observation.uncertainties, "visual_changes": observation.visual_changes}
    return observation, payload


def render_decision(record: HumanDecisionRecord) -> str:
    lines = [f"Observation: {record.observation_id}", f"State: {record.current_state}", "FACT:"]
    lines.extend(f"  - {fact}" for fact in record.facts)
    lines.append("UNKNOWN:")
    lines.extend(f"  - {item}" for item in record.unknowns)
    lines.append(f"Decision: {record.status}")
    if record.proposed_action:
        lines.extend([f"ACTION_PROPOSAL: {record.proposed_action}",
                      f"target_element_id: {record.target_element_id}",
                      f"evidence: {record.evidence_refs}",
                      f"expected: {record.expected_result}",
                      f"verification: {record.verification_rule}"])
    return "\n".join(lines)


def run_manual(*, first_payload: str, screenshot: str | None = None,
               harness: VocalHarness | None = None,
               input_fn: Callable[[str], str] = input) -> VocalHarness:
    session = harness or VocalHarness()
    _observation, before = load_observation(screenshot_path=screenshot, payload_path=first_payload)
    record = session.submit_observation(before)
    print(render_decision(record))
    if not record.proposed_action:
        return session
    command = input_fn("Type approve, reject, or provide_next_observation: ").strip().lower()
    if command == "approve":
        session.approve_action(record.observation_id)
    elif command == "reject":
        session.reject_action(record.observation_id, input_fn("Reason: "))
        return session
    elif command == "provide_next_observation":
        pass
    else:
        print("No approval recorded; stopping.")
        return session
    next_path = input_fn("Path to next observation JSON: ").strip()
    _after_observation, after = load_observation(payload_path=next_path)
    print("Verification:", session.verify_transition(before, after))
    return session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline human-controlled VOCAL MVP harness")
    parser.add_argument("--observation-json", required=True, help="contract VisionObservation JSON")
    parser.add_argument("--screenshot", help="optional screenshot path bound to the payload")
    args = parser.parse_args(argv)
    try:
        run_manual(first_payload=args.observation_json, screenshot=args.screenshot)
    except (OSError, ValueError, VisionAdapterError) as error:
        print(f"HARNESS_ERROR: {error}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
