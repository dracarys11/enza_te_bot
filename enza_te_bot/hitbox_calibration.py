"""Offline target-calibration evidence models.

This module records what was visually estimated and what a deliberate probe
actually produced.  It does not turn visual bounds into an executable hitbox,
and it has no mouse/browser dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class CalibrationSchemaError(ValueError):
    """Raised when calibration evidence is incomplete or overclaims precision."""


class CalibrationResult(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


def _bounds(value: Sequence[float]) -> tuple[float, float, float, float]:
    if len(value) != 4:
        raise CalibrationSchemaError("visual_bounds must have four normalized values")
    result = tuple(float(item) for item in value)
    if not (0 <= result[0] < result[2] <= 1 and 0 <= result[1] < result[3] <= 1):
        raise CalibrationSchemaError("visual_bounds must be normalized and contained in [0, 1]")
    return result


def _point(value: Sequence[float]) -> tuple[float, float]:
    if len(value) != 2:
        raise CalibrationSchemaError("attempted point must have two normalized values")
    result = tuple(float(item) for item in value)
    if not all(0 <= item <= 1 for item in result):
        raise CalibrationSchemaError("attempted point must be normalized")
    return result


@dataclass(frozen=True, slots=True)
class VisualBounds:
    """A screenshot estimate, explicitly not an exact hitbox."""

    bounds: tuple[float, float, float, float]
    precision: str = "APPROXIMATE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "bounds", _bounds(self.bounds))
        precision = str(self.precision).upper()
        if precision != "APPROXIMATE":
            raise CalibrationSchemaError(
                "visual bounds cannot be represented as an exact hitbox")
        object.__setattr__(self, "precision", precision)

    def as_dict(self) -> dict[str, Any]:
        return {"bounds": list(self.bounds), "precision": self.precision}


@dataclass(frozen=True, slots=True)
class CalibrationAttempt:
    """One deliberate probe, including a failed or unknown outcome."""

    point: tuple[float, float]
    result: CalibrationResult
    evidence_ref: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "point", _point(self.point))
        result = self.result if isinstance(self.result, CalibrationResult) else CalibrationResult(str(self.result).upper())
        object.__setattr__(self, "result", result)

    def as_dict(self) -> dict[str, Any]:
        return {
            "point": list(self.point), "result": self.result.value,
            "evidence_ref": self.evidence_ref, "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class TargetCalibration:
    """Immutable, evidence-only calibration for one visually located target."""

    target_id: str
    observation_id: str
    visual_bounds: VisualBounds
    attempted_points: tuple[CalibrationAttempt, ...]
    result: CalibrationResult
    confidence: float

    def __post_init__(self) -> None:
        if not str(self.target_id).strip() or not str(self.observation_id).strip():
            raise CalibrationSchemaError("target_id and observation_id are required")
        if not isinstance(self.visual_bounds, VisualBounds):
            raise CalibrationSchemaError("visual_bounds must be approximate VisualBounds")
        attempts = tuple(self.attempted_points)
        if any(not isinstance(item, CalibrationAttempt) for item in attempts):
            raise CalibrationSchemaError("attempted_points must contain CalibrationAttempt values")
        object.__setattr__(self, "attempted_points", attempts)
        result = self.result if isinstance(self.result, CalibrationResult) else CalibrationResult(str(self.result).upper())
        object.__setattr__(self, "result", result)
        try:
            confidence = float(self.confidence)
        except (TypeError, ValueError) as error:
            raise CalibrationSchemaError("confidence must be numeric") from error
        if not 0 <= confidence <= 1:
            raise CalibrationSchemaError("confidence must be in [0, 1]")
        object.__setattr__(self, "confidence", confidence)
        if result is CalibrationResult.FAILED and not any(
            item.result is CalibrationResult.FAILED for item in attempts
        ):
            raise CalibrationSchemaError("FAILED calibration must record a failed click attempt")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TargetCalibration":
        if not isinstance(data, Mapping):
            raise CalibrationSchemaError("calibration must be an object")
        raw_bounds = data.get("visual_bounds")
        if not isinstance(raw_bounds, Mapping):
            raise CalibrationSchemaError(
                "visual_bounds must declare bounds and approximate precision")
        precision = str(raw_bounds.get("precision", "")).upper()
        if precision != "APPROXIMATE":
            raise CalibrationSchemaError("visual_bounds cannot become an exact hitbox")
        raw_attempts = data.get("attempted_points")
        if not isinstance(raw_attempts, list):
            raise CalibrationSchemaError("attempted_points must be a list")
        attempts = []
        for index, item in enumerate(raw_attempts):
            if not isinstance(item, Mapping):
                raise CalibrationSchemaError(f"attempted_points[{index}] must be an object")
            try:
                attempts.append(CalibrationAttempt(
                    tuple(item["point"]), CalibrationResult(str(item["result"]).upper()),
                    item.get("evidence_ref"), item.get("note"),
                ))
            except (KeyError, TypeError, ValueError) as error:
                raise CalibrationSchemaError(f"invalid attempted_points[{index}]") from error
        try:
            result = CalibrationResult(str(data["result"]).upper())
            return cls(
                str(data["target_id"]), str(data["observation_id"]),
                VisualBounds(tuple(raw_bounds["bounds"]), precision), tuple(attempts),
                result, float(data["confidence"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise CalibrationSchemaError("invalid target calibration fields") from error

    def as_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "observation_id": self.observation_id,
            "visual_bounds": self.visual_bounds.as_dict(),
            "attempted_points": [item.as_dict() for item in self.attempted_points],
            "result": self.result.value,
            "confidence": self.confidence,
            "authorizes_exact_hitbox": False,
        }


__all__ = [
    "CalibrationSchemaError", "CalibrationResult", "VisualBounds",
    "CalibrationAttempt", "TargetCalibration",
]
