"""Offline checks for observational room performance accounting."""
from __future__ import annotations

import unittest

from main import RoomPerformance, compare_performance_samples, successful_performance_samples


class PerformanceTest(unittest.TestCase):
    def successful_sample(self, *, enabled: bool, used: bool | None = None, room_ms: float, transition_ms: float) -> dict:
        return {"success": True, "accelerator_enabled": enabled, "accelerator_used": enabled if used is None else used, "room_total_ms": room_ms,
                "post_action_transition_ms": transition_ms, "accelerator_click_count": 3}

    def test_room_and_post_action_durations_are_recorded(self) -> None:
        performance = RoomPerformance("VOCAL_ROOM", 10.0, accelerator_enabled=True)
        performance.action_sent_at = 12.0
        performance.post_action_observer_started_at = 12.5
        performance.record_accelerator_burst({"status": "CLICKED", "click_count": 3,
                                               "burst_started_at_monotonic": 13.0,
                                               "burst_finished_at_monotonic": 13.2})
        metrics = performance.finish("ROOM_EXIT", "HOME", exited_at_monotonic=20.0)
        self.assertEqual(metrics["room_total_ms"], 10000.0)
        self.assertEqual(metrics["post_action_transition_ms"], 8000.0)
        self.assertEqual(metrics["accelerator_active_ms"], 200.0)
        self.assertEqual(metrics["accelerator_burst_count"], 1)
        self.assertEqual(metrics["accelerator_click_count"], 3)
        self.assertTrue(metrics["accelerator_used"])

    def test_failed_room_is_excluded_from_baseline_comparison(self) -> None:
        failed_metrics = RoomPerformance("VOCAL_ROOM", 5.0, accelerator_enabled=False).finish(
            "TRANSITION_TIMEOUT", "UNKNOWN", exited_at_monotonic=7.0
        )
        self.assertEqual(failed_metrics["room_total_ms"], 2000.0)
        self.assertEqual(failed_metrics["exit_reason"], "TRANSITION_TIMEOUT")
        failed = {"success": False, **failed_metrics}
        samples = [failed, *[self.successful_sample(enabled=True, room_ms=80, transition_ms=40) for _ in range(3)]]
        self.assertEqual(len(successful_performance_samples(samples)), 3)
        comparison = compare_performance_samples(samples)
        self.assertEqual(comparison["status"], "insufficient_evidence")
        self.assertEqual(comparison["baseline_samples"], 0)

    def test_enabled_without_actual_burst_is_not_an_accelerated_sample(self) -> None:
        samples = [self.successful_sample(enabled=True, used=False, room_ms=80, transition_ms=40)]
        comparison = compare_performance_samples(samples)
        self.assertEqual(comparison["accelerated_samples"], 0)
        self.assertEqual(comparison["enabled_not_used_samples"], 1)

    def test_less_than_fifteen_percent_does_not_claim_improvement(self) -> None:
        samples = ([self.successful_sample(enabled=True, room_ms=90, transition_ms=90) for _ in range(3)] +
                   [self.successful_sample(enabled=False, room_ms=100, transition_ms=100) for _ in range(3)])
        comparison = compare_performance_samples(samples)
        self.assertEqual(comparison["status"], "no_confirmed_improvement")
        self.assertEqual(comparison["room_total_improvement_percent"], 10.0)

    def test_fifteen_percent_with_enough_samples_reports_improved(self) -> None:
        samples = ([self.successful_sample(enabled=True, room_ms=85, transition_ms=80) for _ in range(3)] +
                   [self.successful_sample(enabled=False, room_ms=100, transition_ms=100) for _ in range(3)])
        comparison = compare_performance_samples(samples)
        self.assertEqual(comparison["status"], "improved")
        self.assertEqual(comparison["room_total_improvement_percent"], 15.0)


if __name__ == "__main__":
    unittest.main()
