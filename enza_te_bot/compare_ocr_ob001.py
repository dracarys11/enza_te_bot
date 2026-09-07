"""Compare OCR-only outputs for OB001 (read-only utility)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TARGETS = ("プロデュース選択", "W.I.N.G.編", "研修設定", "次へ")


def load(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def _regions(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in document.get("text_regions", []) if isinstance(item, dict)]


def _matches(document: dict[str, Any], target: str) -> list[dict[str, Any]]:
    return [item for item in _regions(document) if str(item.get("text", "")).strip() == target]


def _iou(a: list[float], b: list[float]) -> float | None:
    if len(a) != 4 or len(b) != 4:
        return None
    ax1, ay1, aw, ah = map(float, a); bx1, by1, bw, bh = map(float, b)
    ax2, ay2, bx2, by2 = ax1 + aw, ay1 + ah, bx1 + bw, by1 + bh
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def compare(tesseract: dict[str, Any], paddle: dict[str, Any], gemini: dict[str, Any]) -> str:
    docs = {"Tesseract": tesseract, "PaddleOCR": paddle, "Gemini": gemini}
    lines = ["OB001 perception report", "", "Key text recall", "", "| Text | Tesseract | PaddleOCR | Gemini |",
             "|---|---:|---:|---:|"]
    for target in TARGETS:
        flags = ["✓" if _matches(document, target) else "✗" for document in docs.values()]
        lines.append(f"| {target} | {flags[0]} | {flags[1]} | {flags[2]} |")
    lines += ["", "BBox IoU (exact text matches)", "", "| Text | Tesseract↔Gemini | PaddleOCR↔Gemini |", "|---|---:|---:|"]
    for target in TARGETS:
        gem = _matches(gemini, target)
        tess = _matches(tesseract, target)
        pad = _matches(paddle, target)
        def best(other: list[dict[str, Any]]) -> str:
            if not gem or not other:
                return "—"
            values = [_iou(item.get("bbox", []), gem[0].get("bbox", [])) for item in other]
            valid = [value for value in values if value is not None]
            return f"{max(valid):.3f}" if valid else "—"
        lines.append(f"| {target} | {best(tess)} | {best(pad)} |")
    lines += ["", "Notes:", "- Matching is exact after surrounding whitespace is stripped.",
              "- Missing text or malformed bbox is reported as unavailable (—).",
              "- This utility compares raw perception only; it performs no semantic interpretation."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare OB001 raw OCR outputs")
    parser.add_argument("tesseract")
    parser.add_argument("paddle")
    parser.add_argument("gemini")
    args = parser.parse_args(argv)
    print(compare(load(args.tesseract), load(args.paddle), load(args.gemini)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
