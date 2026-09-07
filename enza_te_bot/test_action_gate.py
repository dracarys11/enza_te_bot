"""Offline tests for the side-effect-free ActionGate."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest
from unittest.mock import patch

from action_gate import (APPROVED, REJECTED, UNKNOWN, ActionGate,
                         issue_observation_provenance)
from environment_provider import ActionIntent
from execution_permission import validate_execution_permission
from perception_models import ActionTarget, Observation, UIElement


def make_observation(state: str = "HOME", *, confidence: float | None = 0.99,
                     provenance: object | None = None, status: str = "VERIFIED",
                     elements: tuple[UIElement, ...] = ()) -> Observation:
    base = Observation.fresh(
        game_window={"left": 0, "top": 0, "width": 100, "height": 100},
        business_state={"state": state, "confidence": confidence} if confidence is not None else {"state": state},
        elements=elements, confidence=confidence, observation_status=status,
    )
    if provenance is None:
        return base
    # Observation is immutable; rebuild only the test evidence object with the
    # provider-issued provenance bound to its generated observation id.
    return Observation(
        base.observation_id, base.captured_at, base.game_window, base.business_state,
        base.screenshot_path, base.elements, base.numerics, base.structures,
        {**base.frame_metadata, "provenance": provenance}, base.candidate_actions,
        base.confidence, base.observation_status,
    )


def with_provenance(state: str = "HOME", **kwargs: object) -> Observation:
    draft = make_observation(state, **{key: value for key, value in kwargs.items() if key != "provenance"})
    provenance = issue_observation_provenance(draft.observation_id, state)
    return Observation(
        draft.observation_id, draft.captured_at, draft.game_window, draft.business_state,
        draft.screenshot_path, draft.elements, draft.numerics, draft.structures,
        {"provenance": provenance}, draft.candidate_actions, draft.confidence,
        draft.observation_status,
    )


class ActionGateTests(unittest.TestCase):
    def test_approved_gate_issues_bound_valid_permission(self) -> None:
        element = UIElement("rest", (0.4, 0.4, 0.6, 0.6), "button", semantic="rest")
        obs = with_provenance(elements=(element,))
        action = ActionIntent(
            "rest_start",
            target=ActionTarget(runtime_element_id="rest"),
            metadata={"room": "REST_ROOM"},
        )

        result = ActionGate(allowed_rooms={"REST_ROOM"}).evaluate(obs, action)

        self.assertEqual(result.decision, APPROVED)
        self.assertIsNotNone(result.permission)
        permission = result.permission
        assert permission is not None
        self.assertTrue(validate_execution_permission(permission).valid)
        self.assertEqual(permission.observation_id, obs.observation_id)
        self.assertEqual(permission.action_intent_id, action.action_intent_id)
        self.assertEqual(permission.target_identity, "element:rest")
        self.assertEqual(permission.scope, "REST_ROOM")
        self.assertTrue(permission.provenance_identity.startswith("provenance_"))
        self.assertGreater(permission.expires_at, permission.issued_at)

    def test_unknown_and_rejected_results_do_not_issue_permission(self) -> None:
        action = ActionIntent(
            "rest_start", coordinate=(0.5, 0.5), metadata={"room": "REST_ROOM"},
        )
        unknown = ActionGate(allowed_rooms={"REST_ROOM"})(
            with_provenance("UNKNOWN", status="UNKNOWN"), action,
        )
        rejected = ActionGate(allowed_rooms={"REST_ROOM"})(make_observation(), action)

        self.assertEqual(unknown.decision, UNKNOWN)
        self.assertIsNone(unknown.permission)
        self.assertEqual(rejected.decision, REJECTED)
        self.assertIsNone(rejected.permission)

    def test_issued_permission_is_immutable_and_target_bound(self) -> None:
        element = UIElement("rest", (0.4, 0.4, 0.6, 0.6), "button", semantic="rest")
        obs = with_provenance(elements=(element,))
        result = ActionGate(allowed_rooms={"REST_ROOM"})(
            obs,
            ActionIntent("rest_start", target=ActionTarget(runtime_element_id="rest"),
                         metadata={"room": "REST_ROOM"}),
        )
        permission = result.permission
        assert permission is not None

        with self.assertRaises(FrozenInstanceError):
            permission.scope = "VOCAL_ROOM"  # type: ignore[misc]
        modified = replace(permission, target_identity="element:other")
        validation = validate_execution_permission(modified)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.reason, "INVALID_SIGNATURE")

    def test_issued_permission_expires(self) -> None:
        obs = with_provenance()
        result = ActionGate(allowed_rooms={"REST_ROOM"})(
            obs,
            ActionIntent("rest_start", coordinate=(0.5, 0.5),
                         metadata={"room": "REST_ROOM"}),
        )
        permission = result.permission
        assert permission is not None

        validation = validate_execution_permission(permission, now=permission.expires_at)
        self.assertFalse(validation.valid)
        self.assertEqual(validation.reason, "EXPIRED")

    def test_produce_selection_unique_next_target_is_approved(self) -> None:
        next_button = UIElement("next", (0.7, 0.7, 0.8, 0.8), "button", semantic="next")
        obs = with_provenance("PRODUCE_SELECTION", elements=(next_button,))
        result = ActionGate(allowed_rooms={"PRODUCE_SELECTION"})(
            obs,
            ActionIntent(
                "audition_next",
                target=ActionTarget(runtime_element_id="next"),
                metadata={"room": "PRODUCE_SELECTION"},
            ),
        )
        self.assertEqual(result.decision, APPROVED)

    def test_valid_evidence_and_target_is_approved(self) -> None:
        element = UIElement("rest", (0.4, 0.4, 0.6, 0.6), "button", semantic="rest")
        obs = with_provenance(elements=(element,))
        result = ActionGate(allowed_rooms={"REST_ROOM"}).evaluate(
            obs, ActionIntent("rest_start", target=ActionTarget(runtime_element_id="rest"),
                              metadata={"room": "REST_ROOM"}),
        )
        self.assertEqual(result.decision, APPROVED)

    def test_missing_and_stale_provenance_are_rejected(self) -> None:
        action = ActionIntent("rest_start", coordinate=(0.5, 0.5), metadata={"room": "REST_ROOM"})
        missing = ActionGate(allowed_rooms={"REST_ROOM"})(make_observation(), action)
        self.assertEqual(missing.decision, REJECTED)
        self.assertIsNone(missing.permission)
        stale = issue_observation_provenance("other", "HOME")
        stale_result = ActionGate(allowed_rooms={"REST_ROOM"})(
            make_observation(provenance=stale), action,
        )
        self.assertEqual(stale_result.decision, REJECTED)
        self.assertIsNone(stale_result.permission)

    def test_unknown_observation_is_not_approved(self) -> None:
        obs = with_provenance("UNKNOWN", status="UNKNOWN")
        result = ActionGate(allowed_rooms={"REST_ROOM"})(obs, ActionIntent("rest_start", coordinate=(0.5, 0.5), metadata={"room": "REST_ROOM"}))
        self.assertEqual(result.decision, UNKNOWN)

    def test_visible_only_observation_is_not_executable_without_calibration(self) -> None:
        element = UIElement("next", (0.7, 0.7, 0.8, 0.8), "button", semantic="next")
        obs = with_provenance("PRODUCE_SELECTION", status="VISIBLE_ONLY", elements=(element,))
        result = ActionGate(allowed_rooms={"PRODUCE_SELECTION"})(
            obs, ActionIntent("next", target=ActionTarget(runtime_element_id="next"),
                              metadata={"room": "PRODUCE_SELECTION"}),
        )
        self.assertEqual(result.decision, UNKNOWN)
        self.assertIsNone(result.permission)

    def test_calibrated_target_can_be_distinguished_from_visible_only(self) -> None:
        element = UIElement(
            "next", (0.7, 0.7, 0.8, 0.8), "button", semantic="next",
            metadata={"source": "CALIBRATION", "verification_level": "CALIBRATED"},
        )
        obs = with_provenance("PRODUCE_SELECTION", status="VISIBLE_ONLY", elements=(element,))
        result = ActionGate(allowed_rooms={"PRODUCE_SELECTION"})(
            obs, ActionIntent("next", target=ActionTarget(runtime_element_id="next"),
                              metadata={"room": "PRODUCE_SELECTION"}),
        )
        self.assertEqual(result.decision, APPROVED)

    def test_screenshot_visible_only_target_is_unknown_even_if_status_is_verified(self) -> None:
        element = UIElement(
            "next", (0.7, 0.7, 0.8, 0.8), "button", semantic="next",
            metadata={"source": "SCREENSHOT", "verification_level": "VISIBLE_ONLY"},
        )
        obs = with_provenance("PRODUCE_SELECTION", status="VERIFIED", elements=(element,))
        result = ActionGate(allowed_rooms={"PRODUCE_SELECTION"})(
            obs, ActionIntent("next", target=ActionTarget(runtime_element_id="next"),
                              metadata={"room": "PRODUCE_SELECTION"}),
        )
        self.assertEqual(result.decision, UNKNOWN)
        self.assertIsNone(result.permission)

    def test_artifact_provenance_does_not_create_permission(self) -> None:
        obs = Observation.fresh(
            game_window={"left": 0, "top": 0, "width": 100, "height": 100},
            business_state={"state": "PRODUCE_SELECTION", "confidence": 0.99},
            frame_metadata={"artifact_provenance": {"source": "ZCODE"}},
            confidence=0.99, observation_status="VISIBLE_ONLY",
        )
        result = ActionGate(allowed_rooms={"PRODUCE_SELECTION"})(
            obs, ActionIntent("next", coordinate=(0.8, 0.8),
                              metadata={"room": "PRODUCE_SELECTION"}),
        )
        self.assertEqual(result.decision, REJECTED)
        self.assertIsNone(result.permission)

    def test_low_confidence_is_rejected(self) -> None:
        obs = with_provenance(confidence=0.4)
        result = ActionGate(allowed_rooms={"REST_ROOM"})(obs, ActionIntent("rest_start", coordinate=(0.5, 0.5), metadata={"room": "REST_ROOM"}))
        self.assertEqual(result.decision, REJECTED)
        self.assertIsNone(result.permission)

    @unittest.expectedFailure
    def test_low_confidence_target_benchmark_expects_unknown(self) -> None:
        """Benchmark requirement: weak evidence should be UNKNOWN.

        The current Phase 1D-1 contract returns REJECTED for a numeric
        confidence below threshold; retain this expected failure until that
        contract is explicitly changed in a later phase.
        """
        obs = with_provenance("PRODUCE_SELECTION", confidence=0.4)
        result = ActionGate(allowed_rooms={"PRODUCE_SELECTION"})(
            obs,
            ActionIntent("audition_next", coordinate=(0.75, 0.75), metadata={"room": "PRODUCE_SELECTION"}),
        )
        self.assertEqual(result.decision, UNKNOWN)

    def test_ambiguous_target_is_rejected(self) -> None:
        elements = (
            UIElement("rest:1", (0.1, 0.1, 0.2, 0.2), "button", semantic="rest"),
            UIElement("rest:2", (0.3, 0.3, 0.4, 0.4), "button", semantic="rest"),
        )
        obs = with_provenance(elements=elements)
        result = ActionGate(allowed_rooms={"REST_ROOM"})(obs, ActionIntent("rest_start", target=ActionTarget(semantic="rest"), metadata={"room": "REST_ROOM"}))
        self.assertEqual(result.decision, REJECTED)
        self.assertIsNone(result.permission)

    @unittest.expectedFailure
    def test_ambiguous_target_benchmark_expects_unknown(self) -> None:
        """Benchmark requirement: unresolved target ambiguity should be UNKNOWN.

        The current resolver/gate reports TARGET_AMBIGUOUS as REJECTED.  This
        test records the requested future classification without changing it.
        """
        elements = (
            UIElement("next:1", (0.1, 0.1, 0.2, 0.2), "button", semantic="next"),
            UIElement("next:2", (0.3, 0.3, 0.4, 0.4), "button", semantic="next"),
        )
        obs = with_provenance("PRODUCE_SELECTION", elements=elements)
        result = ActionGate(allowed_rooms={"PRODUCE_SELECTION"})(
            obs,
            ActionIntent("audition_next", target=ActionTarget(semantic="next"), metadata={"room": "PRODUCE_SELECTION"}),
        )
        self.assertEqual(result.decision, UNKNOWN)

    def test_room_scope_is_enforced(self) -> None:
        obs = with_provenance()
        result = ActionGate(allowed_rooms={"REST_ROOM"})(obs, ActionIntent("rest_start", coordinate=(0.5, 0.5), metadata={"room": "VOCAL_ROOM"}))
        self.assertEqual(result.decision, REJECTED)
        self.assertIsNone(result.permission)

    def test_gate_never_executes_clicks(self) -> None:
        obs = with_provenance()
        action = ActionIntent("rest_start", coordinate=(0.5, 0.5), metadata={"room": "REST_ROOM"})
        with patch("pyautogui.click") as click:
            result = ActionGate(allowed_rooms={"REST_ROOM"})(obs, action)
        self.assertEqual(result.decision, APPROVED)
        click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
