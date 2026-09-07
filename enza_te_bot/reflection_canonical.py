"""Canonical REFLECTION board model and deterministic registration helpers.

This module is deliberately independent of the live executor.  It provides
the small geometry/registration primitives needed before wiring canonical
nodes into execution.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class BoardTransform:
    dx: float = 0.0
    dy: float = 0.0
    scale: float = 1.0
    confidence: float = 1.0
    residual: float = 0.0

    def apply(self, point: tuple[float, float]) -> tuple[float, float]:
        return (point[0] * self.scale + self.dx, point[1] * self.scale + self.dy)


@dataclass(frozen=True)
class CanonicalBoard:
    board: str
    roi: tuple[float, float, float, float]
    origin: tuple[float, float]
    basis_q: tuple[float, float]
    basis_r: tuple[float, float]
    start_anchor: tuple[float, float]
    outer_ring: tuple[tuple[int, int], ...]

    def center(self, axial: tuple[int, int]) -> tuple[float, float]:
        q, r = axial
        return (self.origin[0] + q * self.basis_q[0] + r * self.basis_r[0],
                self.origin[1] + q * self.basis_q[1] + r * self.basis_r[1])


def clockwise_ring(radius: int) -> tuple[tuple[int, int], ...]:
    """Generate a deterministic clockwise axial ring (flat-top convention)."""
    if radius < 1:
        return ()
    q, r = (radius, 0)
    directions = ((0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1), (1, 0))
    result: list[tuple[int, int]] = []
    for dq, dr in directions:
        for _ in range(radius):
            result.append((q, r))
            q, r = q + dq, r + dr
    return tuple(result)


def rotate_to_anchor(points: Iterable[tuple[float, float]], anchor: tuple[float, float]) -> list[tuple[float, float]]:
    values = list(points)
    if not values:
        return []
    index = min(range(len(values)), key=lambda i: math.dist(values[i], anchor))
    return values[index:] + values[:index]


def register_translation(reference: Image.Image, current: Image.Image) -> BoardTransform:
    """Register stable board crops using phase correlation (translation only)."""
    ref = cv2.cvtColor(np.asarray(reference.convert("RGB")), cv2.COLOR_RGB2GRAY).astype(np.float32)
    cur = cv2.cvtColor(np.asarray(current.convert("RGB")), cv2.COLOR_RGB2GRAY).astype(np.float32)
    if ref.shape != cur.shape or ref.size == 0:
        raise ValueError("BOARD_REGISTRATION_UNCERTAIN: reference/current dimensions differ")
    (dx, dy), response = cv2.phaseCorrelate(ref, cur)
    if not np.isfinite(response) or response < 0.05:
        raise ValueError("BOARD_REGISTRATION_UNCERTAIN: weak registration response")
    return BoardTransform(float(dx), float(dy), 1.0, float(response), 1.0 - float(response))


def local_tile_evidence(image: Image.Image, center: tuple[float, float], tile_size: tuple[float, float], threshold: float = 0.18) -> bool:
    """Verify a predicted tile by local edge evidence, never by inner icons."""
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 40, 120)
    w, h = tile_size
    points = [(center[0] + w / 2 * math.cos(math.pi * i / 3),
               center[1] + h / 2 * math.sin(math.pi * i / 3)) for i in range(6)]
    hit = total = 0
    for first, second in zip(points, points[1:] + points[:1]):
        for t in np.linspace(0, 1, 20):
            x = round(first[0] * (1 - t) + second[0] * t)
            y = round(first[1] * (1 - t) + second[1] * t)
            if 0 <= x < edges.shape[1] and 0 <= y < edges.shape[0]:
                total += 1
                hit += int(edges[max(0, y - 2):y + 3, max(0, x - 2):x + 3].max() > 0)
    return bool(total and hit / total >= threshold)


def point_in_roi(point: tuple[float, float], roi: tuple[float, float, float, float]) -> bool:
    return roi[0] <= point[0] <= roi[2] and roi[1] <= point[1] <= roi[3]


def is_configured_state(value: object, expected: str) -> bool:
    """Compare dynamic state labels without requiring enum attributes."""
    return str(getattr(value, "value", value)) == expected


def duplicate_target_flags(points: Iterable[tuple[float, float]], tile_size: tuple[float, float],
                           *, image_size: tuple[int, int] | None = None,
                           normalized: bool = False) -> list[bool]:
    """Return symmetric pairwise duplicate flags in one coordinate space."""
    values = list(points)
    if normalized:
        if not image_size or image_size[0] <= 0 or image_size[1] <= 0:
            raise ValueError("image_size required for normalized duplicate checks")
        threshold = 0.25 * min(tile_size) / min(image_size)
    else:
        threshold = 0.25 * min(tile_size)
    flags = [False] * len(values)
    for i, point in enumerate(values):
        for j in range(i + 1, len(values)):
            if math.dist(point, values[j]) < threshold:
                flags[i] = flags[j] = True
    return flags


def diagnose_board(reference: Image.Image, current: Image.Image, board: CanonicalBoard,
                   *, tile_size: tuple[float, float], verification_threshold: float = 0.18) -> dict:
    """Offline/read-only canonical projection diagnostic."""
    determinant = board.basis_q[0] * board.basis_r[1] - board.basis_q[1] * board.basis_r[0]
    if min(math.dist((0, 0), board.basis_q), math.dist((0, 0), board.basis_r)) < 1e-6 or abs(determinant) < 1e-6:
        raise ValueError("BOARD_REGISTRATION_UNCERTAIN: invalid lattice basis")
    transform = register_translation(reference, current)
    route = [board.center(axial) for axial in board.outer_ring]
    route_pixels = [(point[0] * reference.width, point[1] * reference.height) for point in route]
    transformed_pixels = [transform.apply(point) for point in route_pixels]
    transformed = [(point[0] / current.width, point[1] / current.height) for point in transformed_pixels]
    duplicate_flags = duplicate_target_flags(transformed, tile_size,
                                              image_size=(current.width, current.height), normalized=True)
    rows = []
    for index, (axial, canonical, point) in enumerate(zip(board.outer_ring, route, transformed)):
        inside = point_in_roi(point, board.roi)
        pixel_point = transformed_pixels[index]
        verified = local_tile_evidence(current, pixel_point, tile_size, verification_threshold) if inside else False
        duplicate = duplicate_flags[index]
        rows.append({"axial": list(axial), "canonical_center": list(canonical),
                     "transformed_center": list(point), "verified": verified,
                     "inside_board": inside, "duplicate": duplicate})
    failures = sum(not row["verified"] or not row["inside_board"] or row["duplicate"] for row in rows)
    return {"transform": transform, "nodes": rows, "start_index": 0,
            "route_count": len(route), "verification_failures": failures,
            "status": "OK" if failures == 0 else "LOCAL_VERIFICATION_FAILED"}
