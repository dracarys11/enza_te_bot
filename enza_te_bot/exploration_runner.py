"""Bounded navigation-only exploration runner.

This prototype executes one caller-supplied, fixed scenario through an
EnvironmentProvider.  It contains no planner or strategy selection.  The
repository does not yet include a ZCode provider; a future adapter can use this
runner without changing its observation/action/verification/memory lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
from typing import Any, Iterable, Mapping, Sequence

from decision_trace_schema import validate_decision_trace
from environment_provider import ActionIntent, EnvironmentProvider
from exploration_memory_schema import validate_exploration_session
from perception_models import Observation


NAVIGATION_ONLY = "NAVIGATION_ONLY"
AUTHORIZED_NAVIGATION_ACTIONS = frozenset({"produce_open", "preparation_next"})
RESOURCE_CONFIRMATION_STATES = frozenset({
    "WING_CONFIRMATION_DIALOG", "PRODUCTION_CONFIRMATION",
    "RESOURCE_CONFIRMATION",
})
UNKNOWN_STATES = frozenset({"UNKNOWN", "CONFIRMED_UNKNOWN", "UNREADABLE"})


@dataclass(frozen=True, slots=True)
class NavigationStep:
    source_state: str
    action_name: str
    expected_state: str
    candidate_actions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    uncertainty: str
    information_gain_category: str = "MAP_NEXT_STATE"
    risk_level: str = "LOW"
    coordinate: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class ExplorationRunResult:
    session_id: str
    stop_reason: str
    final_state: str
    actions_executed: int
    memory_path: str


WING_PREPARATION_SCENARIO = (
    NavigationStep(
        "HOME", "produce_open", "PRODUCE_SELECTION",
        ("produce_open", "stop"), ("environment_map_progress:HOME",),
        "produce entry may contain provider-local loading frames",
    ),
    NavigationStep(
        "PRODUCE_SELECTION", "preparation_next", "UNIT_FORMATION",
        ("preparation_next", "stop"), ("OBS_20260903060500",),
        "destination was observed once and remains session-scoped evidence",
    ),
    NavigationStep(
        "UNIT_FORMATION", "preparation_next", "ITEM_SELECTION",
        ("preparation_next", "stop"), ("OBS_20260903060520",),
        "destination was observed once and remains session-scoped evidence",
    ),
    NavigationStep(
        "ITEM_SELECTION", "preparation_next", "WING_CONFIRMATION_DIALOG",
        ("preparation_next", "stop"), ("OBS_20260903060545",),
        "the next page is a resource boundary and must never be confirmed",
        risk_level="HIGH_BOUNDARY_ONLY",
    ),
)


def _state(observation: Observation) -> str:
    return str(observation.detected_state or "UNKNOWN")


def _observation_ref(observation: Observation) -> str:
    return observation.screenshot_path or f"observation:{observation.observation_id}"


def _is_unknown(observation: Observation) -> bool:
    return (observation.observation_status in UNKNOWN_STATES
            or _state(observation) in UNKNOWN_STATES)


def _is_unexpected_modal(state: str) -> bool:
    upper = state.upper()
    return ((upper.endswith("_MODAL") or upper.endswith("_DIALOG"))
            and upper not in RESOURCE_CONFIRMATION_STATES)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(6)}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


class ExplorationRunner:
    """Execute a fixed navigation scenario and persist evidence-only memory."""

    def __init__(self, provider: EnvironmentProvider, *,
                 scenario: Sequence[NavigationStep] = WING_PREPARATION_SCENARIO,
                 output_directory: str | Path = "enza_memory/exploration_sessions") -> None:
        self.provider = provider
        self.scenario = tuple(scenario)
        self.output_directory = Path(output_directory)
        unsupported = sorted({step.action_name for step in self.scenario}
                             - AUTHORIZED_NAVIGATION_ACTIONS)
        if unsupported:
            raise ValueError(
                "scenario contains non-navigation action(s): " + ", ".join(unsupported))

    def run(self, *, session_id: str | None = None) -> ExplorationRunResult:
        session_id = session_id or f"EXP_{datetime.now():%Y%m%d_%H%M%S_%f}"
        observations: list[dict[str, Any]] = []
        decisions: list[dict[str, Any]] = []
        actions: list[dict[str, Any]] = []
        transitions: list[dict[str, Any]] = []
        verifications: list[dict[str, Any]] = []
        unknown_claims: list[dict[str, Any]] = []
        recorded_observations: set[str] = set()

        def record_observation(observation: Observation) -> None:
            if observation.observation_id in recorded_observations:
                return
            recorded_observations.add(observation.observation_id)
            observations.append({
                "observation_id": observation.observation_id,
                "state": _state(observation),
                "status": observation.observation_status,
                "evidence_refs": [_observation_ref(observation)],
                "observation": observation.as_dict(),
            })

        current = self.provider.observe()
        record_observation(current)
        stop_reason = "SCENARIO_EXHAUSTED"

        for step_index, step in enumerate(self.scenario, start=1):
            current_state = _state(current)
            if _is_unknown(current):
                stop_reason = "UNKNOWN_STATE"
                unknown_claims.append(self._unknown_claim(
                    session_id, len(unknown_claims) + 1,
                    f"state at step {step_index} is unknown", current,
                ))
                break
            if current_state in RESOURCE_CONFIRMATION_STATES:
                stop_reason = "RESOURCE_CONFIRMATION_REACHED"
                break
            if _is_unexpected_modal(current_state):
                stop_reason = "UNEXPECTED_MODAL"
                break
            if current_state != step.source_state:
                stop_reason = "UNEXPECTED_STATE"
                unknown_claims.append(self._unknown_claim(
                    session_id, len(unknown_claims) + 1,
                    f"expected {step.source_state}, observed {current_state}", current,
                ))
                break

            action_id = f"{session_id}:ACT:{step_index:03d}"
            decision_id = f"{session_id}:DT:{step_index:03d}"
            transition_id = f"{session_id}:TR:{step_index:03d}"
            verification_id = f"{session_id}:VER:{step_index:03d}"
            intent = ActionIntent(
                step.action_name,
                coordinate=step.coordinate,
                expected_state=step.expected_state,
                metadata={"scope": NAVIGATION_ONLY, "scenario_step": step_index},
            )
            result = self.provider.execute(intent)
            after = result.after_observation or self.provider.observe()
            record_observation(after)
            verification = self.provider.verify(result)
            after_state = _state(after)
            evidence_refs = tuple(dict.fromkeys((
                *step.evidence_refs, _observation_ref(current),
                _observation_ref(after),
            )))

            action_record = {
                "action_id": action_id,
                "action_intent_id": intent.action_intent_id,
                "requested_action": step.action_name,
                "performed": bool(result.issued),
                "before_observation_id": current.observation_id,
                "after_observation_id": after.observation_id,
                "evidence_refs": list(evidence_refs),
                "scope": NAVIGATION_ONLY,
            }
            transition_record = {
                "transition_id": transition_id,
                "previous_state": current_state,
                "action": step.action_name,
                "next_state": after_state,
                "evidence_refs": list(evidence_refs),
                "verification_status": "VERIFIED" if verification.verified else "FAILED",
                "unknowns": [] if verification.verified else [verification.detail or "verification failed"],
            }
            decision_record = {
                "decision_id": decision_id,
                "decision_type": "ACTION",
                "observation_id": current.observation_id,
                "exploration_objective": "advance the fixed WING preparation navigation path",
                "candidate_actions": list(step.candidate_actions),
                "selected_action": step.action_name,
                "evidence_supporting_selection": list(evidence_refs),
                "evidence_refs": list(evidence_refs),
                "information_gain_category": step.information_gain_category,
                "risk_level": step.risk_level,
                "expected_transition": f"{step.source_state} -> {step.expected_state}",
                "unknowns_at_decision": [step.uncertainty],
                "verification_criteria": [
                    "fresh post-action observation",
                    f"detected state equals {step.expected_state}",
                ],
                "action_reference": action_id,
                "transition_reference": transition_id,
                "not_chain_of_thought": True,
                "executable": False,
            }
            validate_decision_trace(
                decision_record, observation_ids=recorded_observations)
            decisions.append(decision_record)
            actions.append(action_record)
            transitions.append(transition_record)
            verifications.append({
                "verification_id": verification_id,
                "status": "VERIFIED" if verification.verified else "FAILED",
                "observation_id": after.observation_id,
                "evidence_refs": list(evidence_refs),
                "detail": verification.detail,
            })

            if not result.issued:
                stop_reason = "ACTION_NOT_ISSUED"
                break
            if _is_unknown(after):
                stop_reason = "UNKNOWN_STATE"
                unknown_claims.append(self._unknown_claim(
                    session_id, len(unknown_claims) + 1,
                    f"post-action state after {step.action_name} is unknown", after,
                ))
                current = after
                break
            if after_state in RESOURCE_CONFIRMATION_STATES:
                stop_reason = "RESOURCE_CONFIRMATION_REACHED"
                current = after
                break
            if _is_unexpected_modal(after_state):
                stop_reason = "UNEXPECTED_MODAL"
                current = after
                break
            if not verification.verified or after_state != step.expected_state:
                stop_reason = "TRANSITION_VERIFICATION_FAILED"
                current = after
                break
            current = after

        memory = {
            "schema_version": 1,
            "executable": False,
            "session_id": session_id,
            "objective": "map the bounded HOME-to-WING-preparation navigation path",
            "scope": NAVIGATION_ONLY,
            "observations": observations,
            "decision_traces": decisions,
            "actions": actions,
            "transitions": transitions,
            "verification_records": verifications,
            "facts": [],
            "inferences": [],
            "unknowns": unknown_claims,
            "stop_reason": stop_reason,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        validate_exploration_session(memory)
        memory_path = self.output_directory / f"{session_id}.json"
        _atomic_write_json(memory_path, memory)
        return ExplorationRunResult(
            session_id, stop_reason, _state(current), len(actions), str(memory_path),
        )

    @staticmethod
    def _unknown_claim(session_id: str, index: int, statement: str,
                       observation: Observation) -> dict[str, Any]:
        return {
            "claim_id": f"{session_id}:UNKNOWN:{index:03d}",
            "statement": statement,
            "classification": "UNKNOWN",
            "source": "PROVIDER_OBSERVATION",
            "evidence_refs": [_observation_ref(observation)],
        }


__all__ = [
    "NAVIGATION_ONLY", "AUTHORIZED_NAVIGATION_ACTIONS",
    "RESOURCE_CONFIRMATION_STATES", "UNKNOWN_STATES", "NavigationStep",
    "ExplorationRunResult", "WING_PREPARATION_SCENARIO", "ExplorationRunner",
]
