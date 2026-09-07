"""Offline tests for the unintegrated ExecutionPermission object."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import unittest

from execution_permission import (AVAILABLE, ExecutionPermission,
                                  consume_execution_permission,
                                  issue_execution_permission,
                                  validate_execution_permission)


def permission(*, issued_at: float = 100.0, ttl_seconds: float = 10.0) -> ExecutionPermission:
    return issue_execution_permission(
        observation_id="obs-1",
        action_intent_id="intent-1",
        target_identity="element:next",
        scope="PRODUCE_SELECTION",
        provenance_identity="provenance:test",
        issued_at=issued_at,
        ttl_seconds=ttl_seconds,
    )


class ExecutionPermissionTests(unittest.TestCase):
    def test_valid_permission_validates_and_is_immutable(self) -> None:
        item = permission()
        self.assertTrue(validate_execution_permission(item, now=101.0).valid)
        with self.assertRaises(FrozenInstanceError):
            item.scope = "OTHER"  # type: ignore[misc]

    def test_expired_permission_fails(self) -> None:
        result = validate_execution_permission(permission(), now=110.0)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "EXPIRED")

    def test_modified_target_fails_signature_validation(self) -> None:
        changed = replace(permission(), target_identity="element:other")
        result = validate_execution_permission(changed, now=101.0)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "INVALID_SIGNATURE")

    def test_modified_observation_id_fails_signature_validation(self) -> None:
        changed = replace(permission(), observation_id="obs-2")
        result = validate_execution_permission(changed, now=101.0)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "INVALID_SIGNATURE")

    def test_replayed_permission_fails(self) -> None:
        item = permission()
        self.assertTrue(consume_execution_permission(item, now=101.0).valid)
        result = validate_execution_permission(item, now=102.0)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "REPLAYED")

    def test_missing_field_fails_validation(self) -> None:
        manual = ExecutionPermission(
            permission_id="manual",
            observation_id="",
            action_intent_id="intent-1",
            target_identity="element:next",
            scope="PRODUCE_SELECTION",
            provenance_identity="provenance:test",
            issued_at=100.0,
            expires_at=110.0,
            single_use_state=AVAILABLE,
        )
        result = validate_execution_permission(manual, now=101.0)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "MISSING_FIELD")

    def test_manual_construction_cannot_create_valid_permission(self) -> None:
        manual = ExecutionPermission(
            permission_id="manual",
            observation_id="obs-1",
            action_intent_id="intent-1",
            target_identity="element:next",
            scope="PRODUCE_SELECTION",
            provenance_identity="provenance:test",
            issued_at=100.0,
            expires_at=110.0,
            single_use_state=AVAILABLE,
        )
        result = validate_execution_permission(manual, now=101.0)
        self.assertFalse(result.valid)
        self.assertEqual(result.reason, "INVALID_SIGNATURE")


if __name__ == "__main__":
    unittest.main()
