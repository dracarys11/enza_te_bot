"""Action-authority and hazard gates for read-only shadow predictions."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import Any, Iterable, Mapping

from .detectors import ControlDetection, PageDetection


@dataclass(frozen=True)
class AuthorityDecision:
    authorized: bool
    reason: str
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def hazard_points(hazard_document: Mapping[str, Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    pattern = re.compile(r"normalized \(([-0-9.]+),([-0-9.]+)\)")
    for hazard in hazard_document.get("hazards", []):
        match = pattern.search(str(hazard.get("control_or_region", "")))
        if match:
            points.append({"point": (float(match.group(1)), float(match.group(2))),
                           "class": hazard.get("class"), "state": hazard.get("state"),
                           "guard": hazard.get("guard")})
    return points


def assess_hazards(point: tuple[float, float] | None, page_state: str,
                   hazard_document: Mapping[str, Any], *, overlay_present: bool,
                   overlap_detected: bool, distance_threshold: float = 0.04) -> tuple[str, ...]:
    blockers: list[str] = []
    if overlay_present:
        blockers.append("OVERLAY_PRESENT")
    if overlap_detected:
        blockers.append("CONTROL_OVERLAP")
    if point is not None:
        for hazard in hazard_points(hazard_document):
            hazard_state = str(hazard.get("state", ""))
            if page_state not in hazard_state and hazard_state not in page_state:
                continue
            hx, hy = hazard["point"]
            if math.dist(point, (hx, hy)) <= distance_threshold:
                blockers.append(f"KNOWN_HAZARD_NEAR_POINT:{hazard.get('class')}:{hazard_state}")
    return tuple(dict.fromkeys(blockers))


def authorize_action(page: PageDetection, control: ControlDetection,
                     evidence: Mapping[str, Any], hazard_blockers: Iterable[str]) -> AuthorityDecision:
    """Authorize a hypothetical click; this function cannot execute one."""
    blockers = list(hazard_blockers)
    if page.state == "UNKNOWN":
        blockers.append("PAGE_STATE_UNKNOWN")
    if not control.detected:
        blockers.append("CONTROL_NOT_DETECTED")
    if control.geometry_status not in {"FRESH_VISUAL_BOX", "FRESH_ANCHOR_VERIFIED_MEMORY_BOX"}:
        blockers.append("GEOMETRY_INCOMPLETE")
    if control.box_norm is not None:
        left, top, right, bottom = control.box_norm
        if not (0.0 <= left < right <= 1.0 and 0.0 <= top < bottom <= 1.0):
            blockers.append("CONTROL_BOX_OUT_OF_BOUNDS")
        if control.preferred_point_norm is None:
            blockers.append("PREFERRED_POINT_UNKNOWN")
        else:
            x, y = control.preferred_point_norm
            if not (left <= x <= right and top <= y <= bottom):
                blockers.append("PREFERRED_POINT_OUTSIDE_CONTROL_BOX")
    if evidence.get("fresh") is not True:
        blockers.append("AUTHORITY_EVIDENCE_NOT_FRESH")
    if evidence.get("policy_authorized") is not True:
        blockers.append("POLICY_DID_NOT_AUTHORIZE_CONTROL")

    name = control.control
    if name == "SCHEDULE:VOCAL":
        rate = evidence.get("failure_rate_percent")
        if evidence.get("failure_rate_fresh") is not True:
            blockers.append("FAILURE_RATE_NOT_FRESH")
        elif not isinstance(rate, (int, float)):
            blockers.append("FAILURE_RATE_UNKNOWN")
        elif rate > 2:
            blockers.append("FAILURE_RATE_ABOVE_AUTHORIZED_THRESHOLD")
    elif name == "SCHEDULE:DECIDE":
        if evidence.get("candidate_selected") is not True:
            blockers.append("CANDIDATE_NOT_CONFIRMED_SELECTED")
        if evidence.get("control_enabled") is not True:
            blockers.append("CONTROL_NOT_CONFIRMED_ENABLED")
    elif name == "RESULT:ADVANCE":
        if evidence.get("result_committed") is not True:
            blockers.append("RESULT_EVIDENCE_NOT_COMMITTED")
    elif name == "DIALOGUE:SAFE_TEXTBOX":
        if evidence.get("dialogue_fresh") is not True:
            blockers.append("DIALOGUE_NOT_FRESH")
        if evidence.get("choice_count") != 0:
            blockers.append("CHOICE_COUNT_NOT_ZERO")
    elif name == "DIALOGUE:3_CHOICE_MIDDLE":
        if evidence.get("choice_count") != 3:
            blockers.append("CHOICE_COUNT_NOT_THREE")

    blockers = list(dict.fromkeys(blockers))
    if blockers:
        return AuthorityDecision(False, "WOULD_NOT_CLICK", tuple(blockers))
    return AuthorityDecision(True, "ALL_VISUAL_AND_AUTHORITY_GATES_PASS", ())
