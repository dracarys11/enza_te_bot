"""Offline comparison of contour-first and lattice-first REFLECTION proposals.

This module never connects to Chrome and never clicks.  It intentionally does
not modify the live executor; it is a measurement tool for the saved evidence.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
from PIL import Image, ImageDraw

from reflection_geometry import BoardCandidate, _board_settings


@dataclass(frozen=True)
class SkillTileCandidate:
    center: tuple[float, float]
    bbox: tuple[float, float, float, float]
    polygon: tuple[tuple[float, float], ...]
    confidence: float
    source: str
    lattice_index: tuple[int, int] | None = None


@dataclass(frozen=True)
class LatticeAnalysis:
    tile_size: tuple[float, float]
    basis_vectors: tuple[tuple[float, float], tuple[float, float]]
    generated_centers: tuple[tuple[float, float], ...]
    verified: tuple[SkillTileCandidate, ...]
    rejected: tuple[dict, ...]


def lattice_spacing_consistent(centers: Sequence[tuple[float, float]],
                               expected: tuple[float, float],
                               tolerance: float = 0.25) -> bool:
    """Return whether adjacent samples agree with the inferred lattice pitch."""
    if len(centers) < 2:
        return False
    distances = []
    for index, point in enumerate(centers):
        for other in centers[index + 1:]:
            dx, dy = abs(point[0] - other[0]), abs(point[1] - other[1])
            if dx < expected[0] * 1.35 and dy < expected[1] * 1.35:
                distances.append((dx, dy))
    if not distances:
        return False
    return all(abs(dx - expected[0]) <= expected[0] * tolerance or
               abs(dy - expected[1]) <= expected[1] * tolerance
               for dx, dy in distances)


def deduplicate_candidate_centers(centers: Sequence[tuple[float, float]],
                                  min_separation: float) -> list[tuple[float, float]]:
    """Merge duplicate visual/lattice proposals deterministically."""
    result: list[tuple[float, float]] = []
    for center in centers:
        if not any(math.hypot(center[0] - prior[0], center[1] - prior[1]) < min_separation
                   for prior in result):
            result.append(center)
    return result


def _contours(board: Image.Image, settings: dict) -> list[tuple[np.ndarray, float, tuple[int, int, int, int], np.ndarray]]:
    frame = cv2.cvtColor(np.asarray(board.convert("RGB")), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(frame, (5, 5), 0), settings.get("hex_canny_low", 40), settings.get("hex_canny_high", 120))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        x, y, width, height = cv2.boundingRect(contour)
        approximation = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        result.append((contour, area, (x, y, width, height), approximation))
    return result


def contour_first(board: Image.Image, settings: dict) -> tuple[list[BoardCandidate], list[dict], list[dict]]:
    """Reproduce the proposal layer and separately identify whole-hex proposals."""
    height, width = board.size[1], board.size[0]
    scale = min(width, height)
    proposals: list[BoardCandidate] = []
    hexes: list[dict] = []
    rejects: list[dict] = []
    for _contour, area, (x, y, w, h), approximation in _contours(board, settings):
        size = max(w, h) / scale
        aspect = max(w / max(h, 1), h / max(w, 1))
        if not settings["min_tile_fraction"] <= size <= settings["max_tile_fraction"] or aspect > settings["max_aspect_ratio"]:
            continue
        candidate = BoardCandidate(x + w / 2, y + h / 2, max(w, h) / 2, area)
        proposals.append(candidate)
        polygon = approximation.reshape(-1, 2)
        solidity = area / max(w * h, 1)
        # A complete tile is materially larger than icon/text fragments but
        # smaller than a merged board/background contour.  The area gate is
        # deliberately relative so this benchmark remains resolution-safe.
        area_fraction = area / max(width * height, 1)
        is_hex = (5 <= len(polygon) <= 7 and cv2.isContourConvex(approximation)
                  and 1.08 <= w / max(h, 1) <= 1.38 and solidity >= 0.58
                  and 0.008 <= area_fraction <= 0.03)
        if is_hex:
            hexes.append({"candidate": candidate, "polygon": polygon.tolist(), "bbox": [x, y, w, h], "solidity": solidity})
        else:
            rejects.append({"reason": "internal_fragment_or_non_hex", "center": [candidate.x, candidate.y],
                            "bbox": [x, y, w, h], "vertices": len(polygon), "solidity": solidity})
    # Nested contour proposals are not separate UI nodes.  Whole-cell
    # contours are deduplicated independently because RETR_LIST commonly
    # returns both the inner and outer edge of the same hexagon.
    dedup: list[BoardCandidate] = []
    for candidate in sorted(proposals, key=lambda item: item.contour_area, reverse=True):
        if not any(math.hypot(candidate.x - prior.x, candidate.y - prior.y) < 0.18 * scale for prior in dedup):
            dedup.append(candidate)
    unique_hexes: list[dict] = []
    for entry in sorted(hexes, key=lambda item: item["candidate"].contour_area, reverse=True):
        center = entry["candidate"]
        if any(math.hypot(center.x - prior["candidate"].x,
                          center.y - prior["candidate"].y) < 0.28 * min(entry["bbox"][2], entry["bbox"][3])
               for prior in unique_hexes):
            rejects.append({"reason": "duplicate_whole_hex_contour", "center": [center.x, center.y],
                            "bbox": entry["bbox"]})
            continue
        unique_hexes.append(entry)
    return dedup, unique_hexes, rejects


def _hex_edge_score(edges: np.ndarray, center: tuple[float, float], tile_size: tuple[float, float]) -> float:
    width, height = tile_size
    vertices = [(center[0] + width / 2 * math.cos(math.pi * index / 3),
                 center[1] + height / 2 * math.sin(math.pi * index / 3)) for index in range(6)]
    hits = total = 0
    for first, second in zip(vertices, vertices[1:] + vertices[:1]):
        for fraction in np.linspace(0, 1, 24):
            x = round(first[0] * (1 - fraction) + second[0] * fraction)
            y = round(first[1] * (1 - fraction) + second[1] * fraction)
            if not (0 <= x < edges.shape[1] and 0 <= y < edges.shape[0]):
                continue
            total += 1
            hits += int(edges[max(0, y - 2):min(edges.shape[0], y + 3), max(0, x - 2):min(edges.shape[1], x + 3)].max() > 0)
    return hits / total if total else 0.0


def lattice_first(board: Image.Image, settings: dict, *, edge_threshold: float = 0.48) -> LatticeAnalysis:
    """Infer a flat-top hex lattice from seed cells, then verify each center locally."""
    _dedup, hexes, rejected = contour_first(board, settings)
    if len(hexes) < 2:
        raise ValueError("ambiguous lattice basis: fewer than two whole-hex seeds")
    widths = [entry["bbox"][2] for entry in hexes]
    heights = [entry["bbox"][3] for entry in hexes]
    tile_size = (float(np.median(widths)), float(np.median(heights)))
    basis = ((tile_size[0] * 0.75, tile_size[1] * 0.5), (0.0, tile_size[1]))
    seed = min(hexes, key=lambda entry: entry["candidate"].x)
    origin = (seed["candidate"].x, seed["candidate"].y)
    frame = cv2.cvtColor(np.asarray(board.convert("RGB")), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(frame, (5, 5), 0), settings.get("hex_canny_low", 40), settings.get("hex_canny_high", 120))
    generated: list[tuple[float, float]] = []
    verified: list[SkillTileCandidate] = []
    seen: list[tuple[float, float]] = []
    for i in range(-12, 13):
        for j in range(-12, 13):
            center = (origin[0] + i * basis[0][0] + j * basis[1][0],
                      origin[1] + i * basis[0][1] + j * basis[1][1])
            if not (tile_size[0] / 2 < center[0] < board.width - tile_size[0] / 2 and
                    tile_size[1] / 2 < center[1] < board.height - tile_size[1] / 2):
                continue
            if any(math.hypot(center[0] - prior[0], center[1] - prior[1]) < 0.25 * min(tile_size) for prior in seen):
                continue
            seen.append(center)
            generated.append(center)
            score = _hex_edge_score(edges, center, tile_size)
            if score < edge_threshold:
                rejected.append({"reason": "local_tile_boundary_insufficient", "center": list(center), "edge_score": score, "lattice_index": [i, j]})
                continue
            polygon = tuple((center[0] + tile_size[0] / 2 * math.cos(math.pi * index / 3),
                             center[1] + tile_size[1] / 2 * math.sin(math.pi * index / 3)) for index in range(6))
            verified.append(SkillTileCandidate(center, (center[0] - tile_size[0] / 2, center[1] - tile_size[1] / 2,
                                                         center[0] + tile_size[0] / 2, center[1] + tile_size[1] / 2),
                                              polygon, score, "reflection_lattice_first", (i, j)))
    if len(verified) < 2:
        raise ValueError("ambiguous lattice verification: insufficient locally verified centers")
    # Generated points are already lattice-unique; reject implausible gaps in
    # the inferred basis rather than inventing additional positions.
    nearest = []
    for candidate in verified:
        distances = sorted(math.hypot(candidate.center[0] - other.center[0], candidate.center[1] - other.center[1])
                           for other in verified if other is not candidate)
        if distances:
            nearest.append(distances[0])
    if nearest and max(nearest) > 2.4 * min(tile_size):
        raise ValueError("ambiguous lattice spacing: verified centers are disconnected")
    return LatticeAnalysis(tile_size, basis, tuple(generated), tuple(verified), tuple(rejected))


def annotate(board: Image.Image, proposals: Sequence[BoardCandidate], hexes: Sequence[dict], lattice: LatticeAnalysis | None, label: str) -> Image.Image:
    image = board.convert("RGB").copy()
    draw = ImageDraw.Draw(image)
    for candidate in proposals:
        draw.ellipse((candidate.x - 8, candidate.y - 8, candidate.x + 8, candidate.y + 8), outline="red", width=2)
    for entry in hexes:
        draw.polygon([tuple(point) for point in entry["polygon"]], outline="yellow", width=3)
    if lattice:
        for center in lattice.generated_centers:
            draw.ellipse((center[0] - 4, center[1] - 4, center[0] + 4, center[1] + 4), outline="orange", width=1)
        for index, tile in enumerate(lattice.verified):
            draw.polygon(lattice_polygon(tile), outline="lime", width=3)
            draw.text((tile.center[0] + 5, tile.center[1] - 5), str(index), fill="lime")
    draw.text((8, 8), label, fill="white")
    return image


def lattice_polygon(tile: SkillTileCandidate) -> list[tuple[float, float]]:
    return list(tile.polygon)


def run_benchmark(image_path: Path, config_path: Path, output_dir: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    image = Image.open(image_path).convert("RGB")
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict = {"image": str(image_path), "boards": {}}
    for board_name in ("upper_left", "lower_right"):
        roi = config["reflection"]["geometry"]["boards"][board_name]["roi"]
        board = image.crop((round(roi[0] * image.width), round(roi[1] * image.height),
                            round(roi[2] * image.width), round(roi[3] * image.height)))
        settings = _board_settings(config)
        proposals, hexes, rejects = contour_first(board, settings)
        entry = {"contour_first": {"raw_proposal_count": len(proposals), "whole_hex_count": len(hexes),
                                    "false_internal_fragment_count": len(rejects),
                                    "centers": [[round(c.x, 2), round(c.y, 2)] for c in proposals]}}
        lattice = None
        try:
            lattice = lattice_first(board, settings)
            entry["lattice_first"] = {"tile_size": lattice.tile_size, "basis_vectors": lattice.basis_vectors,
                                       "generated_center_count": len(lattice.generated_centers),
                                       "generated_centers": [list(center) for center in lattice.generated_centers],
                                       "verified_center_count": len(lattice.verified),
                                       "verified_centers": [list(tile.center) for tile in lattice.verified],
                                       "rejected_centers": list(lattice.rejected)}
        except ValueError as error:
            entry["lattice_first"] = {"error": str(error)}
        contour_image = annotate(board, proposals, hexes, None, "CONTOUR_FIRST")
        contour_image.save(output_dir / f"{board_name}_CONTOUR_FIRST_ANNOTATED.png")
        lattice_image = annotate(board, proposals, hexes, lattice, "LATTICE_FIRST")
        lattice_image.save(output_dir / f"{board_name}_LATTICE_FIRST_ANNOTATED.png")
        entry["annotated_paths"] = [str(output_dir / f"{board_name}_CONTOUR_FIRST_ANNOTATED.png"),
                                     str(output_dir / f"{board_name}_LATTICE_FIRST_ANNOTATED.png")]
        report["boards"][board_name] = entry
    (output_dir / "reflection_candidate_benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).with_name("logs") / "reflection_benchmark")
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.image, args.config, args.output_dir), indent=2))
