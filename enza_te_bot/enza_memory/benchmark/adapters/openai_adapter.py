"""Normalize previously captured OpenAI output; never calls an API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ._common import AdapterError, normalize_response


def _content_text(content: Any) -> str | None:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, Mapping) and isinstance(item.get("text"), str):
                texts.append(item["text"])
        return "".join(texts) or None
    return None


def adapt_response(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        if "output_text" in raw:
            return normalize_response(raw["output_text"])
        choices = raw.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], Mapping) else None
            text = _content_text(message.get("content")) if isinstance(message, Mapping) else None
            if text is not None:
                return normalize_response(text)
        output = raw.get("output")
        if isinstance(output, list):
            texts = []
            for item in output:
                if isinstance(item, Mapping):
                    text = _content_text(item.get("content"))
                    if text:
                        texts.append(text)
            if texts:
                return normalize_response("".join(texts))
    try:
        return normalize_response(raw)
    except AdapterError:
        raise
