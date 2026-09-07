"""Save a game-window screenshot and record deliberate mouse-position samples."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pyautogui
import cv2
import numpy as np

from browser_target import BrowserTarget, TargetError
from config_store import backup_and_write_config
from vision import dynamic_screenshot
BASE_DIR = Path(__file__).resolve().parent
pyautogui.FAILSAFE = True

def main() -> int:
    config = json.loads((BASE_DIR / "config.json").read_text())
    with BrowserTarget(config.get("browser", {}).get("cdp_url")) as target:
        try:
            image, window = dynamic_screenshot(target, config, BASE_DIR)
            mode = "dynamic DOM canvas/iframe detection"
        except TargetError:
            # Last-resort calibration: user visually selects the game on a full desktop
            # screenshot. This never sends mouse events to Chrome or the game.
            target.verify_and_focus()
            full = pyautogui.screenshot()
            frame = cv2.cvtColor(np.array(full), cv2.COLOR_RGB2BGR)
            print("No unique game canvas/iframe. Drag the complete game area; Enter/Space confirms, Esc cancels.")
            x, y, width, height = cv2.selectROI("Calibrate game window", frame, showCrosshair=True, fromCenter=False)
            cv2.destroyAllWindows()
            if width <= 0 or height <= 0:
                print("Cancelled: no fallback calibration was saved.")
                return 0
            window = {"left": int(x), "top": int(y), "width": int(width), "height": int(height)}
            config["fallback_game_window"] = {**window, "viewport_css": target.viewport_signature()}
            backup_path = backup_and_write_config(BASE_DIR / "config.json", config)
            print(f"config backup: {backup_path}")
            image = full.crop((x, y, x + width, y + height))
            mode = "interactive fallback calibration"
    destination = BASE_DIR / "logs" / f"{datetime.now():%Y%m%d_%H%M%S}_calibration.png"
    destination.parent.mkdir(exist_ok=True)
    image.save(destination)
    print(f"Saved game-window screenshot ({mode}): {destination.resolve()}")
    print(f"game_window: {window}")
    print("Move the cursor, then press Enter to record a stable position. Type q then Enter to finish.")
    while True:
        if input("> ").strip().lower() == "q":
            return 0
        x, y = pyautogui.position()
        rel_x, rel_y = x - window["left"], y - window["top"]
        normalized = (rel_x / window["width"], rel_y / window["height"])
        inside = 0.0 <= normalized[0] <= 1.0 and 0.0 <= normalized[1] <= 1.0
        print(f"screen=({x}, {y})  relative=({rel_x}, {rel_y})  normalized=({normalized[0]:.6f}, {normalized[1]:.6f})  inside={inside}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TargetError as error:
        print(f"Browser targeting refused: {error}")
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("\nStopped.")
