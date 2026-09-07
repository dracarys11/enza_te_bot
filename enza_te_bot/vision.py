"""Screenshot capture and config-driven OpenCV template matching."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np
import pyautogui
from PIL import Image, ImageDraw

from states import Detection, State


def screenshot(window: dict) -> Image.Image:
    return pyautogui.screenshot(region=(window["left"], window["top"], window["width"], window["height"]))


def dynamic_screenshot(target, config: dict, base_dir: Path) -> tuple[Image.Image, dict]:
    """Resolve the current window, capture it, and save a full-screen debug overlay."""
    window = target.dynamic_game_window(config)
    full = pyautogui.screenshot()
    logical = pyautogui.size()
    capture_scale = {"x": full.width / logical.width, "y": full.height / logical.height}
    left = round(window["left"] * capture_scale["x"])
    top = round(window["top"] * capture_scale["y"])
    right = round((window["left"] + window["width"]) * capture_scale["x"])
    bottom = round((window["top"] + window["height"]) * capture_scale["y"])
    if left < 0 or top < 0 or right > full.width or bottom > full.height:
        raise ValueError("Detected game window lies outside the current desktop screenshot.")
    debug = full.copy()
    ImageDraw.Draw(debug).rectangle((left, top, right, bottom), outline="red", width=4)
    logs = base_dir / "logs"
    logs.mkdir(exist_ok=True)
    debug.save(logs / "current_game_window_debug.png")
    config["game_window"] = window
    config["capture_scale"] = capture_scale
    return full.crop((left, top, right, bottom)), window


def save_action_debug(window: dict, box: Sequence[float], point: tuple[int, int], base_dir: Path, label: str) -> Path:
    """Save a desktop overlay of the dynamic game window, action box, and point."""
    left, top, right, bottom = [float(value) for value in box]
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("Action box must be normalized and contained in game_window.")
    image = pyautogui.screenshot()
    logical = pyautogui.size()
    scale_x, scale_y = image.width / logical.width, image.height / logical.height
    draw = ImageDraw.Draw(image)
    game_left, game_top = window["left"] * scale_x, window["top"] * scale_y
    game_right, game_bottom = (window["left"] + window["width"]) * scale_x, (window["top"] + window["height"]) * scale_y
    action_rect = (game_left + left * window["width"] * scale_x, game_top + top * window["height"] * scale_y, game_left + right * window["width"] * scale_x, game_top + bottom * window["height"] * scale_y)
    draw.rectangle((game_left, game_top, game_right, game_bottom), outline="red", width=4)
    draw.rectangle(action_rect, outline="lime", width=4)
    radius = 7
    px, py = point[0] * scale_x, point[1] * scale_y
    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill="blue")
    path = base_dir / "logs" / f"{__import__('datetime').datetime.now():%Y%m%d_%H%M%S_%f}_{label}_debug.png"
    path.parent.mkdir(exist_ok=True)
    image.save(path)
    return path


def normalized_roi_to_pixels(roi: Optional[Sequence[float]], window: dict) -> Tuple[int, int, int, int]:
    if roi is None:
        return 0, 0, window["width"], window["height"]
    if len(roi) != 4 or not all(0 <= float(v) <= 1 for v in roi):
        raise ValueError("ROI must be null or [left, top, right, bottom] normalized values.")
    left, top, right, bottom = roi
    if right <= left or bottom <= top:
        raise ValueError("ROI must have positive width and height.")
    return round(left * window["width"]), round(top * window["height"]), round(right * window["width"]), round(bottom * window["height"])


def detect_state(image: Image.Image, config: dict, base_dir: Path) -> Detection:
    """Return the highest scoring configured state, or UNKNOWN when none qualifies."""
    frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    best = Detection(State.UNKNOWN.value)
    for name, spec in config["states"].items():
        if spec.get("feature_only"):
            continue
        x1, y1, x2, y2 = normalized_roi_to_pixels(spec.get("roi"), {"width": frame.shape[1], "height": frame.shape[0]})
        region = frame[y1:y2, x1:x2]
        template_names = list(spec.get("templates", []))
        # Audition reward markers are page-local evidence.  They strengthen
        # the AUDITION_SELECT parent identity but must never replace it.
        if name == "AUDITION_SELECT":
            for feature_name in ("AUDITION_TARGET_40000", "AUDITION_TARGET_50000"):
                feature_spec = config["states"].get(feature_name, {})
                template_names.extend(feature_spec.get("templates", []))
        for template_name in dict.fromkeys(template_names):
            path = base_dir / "templates" / template_name
            template = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if template is None:
                continue
            if template.shape[0] > region.shape[0] or template.shape[1] > region.shape[1]:
                continue
            score = float(cv2.minMaxLoc(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED))[1])
            if score >= float(spec.get("confidence", config["defaults"]["confidence"])) and score > best.confidence:
                best = Detection(name, score, template_name)
        # Battle page identity is the stable control layout, not the mutable
        # Auto/speed glyphs.  This deterministic presence check deliberately
        # reports the parent page while controls change state.
        layout = spec.get("page_layout_presence")
        if name == "AUDITION_BATTLE" and layout and best.state.value == State.UNKNOWN.value:
            regions = layout.get("regions", [])
            present = 0
            for region_roi in regions:
                rx1, ry1, rx2, ry2 = normalized_roi_to_pixels(region_roi, {"width": frame.shape[1], "height": frame.shape[0]})
                sample = frame[ry1:ry2, rx1:rx2]
                if sample.size and float(sample.mean()) >= float(layout.get("minimum_mean", 70.0)) and float(sample.std()) >= float(layout.get("minimum_stddev", 12.0)):
                    present += 1
            if regions and present == len(regions):
                best = Detection(name, 1.0, "page_layout_presence")
    return best


def detect_audition_target_reward(image: Image.Image, config: dict, base_dir: Path) -> tuple[int | None, float, str | None]:
    """Detect reward-marker evidence without replacing AUDITION_SELECT state."""
    import re
    frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2GRAY)
    best: tuple[int | None, float, str | None] = (None, 0.0, None)
    for reward in (40000, 50000, 100000):
        name = f"AUDITION_TARGET_{reward}"
        spec = config.get("states", {}).get(name, {})
        for template_name in spec.get("templates", []):
            template = cv2.imread(str(base_dir / "templates" / template_name), cv2.IMREAD_GRAYSCALE)
            if template is None or template.shape[0] > frame.shape[0] or template.shape[1] > frame.shape[1]:
                continue
            score = float(cv2.minMaxLoc(cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED))[1])
            if score > best[1]:
                best = (reward, score, template_name)
    threshold = float(config.get("states", {}).get("AUDITION_SELECT", {}).get("confidence", 0.88))
    return best if best[1] >= threshold else (None, best[1], best[2])


def detect_audition_battle_speed(image: Image.Image, config: dict) -> dict[str, object]:
    """Read the mutable 1x/2x/3x speed control without affecting page identity.

    The fixed control renders 2x/3x as two/three pink fast-forward arrows.  At
    normal speed it renders a dark ``倍速OFF`` glyph.  Evidence is deliberately
    restricted to the configured speed-control ROI.
    """
    settings = config.get("states", {}).get("AUDITION_BATTLE", {}).get("speed_feature", {})
    roi = settings.get("roi")
    if not isinstance(roi, list):
        return {"speed": None, "confidence": 0.0, "reason": "speed feature ROI missing"}
    rgb = np.array(image.convert("RGB"))
    height, width = rgb.shape[:2]
    x1, y1, x2, y2 = normalized_roi_to_pixels(roi, {"width": width, "height": height})
    crop = rgb[y1:y2, x1:x2]
    if crop.size == 0:
        return {"speed": None, "confidence": 0.0, "reason": "empty speed feature ROI"}
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    top_rows = max(1, round(crop.shape[0] * float(settings.get("arrow_top_fraction", 0.45))))
    top = hsv[:top_rows]
    pink = ((top[:, :, 0] >= int(settings.get("pink_hue_min", 145))) &
            (top[:, :, 0] <= int(settings.get("pink_hue_max", 179))) &
            (top[:, :, 1] >= int(settings.get("pink_saturation_min", 90))) &
            (top[:, :, 2] >= int(settings.get("pink_value_min", 120))))
    ys, xs = np.where(pink)
    pink_fraction = float(pink.mean())
    pink_span = 0.0 if len(xs) == 0 else float(xs.max() - xs.min() + 1) / float(crop.shape[1])
    dark = ((hsv[:, :, 1] <= int(settings.get("off_saturation_max", 100))) &
            (hsv[:, :, 2] <= int(settings.get("off_value_max", 180))))
    dark_fraction = float(dark.mean())
    evidence = {"pink_fraction": pink_fraction, "pink_span": pink_span,
                "dark_fraction": dark_fraction, "source": "audition_battle_speed_feature"}
    if pink_fraction <= float(settings.get("off_pink_fraction_max", 0.01)) and \
            dark_fraction >= float(settings.get("off_dark_fraction_min", 0.08)):
        return {"speed": 1, "confidence": min(1.0, dark_fraction / 0.08), **evidence}
    two_range = settings.get("two_x_span_range", [0.45, 0.7])
    three_range = settings.get("three_x_span_range", [0.7, 0.95])
    if pink_fraction >= float(settings.get("active_pink_fraction_min", 0.12)):
        if float(two_range[0]) <= pink_span < float(two_range[1]):
            return {"speed": 2, "confidence": 1.0, **evidence}
        if float(three_range[0]) <= pink_span <= float(three_range[1]):
            return {"speed": 3, "confidence": 1.0, **evidence}
    return {"speed": None, "confidence": 0.0, "reason": "speed evidence ambiguous", **evidence}


def detect_audition_battle_auto(image: Image.Image, config: dict) -> dict[str, object]:
    """Return fresh AUTO state only when an explicitly taught detector exists."""
    settings = config.get("states", {}).get("AUDITION_BATTLE", {}).get("auto_feature", {})
    if not isinstance(settings, dict) or not isinstance(settings.get("roi"), list):
        return {"auto": "AUTO_UNKNOWN", "confidence": 0.0, "reason": "auto feature ROI missing"}
    return {"auto": "AUTO_UNKNOWN", "confidence": 0.0, "reason": "auto feature detector unconfigured"}


def detect_safe_pink_cta(image: Image.Image, settings: dict) -> dict | None:
    """Detect one large pink CTA inside its explicitly bounded local ROI."""
    rgb = np.array(image.convert("RGB"))
    height, width = rgb.shape[:2]
    x1, y1, x2, y2 = normalized_roi_to_pixels(settings.get("roi"), {"width": width, "height": height})
    region = rgb[y1:y2, x1:x2]
    if region.size == 0:
        return None
    hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)
    lower = np.array([
        int(settings.get("hue_min", 145)),
        int(settings.get("saturation_min", 80)),
        int(settings.get("value_min", 120)),
    ], dtype=np.uint8)
    upper = np.array([int(settings.get("hue_max", 179)), 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), dtype=np.uint8))
    count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask)
    roi_height, roi_width = region.shape[:2]
    roi_area = float(roi_width * roi_height)
    candidates: list[tuple[int, list[int]]] = []
    for component in range(1, count):
        left, top, box_width, box_height, area = [int(value) for value in stats[component]]
        box_area = box_width * box_height
        if box_area <= 0:
            continue
        if box_width / roi_width < float(settings.get("minimum_width_fraction", 0.45)):
            continue
        if box_height / roi_height < float(settings.get("minimum_height_fraction", 0.25)):
            continue
        if area / box_area < float(settings.get("minimum_fill_ratio", 0.5)):
            continue
        if area / roi_area < float(settings.get("minimum_area_fraction", 0.12)):
            continue
        candidates.append((area, [left, top, box_width, box_height]))
    if len(candidates) != 1:
        return None
    area, (left, top, box_width, box_height) = candidates[0]
    absolute_box = [x1 + left, y1 + top, x1 + left + box_width, y1 + top + box_height]
    normalized_box = [absolute_box[0] / width, absolute_box[1] / height,
                      absolute_box[2] / width, absolute_box[3] / height]
    center = ((normalized_box[0] + normalized_box[2]) / 2,
              (normalized_box[1] + normalized_box[3]) / 2)
    return {
        "visible": True,
        "box": normalized_box,
        "center": center,
        "confidence": area / roi_area,
        "source": "post_audition_safe_pink_cta",
    }
