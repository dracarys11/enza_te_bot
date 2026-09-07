"""Offline-only, single-use authorization token model.

This module defines the permission object issued by ActionGate approval for a
future EnvironmentProvider authorization boundary.  It performs no environment
I/O, and EnvironmentProvider does not consume permissions yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import secrets
import time
from typing import Any


AVAILABLE = "AVAILABLE"
_SIGNING_KEY = secrets.token_bytes(32)
_CONSUMED_PERMISSION_IDS: set[str] = set()


@dataclass(frozen=True, slots=True)
class ExecutionPermission:
    permission_id: str
    observation_id: str
    action_intent_id: str
    target_identity: str
    scope: str
    provenance_identity: str
    issued_at: float
    expires_at: float
    single_use_state: str
    _signature: str | None = field(default=None, init=False, repr=False, compare=False)

    def as_dict(self) -> dict[str, Any]:
        """Return public evidence only; the signing material is never exposed."""
        return {
            "permission_id": self.permission_id,
            "observation_id": self.observation_id,
            "action_intent_id": self.action_intent_id,
            "target_identity": self.target_identity,
            "scope": self.scope,
            "provenance_identity": self.provenance_identity,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "single_use_state": self.single_use_state,
        }


@dataclass(frozen=True, slots=True)
class PermissionValidation:
    valid: bool
    reason: str


def _payload(permission: ExecutionPermission) -> bytes:
    values = (
        permission.permission_id,
        permission.observation_id,
        permission.action_intent_id,
        permission.target_identity,
        permission.scope,
        permission.provenance_identity,
        format(permission.issued_at, ".17g"),
        format(permission.expires_at, ".17g"),
        permission.single_use_state,
    )
    return "\x1f".join(values).encode("utf-8")


def _signature(permission: ExecutionPermission) -> str:
    return hmac.new(_SIGNING_KEY, _payload(permission), hashlib.sha256).hexdigest()


def issue_execution_permission(*, observation_id: str, action_intent_id: str,
                               target_identity: str, scope: str,
                               provenance_identity: str,
                               ttl_seconds: float = 5.0,
                               issued_at: float | None = None) -> ExecutionPermission:
    """Issue a signed permission through the sole module-owned issuance path.

    ActionGate is the production caller in the current offline phase.  Runtime
    execution remains deliberately disconnected.
    """
    fields = {
        "observation_id": observation_id,
        "action_intent_id": action_intent_id,
        "target_identity": target_identity,
        "scope": scope,
        "provenance_identity": provenance_identity,
    }
    missing = [name for name, value in fields.items() if not isinstance(value, str) or not value.strip()]
    if missing:
        raise ValueError(f"permission issuance missing fields: {', '.join(missing)}")
    ttl = float(ttl_seconds)
    if ttl <= 0:
        raise ValueError("ttl_seconds must be positive")
    issued = time.monotonic() if issued_at is None else float(issued_at)
    permission = ExecutionPermission(
        permission_id=f"perm_{secrets.token_hex(16)}",
        observation_id=observation_id.strip(),
        action_intent_id=action_intent_id.strip(),
        target_identity=target_identity.strip(),
        scope=scope.strip(),
        provenance_identity=provenance_identity.strip(),
        issued_at=issued,
        expires_at=issued + ttl,
        single_use_state=AVAILABLE,
    )
    object.__setattr__(permission, "_signature", _signature(permission))
    return permission


def validate_execution_permission(permission: object, *, now: float | None = None) -> PermissionValidation:
    """Validate authenticity, completeness, expiry, and single-use state."""
    if not isinstance(permission, ExecutionPermission):
        return PermissionValidation(False, "INVALID_TYPE")
    required = (
        permission.permission_id,
        permission.observation_id,
        permission.action_intent_id,
        permission.target_identity,
        permission.scope,
        permission.provenance_identity,
        permission.single_use_state,
    )
    if any(not isinstance(value, str) or not value.strip() for value in required):
        return PermissionValidation(False, "MISSING_FIELD")
    if permission.single_use_state != AVAILABLE:
        return PermissionValidation(False, "INVALID_SINGLE_USE_STATE")
    if permission._signature is None or not hmac.compare_digest(permission._signature, _signature(permission)):
        return PermissionValidation(False, "INVALID_SIGNATURE")
    if permission.permission_id in _CONSUMED_PERMISSION_IDS:
        return PermissionValidation(False, "REPLAYED")
    current = time.monotonic() if now is None else float(now)
    if permission.expires_at <= permission.issued_at or current >= permission.expires_at:
        return PermissionValidation(False, "EXPIRED")
    return PermissionValidation(True, "VALID")


def consume_execution_permission(permission: object, *, now: float | None = None) -> PermissionValidation:
    """Atomically mark a valid permission consumed in this process."""
    validation = validate_execution_permission(permission, now=now)
    if not validation.valid:
        return validation
    assert isinstance(permission, ExecutionPermission)
    _CONSUMED_PERMISSION_IDS.add(permission.permission_id)
    return PermissionValidation(True, "CONSUMED")


__all__ = [
    "AVAILABLE", "ExecutionPermission", "PermissionValidation",
    "issue_execution_permission", "validate_execution_permission",
    "consume_execution_permission",
]
