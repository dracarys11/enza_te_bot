"""Minimal HOME field projection from fused VisionObservation JSON.

Phase A exploration: the ONLY inputs are the fused VisionObservation payload
and (optionally) GroundedElement records. Raw screenshots are never accepted
and never read — the projection is a pure function of JSON evidence.

Output fields reuse the legacy business vocabulary of
``home_observation.FIELDS``: season, weeks_remaining, fan_gap_to_target,
stamina. Field candidates are text regions of the fused observation whose
bounding-box center falls inside the field's normalized anchor ROI (the
human-taught ROIs stored under ``config["perception"]["home_observation"]``).
Values are only ever parsed from OCR text; nothing is inferred from pixel
appearance, and the caller supplies human clarification answers explicitly.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Mapping


# Must stay equal to home_observation.FIELDS (guarded by test_home_projection).
FIELDS = ("season", "weeks_remaining", "fan_gap_to_target", "stamina")

STATUS_KNOWN = "KNOWN"
STATUS_AMBIGUOUS = "AMBIGUOUS"
STATUS_MISSING = "MISSING"

SOURCE_VISION_FUSION = "vision_fusion"
SOURCE_HUMAN_CLARIFICATION = "human_clarification"

_HUMAN_CLARIFICATION_CONFIDENCE = 0.5
# ASCII digit-only group: mixed-width digits (e.g. full-width mixed with
# ASCII commas) are rejected outright instead of being split into a wrong
# small value. Full-width digits are handled by NFKC normalization first.
_DIGITS = re.compile(r"-?\d[\d,]*")


def _normalize_numeric_text(raw: str) -> str:
    """NFKC-fold digits and punctuation before parsing.

    Turns full-width digits into ASCII; after folding, any remaining
    non-ASCII digit characters (full-width comma, ideographic comma, ...)
    make the token untrustworthy and it must fail closed rather than split.
    """
    import unicodedata

    folded = unicodedata.normalize("NFKC", str(raw or ""))
    return folded


def numeric_tokens(raw: str) -> list[int]:
    """All complete integer tokens in one string, fail-closed.

    NFKC normalizes full-width digits; tokens containing residual non-ASCII
    punctuation are dropped. ``SP:40`` yields ``[40]``; ``123,456`` yields
    ``[123456]``; a mixed-width or multi-number string yields multiple or
    zero tokens and the caller must treat that as AMBIGUOUS, never guess.
    """
    folded = _normalize_numeric_text(raw)
    tokens: list[int] = []
    for match in _DIGITS.finditer(folded):
        text = match.group(0)
        if any(ord(ch) > 127 for ch in text):
            continue  # mixed-width remnant: refuse, do not guess
        cleaned = text.replace(",", "")
        if cleaned in ("", "-", "-"):
            continue
        try:
            tokens.append(int(cleaned))
        except ValueError:
            continue
    return tokens


def parse_numeric_token(raw: str) -> int | None:
    """Single-value convenience over ``numeric_tokens``.

    Returns a value only when exactly one complete token exists; multiple
    tokens (e.g. ``123,456 / 200,000``) return None so callers fail closed
    instead of silently taking the first number.
    """
    tokens = numeric_tokens(raw)
    return tokens[0] if len(tokens) == 1 else None


def _bbox_center(bbox: Iterable[float]) -> tuple[float, float]:
    x, y, width, height = (float(value) for value in bbox)
    return x + width / 2.0, y + height / 2.0


def _anchor_box(anchor: Mapping[str, Any], viewport: Mapping[str, int]) -> tuple[float, float, float, float]:
    left, top, right, bottom = (float(value) for value in anchor["roi"])
    width = float(viewport["width"])
    height = float(viewport["height"])
    return left * width, top * height, right * width, bottom * height


def _point_in_box(point: tuple[float, float], box: tuple[float, float, float, float]) -> bool:
    x, y = point
    left, top, right, bottom = box
    return left <= x <= right and top <= y <= bottom


def project_home_fields(
    fused_observation: Mapping[str, Any],
    grounded_elements: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
    field_anchors: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project the four HOME fields from fused JSON evidence only.

    ``field_anchors`` maps each field name to ``{"roi": [l, t, r, b]}`` in
    normalized viewport coordinates (plus an optional numeric ``"range"``).
    Anchors are human-taught configuration data, never screenshot-derived.
    """
    viewport = fused_observation.get("viewport") or {}
    if not isinstance(viewport.get("width"), int) or not isinstance(viewport.get("height"), int):
        raise ValueError("fused_observation.viewport must carry integer width/height")

    fields: dict[str, Any] = {}
    for name in FIELDS:
        anchor = (field_anchors or {}).get(name)
        if anchor is None or "roi" not in anchor:
            fields[name] = {
                "value": None,
                "evidence_ids": [],
                "confidence": None,
                "status": STATUS_MISSING,
                "source": SOURCE_VISION_FUSION,
                "note": "no anchor configured",
            }
            continue
        box = _anchor_box(anchor, viewport)
        candidates = []
        for region in fused_observation.get("text_regions", []) or []:
            if not isinstance(region, Mapping) or region.get("bbox") is None:
                continue
            if _point_in_box(_bbox_center(region["bbox"]), box):
                tokens = numeric_tokens(str(region.get("text", "")))
                value = tokens[0] if len(tokens) == 1 else None
                candidates.append(
                    {
                        "id": str(region.get("id", "")),
                        "text": str(region.get("text", "")),
                        "value": value,
                        "token_count": len(tokens),
                        "confidence": region.get("confidence"),
                        "source": region.get("source", "unknown"),
                    }
                )

        if not candidates:
            fields[name] = {
                "value": None,
                "evidence_ids": [],
                "confidence": None,
                "status": STATUS_MISSING,
                "source": SOURCE_VISION_FUSION,
                "note": "no text region inside the anchor ROI",
            }
            continue

        parseable = [c for c in candidates if c["value"] is not None]
        if not parseable:
            multi = [c for c in candidates if c.get("token_count", 0) > 1]
            fields[name] = {
                "value": None,
                "evidence_ids": [c["id"] for c in candidates],
                "confidence": None,
                "status": STATUS_AMBIGUOUS if multi else STATUS_MISSING,
                "source": SOURCE_VISION_FUSION,
                "note": ("multi-number text; refusing to pick one"
                         if multi else "anchor ROI text is not numeric"),
            }
            continue

        values = {c["value"] for c in parseable}
        if len(values) > 1:
            fields[name] = {
                "value": None,
                "evidence_ids": sorted(c["id"] for c in parseable),
                "confidence": None,
                "status": STATUS_AMBIGUOUS,
                "source": SOURCE_VISION_FUSION,
                "note": "conflicting numeric readings",
                "candidate_values": sorted(values),
            }
            continue

        value = values.pop()
        value_range = anchor.get("range")
        if (
            isinstance(value_range, (list, tuple))
            and len(value_range) == 2
            and not (value_range[0] <= value <= value_range[1])
        ):
            fields[name] = {
                "value": None,
                "evidence_ids": sorted(c["id"] for c in parseable),
                "confidence": None,
                "status": STATUS_AMBIGUOUS,
                "source": SOURCE_VISION_FUSION,
                "note": f"value {value} outside taught range {list(value_range)}",
            }
            continue

        confidences = [
            float(c["confidence"])
            for c in parseable
            if isinstance(c["confidence"], (int, float))
        ]
        fields[name] = {
            "value": value,
            "evidence_ids": sorted(c["id"] for c in parseable),
            "confidence": round(min(confidences), 4) if confidences else None,
            "status": STATUS_KNOWN,
            "source": SOURCE_VISION_FUSION,
            "note": "",
        }

    missing = [name for name in FIELDS if fields[name]["status"] == STATUS_MISSING]
    ambiguous = [name for name in FIELDS if fields[name]["status"] == STATUS_AMBIGUOUS]
    return {
        "fields": fields,
        "status": "COMPLETE" if not missing and not ambiguous else "INCOMPLETE",
        "missing_fields": missing,
        "ambiguous_fields": ambiguous,
    }


def apply_clarification_answers(
    projection: Mapping[str, Any],
    answers: Mapping[str, str],
    question_ids: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Fold explicit human clarification answers into a projection.

    A clarified field becomes KNOWN with ``source=human_clarification`` and a
    capped confidence of 0.5 (honesty rule: user_reported evidence). Values
    for season / weeks_remaining / fan_gap_to_target must parse as integers;
    stamina may stay textual (e.g. "adequate").
    """
    merged: dict[str, Any] = {
        "fields": {name: dict(projection["fields"][name]) for name in FIELDS},
        "status": projection.get("status", "INCOMPLETE"),
        "missing_fields": list(projection.get("missing_fields", [])),
        "ambiguous_fields": list(projection.get("ambiguous_fields", [])),
    }
    for name in FIELDS:
        raw = answers.get(name)
        if raw is None or str(raw).strip() == "":
            continue
        field = merged["fields"][name]
        if name in ("season", "weeks_remaining", "fan_gap_to_target"):
            value = parse_numeric_token(str(raw))
            if value is None:
                field["note"] = f"rejected non-numeric clarification {raw!r}"
                continue
        else:
            value = str(raw).strip()
        evidence = list(field.get("evidence_ids", []))
        question_id = (question_ids or {}).get(name)
        if question_id:
            evidence.append(question_id)
        field.update(
            {
                "value": value,
                "evidence_ids": evidence,
                "confidence": _HUMAN_CLARIFICATION_CONFIDENCE,
                "status": STATUS_KNOWN,
                "source": SOURCE_HUMAN_CLARIFICATION,
                "note": "resolved by human clarification",
            }
        )
        if name in merged["missing_fields"]:
            merged["missing_fields"].remove(name)
        if name in merged["ambiguous_fields"]:
            merged["ambiguous_fields"].remove(name)
    merged["status"] = (
        "COMPLETE" if not merged["missing_fields"] and not merged["ambiguous_fields"]
        else "INCOMPLETE"
    )
    return merged


__all__ = [
    "FIELDS",
    "STATUS_KNOWN",
    "STATUS_AMBIGUOUS",
    "STATUS_MISSING",
    "SOURCE_VISION_FUSION",
    "SOURCE_HUMAN_CLARIFICATION",
    "apply_clarification_answers",
    "parse_numeric_token",
    "project_home_fields",
]
