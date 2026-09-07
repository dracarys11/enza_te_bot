"""Deterministic, screenshot-only page and control detectors for Bundle A."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

import cv2
import numpy as np
from PIL import Image


UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class PageDetection:
    state: str
    confidence: float
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ControlDetection:
    control: str
    detected: bool
    box_norm: tuple[float, float, float, float] | None
    preferred_point_norm: tuple[float, float] | None
    confidence: float
    geometry_status: str
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


EXPECTED_PAGE = {
    "HOME:SCHEDULE": "HOME",
    "HOME:REST": "HOME",
    "SCHEDULE:VOCAL": "SCHEDULE",
    "SCHEDULE:DECIDE": "SCHEDULE",
    "SCHEDULE:BACK": "SCHEDULE",
    "RESULT:ADVANCE": "RESULT",
    "DIALOGUE:SAFE_TEXTBOX": "DIALOGUE",
    "DIALOGUE:3_CHOICE_MIDDLE": "CHOICE_3",
}


def _hsv(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2HSV)


def _white_rectangles(image: Image.Image) -> list[tuple[float, float, float, float]]:
    hsv = _hsv(image)
    height, width = hsv.shape[:2]
    mask = ((hsv[:, :, 1] < 58) & (hsv[:, :, 2] > 185)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((11, 11), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[float, float, float, float]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if w < width * 0.08 or h < height * 0.045:
            continue
        boxes.append((x / width, y / height, (x + w) / width, (y + h) / height))
    return boxes


def _three_choice_boxes(image: Image.Image) -> list[tuple[float, float, float, float]]:
    boxes = []
    for box in _white_rectangles(image):
        left, top, right, bottom = box
        width, height = right - left, bottom - top
        center_y = (top + bottom) / 2
        if 0.18 <= width <= 0.38 and 0.10 <= height <= 0.34 and center_y < 0.48:
            boxes.append(box)
    boxes.sort(key=lambda item: item[0])
    # Merge duplicate/nested detections by horizontal center.
    merged: list[tuple[float, float, float, float]] = []
    for box in boxes:
        center = (box[0] + box[2]) / 2
        if merged and abs(center - (merged[-1][0] + merged[-1][2]) / 2) < 0.06:
            previous = merged[-1]
            if (box[2] - box[0]) * (box[3] - box[1]) > (previous[2] - previous[0]) * (previous[3] - previous[1]):
                merged[-1] = box
        else:
            merged.append(box)
    return merged


def _fraction(hsv: np.ndarray, roi: tuple[float, float, float, float], *,
              hue: tuple[int, int] | None = None, saturation_min: int = 0,
              value_min: int = 0) -> float:
    height, width = hsv.shape[:2]
    left, top, right, bottom = roi
    crop = hsv[round(top * height):round(bottom * height),
               round(left * width):round(right * width)]
    if crop.size == 0:
        return 0.0
    mask = (crop[:, :, 1] >= saturation_min) & (crop[:, :, 2] >= value_min)
    if hue is not None:
        mask &= (crop[:, :, 0] >= hue[0]) & (crop[:, :, 0] <= hue[1])
    return float(mask.mean())


def detect_page_state(frame: Image.Image) -> PageDetection:
    """Classify only Bundle-A page shapes; unknown layouts fail closed."""
    choice_boxes = _three_choice_boxes(frame)
    if len(choice_boxes) == 3:
        return PageDetection("CHOICE_3", 0.96, ("three distinct upper selectable-card interiors",))
    if len(choice_boxes) == 2:
        return PageDetection("CHOICE_2", 0.93, ("two distinct upper selectable-card interiors",))

    white_boxes = _white_rectangles(frame)
    wide_lower = [b for b in white_boxes if (b[2] - b[0]) >= 0.48 and b[1] >= 0.58]
    right_buttons = [b for b in white_boxes if b[0] >= 0.82 and (b[3] - b[1]) >= 0.07]
    hsv = _hsv(frame)
    schedule_pink = _fraction(hsv, (0.20, 0.12, 0.99, 0.56), hue=(145, 179),
                              saturation_min=45, value_min=110)
    result_pink_border = _fraction(hsv, (0.0, 0.0, 1.0, 1.0), hue=(145, 179),
                                   saturation_min=35, value_min=120)
    left_result_edge = _fraction(hsv, (0.0, 0.0, 0.08, 1.0), hue=(145, 179),
                                 saturation_min=35, value_min=120)
    if (wide_lower and result_pink_border >= 0.10 and schedule_pink < 0.24) or left_result_edge >= 0.25:
        evidence = ["pink presentation overlay"]
        if wide_lower:
            evidence.append("wide lower result panel")
        evidence.append(f"left-edge overlay fraction={left_result_edge:.3f}")
        return PageDetection("RESULT", 0.88, tuple(evidence))
    if schedule_pink >= 0.24:
        return PageDetection("SCHEDULE", min(0.98, 0.65 + schedule_pink),
                             (f"schedule-card pink field fraction={schedule_pink:.3f}",))
    textbox_crop = hsv[round(hsv.shape[0] * 0.72):round(hsv.shape[0] * 0.98),
                        round(hsv.shape[1] * 0.16):round(hsv.shape[1] * 0.83)]
    textbox_neutral = float(((textbox_crop[:, :, 1] < 85) &
                             (textbox_crop[:, :, 2] > 165)).mean()) if textbox_crop.size else 0.0
    if (wide_lower or textbox_neutral >= 0.45) and len(right_buttons) >= 1:
        return PageDetection("DIALOGUE", 0.86,
                             (f"lower neutral textbox fraction={textbox_neutral:.3f}",
                              "right-side dialogue control"))

    bottom_saturated = _fraction(hsv, (0.0, 0.72, 1.0, 1.0), saturation_min=75, value_min=95)
    hue_bands = sum(
        _fraction(hsv, (0.0, 0.70, 1.0, 1.0), hue=band,
                  saturation_min=70, value_min=100) >= 0.015
        for band in ((35, 80), (80, 115), (120, 150), (150, 179))
    )
    if bottom_saturated >= 0.18 and hue_bands >= 3:
        return PageDetection("HOME", min(0.9, 0.62 + bottom_saturated),
                             (f"bottom control colour fraction={bottom_saturated:.3f}",
                              f"distinct hue bands={hue_bands}"))
    return PageDetection(UNKNOWN, 0.0, ("no Bundle-A page layout reached threshold",))


def _local_anchor_present(frame: Image.Image, control: str) -> tuple[bool, float, str]:
    hsv = _hsv(frame)
    specs = {
        "HOME:SCHEDULE": ((0.0, 0.56, 0.25, 1.0), (145, 179), 55, 90, 0.025),
        "HOME:REST": ((0.24, 0.72, 0.50, 1.0), (80, 115), 55, 90, 0.018),
        "SCHEDULE:VOCAL": ((0.20, 0.55, 0.37, 0.90), (145, 179), 65, 100, 0.10),
        "SCHEDULE:DECIDE": ((0.83, 0.82, 1.0, 1.0), (145, 179), 65, 100, 0.10),
    }
    if control not in specs:
        return True, 0.7, "page-specific structural anchor"
    roi, hue, saturation, value, threshold = specs[control]
    fraction = _fraction(hsv, roi, hue=hue, saturation_min=saturation, value_min=value)
    return fraction >= threshold, min(0.95, fraction / max(threshold, 0.001) * 0.65), f"local colour anchor fraction={fraction:.3f}"


def detect_control(frame: Image.Image, page: PageDetection, control: str,
                   memory: Mapping[str, Any]) -> ControlDetection:
    expected = EXPECTED_PAGE.get(control)
    if expected is None:
        return ControlDetection(control, False, None, None, 0.0, "UNSUPPORTED_CONTROL",
                                ("control is outside Bundle A",))
    if page.state != expected:
        return ControlDetection(control, False, None, None, 0.0, "PAGE_MISMATCH",
                                (f"expected {expected}; observed {page.state}",))

    preferred = memory.get("preferred_point_norm")
    preferred_point = tuple(preferred) if isinstance(preferred, (list, tuple)) and len(preferred) == 2 else None
    stored_box = memory.get("visual_box_norm")
    box: tuple[float, float, float, float] | None = (
        tuple(float(value) for value in stored_box)
        if isinstance(stored_box, (list, tuple)) and len(stored_box) == 4 else None
    )
    evidence: list[str] = []
    if control == "DIALOGUE:3_CHOICE_MIDDLE":
        boxes = _three_choice_boxes(frame)
        if len(boxes) != 3:
            return ControlDetection(control, False, None, None, 0.0, "CHOICE_COUNT_UNCERTAIN",
                                    (f"detected choice boxes={len(boxes)}",))
        box = boxes[1]
        preferred_point = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        evidence.append("fresh middle card box from three-card layout")
    elif control == "DIALOGUE:SAFE_TEXTBOX":
        boxes = [b for b in _white_rectangles(frame) if (b[2] - b[0]) >= 0.48 and b[1] >= 0.58]
        if boxes:
            box = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
            preferred_point = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            evidence.append("fresh textbox box")
    present, anchor_confidence, anchor_evidence = _local_anchor_present(frame, control)
    evidence.append(anchor_evidence)
    if not present:
        return ControlDetection(control, False, box, preferred_point, 0.0,
                                "ANCHOR_NOT_DETECTED", tuple(evidence))
    if box is not None and control not in {"DIALOGUE:3_CHOICE_MIDDLE", "DIALOGUE:SAFE_TEXTBOX"}:
        evidence.append("stored visual box revalidated by current-frame local anchor")
        geometry_status = "FRESH_ANCHOR_VERIFIED_MEMORY_BOX"
    else:
        geometry_status = "FRESH_VISUAL_BOX" if box is not None else "GEOMETRY_INCOMPLETE"
    confidence = min(page.confidence, 0.92 if box is not None else anchor_confidence)
    return ControlDetection(control, True, box, preferred_point, round(confidence, 4),
                            geometry_status, tuple(evidence))


def detect_input_ready(_frame: Image.Image) -> dict[str, Any]:
    return {"state": "UNKNOWN", "confidence": 0.0, "implemented_in": "Bundle B"}


def detect_auto_state(_frame: Image.Image) -> dict[str, Any]:
    return {"auto_state": "AUTO_UNKNOWN", "confidence": 0.0, "implemented_in": "Bundle B"}
