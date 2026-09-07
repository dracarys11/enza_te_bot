"""Evidence-bound decision agent for offline evaluation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .base import DecisionAgent, validate_action_candidate


@dataclass(frozen=True)
class GroundedDecisionAgent(DecisionAgent):
    """Resolve configured goals only through exact GroundedElement text evidence."""

    target_text_by_goal: Mapping[str, str | Sequence[str]]

    @staticmethod
    def _unknown(elements: Sequence[Mapping[str, Any]], reason: str) -> dict[str, Any]:
        candidate = {
            "candidate_id": "AC_UNKNOWN",
            "target_element_id": None,
            "action_type": "UNKNOWN",
            "evidence": [f"missing evidence: {reason}"],
            "confidence": 0.0,
        }
        validate_action_candidate(candidate, elements)
        return candidate

    def decide(self, grounded_elements: Sequence[Mapping[str, Any]],
               user_goal: str) -> dict[str, Any]:
        if not isinstance(user_goal, str) or not user_goal.strip():
            return self._unknown(grounded_elements, "user goal is empty")
        configured = self.target_text_by_goal.get(user_goal)
        if not configured:
            return self._unknown(grounded_elements, "goal has no grounded text requirement")
        target_texts = (
            (configured,) if isinstance(configured, str)
            else tuple(text for text in configured if isinstance(text, str) and text)
        )
        if not target_texts:
            return self._unknown(grounded_elements, "goal has no grounded text requirement")

        matches = [
            element for element in grounded_elements
            if any(
                evidence.get("text") in target_texts
                for evidence in element.get("text_evidence", [])
                if isinstance(evidence, Mapping)
            )
        ]
        if not matches:
            return self._unknown(
                grounded_elements,
                f"no GroundedElement has text evidence in {list(target_texts)!r}",
            )
        if len(matches) > 1:
            return self._unknown(
                grounded_elements,
                f"multiple GroundedElements match {list(target_texts)!r}",
            )

        element = matches[0]
        target_text = next(
            evidence["text"]
            for evidence in element.get("text_evidence", [])
            if isinstance(evidence, Mapping) and evidence.get("text") in target_texts
        )
        candidate = {
            "candidate_id": "AC_001",
            "target_element_id": str(element["element_id"]),
            "action_type": "CLICK",
            "evidence": [
                f"text evidence: {target_text}",
                f"visual evidence: interaction candidate {element['element_id']}",
            ],
            "confidence": float(element["grounding_confidence"]),
        }
        validate_action_candidate(candidate, grounded_elements)
        return candidate


__all__ = ["GroundedDecisionAgent"]
