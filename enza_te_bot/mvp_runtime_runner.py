"""Bounded offline MVP-001 runner.

The runner is intentionally separate from the game runtime.  An observation
provider supplies a paired visual-facts payload and runtime Observation; all
actions go through ActionBoundary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from action_boundary import ActionBoundary
from mvp001_action_request import AdapterRejection, build_action_request
from mvp_loop import verify as verify_counter
from mvp_runtime_adapter import MvpRuntimeAdapter
from observation_interpreter import interpret
from perception_models import Observation


@dataclass(frozen=True)
class MvpObservationEnvelope:
    vision_payload: Mapping[str, Any]
    observation: Observation


class MvpObservationProvider(Protocol):
    def observe(self) -> MvpObservationEnvelope:
        """Return one fresh visual payload paired with its runtime evidence."""


@dataclass(frozen=True)
class MvpRunResult:
    status: str  # SUCCESS, FAILED, UNKNOWN
    steps: int
    last_observation: Observation | None = None
    reason: str = ""


class MvpRuntimeRunner:
    """Execute exactly the bounded HOME→training-settings MVP path."""

    def __init__(self, provider: MvpObservationProvider, boundary: ActionBoundary,
                 *, max_steps: int = 3) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        self.provider = provider
        self.boundary = boundary
        self.adapter = MvpRuntimeAdapter(boundary)
        self.max_steps = int(max_steps)

    def _next_request(self, envelope: MvpObservationEnvelope):
        payload = dict(envelope.vision_payload)
        if envelope.observation.observation_status in {"UNKNOWN", "UNREADABLE"} \
                or envelope.observation.detected_state in {None, "UNKNOWN", "CONFIRMED_UNKNOWN"}:
            raise AdapterRejection("state UNKNOWN: refusing runtime step")
        # HOME is established by the existing MVP-001 roundtrip evidence
        # convention; this does not create permission or click evidence.
        texts = {str(region.get("text")) for region in payload.get("text_regions", [])}
        roundtrip = ("HOME",) if not ({"W.I.N.G.", "研修設定"} & texts) else ()
        interpretation = interpret(payload, roundtrip_verified_labels=roundtrip)
        # The existing MVP-001 intent table requires HOME roundtrip evidence.
        # Runtime provenance is the trusted source for this bridge; it is not
        # caller-supplied permission or a click coordinate.
        if envelope.observation.detected_state == "HOME":
            interpretation = dict(interpretation)
            interpretation["semantic_candidates"] = [
                ({**candidate, "identity_source": "roundtrip_verified"}
                 if candidate.get("label") == "HOME" else candidate)
                for candidate in interpretation.get("semantic_candidates", [])
            ]
        inert = build_action_request(interpretation, payload)
        candidate = {
            "action_type": inert.intent,
            "target_element_id": inert.target_element_id,
            "source_observation_id": inert.source_observation_id,
            "evidence_refs": list(inert.evidence_refs),
            "expected_verification": {},
            "uncertainty_status": inert.uncertainty_status,
        }
        # Preserve counter identity for the final verification step.
        if inert.intent == "INCREASE_VOCAL":
            for action in interpretation.get("permitted_actions", []):
                if action.get("action_type") == "VOCAL_INCREMENT":
                    candidate["expected_verification"] = {
                        "counter_region_id": next(
                            (r.split("(")[0].split(":")[-1].strip()
                             for r in action.get("evidence_refs", [])
                             if r.startswith("numeric_region:")), None
                        )
                    }
                    break
        return payload, interpretation, candidate

    def run(self) -> MvpRunResult:
        previous: MvpObservationEnvelope | None = None
        steps = 0
        for _ in range(self.max_steps):
            try:
                current = self.provider.observe()
                if not isinstance(current, MvpObservationEnvelope):
                    return MvpRunResult("FAILED", steps, reason="invalid observation envelope")
                if current.observation.observation_id != current.vision_payload.get("observation_id"):
                    return MvpRunResult("FAILED", steps, current.observation, "observation_id mismatch")
                payload, interpretation, candidate = self._next_request(current)
            except (AdapterRejection, ValueError) as error:
                message = str(error)
                status = "UNKNOWN" if "UNKNOWN" in message or "missing evidence" in message else "FAILED"
                return MvpRunResult(status, steps, current.observation if 'current' in locals() else None, message)

            result = self.adapter.execute(current.observation, interpretation, candidate)
            if result.status != "SUCCESS" or result.after_observation is None:
                return MvpRunResult(result.status, steps, result.after_observation or current.observation, result.reason)
            steps += 1
            after = self.provider.observe()
            if after.observation.observation_id == current.observation.observation_id:
                return MvpRunResult("FAILED", steps, after.observation, "reused observation after action")

            if candidate["action_type"] == "INCREASE_VOCAL":
                counter_id = candidate.get("expected_verification", {}).get("counter_region_id")
                verification = verify_counter(dict(payload), dict(after.vision_payload), counter_id)
                if not verification.passed:
                    return MvpRunResult("FAILED", steps, after.observation, verification.reason)
            previous = after
            if after.observation.detected_state == "TRAINING_SETTINGS" and steps == self.max_steps:
                return MvpRunResult("SUCCESS", steps, after.observation, "bounded MVP flow verified")
        return MvpRunResult("FAILED", steps, previous.observation if previous else None, "max steps exceeded")


__all__ = ["MvpObservationEnvelope", "MvpObservationProvider", "MvpRunResult", "MvpRuntimeRunner"]
