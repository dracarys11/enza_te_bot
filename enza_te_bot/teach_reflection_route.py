"""Teach one explicit REFLECTION route node; this helper never clicks the game."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pyautogui

from browser_target import BrowserTarget, TargetError
from config_store import backup_and_write_config
from reflection import ROUTE_ORDER, validate_normalized_box
from ui_preview import select_scaled_roi
from vision import detect_state, dynamic_screenshot

BASE_DIR = Path(__file__).resolve().parent
pyautogui.FAILSAFE = True


def append_route_node(image, window: dict, config: dict, route: str, node_id: str,
                      cost: int, node_type: str, action_name: str | None = None) -> dict | None:
    if route not in ROUTE_ORDER:
        raise ValueError("Unknown reflection route.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", node_id):
        raise ValueError("node_id must use letters, digits, '.', '_' or '-'.")
    if cost < 0:
        raise ValueError("cost must be non-negative.")
    routes = config.setdefault("reflection", {}).setdefault("skill_routes", {})
    entries = routes.setdefault(route, [])
    if not isinstance(entries, list):
        raise ValueError(f"reflection.skill_routes.{route} must be a list.")
    if any(entry.get("id") == node_id for entry in entries if isinstance(entry, dict)):
        raise ValueError(f"Route node {route}/{node_id} already exists; refusing overwrite.")
    print(f"Drag the clickable region for REFLECTION route {route}/{node_id}. Enter/Space confirms; Esc or c cancels.")
    (x, y, width, height), preview_box, original_size, preview_size, scale, screen_size = select_scaled_roi(
        image, f"Select REFLECTION {route} {node_id}")
    if width <= 0 or height <= 0:
        return None
    capture_scale = config["capture_scale"]
    box = [x / (window["width"] * capture_scale["x"]), y / (window["height"] * capture_scale["y"]),
           (x + width) / (window["width"] * capture_scale["x"]), (y + height) / (window["height"] * capture_scale["y"])]
    normalized = [round(value, 6) for value in validate_normalized_box(box)]
    if action_name is not None:
        # This associates an already-captured REFLECTION action (for example
        # reflection_skill_1) with this route node; it does not create another
        # per-tile state action.
        configured = [action.get("name") for action in config["states"]["REFLECTION"].get("allowed_actions", [])]
        if action_name not in configured:
            raise ValueError(f"Unknown REFLECTION action {action_name!r}.")
    node = {"id": node_id, "box": normalized, "expected_cost": cost, "type": node_type}
    if action_name is not None:
        node["action"] = action_name
    entries.append(node)
    config["game_window"] = None
    config.pop("capture_scale", None)
    backup = backup_and_write_config(BASE_DIR / "config.json", config)
    print(f"route={route}\nnode={node}\npreview_box={preview_box}\n"
          f"original_size={original_size}\npreview_size={preview_size}\nscale={scale:.6f}\n"
          f"screen_size={screen_size}\nconfig backup: {backup}")
    return {"node": node, "backup": str(backup)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("route", choices=ROUTE_ORDER)
    parser.add_argument("node_id")
    parser.add_argument("--cost", required=True, type=int)
    parser.add_argument("--type", required=True, choices=("normal", "appeal"), dest="node_type")
    parser.add_argument("--action", help="Optional existing REFLECTION action to reuse for this node.")
    args = parser.parse_args()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        image, window = dynamic_screenshot(target, config, BASE_DIR)
        detected = detect_state(image, config, BASE_DIR)
    if detected.state.value != "REFLECTION":
        raise TargetError(f"REFLECTION is not detected (found {detected.state.value}); no route node was written.")
    result = append_route_node(image, window, config, args.route, args.node_id, args.cost, args.node_type,
                               args.action)
    if result is None:
        print("Cancelled: no route node was written.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TargetError as error:
        print(f"Safety stop: {error}")
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("\nCancelled.")
