"""Normalize previously captured local-VLM output; never loads a model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import normalize_response


def adapt_response(raw: Any) -> dict[str, Any]:
    if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], Mapping):
        raw = raw[0]
    if isinstance(raw, Mapping):
        for key in ("generated_text", "text", "output", "response"):
            if key in raw:
                return normalize_response(raw[key])
    return normalize_response(raw)
