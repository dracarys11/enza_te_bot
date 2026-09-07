"""Deterministic, evidence-first helpers for the REFLECTION skill route."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence

from PIL import Image


ROUTE_ORDER = ("upper_left_ring", "lower_right_ring")


@dataclass(frozen=True)
class ReflectionSpRead:
    value: int | None
    raw: str
    reason: str | None = None


@dataclass(frozen=True)
class ReflectionNode:
    route: str
    node_id: str
    box: tuple[float, float, float, float]
    expected_cost: int
    node_type: str
    action_name: str | None = None
    runtime_element_id: str | None = None


def fixed_route_nodes(reflection_config: dict) -> list[ReflectionNode]:
    """Load the production fixed normalized route (geometry is diagnostic-only)."""
    entries = reflection_config.get("fixed_route", [])
    if not isinstance(entries, list):
        raise ValueError("reflection.fixed_route must be a list.")
    nodes = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or entry["id"] in seen:
            raise ValueError("fixed_route node IDs must be unique non-empty strings.")
        point = entry.get("point", [])
        if len(point) != 2 or not all(0 <= float(v) <= 1 for v in point):
            raise ValueError(f"fixed_route node {entry['id']} has invalid point.")
        cost, kind = entry.get("cost"), entry.get("type")
        if not isinstance(cost, int) or cost < 0 or kind not in {"normal", "appeal"}:
            raise ValueError(f"fixed_route node {entry['id']} has invalid cost/type.")
        x, y = map(float, point)
        eps = 0.005
        nodes.append(ReflectionNode("fixed_route", entry["id"], (max(0.0, x-eps), max(0.0, y-eps), min(1.0, x+eps), min(1.0, y+eps)), cost, kind,
                                    "reflection_skill_1"))
        seen.add(entry["id"])
    return nodes


def validate_normalized_box(box: Sequence[float]) -> tuple[float, float, float, float]:
    if len(box) != 4:
        raise ValueError("Reflection node box must have four normalized values.")
    values = tuple(float(value) for value in box)
    if not (0 <= values[0] < values[2] <= 1 and 0 <= values[1] < values[3] <= 1):
        raise ValueError("Reflection node box must be contained in the game window.")
    return values


def parse_remaining_sp(raw: str) -> ReflectionSpRead:
    """Parse exactly one non-negative SP integer without joining stray digits."""
    text = raw.strip()
    if not text:
        return ReflectionSpRead(None, raw, "empty OCR")
    tokens = re.findall(r"(?<!\d)(?:\d{1,3}(?:[,.]\d{3})+|\d+)(?!\d)", text)
    if len(tokens) != 1:
        return ReflectionSpRead(None, raw, "expected exactly one numeric SP token")
    token = tokens[0]
    if "," in token or "." in token:
        if not re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", token):
            return ReflectionSpRead(None, raw, "malformed thousands grouping")
        value = int(token.replace(",", "").replace(".", ""))
    else:
        value = int(token)
    return ReflectionSpRead(value, raw)


def crop_normalized(image: Image.Image, roi: Sequence[float]) -> Image.Image:
    left, top, right, bottom = validate_normalized_box(roi)
    width, height = image.size
    return image.crop((round(left * width), round(top * height), round(right * width), round(bottom * height)))


def configured_route_nodes(reflection_config: dict) -> list[ReflectionNode]:
    """Return explicit route order; no geometry or board-position inference."""
    routes = reflection_config.get("skill_routes", {})
    if not isinstance(routes, dict):
        raise ValueError("reflection.skill_routes must be an object.")
    nodes: list[ReflectionNode] = []
    seen_ids: set[str] = set()
    for route in ROUTE_ORDER:
        entries = routes.get(route, [])
        if not isinstance(entries, list):
            raise ValueError(f"reflection.skill_routes.{route} must be a list.")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"{route} contains an invalid node.")
            node_id = entry.get("id")
            cost = entry.get("expected_cost")
            node_type = entry.get("type")
            if not isinstance(node_id, str) or not node_id or node_id in seen_ids:
                raise ValueError("Reflection route node IDs must be unique non-empty strings.")
            if not isinstance(cost, int) or cost < 0:
                raise ValueError(f"Reflection node {node_id} has an invalid expected_cost.")
            if node_type not in {"normal", "appeal"}:
                raise ValueError(f"Reflection node {node_id} has invalid type.")
            action_name = entry.get("action")
            if action_name is not None and (not isinstance(action_name, str) or not action_name):
                raise ValueError(f"Reflection node {node_id} has invalid action reference.")
            seen_ids.add(node_id)
            nodes.append(ReflectionNode(route, node_id, validate_normalized_box(entry.get("box", [])), cost,
                                        node_type, action_name))
    return nodes


def affordable_route_plan(nodes: Iterable[ReflectionNode], remaining_sp: int) -> tuple[list[ReflectionNode], list[ReflectionNode]]:
    """Keep configured order and allow later cheaper nodes after unaffordable ones."""
    if remaining_sp < 0:
        raise ValueError("remaining_sp must be non-negative.")
    affordable: list[ReflectionNode] = []
    skipped: list[ReflectionNode] = []
    for node in nodes:
        (affordable if node.expected_cost <= remaining_sp else skipped).append(node)
    return affordable, skipped


def can_commit_purchase(*, resulting_state: str, remaining_before: int,
                        remaining_after: int | None) -> bool:
    """A route node commits only after known REFLECTION plus a successful SP reread."""
    return resulting_state == "REFLECTION" and remaining_after is not None and remaining_after < remaining_before


def may_advance_route_cursor(*, node_type: str, resulting_state: str,
                             remaining_before: int, remaining_after: int | None) -> bool:
    """Normal nodes advance only after the purchase commit evidence exists."""
    return node_type == "normal" and can_commit_purchase(
        resulting_state=resulting_state,
        remaining_before=remaining_before,
        remaining_after=remaining_after,
    )


def reflection_node_outcome(node: ReflectionNode, resulting_state: str | None) -> str:
    """Pure safety classifier; UNKNOWN never receives an extra click."""
    if resulting_state in {None, "UNKNOWN"}:
        return "UNKNOWN_STOP"
    if node.node_type == "appeal":
        return "APPEAL_REPLACE_ACTION_REQUIRED" if resulting_state == "APPEAL_REPLACE" else "APPEAL_NOT_VERIFIED"
    return "REFLECTION_CONTINUES" if resulting_state == "REFLECTION" else "NEW_STABLE_STATE"
