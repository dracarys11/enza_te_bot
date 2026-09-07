"""Small declarative policy boundary for the offline VOCAL harness."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class PolicyViolation(ValueError):
    pass


def load_policy(path: str | Path | None = None) -> dict[str, Any]:
    policy_path = Path(path) if path is not None else Path(__file__).with_name("vocal_mvp_policy.json")
    with policy_path.open(encoding="utf-8") as handle:
        policy = json.load(handle)
    required = {"policy_id", "allowed_states", "allowed_actions", "forbidden_actions", "max_goal"}
    if not required.issubset(policy):
        raise PolicyViolation("policy missing required fields")
    return policy


def validate_state(state: str, policy: Mapping[str, Any] | None = None) -> bool:
    active = policy or load_policy()
    value = str(state)
    if value not in active.get("allowed_states", []):
        raise PolicyViolation(f"state '{value}' is outside policy allowed_states")
    return True


def validate_action(action: str, policy: Mapping[str, Any] | None = None) -> bool:
    active = policy or load_policy()
    value = str(action)
    if value in active.get("forbidden_actions", []):
        raise PolicyViolation(f"action '{value}' is explicitly forbidden")
    if value not in active.get("allowed_actions", []):
        raise PolicyViolation(f"action '{value}' is outside policy allowed_actions")
    return True


__all__ = ["PolicyViolation", "load_policy", "validate_state", "validate_action"]
