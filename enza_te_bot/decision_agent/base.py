"""Model-agnostic interface and validation for non-executable candidates."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any


class ActionCandidateError(ValueError):
    """Raised when a decision output is ungrounded or malformed."""


ACTION_CANDIDATE_FIELDS = frozenset({
    "candidate_id", "target_element_id", "action_type", "evidence", "confidence",
})


class DecisionAgent(ABC):
    """Reason over existing GroundedElements without executing anything."""

    @abstractmethod
    def decide(self, grounded_elements: Sequence[Mapping[str, Any]],
               user_goal: str) -> dict[str, Any]:
        """Return a validated CLICK candidate or an UNKNOWN result."""
        raise NotImplementedError


def validate_action_candidate(candidate: Mapping[str, Any],
                              grounded_elements: Sequence[Mapping[str, Any]]) -> None:
    unexpected = set(candidate) - ACTION_CANDIDATE_FIELDS
    if unexpected:
        raise ActionCandidateError(
            f"unexpected ActionCandidate fields: {sorted(unexpected)}"
        )
    candidate_id = candidate.get("candidate_id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ActionCandidateError("candidate_id must be a non-empty string")

    action_type = candidate.get("action_type")
    if action_type not in {"CLICK", "UNKNOWN"}:
        raise ActionCandidateError("action_type must be CLICK or UNKNOWN")

    confidence = candidate.get("confidence")
    if not isinstance(confidence, Real) or not 0.0 <= float(confidence) <= 1.0:
        raise ActionCandidateError("confidence must be within [0, 1]")

    evidence = candidate.get("evidence")
    if not isinstance(evidence, list) or not all(
            isinstance(item, str) and item.strip() for item in evidence):
        raise ActionCandidateError("evidence must be a list of non-empty strings")

    target_id = candidate.get("target_element_id")
    if action_type == "UNKNOWN":
        if target_id is not None:
            raise ActionCandidateError("UNKNOWN cannot reference a target element")
        return

    known_ids = {
        str(element.get("element_id"))
        for element in grounded_elements
        if isinstance(element.get("element_id"), str)
    }
    if not isinstance(target_id, str) or target_id not in known_ids:
        raise ActionCandidateError(
            f"target_element_id does not reference an existing GroundedElement: {target_id!r}"
        )
    if not evidence:
        raise ActionCandidateError("CLICK candidate requires grounding evidence")


__all__ = [
    "ACTION_CANDIDATE_FIELDS", "ActionCandidateError", "DecisionAgent",
    "validate_action_candidate",
]
