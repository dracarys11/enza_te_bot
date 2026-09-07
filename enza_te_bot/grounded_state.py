"""Offline grounded-state evidence model.

Business labels are kept separate from what the screenshot actually proves.
This module never authorizes actions and never promotes coordinate-only visual
evidence to a verified semantic state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from observation_artifact_schema import validate_observation_artifact


UNKNOWN_UNIDENTIFIED = "UNKNOWN_UNIDENTIFIED"


class GroundedStateSchemaError(ValueError):
    """Raised when grounded-state evidence is malformed or overclaims."""


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GroundedStateSchemaError(f"{field} is required")
    return value.strip()


def _evidence_flag(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, Mapping):
        return bool(value.get("verified") or value.get("read") or value.get("present"))
    return False


@dataclass(frozen=True, slots=True)
class GroundedState:
    state_id: str
    label: str
    observation_id: str
    identity_source: str
    facts: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    title_text_read: bool = False
    roundtrip_evidence: bool = False
    verification_level: str = "UNKNOWN"

    def __post_init__(self) -> None:
        for field in ("state_id", "label", "observation_id", "identity_source"):
            _text(getattr(self, field), field)
        facts = tuple(str(item) for item in self.facts)
        inferences = tuple(str(item) for item in self.inferences)
        unknowns = tuple(str(item) for item in self.unknowns)
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "inferences", inferences)
        object.__setattr__(self, "unknowns", unknowns)
        verified_evidence = bool(self.title_text_read or self.roundtrip_evidence)
        level = str(self.verification_level).upper()
        if level == "VERIFIED" and not verified_evidence:
            raise GroundedStateSchemaError(
                "VERIFIED state requires title_text_read or roundtrip_evidence")
        if not verified_evidence:
            level = "UNKNOWN"
        if level not in {"UNKNOWN", "VERIFIED"}:
            raise GroundedStateSchemaError("verification_level must be UNKNOWN or VERIFIED")
        object.__setattr__(self, "title_text_read", bool(self.title_text_read))
        object.__setattr__(self, "roundtrip_evidence", bool(self.roundtrip_evidence))
        object.__setattr__(self, "verification_level", level)
        if level == "UNKNOWN":
            object.__setattr__(self, "label", UNKNOWN_UNIDENTIFIED)

    @classmethod
    def from_artifact(cls, data: Mapping[str, Any]) -> "GroundedState":
        """Create evidence without promoting an artifact's semantic label."""
        try:
            validate_observation_artifact(data)
        except ValueError as error:
            raise GroundedStateSchemaError(str(error)) from error
        state = data.get("state")
        if not isinstance(state, Mapping):
            state = {}
        label = str(state.get("label") or UNKNOWN_UNIDENTIFIED)
        identity_source = state.get("identity_source")
        if not isinstance(identity_source, str) or not identity_source.strip():
            capture = data.get("capture_provenance")
            identity_source = capture.get("source") if isinstance(capture, Mapping) else None
        if not isinstance(identity_source, str) or not identity_source.strip():
            identity_source = "UNSPECIFIED"
        evidence = data.get("identity_evidence")
        if not isinstance(evidence, Mapping):
            evidence = state.get("identity_evidence") if isinstance(state.get("identity_evidence"), Mapping) else {}
        title_read = _evidence_flag(evidence.get("title_text_read"))
        roundtrip = _evidence_flag(evidence.get("roundtrip_evidence"))
        facts = data.get("facts", [])
        inferences = data.get("inferences", [])
        unknowns = data.get("unknowns", [])
        return cls(
            state_id=label,
            label=label,
            observation_id=_text(data.get("observation_id"), "observation_id"),
            identity_source=str(identity_source),
            facts=tuple(str(item) for item in facts if isinstance(item, str)),
            inferences=tuple(str(item) for item in inferences if isinstance(item, str)),
            unknowns=tuple(str(item) for item in unknowns if isinstance(item, str)),
            title_text_read=title_read,
            roundtrip_evidence=roundtrip,
            verification_level="VERIFIED" if title_read or roundtrip else "UNKNOWN",
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "GroundedState":
        if not isinstance(data, Mapping):
            raise GroundedStateSchemaError("grounded state must be an object")
        try:
            return cls(
                _text(data.get("state_id"), "state_id"), _text(data.get("label"), "label"),
                _text(data.get("observation_id"), "observation_id"),
                _text(data.get("identity_source"), "identity_source"),
                tuple(str(item) for item in data.get("facts", ())),
                tuple(str(item) for item in data.get("inferences", ())),
                tuple(str(item) for item in data.get("unknowns", ())),
                bool(data.get("title_text_read")), bool(data.get("roundtrip_evidence")),
                str(data.get("verification_level", "UNKNOWN")),
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, GroundedStateSchemaError):
                raise
            raise GroundedStateSchemaError("invalid grounded state") from error

    def as_dict(self) -> dict[str, Any]:
        return {
            "state_id": self.state_id,
            "label": self.label,
            "observation_id": self.observation_id,
            "identity_source": self.identity_source,
            "facts": list(self.facts),
            "inferences": list(self.inferences),
            "unknowns": list(self.unknowns),
            "title_text_read": self.title_text_read,
            "roundtrip_evidence": self.roundtrip_evidence,
            "verification_level": self.verification_level,
        }


__all__ = ["UNKNOWN_UNIDENTIFIED", "GroundedStateSchemaError", "GroundedState"]
