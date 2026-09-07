"""Normalize previously captured Gemini output; never calls a model."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import normalize_response


def adapt_response(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        if isinstance(raw.get("text"), str):
            return normalize_response(raw["text"])
        candidates = raw.get("candidates")
        if isinstance(candidates, list) and candidates:
            candidate = candidates[0]
            content = candidate.get("content") if isinstance(candidate, Mapping) else None
            parts = content.get("parts") if isinstance(content, Mapping) else None
            if isinstance(parts, list):
                text = "".join(
                    part["text"] for part in parts
                    if isinstance(part, Mapping) and isinstance(part.get("text"), str)
                )
                if text:
                    return normalize_response(text)
    return normalize_response(raw)
