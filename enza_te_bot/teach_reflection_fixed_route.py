"""Interactively teach fixed REFLECTION route centers; never clicks the game."""
from __future__ import annotations
import json
from pathlib import Path
import pyautogui
from browser_target import BrowserTarget, TargetError
from config_store import backup_and_write_config
from ui_preview import select_scaled_point
from vision import detect_state, dynamic_screenshot

BASE_DIR = Path(__file__).resolve().parent
pyautogui.FAILSAFE = True

def teach() -> int:
    path = BASE_DIR / "config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        image, window = dynamic_screenshot(target, config, BASE_DIR)
        if detect_state(image, config, BASE_DIR).state.value != "REFLECTION":
            raise TargetError("REFLECTION is not detected; no route was written.")
    route = list(config.setdefault("reflection", {}).get("fixed_route", []))
    print("Teach fixed route in order. Blank node id finishes; Esc/c cancels.")
    while True:
        node_id = input("node id: ").strip()
        if not node_id:
            break
        try:
            cost = int(input("cost: ").strip())
            kind = input("type [normal|appeal]: ").strip().lower()
        except ValueError:
            print("Invalid cost; no config written.")
            return 2
        if kind not in {"normal", "appeal"} or any(n["id"] == node_id for n in route):
            print("Invalid or duplicate node; no config written.")
            return 2
        point, *_ = select_scaled_point(image, f"Select fixed route node {node_id}")
        if point is None:
            print("Cancelled; no config written.")
            return 0
        route.append({"id": node_id, "point": [round(point[0] / image.width, 6), round(point[1] / image.height, 6)],
                      "cost": cost, "type": kind})
    updated = dict(config)
    updated.setdefault("reflection", {})["fixed_route"] = route
    backup = backup_and_write_config(path, updated)
    print(f"fixed_route_nodes={len(route)}\nconfig backup: {backup}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(teach())
    except (TargetError, ValueError) as error:
        print(f"Safety stop: {error}")
        raise SystemExit(2)
