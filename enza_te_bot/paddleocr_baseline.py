"""PaddleOCR raw baseline runner.

This module deliberately emits no state, action, or semantic interpretation.
PaddleOCR is optional; when unavailable, a deterministic empty result records
the dependency failure without fabricating OCR text.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import json
from numbers import Real
from pathlib import Path
import sys
from typing import Any


DEFAULT_IMAGE = Path("ai_decisions/observations/screenshots/OBS_20260903052210_calibration_produce_selection.png")
DEFAULT_OUTPUT = Path("test_data/ob001/paddle_raw.json")


def _debug_result_structure(rows: object) -> None:
    """Print the temporary PaddleOCR result-shape diagnostic to stderr."""
    print(f"PaddleOCR predict result: type={type(rows).__name__}", file=sys.stderr)
    if not isinstance(rows, Sequence):
        return
    print(f"PaddleOCR predict pages: count={len(rows)}", file=sys.stderr)
    for index, page in enumerate(rows):
        raw = getattr(page, "json", page)
        if callable(raw):
            raw = raw()
        keys = list(raw.keys()) if isinstance(raw, Mapping) else []
        print(
            f"PaddleOCR page[{index}]: type={type(page).__name__}, "
            f"json_type={type(raw).__name__}, keys={keys}",
            file=sys.stderr,
        )
        if isinstance(raw, Mapping) and isinstance(raw.get("res"), Mapping):
            payload = raw["res"]
            field_shapes = {
                key: {
                    "type": type(payload.get(key)).__name__,
                    "length": len(payload[key]) if isinstance(payload.get(key), Sequence) else None,
                }
                for key in ("rec_texts", "rec_scores", "rec_boxes", "rec_polys")
                if key in payload
            }
            print(
                f"PaddleOCR page[{index}].res: keys={list(payload.keys())}, "
                f"ocr_fields={field_shapes}",
                file=sys.stderr,
            )


def _result_payload(page: object) -> Mapping[str, Any] | None:
    raw = getattr(page, "json", page)
    if callable(raw):
        raw = raw()
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, Mapping):
        return None
    nested = raw.get("res")
    return nested if isinstance(nested, Mapping) else raw


def _coordinates(box: object) -> tuple[list[float], list[float]] | None:
    points = box.tolist() if hasattr(box, "tolist") else box
    if not isinstance(points, (list, tuple)) or len(points) < 2:
        return None
    if len(points) == 4 and all(isinstance(value, Real) for value in points):
        x1, y1, x2, y2 = map(float, points)
        return [x1, x2], [y1, y2]
    try:
        return (
            [float(point[0]) for point in points],
            [float(point[1]) for point in points],
        )
    except (IndexError, TypeError, ValueError):
        return None


def run(image_path: str | Path = DEFAULT_IMAGE, output_path: str | Path = DEFAULT_OUTPUT,
        *, debug: bool = False) -> dict[str, Any]:
    image = Path(image_path)
    output = Path(output_path)
    result: dict[str, Any] = {
        "source_image": str(image),
        "method": "PaddleOCR",
        "text_regions": [],
    }
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except ImportError as error:
        result["error"] = f"PaddleOCR unavailable: {error}"
    else:
        if not image.is_file():
            result["error"] = f"image not found: {image}"
        else:
            # PaddleOCR 3.x API: orientation is configured at construction and
            # prediction returns Result objects (or JSON-like mappings).
            try:
                engine = PaddleOCR(
                    use_doc_orientation_classify=False,
                    use_doc_unwarping=False,
                    use_textline_orientation=True,
                    lang="japan",
                )
                rows = engine.predict(str(image)) or []
                if debug:
                    _debug_result_structure(rows)
            except Exception as error:
                result["error"] = f"PaddleOCR failed: {error}"
                rows = []
            index = 0
            for page_index, page in enumerate(rows):
                data = _result_payload(page)
                if debug:
                    print(
                        f"PaddleOCR page[{page_index}] payload: "
                        f"type={type(data).__name__}, "
                        f"keys={list(data.keys()) if data is not None else []}",
                        file=sys.stderr,
                    )
                if data is None:
                    continue
                texts = data.get("rec_texts", [])
                scores = data.get("rec_scores", [])
                boxes = data.get("rec_boxes")
                if boxes is None or not hasattr(boxes, "__len__") or len(boxes) == 0:
                    boxes = data.get("rec_polys", [])
                if debug:
                    print(f"PaddleOCR page[{page_index}] texts={texts!r}", file=sys.stderr)
                    print(f"PaddleOCR page[{page_index}] scores={scores!r}", file=sys.stderr)
                    print(f"PaddleOCR page[{page_index}] boxes={boxes!r}", file=sys.stderr)
                for text, confidence, box in zip(texts, scores, boxes):
                    coordinates = _coordinates(box)
                    if debug:
                        print(
                            f"PaddleOCR coordinates: text={text!r}, box={box!r}, "
                            f"coordinates={coordinates!r}",
                            file=sys.stderr,
                        )
                    if coordinates is None:
                        continue
                    xs, ys = coordinates
                    index += 1
                    region = {
                        "id": f"paddle_{index:03d}",
                        "text": str(text),
                        "bbox": [int(min(xs)), int(min(ys)), int(max(xs) - min(xs)), int(max(ys) - min(ys))],
                        "confidence": round(float(confidence), 6),
                    }
                    result["text_regions"].append(region)
                    if debug:
                        print(f"PaddleOCR appended: {region!r}", file=sys.stderr)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the raw PaddleOCR baseline")
    parser.add_argument("--debug", action="store_true", help="print PaddleOCR result structure to stderr")
    arguments = parser.parse_args()
    run(debug=arguments.debug)
