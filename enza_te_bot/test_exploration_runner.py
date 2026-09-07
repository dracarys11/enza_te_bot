"""Offline end-to-end tests for the bounded exploration runner."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from environment_provider import MockEnvironmentProvider
from exploration_memory_schema import load_exploration_session
from exploration_runner import ExplorationRunner, NavigationStep
from perception_models import Observation


def observation(state: str, *, status: str = "VERIFIED") -> Observation:
    return Observation.fresh(
        game_window={"left": 0, "top": 0, "width": 1280, "height": 720},
        business_state={"state": state, "confidence": 0.99},
        screenshot_path=f"screenshots/{state}.png",
        confidence=0.99,
        observation_status=status,
    )


def provider_for_path(*, last_state: str = "WING_CONFIRMATION_DIALOG") -> MockEnvironmentProvider:
    return MockEnvironmentProvider(
        observation("HOME"),
        transitions={
            "produce_open": observation("PRODUCE_SELECTION"),
            "preparation_next": [
                observation("UNIT_FORMATION"),
                observation("ITEM_SELECTION"),
                observation(last_state),
            ],
        },
    )


class ExplorationRunnerTests(unittest.TestCase):
    def test_navigation_path_stops_at_resource_confirmation_and_writes_memory(self) -> None:
        provider = provider_for_path()
        with tempfile.TemporaryDirectory() as directory:
            result = ExplorationRunner(provider, output_directory=directory).run(
                session_id="EXP_RUN_001")
            memory_path = Path(result.memory_path)
            payload = json.loads(memory_path.read_text(encoding="utf-8"))
            session = load_exploration_session(memory_path)

        self.assertEqual(result.stop_reason, "RESOURCE_CONFIRMATION_REACHED")
        self.assertEqual(result.final_state, "WING_CONFIRMATION_DIALOG")
        self.assertEqual(result.actions_executed, 4)
        self.assertEqual([item.action_name for item in provider.executed_intents],
                         ["produce_open", "preparation_next",
                          "preparation_next", "preparation_next"])
        self.assertEqual(len(session.decision_traces), 4)
        self.assertEqual(payload["scope"], "NAVIGATION_ONLY")
        self.assertFalse(payload["executable"])

    def test_unknown_state_stops_immediately_without_another_action(self) -> None:
        provider = provider_for_path(last_state="UNKNOWN")
        with tempfile.TemporaryDirectory() as directory:
            result = ExplorationRunner(provider, output_directory=directory).run(
                session_id="EXP_UNKNOWN")
            payload = json.loads(Path(result.memory_path).read_text(encoding="utf-8"))

        self.assertEqual(result.stop_reason, "UNKNOWN_STATE")
        self.assertEqual(result.actions_executed, 4)
        self.assertEqual(len(payload["unknowns"]), 1)
        self.assertEqual(len(provider.executed_intents), 4)

    def test_unexpected_modal_stops_without_followup_action(self) -> None:
        provider = provider_for_path(last_state="UNEXPECTED_HELP_MODAL")
        with tempfile.TemporaryDirectory() as directory:
            result = ExplorationRunner(provider, output_directory=directory).run(
                session_id="EXP_MODAL")

        self.assertEqual(result.stop_reason, "UNEXPECTED_MODAL")
        self.assertEqual(result.actions_executed, 4)
        self.assertEqual(len(provider.executed_intents), 4)

    def test_failed_transition_verification_is_recorded_and_stops(self) -> None:
        provider = MockEnvironmentProvider(
            observation("HOME"),
            transitions={"produce_open": observation("WRONG_STATE")},
        )
        with tempfile.TemporaryDirectory() as directory:
            result = ExplorationRunner(provider, output_directory=directory).run(
                session_id="EXP_FAILED")
            payload = json.loads(Path(result.memory_path).read_text(encoding="utf-8"))

        self.assertEqual(result.stop_reason, "TRANSITION_VERIFICATION_FAILED")
        self.assertEqual(payload["verification_records"][0]["status"], "FAILED")
        self.assertEqual(len(provider.executed_intents), 1)

    def test_runner_never_executes_resource_confirmation(self) -> None:
        provider = MockEnvironmentProvider(observation("WING_CONFIRMATION_DIALOG"))
        with tempfile.TemporaryDirectory() as directory:
            result = ExplorationRunner(provider, output_directory=directory).run(
                session_id="EXP_BOUNDARY")

        self.assertEqual(result.stop_reason, "RESOURCE_CONFIRMATION_REACHED")
        self.assertEqual(result.actions_executed, 0)
        self.assertEqual(provider.executed_intents, [])

    def test_non_navigation_scenario_action_is_rejected_before_execution(self) -> None:
        provider = MockEnvironmentProvider(observation("ITEM_SELECTION"))
        unsafe = (NavigationStep(
            "ITEM_SELECTION", "confirm_production", "PRODUCTION_STARTED",
            ("confirm_production", "stop"), ("OBS_BOUNDARY",),
            "resource effect is forbidden",
        ),)

        with self.assertRaisesRegex(ValueError, "non-navigation action"):
            ExplorationRunner(provider, scenario=unsafe)
        self.assertEqual(provider.executed_intents, [])


if __name__ == "__main__":
    unittest.main()
