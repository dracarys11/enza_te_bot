"""Interactively define an allowed normalized action box; never clicks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyautogui

from browser_target import BrowserTarget, TargetError
from config_store import backup_and_write_config
from ui_preview import select_scaled_roi
from vision import detect_state, dynamic_screenshot

BASE_DIR = Path(__file__).resolve().parent
pyautogui.FAILSAFE = True

# Verified toggle actions are one-shot per future room run.  This is metadata
# only for now; the bounded room runner is deliberately not changed here.
ONCE_ONLY_ACTIONS = {"battle_speed_on", "battle_auto_on"}

def capture_action_from_image(image, window: dict, config: dict, state_name: str,
                              action_name: str, expected_next_states: list[str], *, repeat: str | None = None) -> dict | None:
    """Use the shared selector to write one explicit click transition safely."""
    if state_name not in config["states"]:
        raise ValueError(f"Unknown configured state {state_name}.")
    if not action_name.strip() or not expected_next_states:
        raise ValueError("Action name and explicitly taught expected next states are required.")
    if any(name not in config["states"] for name in expected_next_states):
        raise ValueError("Every expected next state must already be configured.")
    print(f"Drag the complete clickable region for {state_name} / {action_name}. Enter/Space confirms; Esc or c cancels.")
    (x, y, width, height), preview_box, original_size, preview_size, scale, screen_size = select_scaled_roi(image, f"Select {state_name} {action_name} action")
    if width <= 0 or height <= 0:
        return None
    capture_scale = config["capture_scale"]
    box = [x / (window["width"] * capture_scale["x"]), y / (window["height"] * capture_scale["y"]),
           (x + width) / (window["width"] * capture_scale["x"]), (y + height) / (window["height"] * capture_scale["y"])]
    if not (0.0 <= box[0] < box[2] <= 1.0 and 0.0 <= box[1] < box[3] <= 1.0):
        raise ValueError("Selection is outside game_window; no action was written.")
    new_action = {"name": action_name.strip(), "type": "click", "box": [round(value, 6) for value in box],
                  "expected_next_states": list(dict.fromkeys(expected_next_states))}
    if repeat is not None:
        new_action["repeat"] = repeat
    # Preserve every differently named action in this state. Capturing an
    # action again replaces only that exact action name after its backup.
    existing_actions = list(config["states"][state_name].get("allowed_actions", []))
    config["states"][state_name]["allowed_actions"] = [
        action for action in existing_actions if action.get("name") != new_action["name"]
    ] + [new_action]
    config["game_window"] = None
    config.pop("capture_scale", None)
    backup_path = backup_and_write_config(
        BASE_DIR / "config.json", config, changed_action_states={state_name}, new_actions=[new_action],
        replaced_action_names={state_name: {new_action["name"]}},
    )
    relative = (round(x / capture_scale["x"]), round(y / capture_scale["y"]), round((x + width) / capture_scale["x"]), round((y + height) / capture_scale["y"]))
    absolute = (window["left"] + relative[0], window["top"] + relative[1], window["left"] + relative[2], window["top"] + relative[3])
    info = {"state": state_name, "action": new_action, "backup": str(backup_path), "preview_box": preview_box,
            "original_size": original_size, "preview_size": preview_size, "screen_size": screen_size,
            "scale": scale, "relative": relative, "absolute": absolute}
    print(f"original game_window size: {original_size[0]} x {original_size[1]}")
    print(f"preview size: {preview_size[0]} x {preview_size[1]}")
    print(f"screen size: {screen_size[0]} x {screen_size[1]}")
    print(f"scale factor: {scale:.6f}")
    print(f"selected preview coordinates [left, top, width, height]: {preview_box}")
    print(f"absolute screen box: {absolute}\nrelative game_window box: {relative}")
    print(f"normalized action box: {new_action['box']}\nsaved action in: {BASE_DIR / 'config.json'}\nconfig backup: {backup_path}")
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state")
    parser.add_argument("action")
    parser.add_argument("--expected-next-state", dest="expected_next_states", action="append", required=True,
                        help="Explicit taught next state; repeat for multiple allowed destinations.")
    parser.add_argument("--repeat", choices=("once",), help="Future local execution metadata; capture performs no click.")
    args = parser.parse_args()
    config_path = BASE_DIR / "config.json"
    config = json.loads(config_path.read_text())
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        image, window = dynamic_screenshot(target, config, BASE_DIR)
        detected = detect_state(image, config, BASE_DIR)
        if detected.state != args.state:
            raise TargetError(f"{args.state} is not detected (found {detected.state}); no action was written.")
    repeat = args.repeat or ("once" if args.action in ONCE_ONLY_ACTIONS else None)
    if capture_action_from_image(image, window, config, args.state, args.action, args.expected_next_states,
                                 repeat=repeat) is None:
        print("Cancelled: no action was written.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TargetError as error:
        print(f"Safety stop: {error}")
        raise SystemExit(2)
    except KeyboardInterrupt:
        print("\nCancelled.")
