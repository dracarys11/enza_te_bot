"""Safe, relative mouse actions. PyAutoGUI FAILSAFE is intentionally enabled."""
from __future__ import annotations

import random
import time
from typing import Sequence, Tuple

import pyautogui

pyautogui.FAILSAFE = True


def normalized_box_to_screen(box: Sequence[float], window: dict) -> Tuple[int, int, int, int]:
    """Convert a normalized [left, top, right, bottom] box to screen pixels."""
    if len(box) != 4 or not all(0.0 <= float(v) <= 1.0 for v in box):
        raise ValueError("A normalized box must contain four values in [0.0, 1.0].")
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        raise ValueError("Box must have positive width and height.")
    return (
        round(window["left"] + left * window["width"]),
        round(window["top"] + top * window["height"]),
        round(window["left"] + right * window["width"]),
        round(window["top"] + bottom * window["height"]),
    )


def normalized_point_to_screen(point: Sequence[float], window: dict) -> Tuple[int, int]:
    """Convert one fixed normalized point to a validated screen coordinate."""
    if len(point) != 2 or not all(0.0 <= float(value) <= 1.0 for value in point):
        raise ValueError("A normalized point must contain two values in [0.0, 1.0].")
    x = round(window["left"] + float(point[0]) * window["width"])
    y = round(window["top"] + float(point[1]) * window["height"])
    if not (window["left"] <= x < window["left"] + window["width"] and
            window["top"] <= y < window["top"] + window["height"]):
        raise ValueError("Normalized point lies outside game_window.")
    return x, y


def random_point(box: Sequence[float], window: dict, settings: dict) -> Tuple[int, int]:
    """Choose a point in the inner portion of a normalized target."""
    left, top, right, bottom = normalized_box_to_screen(box, window)
    fraction = float(settings.get("inner_click_fraction", 0.70))
    if not 0 < fraction <= 1:
        raise ValueError("inner_click_fraction must be in (0, 1].")
    margin_x = (right - left) * (1 - fraction) / 2
    margin_y = (bottom - top) * (1 - fraction) / 2
    x = round(random.uniform(left + margin_x, right - margin_x))
    y = round(random.uniform(top + margin_y, bottom - margin_y))
    return x, y


def click_point(point: Tuple[int, int], settings: dict) -> float:
    """Perform an actual click and return its monotonic send timestamp."""
    x, y = point
    duration = random.uniform(*settings["move_duration_seconds"])
    pyautogui.moveTo(x, y, duration=duration)
    pyautogui.click()
    sent_at = time.monotonic()
    time.sleep(random.uniform(*settings["post_click_wait_seconds"]))
    return sent_at


def fast_transaction_click_points(points: Sequence[Tuple[int, int]], click_interval_ms: int) -> None:
    """Issue a bounded transaction burst without the normal post-click wait.

    Callers must already have verified the target, dynamic window, and point
    containment.  This deliberately keeps PyAutoGUI's FAILSAFE active.
    """
    if click_interval_ms < 0:
        raise ValueError("click_interval_ms must be non-negative.")
    interval_seconds = click_interval_ms / 1000.0
    original_pause = pyautogui.PAUSE
    try:
        # PyAutoGUI's global default pause would otherwise add two waits per
        # point.  FAILSAFE remains enabled throughout this narrow burst.
        pyautogui.PAUSE = 0
        for index, point in enumerate(points):
            pyautogui.moveTo(point[0], point[1], duration=0)
            pyautogui.click()
            if index + 1 < len(points) and interval_seconds:
                time.sleep(interval_seconds)
    finally:
        pyautogui.PAUSE = original_pause


def random_click(box: Sequence[float], window: dict, settings: dict, dry_run: bool = True) -> Tuple[int, int]:
    """Choose a safe random point, and click it unless this is a dry run."""
    point = random_point(box, window, settings)
    if not dry_run:
        click_point(point, settings)
    return point


def point_is_inside_window(point: Tuple[int, int], window: dict) -> bool:
    x, y = point
    return window["left"] <= x < window["left"] + window["width"] and window["top"] <= y < window["top"] + window["height"]
