"""Offline MVP runtime adapter.

This is a deliberately thin bridge between the observation interpreter and the
existing ActionBoundary.  It does not choose strategy and it never calls a
provider directly; the boundary remains the only execution path.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from action_boundary import ActionBoundary, ActionRequest, BoundaryExecutionResult
from environment_provider import ActionIntent
from mvp_loop import ActionRequestCandidate
from perception_models import ActionTarget, Observation


class MvpAdapterError(ValueError):
    """The interpreter output cannot be turned into a safe request."""


@dataclass(frozen=True)
class MvpRuntimeResult:
    status: str  # SUCCESS, FAILED, or UNKNOWN
    request: ActionRequest | None = None
    boundary_result: BoundaryExecutionResult | None = None
    after_observation: Observation | None = None
    reason: str = ""


_EXPECTED_STATES = {
    "PRODUCE_OPEN": "WING_SELECTION",
    "OPEN_TRAINING_SETTINGS": "TRAINING_SETTINGS",
    "VOCAL_INCREMENT": "TRAINING_SETTINGS",
    "INCREASE_VOCAL": "TRAINING_SETTINGS",
}


def _candidate_dict(candidate: ActionRequestCandidate | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(candidate, Mapping):
        return dict(candidate)
    return {
        "action_type": candidate.action_type,
        "target_element_id": candidate.target_element_id,
        "source_observation_id": candidate.source_observation_id,
        "evidence_refs": list(candidate.evidence_refs),
        "expected_verification": dict(candidate.expected_verification),
        "uncertainty_status": candidate.uncertainty_status,
    }


def _select_candidate(interpretation: Mapping[str, Any], candidate: Any = None) -> dict[str, Any]:
    if candidate is not None:
        return _candidate_dict(candidate)
    actions = interpretation.get("permitted_actions")
    if not isinstance(actions, list) or len(actions) != 1:
        raise MvpAdapterError("action candidate is missing or ambiguous")
    return _candidate_dict(actions[0])


def build_action_request(observation: Observation, interpretation: Mapping[str, Any],
                         candidate: ActionRequestCandidate | Mapping[str, Any] | None = None) -> ActionRequest:
    """Convert one interpreter candidate into an inert boundary request."""
    if observation.observation_status in {"UNKNOWN", "UNREADABLE"} or observation.detected_state in {
        None, "UNKNOWN", "CONFIRMED_UNKNOWN",
    }:
        raise MvpAdapterError("UNKNOWN observation cannot execute")
    if interpretation.get("observation_id") != observation.observation_id:
        raise MvpAdapterError("interpretation/observation_id mismatch")

    item = _select_candidate(interpretation, candidate)
    action_name = str(item.get("action_type", ""))
    target_id = str(item.get("target_element_id", ""))
    source_id = str(item.get("source_observation_id") or observation.observation_id)
    evidence = item.get("evidence_refs")
    if not action_name or not target_id or source_id != observation.observation_id:
        raise MvpAdapterError("missing action evidence or observation id")
    if not isinstance(evidence, (list, tuple)) or not evidence or not all(str(x).strip() for x in evidence):
        raise MvpAdapterError("missing action evidence")
    # A runtime element is mandatory.  The adapter intentionally does not
    # turn a bare coordinate or an ungrounded id into an executable target.
    element = observation.element(target_id)
    if element is None:
        raise MvpAdapterError("coordinate-only or unresolved target")
    metadata = element.metadata if isinstance(element.metadata, Mapping) else {}
    if str(metadata.get("source", "")).upper() in {"SCREENSHOT", "ARTIFACT"}:
        raise MvpAdapterError("target lacks calibrated runtime evidence")
    if str(metadata.get("verification_level", "")).upper() != "CALIBRATED" and \
            str(metadata.get("calibration_status", "")).upper() != "CALIBRATED":
        raise MvpAdapterError("target lacks calibrated runtime evidence")

    expected = _EXPECTED_STATES.get(action_name)
    intent = ActionIntent(
        action_name=action_name,
        target=ActionTarget(runtime_element_id=target_id),
        expected_state=expected,
        metadata={"room": "MVP_WING", "evidence_refs": tuple(str(x) for x in evidence)},
        action_intent_id=f"intent:{observation.observation_id}:{action_name}",
    )
    target_identity = f"element:{target_id}"
    return ActionRequest(
        action_id=f"request:{observation.observation_id}:{action_name}",
        intent=intent,
        target=target_identity,
        source_observation_id=observation.observation_id,
        target_evidence="; ".join(str(x) for x in evidence),
        scope="MVP_WING",
    )


class MvpRuntimeAdapter:
    """One bounded step through ActionBoundary, with post-action checks."""

    def __init__(self, boundary: ActionBoundary) -> None:
        self.boundary = boundary

    def execute(self, observation: Observation, interpretation: Mapping[str, Any],
                candidate: ActionRequestCandidate | Mapping[str, Any] | None = None) -> MvpRuntimeResult:
        try:
            request = build_action_request(observation, interpretation, candidate)
        except MvpAdapterError as error:
            return MvpRuntimeResult("UNKNOWN" if "UNKNOWN" in str(error) else "FAILED", reason=str(error))

        permission = self.boundary.authorize(request, observation)
        if permission is None:
            return MvpRuntimeResult("UNKNOWN", request=request, reason="ACTION_BOUNDARY_NOT_APPROVED")
        result = self.boundary.execute(request, observation, permission)
        if not result.approved or result.after_observation is None:
            return MvpRuntimeResult("FAILED", request=request, boundary_result=result,
                                    after_observation=result.after_observation,
                                    reason=result.reason or "ACTION_EFFECT_NOT_VERIFIED")
        after = result.after_observation
        expected = request.intent.expected_state
        if expected and after.detected_state != expected:
            return MvpRuntimeResult("FAILED", request=request, boundary_result=result,
                                    after_observation=after,
                                    reason=f"expected {expected}, found {after.detected_state}")
        if after.observation_status in {"UNKNOWN", "UNREADABLE"} or after.detected_state in {"UNKNOWN", "CONFIRMED_UNKNOWN"}:
            return MvpRuntimeResult("UNKNOWN", request=request, boundary_result=result,
                                    after_observation=after, reason="post-action observation unknown")
        return MvpRuntimeResult("SUCCESS", request=request, boundary_result=result,
                                after_observation=after, reason="verified new observation")


__all__ = ["MvpAdapterError", "MvpRuntimeResult", "build_action_request", "MvpRuntimeAdapter"]
