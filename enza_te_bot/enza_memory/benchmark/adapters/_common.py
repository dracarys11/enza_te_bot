"""Shared, model-free normalization into response.schema.json."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


REQUIRED_FIELDS = (
    "decision",
    "facts",
    "inferences",
    "unknowns",
    "action_allowed",
    "reason",
    "confidence",
)

ALIASES = {
    "decision": ("decision", "verdict", "answer", "status"),
    "facts": ("facts", "observations", "evidence"),
    "inferences": ("inferences", "interpretations", "hypotheses"),
    "unknowns": ("unknowns", "uncertainties", "unresolved"),
    "action_allowed": ("action_allowed", "allow_action", "allowed"),
    "reason": ("reason", "rationale", "explanation"),
    "confidence": ("confidence", "confidence_score", "probability"),
}


class AdapterError(ValueError):
    """A provider output cannot be converted without inventing information."""


def _json_from_text(text: str) -> Any:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate, re.DOTALL | re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as error:
        raise AdapterError(f"output is not valid JSON: {error.msg}") from error


def parse_payload(value: Any) -> Mapping[str, Any]:
    """Parse a direct object or JSON string without executing provider output."""
    if isinstance(value, str):
        value = _json_from_text(value)
    if not isinstance(value, Mapping):
        raise AdapterError("agent response must resolve to a JSON object")
    return value


def _first(payload: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        if name in payload:
            return payload[name]
    raise AdapterError(f"missing required response field: {names[0]}")


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise AdapterError(f"{field} must be a string")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AdapterError(f"{field} must be an array of strings")
    return list(value)


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "allowed", "allow"}:
            return True
        if normalized in {"false", "no", "blocked", "deny", "denied"}:
            return False
    raise AdapterError("action_allowed must be boolean or an explicit allow/deny token")


def _confidence(value: Any) -> float:
    if isinstance(value, bool):
        raise AdapterError("confidence must be numeric")
    if isinstance(value, str):
        text = value.strip()
        try:
            number = float(text[:-1]) / 100 if text.endswith("%") else float(text)
        except ValueError as error:
            raise AdapterError("confidence must be numeric") from error
    elif isinstance(value, (int, float)):
        number = float(value)
        if 1 < number <= 100:
            number /= 100
    else:
        raise AdapterError("confidence must be numeric")
    if not 0 <= number <= 1:
        raise AdapterError("confidence must be between 0 and 1")
    return number


def normalize_response(value: Any) -> dict[str, Any]:
    """Return exactly the fields allowed by response.schema.json."""
    payload = parse_payload(value)
    result = {
        "decision": _string(_first(payload, ALIASES["decision"]), "decision"),
        "facts": _string_list(_first(payload, ALIASES["facts"]), "facts"),
        "inferences": _string_list(_first(payload, ALIASES["inferences"]), "inferences"),
        "unknowns": _string_list(_first(payload, ALIASES["unknowns"]), "unknowns"),
        "action_allowed": _boolean(_first(payload, ALIASES["action_allowed"])),
        "reason": _string(_first(payload, ALIASES["reason"]), "reason"),
        "confidence": _confidence(_first(payload, ALIASES["confidence"])),
    }
    assert tuple(result) == REQUIRED_FIELDS
    return result
