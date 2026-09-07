"""OpenCV-only geometric discovery for zoomed REFLECTION skill boards."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np
from PIL import Image
from PIL import ImageDraw

from reflection import validate_normalized_box


@dataclass(frozen=True)
class BoardCandidate:
    x: float
    y: float
    radius: float
    contour_area: float


@dataclass(frozen=True)
class BoardGeometry:
    board_name: str
    center: tuple[float, float]
    candidates: tuple[BoardCandidate, ...]
    outer_ring: tuple[BoardCandidate, ...]
    clockwise: tuple[BoardCandidate, ...]
    start_index: int
    diagnostics: tuple[dict, ...] = ()


class GeometryUncertain(ValueError):
    """Fail-closed geometry error retaining read-only diagnostic evidence."""
    def __init__(self, reason: str, diagnostics: Sequence[dict] = (), *, board_name: str | None = None,
                 board_image: Image.Image | None = None, start_anchor: Sequence[float] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.diagnostics = list(diagnostics)
        self.board_name = board_name
        self.board_image = board_image
        self.start_anchor = list(start_anchor) if start_anchor is not None else None


def diagnostic_payload(diagnostics: Sequence[dict]) -> list[dict]:
    """Drop runtime contour objects while retaining inspectable geometry fields."""
    return [{key: value for key, value in item.items() if key != "candidate"} for item in diagnostics]


def _board_settings(config: dict) -> dict:
    settings = config.get("reflection", {}).get("geometry", {}).get("detection", {})
    return {
        "canny_low": int(settings.get("canny_low", 60)),
        "canny_high": int(settings.get("canny_high", 160)),
        "hex_canny_low": int(settings.get("hex_canny_low", 40)),
        "hex_canny_high": int(settings.get("hex_canny_high", 120)),
        "min_tile_fraction": float(settings.get("min_tile_fraction", 0.025)),
        "max_tile_fraction": float(settings.get("max_tile_fraction", 0.25)),
        "max_aspect_ratio": float(settings.get("max_aspect_ratio", 2.2)),
        "candidate_count_min": int(settings.get("candidate_count_min", 6)),
        "candidate_count_max": int(settings.get("candidate_count_max", 48)),
        "min_separation_fraction": float(settings.get("min_separation_fraction", 0.04)),
        "outer_band_fraction": float(settings.get("outer_band_fraction", 0.18)),
        "outer_count_min": int(settings.get("outer_count_min", 3)),
        "outer_count_max": int(settings.get("outer_count_max", 20)),
        "boundary_distance_fraction": float(settings.get("boundary_distance_fraction", 0.035)),
        "angular_sector_degrees": float(settings.get("angular_sector_degrees", 40.0)),
        "min_angular_separation_degrees": float(settings.get("min_angular_separation_degrees", 8.0)),
        "max_angular_gap_degrees": float(settings.get("max_angular_gap_degrees", 115.0)),
        "max_neighbor_gap_fraction": float(settings.get("max_neighbor_gap_fraction", 0.55)),
        "min_anchor_margin_fraction": float(settings.get("min_anchor_margin_fraction", 0.02)),
        "neighbor_distance_factor": float(settings.get("neighbor_distance_factor", 1.9)),
        "min_boundary_exposure_degrees": float(settings.get("min_boundary_exposure_degrees", 135.0)),
        "topology_score_margin": float(settings.get("topology_score_margin", 0.08)),
        "boundary_tiebreak_distance_fraction": float(settings.get("boundary_tiebreak_distance_fraction", 0.004)),
        "start_anchor_max_distance_fraction": float(settings.get("start_anchor_max_distance_fraction", 0.15)),
    }


def _validate_settings(settings: dict) -> None:
    if not (0 < settings["canny_low"] < settings["canny_high"]):
        raise ValueError("Invalid Canny thresholds.")
    if not (0 < settings["min_tile_fraction"] < settings["max_tile_fraction"] <= 1):
        raise ValueError("Invalid tile-size fractions.")
    if settings["max_aspect_ratio"] < 1 or settings["candidate_count_min"] < 1:
        raise ValueError("Invalid reflection geometry settings.")
    if settings["candidate_count_max"] < settings["candidate_count_min"]:
        raise ValueError("Invalid reflection candidate count range.")
    if not (0 < settings["min_separation_fraction"] <= 1 and 0 < settings["outer_band_fraction"] < 1
            and 0 < settings["boundary_distance_fraction"] <= 1 and 0 < settings["max_neighbor_gap_fraction"] <= 2
            and 0 <= settings["min_anchor_margin_fraction"] <= 1 and settings["neighbor_distance_factor"] > 1
            and 0 <= settings["topology_score_margin"] <= 1 and 0 <= settings["boundary_tiebreak_distance_fraction"] <= 1):
        raise ValueError("Invalid reflection geometry separation/radial settings.")
    if not (0 < settings["min_angular_separation_degrees"] < settings["angular_sector_degrees"] < 180
            and 0 < settings["max_angular_gap_degrees"] <= 360
            and 0 < settings["min_boundary_exposure_degrees"] <= 360):
        raise ValueError("Invalid reflection geometry angular settings.")


def detect_board_candidates(board: Image.Image, settings: dict) -> tuple[list[BoardCandidate], list[dict]]:
    """Find tile-shaped edge contours and deduplicate them by center distance."""
    _validate_settings(settings)
    frame = cv2.cvtColor(np.asarray(board.convert("RGB")), cv2.COLOR_RGB2GRAY)
    height, width = frame.shape
    scale = min(width, height)
    edges = cv2.Canny(cv2.GaussianBlur(frame, (3, 3), 0), settings["canny_low"], settings["canny_high"])
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    raw: list[BoardCandidate] = []
    rejected: list[dict] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        x, y, w, h = cv2.boundingRect(contour)
        size = max(w, h) / scale
        aspect = max(w / max(h, 1), h / max(w, 1))
        if not settings["min_tile_fraction"] <= size <= settings["max_tile_fraction"]:
            rejected.append({"reason": "tile_size", "box": [x, y, w, h]})
            continue
        if aspect > settings["max_aspect_ratio"]:
            rejected.append({"reason": "aspect_ratio", "box": [x, y, w, h]})
            continue
        raw.append(BoardCandidate(x + w / 2, y + h / 2, max(w, h) / 2, area))
    raw.sort(key=lambda candidate: candidate.contour_area, reverse=True)
    deduplicated: list[BoardCandidate] = []
    minimum = settings["min_separation_fraction"] * math.hypot(width, height)
    for candidate in raw:
        if any(math.hypot(candidate.x - kept.x, candidate.y - kept.y) < minimum for kept in deduplicated):
            rejected.append({"reason": "duplicate_or_overlapping_center", "center": [candidate.x, candidate.y]})
            continue
        deduplicated.append(candidate)
    if not settings["candidate_count_min"] <= len(deduplicated) <= settings["candidate_count_max"]:
        raise ValueError(f"candidate_count={len(deduplicated)} outside configured plausible range")
    return deduplicated, rejected


def clockwise_outer_ring(board_name: str, board: Image.Image, start_anchor: Sequence[float],
                         settings: dict) -> tuple[BoardGeometry, list[dict]]:
    """Build a boundary/topology-supported clockwise outer route."""
    candidates, rejected = detect_board_candidates(board, settings)
    width, height = board.size
    try:
        return ordered_outer_candidates(board_name, candidates, (width, height), start_anchor, settings), rejected
    except GeometryUncertain as error:
        error.board_name = board_name
        error.board_image = board.copy()
        error.start_anchor = list(start_anchor)
        error.diagnostics.extend({"reason": entry.get("reason"), "rejected": entry} for entry in rejected)
        raise


def ordered_outer_candidates(board_name: str, candidates: Sequence[BoardCandidate], board_size: tuple[int, int],
                             start_anchor: Sequence[float], settings: dict) -> BoardGeometry:
    """Pure, fail-closed outer-boundary topology selection.

    Radius is recorded and used as a local support signal, but never used as a
    global constant-radius ring classifier.  A route member needs convex-hull/
    boundary support or local angular-sector outer evidence, then must join one
    continuous clockwise cycle.
    """
    _validate_settings(settings)
    width, height = board_size
    if not candidates:
        raise GeometryUncertain("no skill-node candidates")
    center = (width / 2, height / 2)
    diagonal = math.hypot(width, height)
    points = np.asarray([[candidate.x, candidate.y] for candidate in candidates], dtype=np.float32)
    if len(points) < 3:
        raise GeometryUncertain("fewer than three candidates cannot form a boundary cycle")
    hull_indices = set(int(index) for index in cv2.convexHull(points, returnPoints=False).reshape(-1))
    hull_points = points[list(hull_indices)].reshape(-1, 1, 2)
    boundary_threshold = settings["boundary_distance_fraction"] * diagonal
    sector = math.radians(settings["angular_sector_degrees"])
    nearest_all = []
    for index, candidate in enumerate(candidates):
        distances = [math.hypot(candidate.x - other.x, candidate.y - other.y)
                     for other_index, other in enumerate(candidates) if other_index != index]
        if distances:
            nearest_all.append(min(distances))
    adjacency_distance = (float(np.median(nearest_all)) * settings["neighbor_distance_factor"] if nearest_all else 0.0)
    values: list[dict] = []
    for index, candidate in enumerate(candidates):
        radius = math.hypot(candidate.x - center[0], candidate.y - center[1])
        angle = math.atan2(candidate.y - center[1], candidate.x - center[0])
        nearest = sorted(math.hypot(candidate.x - other.x, candidate.y - other.y)
                         for other_index, other in enumerate(candidates) if other_index != index)
        neighbors = [other for other_index, other in enumerate(candidates) if other_index != index
                     and math.hypot(candidate.x - other.x, candidate.y - other.y) <= adjacency_distance]
        neighbor_angles = sorted(math.atan2(other.y - candidate.y, other.x - candidate.x) for other in neighbors)
        neighbor_gaps = [((neighbor_angles[(position + 1) % len(neighbor_angles)] - angle) % (2 * math.pi))
                         for position, angle in enumerate(neighbor_angles)] if len(neighbor_angles) >= 2 else [2 * math.pi]
        boundary_exposure = max(neighbor_gaps)
        graph_boundary = len(neighbors) >= 2 and math.degrees(boundary_exposure) >= settings["min_boundary_exposure_degrees"]
        distance_to_hull = 0.0 if index in hull_indices else abs(float(cv2.pointPolygonTest(hull_points, (candidate.x, candidate.y), True)))
        local = [other for other_index, other in enumerate(candidates)
                 if other_index != index and abs(math.atan2(math.sin(math.atan2(other.y - center[1], other.x - center[0]) - angle),
                                                          math.cos(math.atan2(other.y - center[1], other.x - center[0]) - angle))) <= sector]
        local_outer = not local or radius >= max(math.hypot(other.x - center[0], other.y - center[1]) for other in local)
        boundary_member = index in hull_indices or distance_to_hull <= boundary_threshold
        # Concave members need both exposed local graph topology and proximity
        # to the boundary. A radial outlier in the interior is never enough.
        accepted = graph_boundary and (boundary_member or distance_to_hull <= boundary_threshold * 2)
        topology_score = ((1.0 if graph_boundary else 0.0) + (1.0 if index in hull_indices else 0.0)
                          + min(1.0, math.degrees(boundary_exposure) / 360.0)
                          + max(0.0, 1.0 - distance_to_hull / max(boundary_threshold * 2, 1))) / 4.0
        values.append({"index": index, "candidate": candidate, "center": [candidate.x, candidate.y],
                       "radius": radius, "angle": angle, "nearest_neighbor_distances": nearest[:3],
                       "adjacency_distance": adjacency_distance, "neighbor_count": len(neighbors),
                       "boundary_exposure_degrees": math.degrees(boundary_exposure), "graph_boundary": graph_boundary,
                       "hull_member": index in hull_indices, "distance_to_hull": distance_to_hull,
                       "local_angular_outermost": local_outer, "topology_score": topology_score, "accepted": accepted,
                       "reason": "boundary_topology_supported" if accepted else "interior_or_topology_unsupported"})
    outer_details = [value for value in values if value["accepted"]]
    # One route node per angular position. Close angular candidates are only
    # resolved when boundary topology yields a clear winner; otherwise halt.
    provisional = sorted(outer_details, key=lambda value: value["angle"])
    selected_details: list[dict] = []
    while provisional:
        group = [provisional.pop(0)]
        while provisional and abs(provisional[0]["angle"] - group[-1]["angle"]) < math.radians(settings["min_angular_separation_degrees"]):
            group.append(provisional.pop(0))
        group.sort(key=lambda value: value["topology_score"], reverse=True)
        if len(group) > 1 and group[0]["topology_score"] - group[1]["topology_score"] < settings["topology_score_margin"]:
            # A candidate demonstrably closer to the detected perimeter is a
            # stronger topological fact than small score rounding jitter.
            boundary_gap = abs(group[0]["distance_to_hull"] - group[1]["distance_to_hull"])
            if boundary_gap < settings["boundary_tiebreak_distance_fraction"] * diagonal:
                raise GeometryUncertain(
                    f"ambiguous branch topology at angular candidates {group[0]['index']} and {group[1]['index']}", values)
            group.sort(key=lambda value: (value["distance_to_hull"], -value["topology_score"]))
        winner = group[0]
        selected_details.append(winner)
        for loser in group[1:]:
            loser["accepted"] = False
            loser["reason"] = "angular_overlap_rejected_by_topology"
    # First/last are adjacent around the circular angle boundary.
    if len(selected_details) > 1:
        first, last = selected_details[0], selected_details[-1]
        if abs((first["angle"] + 2 * math.pi) - last["angle"]) < math.radians(settings["min_angular_separation_degrees"]):
            ranked = sorted((first, last), key=lambda value: value["topology_score"], reverse=True)
            if ranked[0]["topology_score"] - ranked[1]["topology_score"] < settings["topology_score_margin"]:
                raise GeometryUncertain("ambiguous branch topology across angular wrap", values)
            loser = ranked[1]
            loser["accepted"] = False
            loser["reason"] = "angular_wrap_overlap_rejected_by_topology"
            selected_details = [value for value in selected_details if value is not loser]
    outer_details = selected_details
    outer = [value["candidate"] for value in outer_details]
    if not settings["outer_count_min"] <= len(outer) <= settings["outer_count_max"]:
        raise GeometryUncertain(f"outer_ring_count={len(outer)} outside configured plausible range", values)
    separation = settings["min_separation_fraction"] * math.hypot(width, height)
    for index, candidate in enumerate(outer):
        if any(math.hypot(candidate.x - other.x, candidate.y - other.y) < separation
               for other in outer[index + 1:]):
            raise GeometryUncertain("outer-ring candidates overlap or are too close", values)
    clockwise = sorted(outer, key=lambda candidate: math.atan2(candidate.y - center[1], candidate.x - center[0]))
    angles = [math.atan2(candidate.y - center[1], candidate.x - center[0]) for candidate in clockwise]
    angular_gaps = [((angles[(index + 1) % len(angles)] - angle) % (2 * math.pi)) for index, angle in enumerate(angles)]
    if any(math.degrees(gap) < settings["min_angular_separation_degrees"] for gap in angular_gaps):
        raise GeometryUncertain("duplicate or overlapping angular positions", values)
    if any(math.degrees(gap) > settings["max_angular_gap_degrees"] for gap in angular_gaps):
        raise GeometryUncertain("boundary cycle has an implausible angular jump", values)
    neighbor_distances = [math.hypot(clockwise[(index + 1) % len(clockwise)].x - candidate.x,
                                     clockwise[(index + 1) % len(clockwise)].y - candidate.y)
                          for index, candidate in enumerate(clockwise)]
    if any(distance > settings["max_neighbor_gap_fraction"] * diagonal for distance in neighbor_distances):
        raise GeometryUncertain("boundary cycle has an implausible neighbor jump", values)
    if len(start_anchor) != 2:
        raise GeometryUncertain("Board start_anchor must contain two normalized coordinates.", values)
    anchor = (float(start_anchor[0]) * width, float(start_anchor[1]) * height)
    anchor_distances = [math.hypot(candidate.x - anchor[0], candidate.y - anchor[1]) for candidate in clockwise]
    start_index = min(range(len(clockwise)), key=lambda index: anchor_distances[index])
    distance = anchor_distances[start_index]
    if distance > settings["start_anchor_max_distance_fraction"] * math.hypot(width, height):
        raise GeometryUncertain("start anchor does not match a plausible outer-ring node", values)
    ordered_anchor_distances = sorted(anchor_distances)
    if len(ordered_anchor_distances) > 1 and ordered_anchor_distances[1] - ordered_anchor_distances[0] < settings["min_anchor_margin_fraction"] * diagonal:
        raise GeometryUncertain("start anchor does not uniquely identify a route node", values)
    rotated = clockwise[start_index:] + clockwise[:start_index]
    by_candidate = {id(item["candidate"]): item for item in values}
    for index, candidate in enumerate(rotated):
        by_candidate[id(candidate)]["clockwise_index"] = index
        by_candidate[id(candidate)]["route_neighbor_distance"] = neighbor_distances[(start_index + index) % len(neighbor_distances)]
    return BoardGeometry(board_name, center, tuple(candidates), tuple(outer), tuple(rotated), start_index, tuple(values))


def candidate_box(candidate: BoardCandidate, board_roi: Sequence[float], board_size: tuple[int, int],
                  *, half_size_fraction: float = 0.025) -> tuple[float, float, float, float]:
    """Produce a tiny contained game-normalized click box around a discovered center."""
    left, top, right, bottom = validate_normalized_box(board_roi)
    width, height = board_size
    x = left + (right - left) * (candidate.x / width)
    y = top + (bottom - top) * (candidate.y / height)
    half = half_size_fraction
    return validate_normalized_box((max(left, x - half), max(top, y - half), min(right, x + half), min(bottom, y + half)))


def annotate_board_geometry(board: Image.Image, *, diagnostics: Sequence[dict], start_anchor: Sequence[float] | None,
                            geometry: BoardGeometry | None = None) -> Image.Image:
    """Render read-only geometry evidence for successful and failed analysis."""
    rendered = board.convert("RGB").copy()
    draw = ImageDraw.Draw(rendered)
    width, height = rendered.size
    center = geometry.center if geometry is not None else (width / 2, height / 2)
    draw.ellipse((center[0] - 4, center[1] - 4, center[0] + 4, center[1] + 4), fill="cyan")
    accepted = set(id(candidate) for candidate in geometry.outer_ring) if geometry else set()
    route_index = {id(candidate): index for index, candidate in enumerate(geometry.clockwise)} if geometry else {}
    for item in diagnostics:
        candidate = item.get("candidate")
        if not isinstance(candidate, BoardCandidate):
            continue
        color = "lime" if id(candidate) in accepted else "red"
        radius = max(4, round(candidate.radius))
        draw.ellipse((candidate.x - radius, candidate.y - radius, candidate.x + radius, candidate.y + radius), outline=color, width=2)
        label = str(item.get("index", "?"))
        if id(candidate) in route_index:
            label += f"→{route_index[id(candidate)]}"
        draw.text((candidate.x + radius + 2, candidate.y - radius), label, fill=color)
    if geometry is not None and geometry.clockwise:
        route = list(geometry.clockwise)
        for index, candidate in enumerate(route):
            following = route[(index + 1) % len(route)]
            draw.line((candidate.x, candidate.y, following.x, following.y), fill="lime", width=2)
    if start_anchor is not None and len(start_anchor) == 2:
        x, y = float(start_anchor[0]) * width, float(start_anchor[1]) * height
        draw.line((x - 7, y, x + 7, y), fill="yellow", width=2)
        draw.line((x, y - 7, x, y + 7), fill="yellow", width=2)
    return rendered


def classify_node_tile(tile: Image.Image, semantics: dict, templates_dir: Path) -> tuple[str, dict]:
    """Template hook for normal/appeal/unavailable; no match remains unknown."""
    threshold = float(semantics.get("confidence", 0.9))
    if not 0 < threshold <= 1:
        raise ValueError("reflection node semantics confidence must be in (0, 1].")
    frame = cv2.cvtColor(np.asarray(tile.convert("RGB")), cv2.COLOR_RGB2GRAY)
    scores: dict[str, float] = {}
    for label, field in (("normal", "normal_templates"), ("appeal", "appeal_templates"),
                         ("unavailable", "unavailable_templates")):
        names = semantics.get(field, [])
        if not isinstance(names, list):
            raise ValueError(f"{field} must be a list.")
        for name in names:
            if not isinstance(name, str):
                continue
            template = cv2.imread(str(templates_dir / name), cv2.IMREAD_GRAYSCALE)
            if template is None or template.size == 0:
                continue
            resized = cv2.resize(template, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_CUBIC)
            scores[f"{label}:{name}"] = float(cv2.minMaxLoc(cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED))[1])
    if not scores:
        return "unknown", {"scores": scores, "reason": "no taught semantic templates"}
    key, score = max(scores.items(), key=lambda item: item[1])
    return (key.split(":", 1)[0] if score >= threshold else "unknown"), {
        "scores": scores, "top": key, "top_score": score, "threshold": threshold,
    }


def analyze_boards(image: Image.Image, reflection_config: dict, templates_dir: Path) -> tuple[list[dict], list[dict]]:
    """Return ordered outer-ring candidates and diagnostics for both taught boards."""
    geometry_config = reflection_config.get("geometry", {})
    boards = geometry_config.get("boards", {})
    settings = _board_settings({"reflection": reflection_config})
    semantics = geometry_config.get("node_semantics", {})
    results: list[dict] = []
    rejected: list[dict] = []
    for name in ("upper_left", "lower_right"):
        spec = boards.get(name, {})
        roi, anchor = spec.get("roi"), spec.get("start_anchor")
        if roi is None or anchor is None:
            raise ValueError(f"{name} board ROI/start anchor has not been taught")
        validate_normalized_box(roi)
        board = image.crop((round(roi[0] * image.width), round(roi[1] * image.height),
                            round(roi[2] * image.width), round(roi[3] * image.height)))
        board_geometry, board_rejected = clockwise_outer_ring(name, board, anchor, settings)
        rejected.extend({"board": name, **entry} for entry in board_rejected)
        ordered: list[dict] = []
        for index, candidate in enumerate(board_geometry.clockwise):
            half = max(0.01, min(0.04, candidate.radius / min(board.size)))
            box = candidate_box(candidate, roi, board.size, half_size_fraction=half)
            tile = image.crop((round(box[0] * image.width), round(box[1] * image.height),
                               round(box[2] * image.width), round(box[3] * image.height)))
            semantic, semantic_details = classify_node_tile(tile, semantics, templates_dir)
            ordered.append({"order": index, "center": [candidate.x, candidate.y],
                            "radius": math.hypot(candidate.x - board_geometry.center[0], candidate.y - board_geometry.center[1]),
                            "angle": math.atan2(candidate.y - board_geometry.center[1], candidate.x - board_geometry.center[0]),
                            "box": list(box), "semantic": semantic, "semantic_details": semantic_details})
        results.append({"board": name, "roi": roi, "center": list(board_geometry.center),
                        "candidate_count": len(board_geometry.candidates),
                        "outer_ring_count": len(board_geometry.outer_ring),
                        "start_anchor_rotation": board_geometry.start_index, "ordered": ordered,
                        "costs_by_order": spec.get("costs_by_order", []),
                        "candidate_diagnostics": diagnostic_payload(board_geometry.diagnostics),
                        "annotated_board": annotate_board_geometry(board, diagnostics=board_geometry.diagnostics,
                                                                    start_anchor=anchor, geometry=board_geometry)})
    return results, rejected
