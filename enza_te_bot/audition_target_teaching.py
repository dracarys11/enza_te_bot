"""Read-only teaching support for audition reward feature markers."""
from __future__ import annotations

import argparse
from pathlib import Path

from capture_template import capture_template_from_image


AUDITION_TARGET_AMOUNTS = (40000, 50000, 100000)


def feature_name(amount: int) -> str:
    if amount not in AUDITION_TARGET_AMOUNTS:
        raise ValueError(f"Unsupported audition target reward: {amount}")
    return f"AUDITION_TARGET_{amount}"


def template_filename(amount: int) -> str:
    feature_name(amount)  # Validate before deriving a filesystem name.
    return f"audition_target_{amount}_marker.png"


def add_cli_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--teach-audition-target",
        type=int,
        choices=AUDITION_TARGET_AMOUNTS,
        metavar="{40000,50000,100000}",
        help="Teach one audition reward marker as feature-only evidence; never clicks the game.",
    )


def _feature_placeholder(config: dict) -> dict:
    return {
        "templates": [],
        "feature_only": True,
        "roi": None,
        "confidence": float(config.get("defaults", {}).get("confidence", 0.88)),
        "allowed_actions": [],
        "expected_next_states": [],
        "timeout_seconds": 5,
        "retries": 0,
    }


def capture_audition_target_from_image(image, window: dict, config: dict, amount: int,
                                       *, base_dir: Path) -> dict | None:
    """Capture one reward marker and preserve it as page-local feature evidence."""
    state_name = feature_name(amount)
    spec = config.setdefault("states", {}).setdefault(state_name, _feature_placeholder(config))
    spec["feature_only"] = True
    filename = template_filename(amount)
    return capture_template_from_image(
        image,
        window,
        config,
        state_name,
        filename,
        title=f"Select +{amount} audition reward marker",
        base_dir=base_dir,
    )
