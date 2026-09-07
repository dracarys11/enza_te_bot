"""Teach one zoomed REFLECTION board ROI and its clockwise start anchor; never clicks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyautogui

from browser_target import BrowserTarget, TargetError
from config_store import backup_and_write_config
from reflection import validate_normalized_box
from ui_preview import select_scaled_point, select_scaled_roi
from vision import detect_state, dynamic_screenshot

BASE_DIR = Path(__file__).resolve().parent
BOARD_NAMES = ("upper_left", "lower_right")
pyautogui.FAILSAFE = True


def teach_reflection_board(board: str) -> int:
    if board not in BOARD_NAMES:
        raise ValueError(f"Unknown reflection board {board!r}.")
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        image, window = dynamic_screenshot(target, config, BASE_DIR)
        detected = detect_state(image, config, BASE_DIR)
    if detected.state.value != "REFLECTION":
        raise TargetError(f"REFLECTION is not detected (found {detected.state.value}); no board was written.")
    print("Drag the complete skill board ROI after zoom-out. Enter/Space confirms; Esc or c cancels.")
    (x, y, width, height), preview_box, original_size, preview_size, scale, screen_size = select_scaled_roi(
        image, f"Select REFLECTION {board} board")
    if width <= 0 or height <= 0:
        print("Cancelled: no board was written.")
        return 0
    capture_scale = config["capture_scale"]
    roi = [x / (window["width"] * capture_scale["x"]), y / (window["height"] * capture_scale["y"]),
           (x + width) / (window["width"] * capture_scale["x"]), (y + height) / (window["height"] * capture_scale["y"])]
    roi = [round(value, 6) for value in validate_normalized_box(roi)]
    board_crop = image.crop((x, y, x + width, y + height))
    print("Click the first clockwise outer-ring node (the route start), then Enter/Space. Esc or c cancels.")
    point, _board_size, anchor_preview_size, anchor_scale, _anchor_screen = select_scaled_point(
        board_crop, f"Select REFLECTION {board} start anchor")
    if point is None:
        print("Cancelled: no board was written.")
        return 0
    anchor = [round(point[0] / width, 6), round(point[1] / height, 6)]
    geometry = config.setdefault("reflection", {}).setdefault("geometry", {}).setdefault("boards", {})
    spec = geometry.setdefault(board, {})
    spec.update({"roi": roi, "start_anchor": anchor, "clockwise": True})
    config["game_window"] = None
    config.pop("capture_scale", None)
    backup = backup_and_write_config(BASE_DIR / "config.json", config)
    print(f"board={board}\nroi={roi}\nstart_anchor={anchor}\n"
          f"board_preview_box={preview_box}\noriginal_size={original_size}\npreview_size={preview_size}\n"
          f"roi_scale={scale:.6f}\nanchor_preview_size={anchor_preview_size}\nanchor_scale={anchor_scale:.6f}\n"
          f"screen_size={screen_size}\nconfig backup: {backup}")
    return 0


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("board", choices=BOARD_NAMES)
        raise SystemExit(teach_reflection_board(parser.parse_args().board))
    except TargetError as error:
        print(f"Safety stop: {error}")
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("\nCancelled.")
