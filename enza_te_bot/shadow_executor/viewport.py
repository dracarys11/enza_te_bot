"""Fresh game-viewport calibration for screenshot-only shadow observation."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np
from PIL import Image


VIEWPORT_KNOWN = "VIEWPORT_KNOWN"
VIEWPORT_UNKNOWN = "VIEWPORT_UNKNOWN"
TARGET_ASPECT = 16.0 / 9.0


@dataclass(frozen=True)
class ViewportDetection:
    status: str
    screen_width: int
    screen_height: int
    game_left: int | None
    game_top: int | None
    game_width: int | None
    game_height: int | None
    normalized_mapping: dict[str, str] | None
    viewport_profile_id: str | None
    confidence: float
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


def _known(width: int, height: int, left: int, top: int, game_width: int,
           game_height: int, confidence: float, reason: str) -> ViewportDetection:
    profile = f"FRESH_{game_width}x{game_height}"
    if game_width == 1280 and game_height == 720:
        profile = "MAC_CURRENT_V1"
    return ViewportDetection(
        VIEWPORT_KNOWN, width, height, left, top, game_width, game_height,
        {
            "screen_to_normalized": "nx=(screen_x-game_left)/game_width; ny=(screen_y-game_top)/game_height",
            "normalized_to_screen": "screen_x=game_left+nx*game_width; screen_y=game_top+ny*game_height",
        },
        profile, round(confidence, 4), reason,
    )


def _unknown(width: int, height: int, reason: str) -> ViewportDetection:
    return ViewportDetection(
        VIEWPORT_UNKNOWN, width, height, None, None, None, None, None, None,
        0.0, reason,
    )


def detect_game_viewport(image: Image.Image) -> ViewportDetection:
    """Locate a 16:9 game frame without assuming a zero origin.

    Exact 16:9 inputs are accepted as already-cropped game frames only when
    they contain sufficient visual information.  Larger inputs are accepted
    only when a single 16:9 content rectangle is isolated by a flat border;
    arbitrary desktop/browser layouts fail closed.
    """
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    if width < 640 or height < 360:
        return _unknown(width, height, "SCREEN_TOO_SMALL")
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if abs((width / height) - TARGET_ASPECT) <= 0.01:
        if float(gray.std()) < 18.0:
            return _unknown(width, height, "FULL_FRAME_HAS_INSUFFICIENT_VISUAL_VARIANCE")
        return _known(width, height, 0, 0, width, height, 0.98,
                      "FRESH_FULL_FRAME_16_9")

    corners = np.vstack((rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1])).astype(np.int16)
    border_colour = np.median(corners, axis=0)
    if float(np.max(np.linalg.norm(corners - border_colour, axis=1))) > 18.0:
        return _unknown(width, height, "NON_UNIFORM_SCREEN_BORDER")
    difference = np.linalg.norm(rgb.astype(np.int16) - border_colour, axis=2)
    mask = (difference > 24.0).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[float, tuple[int, int, int, int]]] = []
    screen_area = width * height
    for contour in contours:
        left, top, candidate_width, candidate_height = cv2.boundingRect(contour)
        area_fraction = candidate_width * candidate_height / screen_area
        if candidate_width < 640 or candidate_height < 360 or area_fraction < 0.25:
            continue
        aspect_error = abs(candidate_width / candidate_height - TARGET_ASPECT)
        if aspect_error > 0.025:
            continue
        score = area_fraction - aspect_error
        candidates.append((score, (left, top, candidate_width, candidate_height)))
    if len(candidates) != 1:
        return _unknown(width, height, "UNIQUE_FLAT_BORDER_16_9_REGION_NOT_FOUND")
    _, (left, top, game_width, game_height) = candidates[0]
    crop = gray[top:top + game_height, left:left + game_width]
    if crop.size == 0 or float(crop.std()) < 18.0:
        return _unknown(width, height, "CANDIDATE_HAS_INSUFFICIENT_VISUAL_VARIANCE")
    return _known(width, height, left, top, game_width, game_height, 0.9,
                  "FRESH_FLAT_BORDER_16_9_REGION")


def crop_game_viewport(image: Image.Image, viewport: ViewportDetection) -> Image.Image | None:
    if viewport.status != VIEWPORT_KNOWN:
        return None
    assert viewport.game_left is not None and viewport.game_top is not None
    assert viewport.game_width is not None and viewport.game_height is not None
    return image.crop((viewport.game_left, viewport.game_top,
                       viewport.game_left + viewport.game_width,
                       viewport.game_top + viewport.game_height))
