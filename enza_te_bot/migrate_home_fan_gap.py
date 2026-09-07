"""One-time semantic migration: HOME fan_count is a remaining target gap."""
from __future__ import annotations

import json
from pathlib import Path

from config_store import backup_and_write_config


BASE_DIR = Path(__file__).resolve().parent


def migrate() -> Path:
    config_path = BASE_DIR / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    observation = config["perception"]["home_observation"]
    if "fan_gap_to_target" in observation:
        raise ValueError("fan_gap_to_target is already configured; refusing to overwrite evidence.")
    legacy = observation.pop("fan_count", None)
    if not isinstance(legacy, dict) or "roi" not in legacy:
        raise ValueError("Expected the captured perception.home_observation.fan_count ROI.")
    observation["fan_gap_to_target"] = legacy
    observation["season"]["range"] = [1, 4]
    # No evidence establishes a narrower week maximum. This is a structural
    # OCR guard, not a farming-policy threshold.
    observation["weeks_remaining"]["range"] = [0, 99]
    return backup_and_write_config(config_path, config)


if __name__ == "__main__":
    print(f"config backup: {migrate()}")
