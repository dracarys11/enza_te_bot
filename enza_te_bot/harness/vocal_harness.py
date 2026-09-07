"""Human approval harness for the bounded VOCAL grounded loop.

This module is deliberately simulation-only: it interprets supplied visual
payloads and records proposals/verification, but has no execution method and
does not depend on browser, PyAutoGUI, or ActionBoundary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
from typing import Any, Mapping

from mvp001_action_request import AdapterRejection, build_action_request
from mvp_loop import verify as verify_counter
from observation_interpreter import interpret
from vision_observation_schema import VisionObservation
from .policy import PolicyViolation, load_policy, validate_action, validate_state


@dataclass
class HumanDecisionRecord:
    observation_id: str
    timestamp: str
    current_state: str
    facts: list[str]
    inferences: list[str]
    unknowns: list[str]
    proposed_action: str | None
    target_element_id: str | None
    evidence_refs: list[str]
    expected_result: dict[str, Any]
    verification_rule: dict[str, Any]
    status: str
    policy_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class VocalHarness:
    """Collect observations and human decisions for HOME→VOCAL +1."""

    def __init__(self, *, session_id: str = "vocal_harness_001",
                 storage_dir: str | Path = "enza_memory/harness_sessions") -> None:
        self.session_id = session_id
        self.storage_dir = Path(storage_dir)
        self.path = self.storage_dir / f"{session_id}.json"
        self.observations: list[dict[str, Any]] = []
        self.decisions: list[HumanDecisionRecord] = []
        self.approvals: list[dict[str, Any]] = []
        self.verifications: list[dict[str, Any]] = []
        self.policy = load_policy()

    def _persist(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        document = {
            "session_id": self.session_id,
            "mode": "HUMAN_IN_THE_LOOP_OFFLINE",
            "observations": self.observations,
            "decisions": [item.as_dict() for item in self.decisions],
            "approvals": self.approvals,
            "verifications": self.verifications,
        }
        fd, temporary = tempfile.mkstemp(prefix=f".{self.session_id}.", suffix=".tmp", dir=self.storage_dir)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                json.dump(document, handle, ensure_ascii=False, indent=2)
                handle.flush()
            Path(temporary).replace(self.path)
        finally:
            temporary_path = Path(temporary)
            if temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def _home_roundtrip(interpretation: dict[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
        """Use the existing MVP-001 HOME evidence requirement."""
        result = dict(interpretation)
        texts = {str(region.get("text")) for region in payload.get("text_regions", [])}
        if "ホーム" in texts and not ({"W.I.N.G.", "研修設定"} & texts):
            result["semantic_candidates"] = [
                ({**candidate, "identity_source": "roundtrip_verified"}
                 if candidate.get("label") == "HOME" else candidate)
                for candidate in result.get("semantic_candidates", [])
            ]
        return result

    def submit_observation(self, payload: Mapping[str, Any]) -> HumanDecisionRecord:
        """Record one supplied observation and create at most one proposal."""
        raw = dict(payload)
        observation = VisionObservation.from_payload(raw)
        self.observations.append(raw)
        texts = {str(region.get("text")) for region in raw.get("text_regions", [])}
        roundtrip = ("HOME",) if "ホーム" in texts and not ({"W.I.N.G.", "研修設定"} & texts) else ()
        interpretation = interpret(raw, roundtrip_verified_labels=roundtrip)
        interpretation = self._home_roundtrip(interpretation, raw)
        candidates = interpretation.get("semantic_candidates", [])
        state = candidates[0].get("label") if len(candidates) == 1 else "UNKNOWN"
        facts = list(interpretation.get("visible_facts", []))
        unknowns = list(interpretation.get("unknowns", []))
        proposed: str | None = None
        target: str | None = None
        evidence: list[str] = []
        expected: dict[str, Any] = {}
        rule: dict[str, Any] = {}
        status = "STOPPED_UNKNOWN"

        try:
            validate_state(str(state), self.policy)
        except PolicyViolation as error:
            record = HumanDecisionRecord(observation.observation_id, observation.capture["timestamp"],
                                         str(state), facts, [str(c) for c in candidates], unknowns,
                                         None, None, [], {}, {}, "REJECTED", self.policy["policy_id"])
            unknowns.append(str(error))
            record.unknowns = unknowns
            self.decisions.append(record)
            self._persist()
            return record

        blocking_unknowns = [u for u in unknowns
                             if "no unresolved identity questions" not in u
                             and "small_description_text_not_requested" not in u]
        if state in {"HOME", "WING_SELECTION", "TRAINING_SETTINGS"} and not blocking_unknowns:
            try:
                inert = build_action_request(interpretation, raw)
                proposed = {"PRODUCE_OPEN": "produce_open", "OPEN_TRAINING_SETTINGS": "open_training_settings",
                            "INCREASE_VOCAL": "vocal_plus"}.get(inert.intent, inert.intent)
                validate_action(proposed, self.policy)
                target = inert.target_element_id
                evidence = list(inert.evidence_refs)
                expected = {"destination": {"PRODUCE_OPEN": "WING_SELECTION",
                                             "OPEN_TRAINING_SETTINGS": "TRAINING_SETTINGS",
                                             "INCREASE_VOCAL": "TRAINING_SETTINGS"}[inert.intent]}
                if inert.intent == "INCREASE_VOCAL":
                    rule = {"type": "counter_delta", "delta": 1}
                status = "PROPOSED"
            except (AdapterRejection, PolicyViolation) as error:
                unknowns.append(str(error))
                status = "REJECTED" if isinstance(error, PolicyViolation) else "STOPPED_MISSING_EVIDENCE"
        record = HumanDecisionRecord(observation.observation_id,
                                     observation.capture["timestamp"], str(state), facts,
                                     [str(c) for c in candidates], unknowns, proposed, target,
                                     evidence, expected, rule, status,
                                     self.policy["policy_id"] if status == "REJECTED" else None)
        self.decisions.append(record)
        self._persist()
        return record

    def _decision(self, action_id: str) -> HumanDecisionRecord:
        for decision in reversed(self.decisions):
            candidate_id = f"HD-{decision.observation_id}-{decision.proposed_action}"
            if candidate_id == action_id or decision.observation_id == action_id:
                return decision
        raise KeyError(f"unknown action id: {action_id}")

    def approve_action(self, action_id: str) -> HumanDecisionRecord:
        decision = self._decision(action_id)
        if decision.status != "PROPOSED":
            raise ValueError("only proposed actions may be approved")
        decision.status = "APPROVED"
        self.approvals.append({"action_id": action_id, "approved_by_human": True,
                               "timestamp": datetime.now(timezone.utc).isoformat()})
        self._persist()
        return decision

    def reject_action(self, action_id: str, reason: str) -> HumanDecisionRecord:
        decision = self._decision(action_id)
        decision.status = "REJECTED"
        self.approvals.append({"action_id": action_id, "approved_by_human": False,
                               "reason": str(reason), "timestamp": datetime.now(timezone.utc).isoformat()})
        self._persist()
        return decision

    def verify_transition(self, before_observation: Mapping[str, Any],
                          after_observation: Mapping[str, Any]) -> dict[str, Any]:
        """Verify only the VOCAL counter delta; never executes an action."""
        result = verify_counter(dict(before_observation), dict(after_observation))
        record = {"before_observation_id": before_observation.get("observation_id"),
                  "after_observation_id": after_observation.get("observation_id"),
                  "passed": result.passed, "counter_id": result.counter_id,
                  "old_value": result.old_value, "new_value": result.new_value,
                  "reason": result.reason}
        self.verifications.append(record)
        self._persist()
        return record


__all__ = ["HumanDecisionRecord", "VocalHarness"]
