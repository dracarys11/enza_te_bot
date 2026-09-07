"""Offline tests for the small structured-perception / grounding boundary."""
from __future__ import annotations

import unittest

from grounding import configured_action_target, resolve_action_target
from perception_models import (ActionResult, ActionTarget, EffectEvidence, FailureReason,
                               Observation, UIElement)
from trajectory import trajectory_step


def observation(*elements: UIElement) -> Observation:
    return Observation.fresh(game_window={"left": 0, "top": 0, "width": 100, "height": 100},
                             business_state={"state": "REFLECTION", "confidence": 1.0}, elements=elements)


class StructuredPerceptionTest(unittest.TestCase):
    def test_runtime_elements_are_normalized_unique_and_source_recorded(self) -> None:
        element = UIElement("node:0", (0.1, 0.2, 0.3, 0.4), "skill_node", semantic="normal",
                            confidence=0.95, detector="opencv")
        item = observation(element)
        self.assertEqual(item.elements[0].center, (0.2, 0.30000000000000004))
        self.assertEqual(item.elements[0].detector, "opencv")
        with self.assertRaisesRegex(ValueError, "unique"):
            observation(element, element)

    def test_runtime_id_has_priority_over_weaker_fallback(self) -> None:
        element = UIElement("node:0", (0.1, 0.1, 0.2, 0.2), "skill_node", semantic="normal")
        result = resolve_action_target(observation(element), ActionTarget(runtime_element_id="node:0",
                                                                            fallback_bbox=(0.5, 0.5, 0.6, 0.6),
                                                                            allow_fallback=True))
        self.assertTrue(result.resolved)
        self.assertEqual(result.source, "runtime_element")
        self.assertEqual(result.bbox, element.bbox)

    def test_geometry_semantic_resolution_and_ambiguous_halt(self) -> None:
        first = UIElement("upper:0", (0.1, 0.1, 0.2, 0.2), "skill_node", semantic="normal",
                          metadata={"board": "upper_left", "clockwise_index": 0})
        second = UIElement("upper:1", (0.3, 0.1, 0.4, 0.2), "skill_node", semantic="normal",
                           metadata={"board": "upper_left", "clockwise_index": 1})
        unique = resolve_action_target(observation(first, second), ActionTarget(semantic="normal",
            relation={"board": "upper_left", "clockwise_index": 1}))
        self.assertEqual(unique.element.element_id, "upper:1")
        ambiguous = resolve_action_target(observation(first, second), ActionTarget(semantic="normal"))
        self.assertEqual(ambiguous.failure, FailureReason.TARGET_AMBIGUOUS)

    def test_configured_fallback_is_explicit_only(self) -> None:
        item = observation()
        blocked = resolve_action_target(item, ActionTarget(runtime_element_id="missing", fallback_bbox=(0.1, 0.1, 0.2, 0.2)))
        self.assertEqual(blocked.failure, FailureReason.TARGET_NOT_FOUND)
        allowed = resolve_action_target(item, ActionTarget(semantic="normal", fallback_bbox=(0.1, 0.1, 0.2, 0.2),
                                                            allow_fallback=True))
        self.assertEqual(allowed.source, "configured_fallback")
        configured = resolve_action_target(item, configured_action_target({"box": [0.2, 0.2, 0.3, 0.3]}))
        self.assertEqual(configured.bbox, (0.2, 0.2, 0.3, 0.3))

    def test_trajectory_adapter_preserves_issue_effect_and_commit_boundaries(self) -> None:
        record = trajectory_step(episode="test", goal="purchase", step=1, observation={"state": "REFLECTION"},
            action={"name": "purchase"}, result=ActionResult("purchase", issued=True, destination_verified=True,
                effect=EffectEvidence(destination_state="REFLECTION", numeric_before=30, numeric_after=20, verified=True),
                committed=True))
        self.assertTrue(record["action_result"]["issued"])
        self.assertTrue(record["action_result"]["effect"]["verified"])
        self.assertTrue(record["action_result"]["committed"])


if __name__ == "__main__":
    unittest.main()
