"""Cheap, AGY-free HOME observation and control-evidence helpers.

This module deliberately stops at evidence and authorization inputs.  It does
not choose a room, call AGY, or inject input.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import time
from typing import Any, Iterable, Mapping

from PIL import Image

from home_observation import (
    configured_rois, detect_fan_target_clear, detect_stamina_adequate,
    parse_fan_gap_to_target, parse_season, parse_weeks_remaining, smoke_ocr,
)
from states import State
from vision import detect_state, normalized_roi_to_pixels


ESCALATION_REQUIRED = "escalation_required"
KNOWN = "KNOWN"
UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HomeFastObservation:
    status: str
    state: str
    fields: dict[str, Any]
    evidence: dict[str, Any]
    screenshot_sha256: str
    viewport_signature: str
    timings: dict[str, float]
    escalation_required: bool
    escalation_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ControlBinding:
    control_id: str
    source_state: str
    viewport_signature: str
    geometry_space: str
    normalized_bbox: tuple[float, float, float, float]
    expected_next_states: tuple[str, ...]
    local_anchor: str | None = None
    template_identity: str | None = None


def viewport_signature(image: Image.Image, window: Mapping[str, Any] | None = None) -> str:
    payload = {"image_size": [image.width, image.height], "window": dict(window or {})}
    return hashlib.sha256(repr(sorted(payload.items())).encode()).hexdigest()[:24]


def _crop(image: Image.Image, roi: list[float]):
    x1, y1, x2, y2 = normalized_roi_to_pixels(roi, {"width": image.width, "height": image.height})
    return image.crop((x1, y1, x2, y2))


def observe_home_fast(image: Image.Image, config: Mapping[str, Any], *,
                      required_fields: Iterable[str] = (),
                      expected_values: Mapping[str, Any] | None = None,
                      screenshot_sha256: str | None = None,
                      window: Mapping[str, Any] | None = None) -> HomeFastObservation:
    """Observe only requested HOME fields using local cheap sensors."""
    started = time.perf_counter()
    required = tuple(dict.fromkeys(required_fields))
    unknown_fields = [f for f in required if f not in {"season", "weeks_remaining", "fan_gap_to_target", "stamina"}]
    state_started = time.perf_counter()
    state = detect_state(image, dict(config), __import__("pathlib").Path(__file__).resolve().parent)
    state_ms = (time.perf_counter() - state_started) * 1000
    reasons: list[str] = list(f"unknown_required_field:{f}" for f in unknown_fields)
    if state.state.value != State.HOME.value:
        reasons.append("home_state_not_confirmed")
    rois = configured_rois(dict(config))
    fields: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    projection_started = time.perf_counter()
    home_cfg = (config.get("perception") or {}).get("home_observation") or {}
    ocr_fields = [f for f in required if f in {"season", "weeks_remaining", "fan_gap_to_target"} and f in rois]
    raw, diagnostics = (smoke_ocr(
        image, {f: rois[f] for f in ocr_fields},
        weeks_template_matching=home_cfg.get("weeks_remaining", {}).get("template_matching"),
        fan_target_clear_settings=home_cfg.get("fan_gap_to_target", {}).get("clear_marker"),
        stamina_settings=home_cfg.get("stamina"),
    ) if ocr_fields else ({}, {}))
    for field in required:
        if field == "season":
            value, error = parse_season(raw.get(field, ""))
        elif field == "weeks_remaining":
            value, error = parse_weeks_remaining(raw.get(field, ""), home_cfg.get(field, {}).get("range", []))
        elif field == "fan_gap_to_target":
            value, error = parse_fan_gap_to_target(raw.get(field, ""))
        elif field == "stamina":
            marker = detect_stamina_adequate(_crop(image, rois[field]), home_cfg.get(field)) if field in rois else {"adequate": None, "reason": "stamina ROI missing"}
            value, error = marker.get("adequate"), marker.get("reason")
            evidence[field] = marker
        else:
            continue
        fields[field] = value if error is None else None
        evidence.setdefault(field, {}).update(diagnostics.get(field, {}))
        evidence[field]["raw"] = raw.get(field, "")
        if error:
            evidence[field]["error"] = error
            reasons.append(f"missing_or_ambiguous:{field}")
    if "fan_gap_to_target" in required and "fan_gap_to_target" in rois:
        evidence.setdefault("fan_gap_to_target", {})["clear_marker"] = detect_fan_target_clear(
            _crop(image, rois["fan_gap_to_target"]), home_cfg.get("fan_gap_to_target", {}).get("clear_marker")
        )
    projection_ms = (time.perf_counter() - projection_started) * 1000
    expected_values = expected_values or {}
    for field, expected in expected_values.items():
        if field in fields and fields[field] is not None and fields[field] != expected:
            reasons.append(f"expected_value_conflict:{field}")
    digest = screenshot_sha256 or ("sha256:" + hashlib.sha256(image.tobytes()).hexdigest())
    timings = {"screenshot_ms": 0.0, "state_detection_ms": round(state_ms, 3),
               "field_projection_ms": round(projection_ms, 3), "action_gate_ms": 0.0}
    timings["total_observation_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return HomeFastObservation(
        status=KNOWN if not reasons else UNKNOWN, state=state.state.value, fields=fields,
        evidence=evidence, screenshot_sha256=digest,
        viewport_signature=viewport_signature(image, window), timings=timings,
        escalation_required=bool(reasons), escalation_reasons=tuple(reasons),
    )


def authorize_control(observation: HomeFastObservation, binding: ControlBinding, *,
                      action_ttl_valid: bool, bbox_in_bounds: bool,
                      local_anchor_valid: bool) -> tuple[bool, str]:
    """Perform cheap pre-gate checks; never executes an action."""
    if observation.status != KNOWN or observation.state != binding.source_state:
        return False, "STATE_NOT_FRESH"
    if observation.viewport_signature != binding.viewport_signature:
        return False, "STALE_VIEWPORT"
    if binding.geometry_space != "game_window_normalized":
        return False, "INVALID_GEOMETRY_SPACE"
    if not bbox_in_bounds:
        return False, "BBOX_OUT_OF_BOUNDS"
    if not local_anchor_valid:
        return False, "LOCAL_ANCHOR_MISMATCH"
    if not action_ttl_valid:
        return False, "ACTION_TTL_EXPIRED"
    return True, "EVIDENCE_AND_GEOMETRY_VALID"


def verify_expected_next_state(image: Image.Image, config: Mapping[str, Any],
                               expected_next_states: Iterable[str]) -> tuple[bool, str]:
    detected = detect_state(image, dict(config), __import__("pathlib").Path(__file__).resolve().parent)
    expected = tuple(expected_next_states)
    return (True, detected.state.value) if detected.state.value in expected else (False, "UNKNOWN")


__all__ = ["HomeFastObservation", "ControlBinding", "observe_home_fast",
           "authorize_control", "verify_expected_next_state", "ESCALATION_REQUIRED"]
