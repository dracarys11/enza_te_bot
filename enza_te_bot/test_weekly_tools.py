import unittest

from goal_execution import GoalContext
from weekly_tools import execute_vocal


class VocalToolTests(unittest.TestCase):
    def test_room_success_and_fresh_home_commits_goal(self) -> None:
        calls = []
        result = execute_vocal(
            GoalContext("VOCAL"),
            live=True,
            run_vocal_room_once=lambda: calls.append("room") or 0,
            observe_home_boundary=lambda: calls.append("observe") or ("HOME", True),
        )
        self.assertEqual(result.status, "GOAL_SUCCESS")
        self.assertTrue(result.committed)
        self.assertEqual(result.final_state, "HOME")
        self.assertEqual(calls, ["room", "observe"])

    def test_room_success_without_home_does_not_commit(self) -> None:
        result = execute_vocal(
            GoalContext("VOCAL"),
            live=True,
            run_vocal_room_once=lambda: 0,
            observe_home_boundary=lambda: ("VOCAL_RESULT", False),
        )
        self.assertEqual(result.status, "BOUNDARY_FAILURE")
        self.assertFalse(result.committed)
        self.assertEqual(result.final_state, "VOCAL_RESULT")

    def test_executor_failure_is_goal_failure_and_skips_home_observation(self) -> None:
        observations = []
        result = execute_vocal(
            GoalContext("VOCAL"),
            live=True,
            run_vocal_room_once=lambda: 2,
            observe_home_boundary=lambda: observations.append("observe") or ("HOME", True),
        )
        self.assertEqual(result.status, "EXECUTOR_FAILURE")
        self.assertFalse(result.committed)
        self.assertEqual(observations, [])


if __name__ == "__main__":
    unittest.main()
