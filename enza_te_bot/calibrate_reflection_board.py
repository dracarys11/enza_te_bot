"""One-time canonical REFLECTION board calibration; never clicks the game."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyautogui

from browser_target import BrowserTarget, TargetError
from config_store import backup_and_write_config
from reflection_canonical import clockwise_ring
from ui_preview import select_scaled_point, select_scaled_roi
from vision import detect_state, dynamic_screenshot

BASE_DIR = Path(__file__).resolve().parent
pyautogui.FAILSAFE = True


def calibrate(board: str) -> int:
    config_path = BASE_DIR / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        image, _window = dynamic_screenshot(target, config, BASE_DIR)
        if detect_state(image, config, BASE_DIR).state.value != "REFLECTION":
            raise TargetError("REFLECTION is not detected; no calibration written.")
    (x, y, w, h), *_ = select_scaled_roi(image, f"Select canonical {board} board ROI")
    if w <= 0 or h <= 0:
        return 0
    crop = image.crop((x, y, x + w, y + h))
    points = []
    for prompt in ("board origin", "adjacent q node", "adjacent r node", "route start node"):
        print(f"Select {prompt}; Enter/Space confirms, Esc/c cancels.")
        point, *_ = select_scaled_point(crop, f"Select {board} {prompt}")
        if point is None:
            return 0
        points.append((point[0] / w, point[1] / h))
    basis_q = (points[1][0] - points[0][0], points[1][1] - points[0][1])
    basis_r = (points[2][0] - points[0][0], points[2][1] - points[0][1])
    board_cfg = config.setdefault("reflection", {}).setdefault("canonical", {}).setdefault("boards", {})
    board_cfg[board] = {"roi": [round(v, 6) for v in (x / image.width, y / image.height,
                                                         (x + w) / image.width, (y + h) / image.height)],
                        "origin": [round(v, 6) for v in points[0]],
                        "basis_q": [round(v, 6) for v in basis_q],
                        "basis_r": [round(v, 6) for v in basis_r],
                        "start_anchor": [round(v, 6) for v in points[3]],
                        "outer_ring": [list(p) for p in clockwise_ring(1)]}
    ref_dir = BASE_DIR / "templates" / "reflection_boards"
    ref_dir.mkdir(parents=True, exist_ok=True)
    reference_path = ref_dir / f"{board}.png"
    crop.save(reference_path)
    backup = backup_and_write_config(config_path, config)
    print(f"canonical board={board} reference={reference_path} backup={backup}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("board", choices=("upper_left", "lower_right"))
    try:
        raise SystemExit(calibrate(parser.parse_args().board))
    except (TargetError, ValueError) as error:
        print(f"Safety stop: {error}")
        raise SystemExit(2)
