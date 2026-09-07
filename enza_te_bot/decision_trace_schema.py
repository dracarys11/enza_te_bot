"""Validated, non-authorizing decision traces for offline exploration memory."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


_CLASSIFICATIONS = frozenset({"FACT", "INFERENCE", "UNKNOWN"})
_CHAIN_OF_THOUGHT_FIELDS = frozenset({
    "chain_of_thought", "internal_reasoning", "reasoning_steps",
    "private_reasoning", "thought_process",
})
_AUTHORIZATION_FIELDS = frozenset({
    "authorized", "authorization", "execution_permission", "permission",
})
_UNKNOWN_RESOLUTION_FIELDS = frozenset({
    "resolved_unknowns", "unknowns_resolved", "unknown_resolution",
})
ACTION = "ACTION"
NO_ACTION = "NO_ACTION"
_DECISION_TYPES = frozenset({ACTION, NO_ACTION})


class DecisionTraceSchemaError(ValueError):
    """Raised when a decision trace violates the evidence-only contract."""


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    decision_id: str
    decision_type: str
    observation_id: str
    exploration_objective: str
    candidate_actions: tuple[Any, ...]
    selected_action: Any | None
    evidence_supporting_selection: tuple[Any, ...]
    risk_level: str | None
    expected_transition: str | None
    unknowns_at_decision: tuple[Any, ...]
    verification_criteria: tuple[Any, ...]
    action_reference: Any | None
    transition_reference: Any | None
    rejected_actions: tuple[Any, ...] = ()
    rejection_reasons: tuple[tuple[str, str], ...] = ()
    risk_assessment: str | None = None
    unknowns: tuple[Any, ...] = ()
    authorization_gap: str | None = None
    verification_status: str | None = None
    not_chain_of_thought: bool = True
    executable: bool = False
    planner_objective: str | None = None
    planner_reason: str | None = None
    permitting_gates: tuple[Mapping[str, Any], ...] = ()


def _required_text(data: Mapping[str, Any], field: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DecisionTraceSchemaError(f"{field} is required")
    return value.strip()


def _required_list(data: Mapping[str, Any], field: str, *, nonempty: bool = False) -> tuple[Any, ...]:
    value = data.get(field)
    if not isinstance(value, list) or (nonempty and not value):
        suffix = " and cannot be empty" if nonempty else ""
        raise DecisionTraceSchemaError(f"{field} must be a list{suffix}")
    return tuple(value)


def _required_reference(data: Mapping[str, Any], field: str) -> Any:
    value = data.get(field)
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, Mapping) and value:
        return dict(value)
    raise DecisionTraceSchemaError(f"{field} is required")


def _claim_key(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return repr(value)


def _validate_evidence_boundaries(value: Any, *, path: str = "trace") -> None:
    """Reject hidden reasoning, authorization, and evidence-class promotion."""
    if isinstance(value, Mapping):
        lowered = {str(key).lower(): key for key in value}
        thought_fields = sorted(_CHAIN_OF_THOUGHT_FIELDS.intersection(lowered))
        if thought_fields:
            raise DecisionTraceSchemaError(
                f"chain-of-thought field is forbidden at {path}: {', '.join(thought_fields)}")
        authorization = sorted(_AUTHORIZATION_FIELDS.intersection(lowered))
        if authorization:
            raise DecisionTraceSchemaError(
                f"decision trace cannot authorize actions at {path}: {', '.join(authorization)}")
        resolved_unknowns = sorted(_UNKNOWN_RESOLUTION_FIELDS.intersection(lowered))
        if resolved_unknowns:
            raise DecisionTraceSchemaError(
                f"unknowns cannot be silently resolved at {path}: {', '.join(resolved_unknowns)}")

        classification = value.get("classification")
        if classification is not None:
            normalized = str(classification).upper()
            if normalized not in _CLASSIFICATIONS:
                raise DecisionTraceSchemaError(f"invalid evidence classification at {path}")
            source = str(value.get("source", value.get("provenance", ""))).upper()
            if normalized == "FACT" and source == "USER_REPORTED":
                raise DecisionTraceSchemaError("user-reported evidence cannot become FACT")

        groups: dict[str, set[str]] = {}
        aliases = {
            "FACT": ("facts", "FACT"),
            "INFERENCE": ("inferences", "INFERENCE"),
            "UNKNOWN": ("unknowns", "UNKNOWN"),
        }
        for classification_name, keys in aliases.items():
            items: list[Any] = []
            for key in keys:
                candidate = value.get(key)
                if isinstance(candidate, list):
                    items.extend(candidate)
            groups[classification_name] = {_claim_key(item) for item in items}
        if ((groups["FACT"] & groups["INFERENCE"])
                or (groups["FACT"] & groups["UNKNOWN"])
                or (groups["INFERENCE"] & groups["UNKNOWN"])):
            raise DecisionTraceSchemaError(
                f"evidence cannot cross FACT/INFERENCE/UNKNOWN boundaries at {path}")

        for key, child in value.items():
            _validate_evidence_boundaries(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _validate_evidence_boundaries(child, path=f"{path}[{index}]")


def _normalize_legacy_fields(data: Mapping[str, Any]) -> dict[str, Any]:
    """Map historical artifact names without mutating or promoting evidence."""
    normalized = dict(data)
    if "decision_id" not in normalized and "decision_trace_id" in normalized:
        normalized["decision_id"] = normalized["decision_trace_id"]
    if "action_reference" not in normalized and "action_record" in normalized:
        normalized["action_reference"] = normalized["action_record"]
    if "transition_reference" not in normalized and "transition_record" in normalized:
        normalized["transition_reference"] = normalized["transition_record"]
    if "decision_type" not in normalized:
        normalized["decision_type"] = ACTION
    return normalized


def _action_identity(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, Mapping):
        for field in ("action", "action_id", "name"):
            candidate = value.get(field)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    raise DecisionTraceSchemaError("candidate/rejected action requires a stable identity")


def _validate_no_action(normalized: Mapping[str, Any],
                        candidate_actions: tuple[Any, ...]) -> dict[str, Any]:
    rejected_actions = _required_list(normalized, "rejected_actions", nonempty=True)
    rejection_reasons = normalized.get("rejection_reasons")
    if not isinstance(rejection_reasons, Mapping) or not rejection_reasons:
        raise DecisionTraceSchemaError("rejection_reasons must be a non-empty object")
    candidate_ids = {_action_identity(item) for item in candidate_actions}
    rejected_ids = tuple(_action_identity(item) for item in rejected_actions)
    if any(action_id not in candidate_ids for action_id in rejected_ids):
        raise DecisionTraceSchemaError("rejected_actions must reference candidate_actions")
    reasons: list[tuple[str, str]] = []
    for action_id in rejected_ids:
        reason = rejection_reasons.get(action_id)
        if not isinstance(reason, str) or not reason.strip():
            raise DecisionTraceSchemaError(
                f"missing rejection reason for action {action_id!r}")
        reasons.append((action_id, reason.strip()))

    selected = normalized.get("selected_action")
    if selected not in (None, "", False, NO_ACTION):
        raise DecisionTraceSchemaError("NO_ACTION cannot contain a selected executable action")
    if normalized.get("action_reference") not in (None, "", False):
        raise DecisionTraceSchemaError("NO_ACTION cannot contain an action_reference")

    return {
        "rejected_actions": rejected_actions,
        "rejection_reasons": tuple(reasons),
        "risk_assessment": _required_text(normalized, "risk_assessment"),
        "unknowns": _required_list(normalized, "unknowns"),
        "authorization_gap": _required_text(normalized, "authorization_gap"),
        "verification_status": _required_text(normalized, "verification_status"),
    }


def validate_decision_trace(data: Mapping[str, Any], *,
                            observation_ids: Iterable[str]) -> DecisionTrace:
    """Validate one trace against a caller-supplied observation inventory."""
    normalized = _normalize_legacy_fields(data)
    _validate_evidence_boundaries(normalized)
    if normalized.get("not_chain_of_thought") is not True:
        raise DecisionTraceSchemaError("not_chain_of_thought must be true")
    if normalized.get("executable", False) is not False:
        raise DecisionTraceSchemaError("decision trace must remain non-executable")
    decision_type = _required_text(normalized, "decision_type").upper()
    if decision_type not in _DECISION_TYPES:
        raise DecisionTraceSchemaError(f"unsupported decision_type: {decision_type}")

    observation_id = _required_text(normalized, "observation_id")
    known_observations = {str(item) for item in observation_ids}
    if observation_id not in known_observations:
        raise DecisionTraceSchemaError(
            f"observation reference does not exist: {observation_id}")

    candidate_actions = _required_list(normalized, "candidate_actions", nonempty=True)
    evidence = _required_list(
        normalized, "evidence_supporting_selection", nonempty=True)
    # Legacy traces remain readable; gate evidence never supplies a missing
    # business justification. New split records must carry both planner fields.
    split = {}
    if any(key in normalized for key in ("planner_objective", "planner_reason", "permitting_gates")):
        split["planner_objective"] = _required_text(normalized, "planner_objective")
        split["planner_reason"] = _required_text(normalized, "planner_reason")
        gates = _required_list(normalized, "permitting_gates")
        for gate in gates:
            if not isinstance(gate, Mapping):
                raise DecisionTraceSchemaError("permitting gate must be an object")
            _required_text(gate, "risk_gate")
            _required_text(gate, "risk_reason")
            if gate.get("risk_decision") not in {"ALLOW", "BLOCK"}:
                raise DecisionTraceSchemaError("risk_decision must be ALLOW or BLOCK")
            if "risk_observation" not in gate:
                raise DecisionTraceSchemaError("risk_observation is required")
        split["permitting_gates"] = tuple(dict(gate) for gate in gates)
    common = {
        **split,
        "decision_id": _required_text(normalized, "decision_id"),
        "decision_type": decision_type,
        "observation_id": observation_id,
        "exploration_objective": _required_text(normalized, "exploration_objective"),
        "candidate_actions": candidate_actions,
        "evidence_supporting_selection": evidence,
    }
    if decision_type == NO_ACTION:
        no_action = _validate_no_action(normalized, candidate_actions)
        return DecisionTrace(
            **common,
            selected_action=None,
            risk_level=None,
            expected_transition=None,
            unknowns_at_decision=no_action["unknowns"],
            verification_criteria=(),
            action_reference=None,
            transition_reference=normalized.get("transition_reference"),
            **no_action,
        )

    return DecisionTrace(
        **common,
        selected_action=_required_reference(normalized, "selected_action"),
        risk_level=_required_text(normalized, "risk_level"),
        expected_transition=_required_text(normalized, "expected_transition"),
        unknowns_at_decision=_required_list(normalized, "unknowns_at_decision"),
        verification_criteria=_required_list(
            normalized, "verification_criteria", nonempty=True),
        action_reference=_required_reference(normalized, "action_reference"),
        transition_reference=_required_reference(normalized, "transition_reference"),
    )


def load_decision_trace(path: str | Path, *,
                        observation_ids: Iterable[str]) -> DecisionTrace:
    """Load a historical or canonical JSON trace as offline-only evidence."""
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise DecisionTraceSchemaError("decision trace root must be an object")
    return validate_decision_trace(data, observation_ids=observation_ids)


__all__ = [
    "ACTION", "NO_ACTION", "DecisionTraceSchemaError", "DecisionTrace",
    "validate_decision_trace", "load_decision_trace",
]
