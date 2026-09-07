#!/usr/bin/env python3
"""Offline, observation-only VLM extraction boundary.

This module deliberately does not call a model.  Without an injected
observation annotation it emits a fail-closed UNKNOWN/PENDING record.  A
future offline VLM adapter may provide the optional annotation payload, but
the payload is restricted to visual observation fields here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


OBSERVATION_FIELDS = {
    "state",
    "phase",
    "event_type",
    "visible_text",
    "visible_controls",
    "layout_family",
}
FORBIDDEN_FIELDS = {
    "authority_type",
    "failure_category",
    "planner_decision",
    "execution_permission",
    "action_permission",
    "action_allowed",
}
UNKNOWN_OBSERVATION = {
    "state": "UNKNOWN",
    "phase": "UNKNOWN",
    "event_type": "UNKNOWN",
    "visible_text": None,
    "visible_controls": [],
    "layout_family": "UNKNOWN_LAYOUT",
}


def sha256_file(image_path: str | Path) -> str:
    """Hash image bytes without modifying or decoding the image."""
    digest = hashlib.sha256()
    with Path(image_path).open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_annotation(annotation: dict[str, Any]) -> dict[str, Any]:
    forbidden = sorted(FORBIDDEN_FIELDS.intersection(annotation))
    if forbidden:
        raise ValueError(f"forbidden authority fields: {', '.join(forbidden)}")
    extra = sorted(set(annotation) - OBSERVATION_FIELDS)
    if extra:
        raise ValueError(f"unsupported observation fields: {', '.join(extra)}")
    result = dict(UNKNOWN_OBSERVATION)
    result.update(annotation)
    return result


def extract_observation(image_path: str | Path, annotation: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return an observation package for an existing image.

    ``annotation`` is optional and must already be observation-only.  The
    default result makes no visual claim because this module has no model
    backend and must not invent pixel facts.
    """
    path = Path(image_path)
    observation = _validate_annotation(annotation or {})
    return {
        "image": str(image_path),
        "sha256": sha256_file(path),
        "observation": observation,
        "confidence": 0.0 if annotation is None else 0.5,
        "vlm_status": "PENDING" if annotation is None else "ANNOTATED",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an offline observation-only VLM record")
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotation", type=Path, help="Optional observation-only JSON payload")
    args = parser.parse_args()
    annotation = json.loads(args.annotation.read_text()) if args.annotation else None
    result = extract_observation(args.image, annotation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
