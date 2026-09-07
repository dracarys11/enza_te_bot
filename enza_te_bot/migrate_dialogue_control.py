"""One-time, loss-averse migration of a shared dialogue-control marker."""
from __future__ import annotations

import json
from pathlib import Path

from config_store import backup_and_write_config

BASE_DIR = Path(__file__).resolve().parent
OLD_STATE = "SUPPORT_EVENT"
NEW_STATE = "DIALOGUE_FAST_FORWARD_OFF"
MARKER = "support_event_marker.png"


def migrate() -> Path:
    config_path = BASE_DIR / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    old = config["states"][OLD_STATE]
    existing_action = old.get("allowed_actions", [])
    if len(existing_action) != 1 or existing_action[0].get("name") != "support_advance":
        raise ValueError("Expected exactly one existing SUPPORT_EVENT support_advance action for migration.")
    old_action = existing_action[0]
    new_action = {
        "name": "dialogue_fast_forward_on",
        "type": "click",
        "box": list(old_action["box"]),
        "expected_next_states": ["HOME", "CHOICE_REQUIRED", "SEASON_CLEAR", "SEASON_RESULT"],
    }
    config["states"][NEW_STATE] = {
        "templates": [MARKER], "roi": old.get("roi"), "confidence": old.get("confidence", 0.85),
        "allowed_actions": [new_action], "expected_next_states": [],
        "timeout_seconds": old.get("timeout_seconds", 5),
        "event_transition_timeout_seconds": old.get("event_transition_timeout_seconds", 20),
        "retries": old.get("retries", 0),
    }
    old["templates"] = []
    old["allowed_actions"] = []
    room_interruptions = config["rooms"]["VOCAL_ROOM"]["interruptions"]
    config["rooms"]["VOCAL_ROOM"]["interruptions"] = [
        NEW_STATE if name == OLD_STATE else name for name in room_interruptions
    ]
    return backup_and_write_config(
        config_path, config,
        changed_action_states={OLD_STATE, NEW_STATE},
        changed_template_states={OLD_STATE, NEW_STATE},
        new_actions=[new_action],
        moved_templates={MARKER: NEW_STATE},
        replaced_action_names={OLD_STATE: {old_action["name"]}},
    )


if __name__ == "__main__":
    print(f"config backup: {migrate()}")
