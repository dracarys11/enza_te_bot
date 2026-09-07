import json
import unittest
from unittest.mock import patch

from goal_execution import GoalContext, GoalResult
from room_adapter import (
    FAILED,
    HOME_FRESH_PARAMETER,
    HOME_PROVENANCE_PARAMETER,
    HOME_VERIFIED_PARAMETER,
    SUCCESS_HOME,
    UNKNOWN,
    canonical_room_result,
    home_provenance_metadata,
    issue_home_provenance,
)
from weekly_tools import RestRoomAdapter, VocalRoomAdapter


def verified_context(goal: str) -> GoalContext:
    return GoalContext(goal, parameters={
        HOME_PROVENANCE_PARAMETER: issue_home_provenance(f"test-{goal}"),
    })


class RoomAdapterParityTests(unittest.TestCase):
    def test_vocal_adapter_delegates_to_existing_function_adapter(self) -> None:
        context = verified_context("VOCAL")
        legacy = GoalResult(
            "GOAL_SUCCESS", context, executor="VOCAL_ROOM",
            final_state="HOME", committed=True,
        )
        adapter = VocalRoomAdapter(
            live=True,
            run_vocal_room_once=lambda: self.fail("legacy adapter was bypassed"),
            observe_home_boundary=lambda: self.fail("legacy adapter was bypassed"),
        )

        with patch("weekly_tools.execute_vocal", return_value=legacy) as execute:
            result = adapter.execute("VOCAL", context)

        execute.assert_called_once()
        self.assertEqual(result.status, SUCCESS_HOME)

    def test_vocal_adapter_delegates_and_commits_verified_home(self) -> None:
        calls = []
        adapter = VocalRoomAdapter(
            live=True,
            run_vocal_room_once=lambda: calls.append("vocal") or 0,
            observe_home_boundary=lambda: calls.append("home") or ("HOME", True),
        )

        result = adapter.execute("VOCAL", verified_context("VOCAL"))

        self.assertEqual(result.status, SUCCESS_HOME)
        self.assertTrue(result.committed)
        self.assertEqual(result.final_state, "HOME")
        self.assertEqual(calls, ["vocal", "home"])

    def test_vocal_adapter_preserves_failure_and_unknown_semantics(self) -> None:
        failed = VocalRoomAdapter(
            live=True,
            run_vocal_room_once=lambda: 2,
            observe_home_boundary=lambda: ("HOME", True),
        ).execute("VOCAL", verified_context("VOCAL"))
        unknown = VocalRoomAdapter(
            live=True,
            run_vocal_room_once=lambda: 0,
            observe_home_boundary=lambda: ("UNKNOWN", False),
        ).execute("VOCAL", verified_context("VOCAL"))

        self.assertEqual(failed.status, FAILED)
        self.assertFalse(failed.committed)
        self.assertEqual(unknown.status, UNKNOWN)
        self.assertFalse(unknown.committed)

    def test_rest_adapter_delegates_and_commits_verified_home(self) -> None:
        calls = []
        adapter = RestRoomAdapter(
            live=True,
            run_rest_room_once=lambda: calls.append("rest") or 0,
            observe_home_boundary=lambda: calls.append("home") or ("HOME", True),
        )

        result = adapter.execute("REST", verified_context("REST"))

        self.assertEqual(result.status, SUCCESS_HOME)
        self.assertTrue(result.committed)
        self.assertEqual(result.executor, "REST_ROOM")
        self.assertEqual(calls, ["rest", "home"])

    def test_rest_adapter_delegates_to_existing_function_adapter(self) -> None:
        context = verified_context("REST")
        legacy = GoalResult(
            "GOAL_SUCCESS", context, executor="REST_ROOM",
            final_state="HOME", committed=True,
        )
        adapter = RestRoomAdapter(
            live=True,
            run_rest_room_once=lambda: self.fail("legacy adapter was bypassed"),
            observe_home_boundary=lambda: self.fail("legacy adapter was bypassed"),
        )

        with patch("weekly_tools.execute_rest", return_value=legacy) as execute:
            result = adapter.execute("REST", context)

        execute.assert_called_once()
        self.assertEqual(result.status, SUCCESS_HOME)

    def test_rest_adapter_preserves_failure_and_unknown_semantics(self) -> None:
        failed = RestRoomAdapter(
            live=True,
            run_rest_room_once=lambda: 2,
            observe_home_boundary=lambda: ("HOME", True),
        ).execute("REST", verified_context("REST"))
        unknown = RestRoomAdapter(
            live=True,
            run_rest_room_once=lambda: 0,
            observe_home_boundary=lambda: ("UNKNOWN", False),
        ).execute("REST", verified_context("REST"))

        self.assertEqual(failed.status, FAILED)
        self.assertFalse(failed.committed)
        self.assertEqual(unknown.status, UNKNOWN)
        self.assertFalse(unknown.committed)

    def test_rest_adapter_rejects_stale_home_entry(self) -> None:
        calls = []
        stale = GoalContext("REST", parameters={
            HOME_PROVENANCE_PARAMETER: issue_home_provenance("stale", fresh=False),
        })
        result = RestRoomAdapter(
            live=True,
            run_rest_room_once=lambda: calls.append("room") or 0,
            observe_home_boundary=lambda: ("HOME", True),
        ).execute("REST", stale)

        self.assertEqual(result.status, FAILED)
        self.assertFalse(result.committed)
        self.assertEqual(calls, [])

    def test_rest_adapter_rejects_legacy_home_flags_without_provenance(self) -> None:
        calls = []
        fake_flags = GoalContext("REST", parameters={
            HOME_VERIFIED_PARAMETER: True,
            HOME_FRESH_PARAMETER: True,
        })
        result = RestRoomAdapter(
            live=True,
            run_rest_room_once=lambda: calls.append("room") or 0,
            observe_home_boundary=lambda: ("HOME", True),
        ).execute("REST", fake_flags)

        self.assertEqual(result.status, FAILED)
        self.assertFalse(result.committed)
        self.assertEqual(calls, [])

    def test_home_provenance_diagnostics_are_json_safe(self) -> None:
        metadata = home_provenance_metadata(issue_home_provenance("trace-proof"))
        json.dumps(metadata)
        self.assertTrue(metadata["valid"])

    def test_unknown_or_missing_objective_is_safe(self) -> None:
        calls = []
        adapter = VocalRoomAdapter(
            live=True,
            run_vocal_room_once=lambda: calls.append("click") or 0,
            observe_home_boundary=lambda: ("HOME", True),
        )

        result = adapter.execute("REST", verified_context("VOCAL"))

        self.assertEqual(result.status, FAILED)
        self.assertFalse(result.committed)
        self.assertEqual(calls, [])

    def test_dry_run_preserves_legacy_non_execution(self) -> None:
        calls = []
        result = RestRoomAdapter(
            live=False,
            run_rest_room_once=lambda: calls.append("room") or 0,
            observe_home_boundary=lambda: calls.append("observe") or ("HOME", True),
        ).execute("REST", verified_context("REST"))

        self.assertEqual(result.status, FAILED)
        self.assertFalse(result.committed)
        self.assertEqual(calls, [])

    def test_missing_home_entry_evidence_blocks_without_calling_legacy_runner(self) -> None:
        calls = []
        result = VocalRoomAdapter(
            live=True,
            run_vocal_room_once=lambda: calls.append("room") or 0,
            observe_home_boundary=lambda: calls.append("observe") or ("HOME", True),
        ).execute("VOCAL", GoalContext("VOCAL"))

        self.assertEqual(result.status, FAILED)
        self.assertIn("verified HOME", result.detail or "")
        self.assertEqual(calls, [])

    def test_stale_home_entry_is_rejected(self) -> None:
        calls = []
        stale = GoalContext("VOCAL", parameters={
            HOME_PROVENANCE_PARAMETER: issue_home_provenance("stale", fresh=False),
        })
        result = VocalRoomAdapter(
            live=True,
            run_vocal_room_once=lambda: calls.append("room") or 0,
            observe_home_boundary=lambda: ("HOME", True),
        ).execute("VOCAL", stale)

        self.assertEqual(result.status, FAILED)
        self.assertEqual(calls, [])

    def test_stale_home_result_cannot_be_canonical_success(self) -> None:
        stale = GoalContext("VOCAL", parameters={
            HOME_PROVENANCE_PARAMETER: issue_home_provenance("stale", fresh=False),
        })
        result = canonical_room_result(GoalResult(
            "GOAL_SUCCESS", stale, executor="VOCAL_ROOM",
            final_state="HOME", committed=True,
        ))

        self.assertEqual(result.status, FAILED)
        self.assertFalse(result.committed)

    def test_unknown_legacy_status_cannot_commit_home(self) -> None:
        context = verified_context("VOCAL")
        adapter = VocalRoomAdapter(
            live=True,
            run_vocal_room_once=lambda: 0,
            observe_home_boundary=lambda: ("HOME", True),
        )
        with patch("weekly_tools.execute_vocal", return_value=GoalResult(
                "UNKNOWN", context, executor="VOCAL_ROOM",
                final_state="HOME", committed=True)):
            outcome = adapter.execute("VOCAL", context)

        self.assertEqual(outcome.status, UNKNOWN)
        self.assertFalse(outcome.committed)

    def test_unknown_with_home_flag_remains_unknown(self) -> None:
        context = GoalContext("VOCAL", parameters={
            HOME_VERIFIED_PARAMETER: True,
            HOME_FRESH_PARAMETER: True,
        })
        result = canonical_room_result(GoalResult(
            "UNKNOWN", context, executor="VOCAL_ROOM",
            final_state="HOME", committed=True,
        ))

        self.assertEqual(result.status, UNKNOWN)
        self.assertFalse(result.committed)

    def test_success_requires_legacy_success_and_commit_flags(self) -> None:
        context = verified_context("VOCAL")
        adapter = VocalRoomAdapter(
            live=True,
            run_vocal_room_once=lambda: 0,
            observe_home_boundary=lambda: ("HOME", True),
        )
        with patch("weekly_tools.execute_vocal", return_value=GoalResult(
                "GOAL_SUCCESS", context, executor="VOCAL_ROOM",
                final_state="HOME", committed=False)):
            outcome = adapter.execute("VOCAL", context)

        self.assertEqual(outcome.status, FAILED)
        self.assertFalse(outcome.committed)

    def test_failed_legacy_status_cannot_commit_even_if_flagged(self) -> None:
        context = verified_context("VOCAL")
        result = canonical_room_result(GoalResult(
            "EXECUTOR_FAILURE", context, executor="VOCAL_ROOM",
            final_state="HOME", committed=True,
        ))

        self.assertEqual(result.status, FAILED)
        self.assertFalse(result.committed)


if __name__ == "__main__":
    unittest.main()
