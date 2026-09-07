"""Fuse raw perception sensors into VisionObservation Contract v0.1.

PaddleOCR supplies primary text grounding. Tesseract is used only when Paddle
has no text regions. The visual artifact supplies visual regions and interaction
candidates, with its provider preserved from metadata.
This module performs no semantic interpretation and produces no action.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from vision_observation_schema import LOW_CONFIDENCE_THRESHOLD, VisionObservation


ROOT = Path(__file__).parent
DEFAULT_DATA_DIR = ROOT / "test_data" / "ob001"

# provider != model: the visual source label comes from the artifact's
# metadata.provider (e.g. an AGY artifact using a Gemini model stays "agy").
_VISUAL_PROVIDER_SOURCES = {
    "agy": "agy",
    "gemini": "gemini",
}

# Fused-artifact metadata uses the manifest-style canonical provider name.
_CANONICAL_PROVIDER_NAMES = {
    "agy": "AGY",
    "gemini": "Gemini",
}


class FusionProvenanceError(ValueError):
    """Raised when the visual payload's provider cannot be established."""


def _bbox(region: dict[str, Any]) -> tuple[float, float, float, float]:
    x, y, width, height = region["bbox"]
    return float(x), float(y), float(width), float(height)


def _match_score(left: dict[str, Any], right: dict[str, Any]) -> tuple[float, float]:
    """Rank exact-text matches by overlap, then by center distance."""
    lx, ly, lw, lh = _bbox(left)
    rx, ry, rw, rh = _bbox(right)
    intersection_width = max(0.0, min(lx + lw, rx + rw) - max(lx, rx))
    intersection_height = max(0.0, min(ly + lh, ry + rh) - max(ly, ry))
    intersection = intersection_width * intersection_height
    union = lw * lh + rw * rh - intersection
    iou = intersection / union if union else 0.0
    distance = (lx + lw / 2 - rx - rw / 2) ** 2 + (ly + lh / 2 - ry - rh / 2) ** 2
    return iou, -distance


def _with_source(regions: Iterable[dict[str, Any]], source: str) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for region in regions:
        item = deepcopy(region)
        item["source"] = source
        copied.append(item)
    return copied


def _overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    lx, ly, lw, lh = _bbox(left)
    rx, ry, rw, rh = _bbox(right)
    return lx < rx + rw and rx < lx + lw and ly < ry + rh and ry < ly + lh


def _text_id_map(gemini_texts: Iterable[dict[str, Any]],
                 fused_texts: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for gemini_text in gemini_texts:
        candidates = [
            text for text in fused_texts
            if str(text.get("text", "")).strip() == str(gemini_text.get("text", "")).strip()
        ]
        if not candidates or not gemini_text.get("id"):
            continue
        matched = max(candidates, key=lambda candidate: _match_score(gemini_text, candidate))
        mapping[str(gemini_text["id"])] = str(matched["id"])
    return mapping


def _visual_source(visual: dict[str, Any]) -> str:
    """Resolve the fused visual-region source from ``metadata.provider``.

    provider != model: an AGY artifact using a Gemini model stays "agy".
    Fail closed: a missing, empty, or unknown provider must never default to
    "gemini" — the caller (or a legacy fixture run via ``main``) must declare
    the provider explicitly.
    """
    metadata = visual.get("metadata")
    provider = metadata.get("provider") if isinstance(metadata, dict) else None
    if not isinstance(provider, str) or not provider.strip():
        raise FusionProvenanceError(
            "visual payload metadata.provider is required; "
            "refusing to default the fusion source to 'gemini'"
        )
    key = provider.strip().casefold()
    if key not in _VISUAL_PROVIDER_SOURCES:
        raise FusionProvenanceError(
            f"unsupported visual provider {provider!r}; expected one of "
            f"{sorted(_VISUAL_PROVIDER_SOURCES)}"
        )
    return _VISUAL_PROVIDER_SOURCES[key]


def fused_metadata(visual: dict[str, Any]) -> dict[str, Any]:
    """Self-describing provenance for the fused artifact.

    provider/model/skill_version come from the visual artifact's metadata
    (the text sensor stays attributed per-region via ``source``);
    screenshot_sha256 is lifted from capture.screenshot_digest. Adds
    provenance only -- region semantics are untouched.
    """
    metadata = visual.get("metadata") if isinstance(visual.get("metadata"), dict) else {}
    capture = visual.get("capture") if isinstance(visual.get("capture"), dict) else {}
    digest = str(capture.get("screenshot_digest", ""))
    if digest.startswith("sha256:"):
        digest = digest[len("sha256:"):]
    return {
        "provider": _CANONICAL_PROVIDER_NAMES[_visual_source(visual)],
        "model": metadata.get("model"),
        "skill_version": metadata.get("skill_version"),
        "screenshot_sha256": digest,
    }


def fused_artifact_digest(payload: dict[str, Any]) -> str:
    """Self-hash of a fused artifact: sha256 over the canonical serialization
    of the payload with ``metadata.artifact_sha256`` removed, so consumers can
    recompute and verify without a chicken-and-egg problem."""
    body = deepcopy(payload)
    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("artifact_sha256", None)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _sensor_status(paddle: dict[str, Any], gemini: dict[str, Any],
                  tesseract: dict[str, Any] | None, visual_source: str) -> dict[str, Any]:
    """Sensor-level provenance for the fused artifact.

    Records why the text layer looks the way it does -- most importantly
    ``paddle_ocr_empty``: a text region absence caused by a blind sensor must
    stay distinguishable from an absence caused by the scene itself. Pure
    description; no decision logic.
    """
    paddle_regions = paddle.get("text_regions", []) or []
    tesseract_regions = (tesseract or {}).get("text_regions", []) or []
    if paddle_regions:
        text_sensor = "paddle"
    elif tesseract_regions:
        text_sensor = "tesseract"
    else:
        text_sensor = "none"
    return {
        "text_sensor": text_sensor,
        "paddle_region_count": len(paddle_regions),
        "paddle_ocr_empty": not paddle_regions,
        "visual_provider": visual_source,
        "visual_interaction_count": len(gemini.get("interaction_candidates", []) or []),
        "visual_detection_failure_count": len(gemini.get("detection_failures", []) or []),
    }


def fuse_perception(paddle: dict[str, Any], gemini: dict[str, Any],
                    tesseract: dict[str, Any] | None = None) -> dict[str, Any]:
    paddle_texts = paddle.get("text_regions", [])
    if paddle_texts:
        fused_texts = _with_source(paddle_texts, "paddle")
    else:
        fused_texts = _with_source((tesseract or {}).get("text_regions", []), "tesseract")

    visual_source = _visual_source(gemini)
    text_ids = _text_id_map(gemini.get("text_regions", []), fused_texts)
    interactions = _with_source(gemini.get("interaction_candidates", []), visual_source)
    for element in interactions:
        element["linked_text_ids"] = [
            text_ids[text_id]
            for text_id in element.get("linked_text_ids", [])
            if text_id in text_ids
        ]

    overlays = _with_source(gemini.get("overlay_regions", []), visual_source)
    for overlay in overlays:
        overlay["linked_text_ids"] = [
            text_ids[text_id]
            for text_id in overlay.get("linked_text_ids", [])
            if text_id in text_ids
        ]

    uncertainties = _with_source(gemini.get("uncertainties", []), visual_source)
    for text in fused_texts:
        confidence = text.get("confidence")
        if (isinstance(confidence, (int, float))
                and confidence < LOW_CONFIDENCE_THRESHOLD
                and not any(_overlaps(text, uncertainty) for uncertainty in uncertainties)):
            uncertainties.append({
                "bbox": deepcopy(text["bbox"]),
                "reason": "low_confidence_text_region",
                "source": text["source"],
            })

    fused = {
        "observation_id": gemini["observation_id"],
        "capture": deepcopy(gemini["capture"]),
        "viewport": deepcopy(gemini["viewport"]),
        "text_regions": fused_texts,
        "interaction_candidates": interactions,
        "numeric_regions": _with_source(gemini.get("numeric_regions", []), visual_source),
        "overlay_regions": overlays,
        "uncertainties": uncertainties,
        "detection_failures": _with_source(
            gemini.get("detection_failures", []), visual_source),
        "sensor_status": _sensor_status(paddle, gemini, tesseract, visual_source),
        "metadata": fused_metadata(gemini),
    }
    VisionObservation.from_payload(fused)
    return fused


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Fuse raw OB-001 perception artifacts")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument(
        "--visual-provider", default=None,
        help="explicit provider label for pre-metadata legacy fixtures (e.g. Gemini); "
             "payloads carrying metadata.provider always win",
    )
    arguments = parser.parse_args()
    data_dir = arguments.data_dir
    visual = _load(data_dir / "gemini_raw.json")
    if arguments.visual_provider and not isinstance(visual.get("metadata"), dict):
        visual["metadata"] = {"provider": arguments.visual_provider}
    fused = fuse_perception(
        _load(data_dir / "paddle_raw.json"),
        visual,
        _load(data_dir / "tesseract_raw.json"),
    )
    output = data_dir / "fused_observation.json"
    output.write_text(json.dumps(fused, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
