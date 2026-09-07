"""Validated, non-executable memory for offline environment exploration.

The schema stores auditable exploration evidence without turning observations,
inferences, or user reports into action authorization or production policy.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = 1
FACT = "FACT"
INFERENCE = "INFERENCE"
UNKNOWN = "UNKNOWN"
_FORBIDDEN_AUTHORIZATION_FIELDS = frozenset({
    "authorized", "authorization", "execution_permission", "permission",
})


class ExplorationMemorySchemaError(ValueError):
    """Raised when exploration memory violates its evidence contract."""


def _required_text(data: Mapping[str, Any], field: str, *, context: str) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ExplorationMemorySchemaError(f"{context}.{field} is required")
    return value.strip()


def _required_refs(data: Mapping[str, Any], *, context: str) -> tuple[str, ...]:
    value = data.get("evidence_refs")
    if not isinstance(value, list) or not value:
        raise ExplorationMemorySchemaError(f"{context}.evidence_refs is required")
    refs = tuple(str(item).strip() for item in value)
    if any(not item for item in refs):
        raise ExplorationMemorySchemaError(f"{context}.evidence_refs contains an empty reference")
    return refs


def _reject_authorization_fields(data: Mapping[str, Any], *, context: str) -> None:
    forbidden = sorted(_FORBIDDEN_AUTHORIZATION_FIELDS.intersection(data))
    if forbidden:
        raise ExplorationMemorySchemaError(
            f"{context} cannot contain action authorization: {', '.join(forbidden)}")


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    claim_id: str
    statement: str
    classification: str
    source: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecisionTrace:
    decision_id: str
    observation_id: str
    candidate_actions: tuple[str, ...]
    selected_action: str
    evidence_refs: tuple[str, ...]
    information_gain_category: str
    risk_level: str
    expected_transition: str


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    previous_state: str
    action: str
    next_state: str
    evidence_refs: tuple[str, ...]
    verification_status: str
    unknowns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExplorationSession:
    schema_version: int
    session_id: str
    objective: str
    scope: str
    observations: tuple[Mapping[str, Any], ...]
    decision_traces: tuple[DecisionTrace, ...]
    actions: tuple[Mapping[str, Any], ...]
    transitions: tuple[TransitionRecord, ...]
    verification_records: tuple[Mapping[str, Any], ...]
    facts: tuple[EvidenceClaim, ...]
    inferences: tuple[EvidenceClaim, ...]
    unknowns: tuple[EvidenceClaim, ...]
    stop_reason: str
    executable: bool = False


def _parse_claims(value: object, classification: str) -> tuple[EvidenceClaim, ...]:
    if not isinstance(value, list):
        raise ExplorationMemorySchemaError(f"{classification.lower()}s must be a list")
    claims: list[EvidenceClaim] = []
    for index, item in enumerate(value):
        context = f"{classification.lower()}s[{index}]"
        if not isinstance(item, Mapping):
            raise ExplorationMemorySchemaError(f"{context} must be an object")
        _reject_authorization_fields(item, context=context)
        declared = _required_text(item, "classification", context=context).upper()
        if declared != classification:
            raise ExplorationMemorySchemaError(
                f"{context} classification must remain {classification}")
        source = _required_text(item, "source", context=context)
        if classification == FACT and source.upper() == "USER_REPORTED":
            raise ExplorationMemorySchemaError("user-reported data cannot become FACT")
        claims.append(EvidenceClaim(
            _required_text(item, "claim_id", context=context),
            _required_text(item, "statement", context=context),
            classification,
            source,
            _required_refs(item, context=context),
        ))
    return tuple(claims)


def _parse_decision(item: object, index: int, observation_ids: set[str]) -> DecisionTrace:
    context = f"decision_traces[{index}]"
    if not isinstance(item, Mapping):
        raise ExplorationMemorySchemaError(f"{context} must be an object")
    _reject_authorization_fields(item, context=context)
    observation_id = _required_text(item, "observation_id", context=context)
    if observation_id not in observation_ids:
        raise ExplorationMemorySchemaError(
            f"{context} references missing observation {observation_id!r}")
    candidates = item.get("candidate_actions")
    if not isinstance(candidates, list):
        raise ExplorationMemorySchemaError(f"{context}.candidate_actions must be a list")
    candidate_actions = tuple(str(value).strip() for value in candidates)
    if any(not value for value in candidate_actions):
        raise ExplorationMemorySchemaError(f"{context}.candidate_actions contains an empty action")
    return DecisionTrace(
        _required_text(item, "decision_id", context=context),
        observation_id,
        candidate_actions,
        _required_text(item, "selected_action", context=context),
        _required_refs(item, context=context),
        _required_text(item, "information_gain_category", context=context),
        _required_text(item, "risk_level", context=context),
        _required_text(item, "expected_transition", context=context),
    )


def _parse_transition(item: object, index: int) -> TransitionRecord:
    context = f"transitions[{index}]"
    if not isinstance(item, Mapping):
        raise ExplorationMemorySchemaError(f"{context} must be an object")
    _reject_authorization_fields(item, context=context)
    unknowns = item.get("unknowns")
    if not isinstance(unknowns, list):
        raise ExplorationMemorySchemaError(f"{context}.unknowns must be a list")
    return TransitionRecord(
        _required_text(item, "previous_state", context=context),
        _required_text(item, "action", context=context),
        _required_text(item, "next_state", context=context),
        _required_refs(item, context=context),
        _required_text(item, "verification_status", context=context),
        tuple(str(value) for value in unknowns),
    )


def validate_exploration_session(data: Mapping[str, Any]) -> ExplorationSession:
    """Validate and materialize one offline-only exploration session."""
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ExplorationMemorySchemaError(
            f"unsupported schema_version: {data.get('schema_version')!r}")
    if data.get("executable") is not False:
        raise ExplorationMemorySchemaError("exploration memory must declare executable=false")
    _reject_authorization_fields(data, context="session")

    observations = data.get("observations")
    actions = data.get("actions")
    verification_records = data.get("verification_records")
    for field, value in (
        ("observations", observations), ("actions", actions),
        ("verification_records", verification_records),
    ):
        if not isinstance(value, list):
            raise ExplorationMemorySchemaError(f"{field} must be a list")

    observation_ids: set[str] = set()
    for index, observation in enumerate(observations):
        context = f"observations[{index}]"
        if not isinstance(observation, Mapping):
            raise ExplorationMemorySchemaError(f"{context} must be an object")
        _reject_authorization_fields(observation, context=context)
        observation_id = _required_text(observation, "observation_id", context=context)
        _required_refs(observation, context=context)
        if observation_id in observation_ids:
            raise ExplorationMemorySchemaError(f"duplicate observation_id: {observation_id}")
        observation_ids.add(observation_id)

    for collection_name, collection in (
        ("actions", actions), ("verification_records", verification_records),
    ):
        for index, item in enumerate(collection):
            if not isinstance(item, Mapping):
                raise ExplorationMemorySchemaError(f"{collection_name}[{index}] must be an object")
            _reject_authorization_fields(item, context=f"{collection_name}[{index}]")

    facts = _parse_claims(data.get("facts"), FACT)
    inferences = _parse_claims(data.get("inferences"), INFERENCE)
    unknowns = _parse_claims(data.get("unknowns"), UNKNOWN)
    claim_groups = {
        FACT: {claim.claim_id for claim in facts},
        INFERENCE: {claim.claim_id for claim in inferences},
        UNKNOWN: {claim.claim_id for claim in unknowns},
    }
    if ((claim_groups[FACT] & claim_groups[INFERENCE])
            or (claim_groups[FACT] & claim_groups[UNKNOWN])
            or (claim_groups[INFERENCE] & claim_groups[UNKNOWN])):
        raise ExplorationMemorySchemaError(
            "claim identity cannot cross FACT/INFERENCE/UNKNOWN boundaries")

    decisions_value = data.get("decision_traces")
    transitions_value = data.get("transitions")
    if not isinstance(decisions_value, list):
        raise ExplorationMemorySchemaError("decision_traces must be a list")
    if not isinstance(transitions_value, list):
        raise ExplorationMemorySchemaError("transitions must be a list")

    return ExplorationSession(
        SCHEMA_VERSION,
        _required_text(data, "session_id", context="session"),
        _required_text(data, "objective", context="session"),
        _required_text(data, "scope", context="session"),
        tuple(observations),
        tuple(_parse_decision(item, index, observation_ids)
              for index, item in enumerate(decisions_value)),
        tuple(actions),
        tuple(_parse_transition(item, index)
              for index, item in enumerate(transitions_value)),
        tuple(verification_records),
        facts,
        inferences,
        unknowns,
        _required_text(data, "stop_reason", context="session"),
        False,
    )


def load_exploration_session(path: str | Path) -> ExplorationSession:
    """Load one JSON artifact without granting it execution authority."""
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, Mapping):
        raise ExplorationMemorySchemaError("exploration session root must be an object")
    return validate_exploration_session(data)


__all__ = [
    "SCHEMA_VERSION", "FACT", "INFERENCE", "UNKNOWN",
    "ExplorationMemorySchemaError", "EvidenceClaim", "DecisionTrace",
    "TransitionRecord", "ExplorationSession", "validate_exploration_session",
    "load_exploration_session",
]
