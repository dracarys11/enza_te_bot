"""Register the taught promise-choice screen as a VOCAL_ROOM interruption boundary."""
from __future__ import annotations

import json
from pathlib import Path

from config_store import backup_and_write_config


BASE_DIR = Path(__file__).resolve().parent


def migrate() -> Path:
    config_path = BASE_DIR / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if "PROMISE_CHOICE" not in config["states"]:
        raise ValueError("PROMISE_CHOICE must be taught before it can become a room boundary.")
    interruptions = config["rooms"]["VOCAL_ROOM"]["interruptions"]
    if "PROMISE_CHOICE" not in interruptions:
        interruptions.append("PROMISE_CHOICE")
    return backup_and_write_config(config_path, config)


if __name__ == "__main__":
    print(f"config backup: {migrate()}")
