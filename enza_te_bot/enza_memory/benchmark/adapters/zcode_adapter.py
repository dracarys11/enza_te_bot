"""Normalize previously captured ZCode output; never contacts a browser."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import normalize_response


def adapt_response(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        for key in ("response", "result", "output", "content", "text"):
            if key in raw and isinstance(raw[key], (str, Mapping)):
                return normalize_response(raw[key])
    return normalize_response(raw)
