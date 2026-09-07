"""Offline safety checks for the deterministic REFLECTION route model."""
from __future__ import annotations

import unittest

from reflection import (ReflectionNode, affordable_route_plan, can_commit_purchase,
                        configured_route_nodes, may_advance_route_cursor, parse_remaining_sp,
                        reflection_node_outcome, fixed_route_nodes)


class ReflectionRouteTest(unittest.TestCase):
    def nodes(self):
        return configured_route_nodes({"skill_routes": {
            "upper_left_ring": [
                {"id": "upper_1", "box": [0.1, 0.1, 0.2, 0.2], "expected_cost": 50, "type": "normal"},
                {"id": "upper_2", "box": [0.2, 0.1, 0.3, 0.2], "expected_cost": 200, "type": "normal"},
            ],
            "lower_right_ring": [
                {"id": "lower_1", "box": [0.7, 0.7, 0.8, 0.8], "expected_cost": 40, "type": "normal"},
                {"id": "appeal_1", "box": [0.8, 0.7, 0.9, 0.8], "expected_cost": 30, "type": "appeal"},
            ],
        }})

    def test_configured_clockwise_order_and_upper_left_precedence_are_preserved(self) -> None:
        self.assertEqual([node.node_id for node in self.nodes()], ["upper_1", "upper_2", "lower_1", "appeal_1"])

    def test_unaffordable_node_is_skipped_but_later_cheaper_node_is_considered(self) -> None:
        affordable, skipped = affordable_route_plan(self.nodes(), 60)
        self.assertEqual([node.node_id for node in affordable], ["upper_1", "lower_1", "appeal_1"])
        self.assertEqual([node.node_id for node in skipped], ["upper_2"])

    def test_remaining_sp_parser_requires_one_token(self) -> None:
        self.assertEqual(parse_remaining_sp("SP 1,250").value, 1250)
        self.assertIsNone(parse_remaining_sp("SP 12 50").value)

    def test_purchase_commits_only_after_reflection_reverified_and_sp_reread_decreases(self) -> None:
        self.assertTrue(can_commit_purchase(resulting_state="REFLECTION", remaining_before=120, remaining_after=70))
        self.assertFalse(can_commit_purchase(resulting_state="REFLECTION", remaining_before=120, remaining_after=None))
        self.assertFalse(can_commit_purchase(resulting_state="REFLECTION", remaining_before=120, remaining_after=120))
        self.assertFalse(can_commit_purchase(resulting_state="APPEAL_REPLACE", remaining_before=120, remaining_after=70))

    def test_next_normal_node_is_not_allowed_until_prior_purchase_is_committed(self) -> None:
        # ul_ring_01 click alone, or a purchase without a successful SP reread,
        # cannot advance the cursor to ul_ring_02.
        self.assertFalse(may_advance_route_cursor(node_type="normal", resulting_state="REFLECTION",
                                                  remaining_before=120, remaining_after=None))
        self.assertFalse(may_advance_route_cursor(node_type="normal", resulting_state="REFLECTION",
                                                  remaining_before=120, remaining_after=120))
        self.assertTrue(may_advance_route_cursor(node_type="normal", resulting_state="REFLECTION",
                                                 remaining_before=120, remaining_after=70))

    def test_node_purchase_verify_then_only_next_node_ordering(self) -> None:
        first, second = self.nodes()[:2]
        # The executor may select first, but cannot advance its route cursor to
        # second until the separate purchase has reverified REFLECTION and the
        # fresh SP observation is lower.
        self.assertEqual(first.node_id, "upper_1")
        self.assertFalse(may_advance_route_cursor(node_type="normal", resulting_state="REFLECTION",
                                                  remaining_before=100, remaining_after=None))
        self.assertTrue(may_advance_route_cursor(node_type="normal", resulting_state="REFLECTION",
                                                 remaining_before=100, remaining_after=50))
        self.assertEqual(second.node_id, "upper_2")

    def test_appeal_node_stops_for_explicit_replacement_flow(self) -> None:
        appeal = self.nodes()[-1]
        self.assertEqual(reflection_node_outcome(appeal, "APPEAL_REPLACE"), "APPEAL_REPLACE_ACTION_REQUIRED")

    def test_unknown_never_requests_a_generic_extra_click(self) -> None:
        normal = self.nodes()[0]
        self.assertEqual(reflection_node_outcome(normal, "UNKNOWN"), "UNKNOWN_STOP")

    def test_fixed_route_preserves_order_and_affordability(self):
        nodes = fixed_route_nodes({"fixed_route": [
            {"id": "a", "point": [0.2, 0.2], "cost": 50, "type": "normal"},
            {"id": "b", "point": [0.3, 0.3], "cost": 200, "type": "normal"},
            {"id": "c", "point": [0.4, 0.4], "cost": 20, "type": "appeal"},
        ]})
        affordable, skipped = affordable_route_plan(nodes, 60)
        self.assertEqual([n.node_id for n in affordable], ["a", "c"])
        self.assertEqual([n.node_id for n in skipped], ["b"])


if __name__ == "__main__":
    unittest.main()
