"""Interactively crop a configured game-window screenshot into a template."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyautogui

from browser_target import BrowserTarget, TargetError
from config_store import backup_and_write_config
from ui_preview import select_scaled_roi
from vision import dynamic_screenshot
BASE_DIR = Path(__file__).resolve().parent
WINDOW_TITLE = "Select template — drag, then Enter/Space; Esc cancels"
pyautogui.FAILSAFE = True

TEMPLATE_STATE = {
    "home_marker": "HOME",
    "produce_menu_marker": "PRODUCE_MENU",
    "vocal_result_marker": "VOCAL_RESULT",
}


def default_state_spec(config: dict) -> dict:
    """Create an inert, template-ready state; it never gains an action implicitly."""
    return {
        "templates": [], "roi": None,
        "confidence": config["defaults"].get("confidence", 0.85),
        "allowed_actions": [], "expected_next_states": [],
        "timeout_seconds": 5, "retries": 0,
    }


def capture_template_from_image(image, window: dict, config: dict, state_name: str,
                                template_name: str, *, title: str = WINDOW_TITLE,
                                base_dir: Path = BASE_DIR) -> dict | None:
    """Use the shared OpenCV crop workflow and safely register one template.

    The caller owns browser capture; this function never sends game input.
    """
    print("Drag a stable template region. Enter/Space confirms; Esc or c cancels.")
    (x, y, width, height), preview_box, original_size, preview_size, scale, screen_size = select_scaled_roi(image, title)
    if width <= 0 or height <= 0:
        return None
    name = safe_template_name(template_name)
    capture_scale = config["capture_scale"]
    normalized = (x / (window["width"] * capture_scale["x"]), y / (window["height"] * capture_scale["y"]),
                  (x + width) / (window["width"] * capture_scale["x"]), (y + height) / (window["height"] * capture_scale["y"]))
    if not (0.0 <= normalized[0] < normalized[2] <= 1.0 and 0.0 <= normalized[1] < normalized[3] <= 1.0):
        raise ValueError("Selected crop lies outside the detected game window.")
    if state_name not in config["states"]:
        config["states"][state_name] = default_state_spec(config)
    destination = base_dir / "templates" / f"{name}.png"
    destination.parent.mkdir(exist_ok=True)
    image.crop((x, y, x + width, y + height)).save(destination)
    templates = config["states"][state_name]["templates"]
    if destination.name not in templates:
        templates.append(destination.name)
    config["game_window"] = None
    config.pop("capture_scale", None)
    backup_path = backup_and_write_config(base_dir / "config.json", config, changed_template_states={state_name})
    relative = (round(x / capture_scale["x"]), round(y / capture_scale["y"]), round((x + width) / capture_scale["x"]), round((y + height) / capture_scale["y"]))
    absolute = (window["left"] + relative[0], window["top"] + relative[1], window["left"] + relative[2], window["top"] + relative[3])
    info = {"template": str(destination.resolve()), "backup": str(backup_path), "state": state_name,
            "preview_box": preview_box, "original_size": original_size, "preview_size": preview_size,
            "screen_size": screen_size, "scale": scale, "normalized": [round(v, 6) for v in normalized],
            "relative": relative, "absolute": absolute}
    print(f"original game_window size: {original_size[0]} x {original_size[1]}")
    print(f"preview size: {preview_size[0]} x {preview_size[1]}")
    print(f"screen size: {screen_size[0]} x {screen_size[1]}")
    print(f"scale factor: {scale:.6f}")
    print(f"selected preview coordinates [left, top, width, height]: {preview_box}")
    print(f"absolute screen coordinates [left, top, right, bottom]: {absolute}")
    print(f"relative game_window coordinates [left, top, right, bottom]: {relative}")
    print(f"normalized game_window coordinates: {info['normalized']}")
    print(f"saved template: {info['template']}\nregistered template for state: {state_name}\nconfig backup: {backup_path}")
    return info


def safe_template_name(value: str) -> str:
    """Return a filename stem and prevent writes outside templates/."""
    name = Path(value.strip()).name
    if name.lower().endswith(".png"):
        name = name[:-4]
    if not name or name in {".", ".."}:
        raise ValueError("Template name must be a non-empty filename.")
    return name


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", nargs="?", help="Template filename (.png optional)")
    parser.add_argument("--state", help="Register this template to an existing configured state")
    parser.add_argument("--passive-from", help="Explicitly add this taught state to a source state's passive expected_next_states")
    args = parser.parse_args()
    config = json.loads((BASE_DIR / "config.json").read_text())
    # This reads pixels only; it does not send a click to the game window.
    with BrowserTarget(config.get("browser", {}).get("cdp_url")) as target:
        image, window = dynamic_screenshot(target, config, BASE_DIR)
    try:
        name = safe_template_name(args.name or input("Template filename (without extension): "))
    except ValueError as error:
        raise SystemExit(str(error)) from error
    state_name = args.state or TEMPLATE_STATE.get(name)
    if state_name and state_name not in config["states"]:
        raise SystemExit(f"Unknown configured state {state_name}; template was saved but not registered.")
    if args.passive_from and not state_name:
        raise SystemExit("--passive-from requires --state so the target state is explicit.")
    if args.passive_from and args.passive_from not in config["states"]:
        raise SystemExit(f"Unknown passive source state {args.passive_from}.")
    if not state_name:
        raise SystemExit("--state is required for templates without a built-in state mapping.")
    result = capture_template_from_image(image, window, config, state_name, name)
    if result is None:
        print("Cancelled: no template was saved.")
        return 0
    if args.passive_from:
        # Preserve the historic helper behavior with a second safe config mutation.
        config = json.loads((BASE_DIR / "config.json").read_text())
        passive = config["states"][args.passive_from].get("passive_transition")
        if not passive or passive.get("type") != "passive_wait":
            raise SystemExit(f"{args.passive_from} has no configured passive_wait transition.")
        if state_name not in passive.setdefault("expected_next_states", []):
            passive["expected_next_states"].append(state_name)
        backup_path = backup_and_write_config(BASE_DIR / "config.json", config, changed_action_states={args.passive_from})
        print(f"registered explicit passive outcome: {args.passive_from} → {state_name}\nconfig backup: {backup_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TargetError as error:
        print(f"Browser targeting refused: {error}")
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("\nCancelled.")
