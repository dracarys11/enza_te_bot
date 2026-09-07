"""Teach only the REFLECTION remaining-SP ROI; never clicks the game."""
from __future__ import annotations

import json
from pathlib import Path

import pyautogui

from browser_target import BrowserTarget, TargetError
from config_store import backup_and_write_config
from reflection import validate_normalized_box
from ui_preview import select_scaled_roi
from vision import detect_state, dynamic_screenshot

BASE_DIR = Path(__file__).resolve().parent
pyautogui.FAILSAFE = True


def main() -> int:
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        image, window = dynamic_screenshot(target, config, BASE_DIR)
        detected = detect_state(image, config, BASE_DIR)
    if detected.state.value != "REFLECTION":
        raise TargetError(f"REFLECTION is not detected (found {detected.state.value}); no ROI was written.")
    print("Drag only the numeric remaining-SP glyphs in the upper-left. Enter/Space confirms; Esc or c cancels.")
    (x, y, width, height), preview_box, original_size, preview_size, scale, screen_size = select_scaled_roi(
        image, "Select REFLECTION remaining SP ROI")
    if width <= 0 or height <= 0:
        print("Cancelled: no ROI was written.")
        return 0
    capture_scale = config["capture_scale"]
    roi = [x / (window["width"] * capture_scale["x"]), y / (window["height"] * capture_scale["y"]),
           (x + width) / (window["width"] * capture_scale["x"]), (y + height) / (window["height"] * capture_scale["y"])]
    roi = [round(value, 6) for value in validate_normalized_box(roi)]
    config.setdefault("reflection", {}).setdefault("remaining_sp", {})["roi"] = roi
    config["game_window"] = None
    config.pop("capture_scale", None)
    backup = backup_and_write_config(BASE_DIR / "config.json", config)
    print(f"remaining_sp.roi={roi}\npreview_box={preview_box}\noriginal_size={original_size}\n"
          f"preview_size={preview_size}\nscale={scale:.6f}\nscreen_size={screen_size}\nconfig backup: {backup}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TargetError as error:
        print(f"Safety stop: {error}")
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("\nCancelled.")
