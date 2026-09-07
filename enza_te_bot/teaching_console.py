"""Interactive, human-confirmed teaching session built on the shared registry."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from actions import click_point, point_is_inside_window, random_point
from browser_target import BrowserTarget, TargetError
from capture_action_box import capture_action_from_image
from capture_template import capture_template_from_image
from config_store import backup_and_write_config
from states import Detection, State
from vision import detect_state, dynamic_screenshot, save_action_debug

BASE_DIR = Path(__file__).resolve().parent
SUGGESTED_LABELS = [
    "HOME", "PRODUCE_MENU", "VOCAL_RESULT", "SUPPORT_EVENT", "STORY_EVENT",
    "MORNING_DIALOGUE", "MORNING_CHOICE", "RESULT", "CONFIRM", "LOADING",
]


def _trace(path: Path, record: dict) -> None:
    record["timestamp"] = datetime.now().isoformat(timespec="milliseconds")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _save(image, label: str) -> Path:
    path = BASE_DIR / "logs" / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{label}.png"
    image.save(path)
    return path


def _screenshot(target: BrowserTarget, config: dict):
    target.verify_and_focus()
    return dynamic_screenshot(target, config, BASE_DIR)


def _valid_label(value: str) -> str:
    label = value.strip().upper().replace("-", "_").replace(" ", "_")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", label):
        raise ValueError("State labels must use A-Z, 0-9, and underscores, beginning with a letter.")
    return label


def _choose_label(config: dict) -> str | None:
    labels = list(dict.fromkeys([*SUGGESTED_LABELS, *config["states"].keys()]))
    print("Available labels: " + ", ".join(labels) + ", NEW_STATE")
    choice = input("Label this screen (or q to leave it unknown): ").strip()
    if choice.lower() in {"q", ""}:
        return None
    if choice.upper() == "NEW_STATE":
        return _valid_label(input("New state label: "))
    label = _valid_label(choice)
    if label not in labels:
        print("That label is not listed. Choose NEW_STATE to add it explicitly.")
        return None
    return label


def _expected_states(config: dict) -> list[str]:
    value = input("Explicit allowed next states (comma-separated; blank means none taught yet): ").strip()
    if not value:
        return []
    result = [_valid_label(item) for item in value.split(",") if item.strip()]
    unknown = [name for name in result if name not in config["states"]]
    if unknown:
        raise ValueError("Expected next states must be registered first: " + ", ".join(unknown))
    return list(dict.fromkeys(result))


def _configure_behavior(config: dict, image, window: dict, state: str) -> tuple[str | None, list[str]]:
    if state == State.MORNING_CHOICE.value:
        print("MORNING_CHOICE is protected: no generic automatic choice can be configured here.")
        return None, []
    choice = input("Behavior: [a] click action, [p] passive wait, [n] no action/hard stop: ").strip().lower()
    if choice in {"", "n"}:
        return None, []
    expected = _expected_states(config)
    if choice == "p":
        replaced_names = {action.get("name") for action in config["states"][state].get("allowed_actions", []) if action.get("name")}
        config["states"][state].pop("allowed_actions", None)
        config["states"][state]["allowed_actions"] = []
        config["states"][state]["passive_transition"] = {"type": "passive_wait", "expected_next_states": expected}
        backup = backup_and_write_config(
            BASE_DIR / "config.json", config, changed_action_states={state},
            replaced_action_names={state: replaced_names},
        )
        print(f"Saved passive wait for {state}; config backup: {backup}")
        return "passive_wait", expected
    if choice != "a":
        raise ValueError("Choose a, p, or n.")
    action_name = input("Action name: ").strip()
    if not action_name:
        raise ValueError("Action name cannot be empty.")
    result = capture_action_from_image(image, window, config, state, action_name, expected)
    return (result["action"]["name"] if result else None), expected


def _wait_for_change(target: BrowserTarget, config: dict, source: str, timeout: float) -> tuple[Detection, object, str | None]:
    deadline = time.monotonic() + timeout
    candidate: Detection | None = None
    last = None
    while time.monotonic() < deadline:
        image, _window = _screenshot(target, config)
        detected = detect_state(image, config, BASE_DIR)
        last = image
        if detected.state == State.UNKNOWN.value:
            return detected, image, "UNKNOWN"
        if detected.state == source:
            candidate = None
        elif candidate is not None and candidate.state == detected.state:
            return detected, image, None
        else:
            candidate = detected
        time.sleep(config["defaults"]["poll_interval_seconds"])
    return Detection(State.UNKNOWN.value), last, "TIMEOUT"


def _teach_unknown(target: BrowserTarget, config: dict, image, window: dict, trace: Path, previous_state: str | None,
                   previous_action: str | None) -> tuple[bool, str | None, str | None]:
    evidence = _save(image, "TEACH_UNKNOWN")
    _trace(trace, {"kind": "unknown", "current_state": "UNKNOWN", "known": False,
                   "previous_state": previous_state, "previous_action": previous_action,
                   "screenshot": str(evidence)})
    print(f"UNKNOWN saved: {evidence}")
    label = _choose_label(config)
    if label is None:
        return False, previous_state, previous_action
    name = input(f"Template name [{label.lower()}_marker]: ").strip() or f"{label.lower()}_marker"
    result = capture_template_from_image(image, window, config, label, name, title=f"Teach {label} template")
    if result is None:
        print("Template capture cancelled; state remains UNKNOWN.")
        return True, previous_state, previous_action
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    # The template write deliberately clears runtime geometry. Reacquire it before
    # opening an action selector so its normalized box maps to the live window.
    image, window = _screenshot(target, config)
    action, expected = _configure_behavior(config, image, window, label)
    _trace(trace, {"kind": "teaching", "current_state": "UNKNOWN", "known": False,
                   "previous_state": previous_state, "previous_action": previous_action,
                   "human_assigned_label": label, "template_added": result["template"],
                   "action_added": action, "expected_next_states": expected,
                   "screenshot": str(evidence), "decision": "continue"})
    return True, label, action


def _teach_action_for_known_state(config: dict, image, window: dict, state: str, trace: Path) -> str | None:
    """Teach one explicit action for a known inert state; this never clicks."""
    expected = _expected_states(config)
    action_name = input("Action name: ").strip()
    if not action_name:
        raise ValueError("Action name cannot be empty.")
    result = capture_action_from_image(image, window, config, state, action_name, expected)
    action = result["action"]["name"] if result else None
    _trace(trace, {"kind": "known_action_teaching", "current_state": state,
                   "known": True, "action_added": action,
                   "expected_next_states": expected,
                   "config_backup": result["backup"] if result else None,
                   "decision": "action_captured" if result else "action_capture_cancelled"})
    if result:
        print(f"Action {action!r} captured. It is configured only; a later explicit Enter is required before any click.")
    return action


def teach() -> int:
    """Run the interactive console. It never clicks without an Enter confirmation."""
    trace = BASE_DIR / "logs" / f"teach_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl"
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    previous_state: str | None = None
    previous_action: str | None = None
    print(f"Interactive teaching started. Trace: {trace}")
    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            while True:
                config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
                image, window = _screenshot(target, config)
                current = detect_state(image, config, BASE_DIR)
                known = current.state != State.UNKNOWN.value
                _trace(trace, {"kind": "observation", "current_state": current.state, "confidence": current.confidence,
                               "matched_template": current.template, "known": known,
                               "previous_state": previous_state, "previous_action": previous_action})
                if not known:
                    keep_going, previous_state, previous_action = _teach_unknown(target, config, image, window, trace, previous_state, previous_action)
                    if not keep_going:
                        print(f"Teaching stopped safely. Trace: {trace}")
                        return 0
                    continue
                spec = config["states"][current.state]
                actions = spec.get("allowed_actions", [])
                passive = spec.get("passive_transition")
                if current.state == State.MORNING_CHOICE.value:
                    evidence = _save(image, "TEACH_MORNING_CHOICE")
                    _trace(trace, {"kind": "stop", "current_state": current.state, "confidence": current.confidence,
                                   "known": True, "previous_state": previous_state, "previous_action": previous_action,
                                   "screenshot": str(evidence), "decision": "MORNING_CHOICE_HARD_STOP"})
                    print(f"MORNING_CHOICE requires a specific event rule; no generic choice is allowed. Screenshot: {evidence}")
                    return 0
                if len(actions) == 1:
                    action = actions[0]
                    expected = action.get("expected_next_states", [])
                    print(f"\ncurrent_state={current.state} confidence={current.confidence:.3f}\naction={action.get('name')}\nexpected_next_states={expected}")
                    command = input("[Enter] execute one bounded safe step | [s] skip / observe manually | [q] quit: ").strip().lower()
                    if command == "q":
                        _trace(trace, {"kind": "stop", "current_state": current.state, "known": True, "decision": "quit"})
                        return 0
                    if command == "s":
                        input("Make any manual observation in the game, then press Enter to re-detect (q also re-detects): ")
                        _trace(trace, {"kind": "manual_observe", "current_state": current.state, "known": True,
                                       "previous_state": previous_state, "previous_action": previous_action})
                        previous_state, previous_action = current.state, "manual"
                        continue
                    if command:
                        print("No action taken; choose Enter, s, or q.")
                        continue
                    before_image, _ = _screenshot(target, config)
                    before = detect_state(before_image, config, BASE_DIR)
                    if before.state != current.state:
                        evidence = _save(before_image, "TEACH_STATE_CHANGED")
                        print(f"State changed before click; no click made. Screenshot: {evidence}")
                        previous_state, previous_action = current.state, "state_changed"
                        continue
                    point = random_point(action["box"], config["game_window"], config["defaults"])
                    if not point_is_inside_window(point, config["game_window"]):
                        raise ValueError("Proposed click is outside the current game window.")
                    debug = save_action_debug(config["game_window"], action["box"], point, BASE_DIR, f"teach_{action['name']}")
                    target.verify_and_focus()
                    click_point(point, config["defaults"])
                    next_state, next_image, reason = _wait_for_change(target, config, current.state, float(spec.get("timeout_seconds", 5)))
                    evidence = _save(next_image or before_image, "TEACH_TRANSITION")
                    _trace(trace, {"kind": "transition", "current_state": current.state, "confidence": current.confidence,
                                   "matched_template": current.template, "known": True, "previous_state": previous_state,
                                   "previous_action": previous_action, "action": action["name"], "expected_next_states": expected,
                                   "proposed_click": point, "actual_click": point, "debug_screenshot": str(debug),
                                   "screenshot": str(evidence), "actual_next_state": next_state.state,
                                   "actual_confidence": next_state.confidence, "stop_reason": reason})
                    previous_state, previous_action = current.state, action["name"]
                    if reason == "TIMEOUT":
                        print(f"Transition timed out; evidence saved at {evidence}. Teaching remains interactive.")
                    elif next_state.state != State.UNKNOWN.value and next_state.state not in expected:
                        print(f"Known state {next_state.state} was not explicitly allowed; no further click will occur until you teach it.")
                    continue
                if passive and passive.get("type") == "passive_wait":
                    expected = passive.get("expected_next_states", [])
                    print(f"\ncurrent_state={current.state} confidence={current.confidence:.3f}\npassive_wait expected_next_states={expected}")
                    command = input("[Enter] observe passively | [s] observe manually | [q] quit: ").strip().lower()
                    if command == "q":
                        return 0
                    if command == "s":
                        input("Observe manually, then press Enter to re-detect: ")
                        previous_state, previous_action = current.state, "manual"
                        continue
                    if command:
                        continue
                    next_state, next_image, reason = _wait_for_change(target, config, current.state, float(spec.get("timeout_seconds", 5)))
                    evidence = _save(next_image or image, "TEACH_PASSIVE")
                    _trace(trace, {"kind": "passive_wait", "current_state": current.state, "confidence": current.confidence,
                                   "known": True, "previous_state": previous_state, "previous_action": previous_action,
                                   "expected_next_states": expected, "actual_next_state": next_state.state,
                                   "actual_confidence": next_state.confidence, "screenshot": str(evidence), "stop_reason": reason})
                    previous_state, previous_action = current.state, "passive_wait"
                    if reason == "TIMEOUT":
                        print(f"Passive observation timed out; screenshot: {evidence}")
                    continue
                evidence = _save(image, "TEACH_NO_ACTION")
                print(f"Known state {current.state} has no configured action. Screenshot: {evidence}")
                command = input("[a] teach/add action | [s] observe manually | [q] quit: ").strip().lower()
                _trace(trace, {"kind": "known_no_action", "current_state": current.state, "confidence": current.confidence,
                               "known": True, "previous_state": previous_state, "previous_action": previous_action,
                               "screenshot": str(evidence), "decision": command or "quit"})
                if command == "a":
                    action = _teach_action_for_known_state(config, image, window, current.state, trace)
                    previous_state, previous_action = current.state, action or "action_capture_cancelled"
                    continue
                if command != "s":
                    return 0
                input("Observe manually, then press Enter to re-detect: ")
                previous_state, previous_action = current.state, "manual"
    except KeyboardInterrupt:
        _trace(trace, {"kind": "stop", "reason": "INTERRUPTED", "previous_state": previous_state, "previous_action": previous_action})
        print(f"Teaching interrupted safely. Trace: {trace}")
        return 130
    except (TargetError, ValueError) as error:
        _trace(trace, {"kind": "stop", "reason": "SAFETY_ERROR", "detail": str(error), "previous_state": previous_state, "previous_action": previous_action})
        print(f"Teaching safety stop: {error}\nTrace: {trace}")
        return 2
