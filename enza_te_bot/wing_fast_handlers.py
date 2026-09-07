"""Bounded fast-path handlers distilled from live WING run findings.

Pure decision functions only: perception results (what native cheap vision
saw) are passed in as explicit flags; this module never interprets pixels,
never clicks, and never calls AGY.  Every function fails closed when the
required perception is missing or ambiguous.
"""
from __future__ import annotations

from typing import Any, Mapping


# ---------------------------------------------------------------------------
# 0. VOCAL failure-rate attention ROI contract (SCHEDULE page)
# ---------------------------------------------------------------------------

VOCAL_FAILURE_ROI = {
    "field": "vocal_failure_rate_percent",
    "source_state": "SCHEDULE",
    "control_card": "VOCAL",
    "validated_viewport": {"width": 1280, "height": 720},
    # normalized ROI over the VOCAL card's 失敗率 label+value block
    "normalized_roi": [0.235, 0.72, 0.115, 0.08],
    "expected_label_context": ["失敗率", "失敗", "percent sign"],
    "digit_range": (0, 100),
}


def vocal_failure_roi_status(viewport: Mapping[str, Any]) -> str:
    """Return the ROI contract state for the current viewport signature."""
    if (viewport.get("width"), viewport.get("height")) == (
        VOCAL_FAILURE_ROI["validated_viewport"]["width"],
        VOCAL_FAILURE_ROI["validated_viewport"]["height"],
    ):
        return "VALIDATED"
    return "UNVALIDATED"


def parse_failure_rate_percent(reads: list[str]) -> int | None:
    """Parse cheap digit reads from the ROI into a percent int, or None.

    ``reads`` are the raw single/multi digit strings seen in the ROI.
    Conflicting readings fail closed to None (never guessed to 0).
    """
    cleaned: list[int] = []
    for r in reads:
        if r is None:
            continue
        text = str(r).replace("%", "").strip()
        if not text.isdigit():
            continue
        value = int(text)
        lo, hi = VOCAL_FAILURE_ROI["digit_range"]
        if value < lo or value > hi:
            continue
        cleaned.append(value)
    if not cleaned:
        return None
    if len(set(cleaned)) != 1:
        return None  # OCR conflict → fail closed
    return cleaned[0]


SCHEDULE_BACK_TO_REST_PATH = {
    "steps": [
        {"action": "back", "control": "SCHEDULE.back_arrow", "coordinate": [57, 660]},
        {"action": "verify", "target": "WING_HOME fresh"},
        {"action": "click", "control": "WING_HOME.rest", "coordinate": [430, 660]},
        {"action": "verify", "target": "REST room entry transition"},
    ],
    "risk_class": "SAFE_NAVIGATION",
    "viewport_signature": "1280x720",
}


# ---------------------------------------------------------------------------
# 1. Morning timed three-choice fast handler
# ---------------------------------------------------------------------------

def morning_three_choice(detection: Mapping[str, Any]) -> dict[str, Any]:
    """Decide how to handle a suspected morning timed 3-choice screen.

    ``detection`` keys (produced by cheap runtime vision over the taught ROI):
      state_confirmed:        bool — page identity is a known morning-choice context
      green_frames:           int | None — count of green-frame option boxes detected in ROI
      options_visible:        int | None — number of selectable options confirmed visible
      middle_option_clickable: bool — middle option passed viewport/geometry guard
      viewport_signature:     any — must match the taught viewport for coords
    """
    timings = {
        "detection_ms": detection.get("detection_ms"),
        "click_latency_ms": detection.get("click_latency_ms"),
        "total_handler_ms": detection.get("total_handler_ms"),
    }
    if detection.get("state_confirmed") is not True:
        return {**timings, "decision": "STOP", "reason": "MORNING_STATE_UNCERTAIN"}
    greens = detection.get("green_frames")
    options = detection.get("options_visible")
    if greens is not None and greens >= 3 and options == 3:
        if detection.get("middle_option_clickable") is True:
            return {**timings, "decision": "CHOOSE_MIDDLE",
                    "reason": "MORNING_THREE_CHOICE_CONFIRMED", "selection_index": 2}
        return {**timings, "decision": "STOP", "reason": "MIDDLE_OPTION_NOT_CLICKABLE"}
    # green-frame detection missed, but the state is confirmed and the taught
    # middle coordinate passed the viewport/geometry guard: one guarded click.
    if detection.get("taught_middle_coord_valid") is True:
        return {**timings, "decision": "GUARDED_FALLBACK_CLICK",
                "reason": "GREEN_FRAME_MISS_GUARDED_FALLBACK", "selection_index": 2}
    return {**timings, "decision": "STOP", "reason": "MORNING_THREE_CHOICE_UNCONFIRMED"}


# ---------------------------------------------------------------------------
# 2. Promise / constraint dialogue 見送 fast path
# ---------------------------------------------------------------------------

def promise_dialogue(facts: Mapping[str, Any]) -> dict[str, Any]:
    """Decide the fastest safe exit for a promise/constraint dialogue.

    ``facts`` keys (fresh, current-page-only visual/control evidence):
      dialogue_page_fresh:  bool — this evidence is from the current frame
      miokuri_visible:      bool — 見送 control detected on this dialogue page
      miokuri_geometry_valid: bool — passed viewport/geometry guard
      in_true_choice:       bool — page is already a real 2/3-choice state
    Precedence: 見送 fast path > fast-forward/textbox fallback > choice policy;
    the fast path must never override an actual business-choice state.
    """
    if facts.get("dialogue_page_fresh") is not True:
        return {"decision": "STOP", "reason": "STALE_DIALOGUE_EVIDENCE"}
    if facts.get("in_true_choice") is True:
        return {"decision": "USE_BUSINESS_CHOICE_POLICY",
                "reason": "CHOICE_POLICY_PRECEDES_MIOKURI"}
    if facts.get("miokuri_visible") is True and facts.get("miokuri_geometry_valid") is True:
        return {"decision": "CLICK_MIOKURI", "reason": "PROMISE_MIOKURI_FAST_PATH"}
    if facts.get("miokuri_visible") is True:
        return {"decision": "STOP", "reason": "MIOKURI_GEOMETRY_INVALID"}
    return {"decision": "FALLBACK_FAST_FORWARD_OR_TEXTBOX",
            "reason": "MIOKURI_NOT_PRESENT"}
