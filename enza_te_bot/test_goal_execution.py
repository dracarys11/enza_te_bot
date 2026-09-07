import unittest

from goal_execution import GoalContext, execute_goal, resolve_goal_event


class GoalExecutionTests(unittest.TestCase):
    def test_goal_commits_only_after_verified_home_boundary(self) -> None:
        result = execute_goal(
            GoalContext("VOCAL"), live=True, executor_name="VOCAL_ROOM",
            run_executor=lambda: 0,
            verify_terminal_boundary=lambda: ("HOME", True),
        )
        self.assertEqual(result.status, "GOAL_SUCCESS")
        self.assertTrue(result.committed)
        self.assertEqual(result.final_state, "HOME")

    def test_executor_success_without_home_does_not_commit(self) -> None:
        result = execute_goal(
            GoalContext("VOCAL"), live=True, executor_name="VOCAL_ROOM",
            run_executor=lambda: 0,
            verify_terminal_boundary=lambda: ("VOCAL_RESULT", False),
        )
        self.assertEqual(result.status, "BOUNDARY_FAILURE")
        self.assertFalse(result.committed)

    def test_dry_run_never_executes_or_verifies(self) -> None:
        calls = []
        result = execute_goal(
            GoalContext("REST"), live=False, executor_name="REST_ROOM",
            run_executor=lambda: calls.append("run") or 0,
            verify_terminal_boundary=lambda: calls.append("verify") or ("HOME", True),
        )
        self.assertEqual(result.status, "DRY_RUN")
        self.assertEqual(calls, [])

    def test_shared_event_resolution_preserves_safety_precedence(self) -> None:
        context = GoalContext(
            "VOCAL",
            allowed_events=frozenset({"DIALOGUE_FAST_FORWARD_OFF", "AUDITION_BATTLE"}),
        )
        self.assertEqual(resolve_goal_event(context, "HOME").disposition, "TERMINAL")
        self.assertEqual(resolve_goal_event(context, "DIALOGUE_FAST_FORWARD_OFF").disposition, "DISPATCH")
        self.assertEqual(resolve_goal_event(context, "AUDITION_BATTLE").disposition, "DISPATCH")
        self.assertEqual(resolve_goal_event(context, "CHOICE_REQUIRED").disposition, "PROTECTED_STOP")
        self.assertEqual(resolve_goal_event(context, "UNKNOWN").disposition, "UNKNOWN_STOP")
        self.assertEqual(resolve_goal_event(context, "PRODUCE_MENU").disposition, "UNSUPPORTED_STOP")

    def test_room_failure_is_goal_failure_without_boundary_verification(self) -> None:
        calls = []
        result = execute_goal(
            GoalContext("VOCAL"), live=True, executor_name="VOCAL_ROOM",
            run_executor=lambda: 2,
            verify_terminal_boundary=lambda: calls.append("verify") or ("HOME", True),
        )
        self.assertEqual(result.status, "EXECUTOR_FAILURE")
        self.assertFalse(result.committed)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
