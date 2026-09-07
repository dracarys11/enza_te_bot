"""Loss-averse config updates: backup, validate, then atomically replace."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable


def _validate_action(action: dict) -> None:
    box = action.get("box")
    expected = action.get("expected_next_states")
    if not action.get("name") or action.get("type") != "click":
        raise ValueError("New action must have a name and click type.")
    if not isinstance(expected, list) or not expected:
        raise ValueError("New action must have expected_next_states.")
    if not isinstance(box, list) or len(box) != 4 or not all(isinstance(value, (int, float)) and 0.0 <= value <= 1.0 for value in box):
        raise ValueError("New action box must contain four normalized values in [0.0, 1.0].")
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("New action box must have positive width and height.")
    if "repeat" in action and action["repeat"] not in {"once"}:
        raise ValueError("Action repeat metadata must be 'once' when present.")


def _validate_preservation(before: dict, after: dict, changed_action_states: set[str], changed_template_states: set[str], new_actions: Iterable[dict], moved_templates: dict[str, str], replaced_action_names: dict[str, set[str]]) -> None:
    if not isinstance(after.get("states"), dict):
        raise ValueError("Updated config has no states object.")
    for state, previous_spec in before.get("states", {}).items():
        if state not in after["states"]:
            raise ValueError(f"Existing state {state} would be removed.")
        current_spec = after["states"][state]
        previous_templates = set(previous_spec.get("templates", []))
        retained = set(current_spec.get("templates", []))
        moved = {template for template in previous_templates if moved_templates.get(template)}
        if not (previous_templates - moved).issubset(retained):
            raise ValueError(f"Existing templates for {state} would be lost.")
        for template in moved:
            destination = moved_templates[template]
            if destination not in after["states"] or template not in after["states"][destination].get("templates", []):
                raise ValueError(f"Moved template {template} is not preserved in destination state {destination}.")
        if state not in changed_action_states and current_spec.get("allowed_actions", []) != previous_spec.get("allowed_actions", []):
            raise ValueError(f"Unrelated actions for {state} would be changed.")
        if state in changed_action_states:
            replacements = replaced_action_names.get(state, set())
            current_by_name = {action.get("name"): action for action in current_spec.get("allowed_actions", [])}
            for old_action in previous_spec.get("allowed_actions", []):
                name = old_action.get("name")
                if name not in replacements and current_by_name.get(name) != old_action:
                    raise ValueError(f"Unrelated action {name!r} for {state} would be changed or lost.")
        if state not in changed_template_states and current_spec.get("templates", []) != previous_spec.get("templates", []):
            raise ValueError(f"Unrelated templates for {state} would be changed.")
    for action in new_actions:
        _validate_action(action)
        if any(name not in after["states"] for name in action["expected_next_states"]):
            raise ValueError("New action references an unknown expected state.")


def _validate_reflection_config(config: dict) -> None:
    """Validate only explicit REFLECTION teaching data; never infer node order."""
    reflection = config.get("reflection")
    if reflection is None:
        return
    if not isinstance(reflection, dict):
        raise ValueError("reflection must be an object.")
    fixed = reflection.get("fixed_route")
    if fixed is not None:
        if not isinstance(fixed, list):
            raise ValueError("reflection.fixed_route must be a list.")
        ids = set()
        for node in fixed:
            if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"] or node["id"] in ids:
                raise ValueError("reflection.fixed_route IDs must be unique non-empty strings.")
            point = node.get("point")
            if not isinstance(point, list) or len(point) != 2 or not all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in point):
                raise ValueError("reflection.fixed_route points must be normalized [x, y].")
            if not isinstance(node.get("cost"), int) or node["cost"] < 0 or node.get("type") not in {"normal", "appeal"}:
                raise ValueError("reflection.fixed_route nodes need non-negative cost and normal/appeal type.")
            ids.add(node["id"])
    remaining = reflection.get("remaining_sp", {})
    if not isinstance(remaining, dict):
        raise ValueError("reflection.remaining_sp must be an object.")
    roi = remaining.get("roi")
    if roi is not None:
        if not isinstance(roi, list) or len(roi) != 4 or not all(isinstance(value, (int, float)) for value in roi):
            raise ValueError("reflection.remaining_sp.roi must be null or a normalized box.")
        if not (0 <= roi[0] < roi[2] <= 1 and 0 <= roi[1] < roi[3] <= 1):
            raise ValueError("reflection.remaining_sp.roi must be contained in [0, 1].")
    routes = reflection.get("skill_routes", {})
    if not isinstance(routes, dict):
        raise ValueError("reflection.skill_routes must be an object.")
    seen: set[str] = set()
    for route in ("upper_left_ring", "lower_right_ring"):
        nodes = routes.get(route, [])
        if not isinstance(nodes, list):
            raise ValueError(f"reflection.skill_routes.{route} must be a list.")
        for node in nodes:
            if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not node["id"] or node["id"] in seen:
                raise ValueError("Reflection route nodes need globally unique IDs.")
            seen.add(node["id"])
            box = node.get("box")
            if not isinstance(box, list) or len(box) != 4 or not all(isinstance(value, (int, float)) for value in box):
                raise ValueError("Reflection route node box must be normalized.")
            if not (0 <= box[0] < box[2] <= 1 and 0 <= box[1] < box[3] <= 1):
                raise ValueError("Reflection route node box must be contained in [0, 1].")
            if not isinstance(node.get("expected_cost"), int) or node["expected_cost"] < 0:
                raise ValueError("Reflection route node expected_cost must be a non-negative integer.")
            if node.get("type") not in {"normal", "appeal"}:
                raise ValueError("Reflection route node type must be normal or appeal.")
            if "action" in node and (not isinstance(node["action"], str) or not node["action"]):
                raise ValueError("Reflection route node action reference must be a non-empty string.")
    geometry = reflection.get("geometry")
    if geometry is None:
        return
    if not isinstance(geometry, dict):
        raise ValueError("reflection.geometry must be an object.")
    boards = geometry.get("boards", {})
    if not isinstance(boards, dict):
        raise ValueError("reflection.geometry.boards must be an object.")
    for board_name in ("upper_left", "lower_right"):
        board = boards.get(board_name, {})
        if not isinstance(board, dict):
            raise ValueError(f"reflection.geometry.boards.{board_name} must be an object.")
        board_roi = board.get("roi")
        if board_roi is not None:
            if not isinstance(board_roi, list) or len(board_roi) != 4 or not all(isinstance(value, (int, float)) for value in board_roi):
                raise ValueError(f"reflection.geometry.boards.{board_name}.roi must be null or a normalized box.")
            if not (0 <= board_roi[0] < board_roi[2] <= 1 and 0 <= board_roi[1] < board_roi[3] <= 1):
                raise ValueError(f"reflection.geometry.boards.{board_name}.roi must be contained in [0, 1].")
        anchor = board.get("start_anchor")
        if anchor is not None and (not isinstance(anchor, list) or len(anchor) != 2 or not all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in anchor)):
            raise ValueError(f"reflection.geometry.boards.{board_name}.start_anchor must be null or two normalized values.")
        if "clockwise" in board and not isinstance(board["clockwise"], bool):
            raise ValueError(f"reflection.geometry.boards.{board_name}.clockwise must be boolean.")
        costs = board.get("costs_by_order", [])
        if not isinstance(costs, list) or not all(isinstance(cost, int) and cost >= 0 for cost in costs):
            raise ValueError(f"reflection.geometry.boards.{board_name}.costs_by_order must be non-negative integer list.")
    semantics = geometry.get("node_semantics", {})
    if not isinstance(semantics, dict):
        raise ValueError("reflection.geometry.node_semantics must be an object.")
    for key in ("normal_templates", "appeal_templates", "unavailable_templates"):
        if key in semantics and (not isinstance(semantics[key], list) or not all(isinstance(value, str) and value for value in semantics[key])):
            raise ValueError(f"reflection.geometry.node_semantics.{key} must be a list of template names.")
    if "confidence" in semantics and (not isinstance(semantics["confidence"], (int, float)) or not 0 < semantics["confidence"] <= 1):
        raise ValueError("reflection.geometry.node_semantics.confidence must be in (0, 1].")
    detection = geometry.get("detection", {})
    if not isinstance(detection, dict):
        raise ValueError("reflection.geometry.detection must be an object.")
    for key in ("canny_low", "canny_high", "candidate_count_min", "candidate_count_max", "outer_count_min", "outer_count_max"):
        if key in detection and (not isinstance(detection[key], int) or detection[key] < 1):
            raise ValueError(f"reflection.geometry.detection.{key} must be a positive integer.")
    for key in ("min_tile_fraction", "max_tile_fraction", "min_separation_fraction", "outer_band_fraction", "boundary_distance_fraction", "max_neighbor_gap_fraction", "min_anchor_margin_fraction", "start_anchor_max_distance_fraction", "topology_score_margin", "boundary_tiebreak_distance_fraction"):
        if key in detection and (not isinstance(detection[key], (int, float)) or not 0 < detection[key] <= 1):
            raise ValueError(f"reflection.geometry.detection.{key} must be in (0, 1].")
    if "max_aspect_ratio" in detection and (not isinstance(detection["max_aspect_ratio"], (int, float)) or detection["max_aspect_ratio"] < 1):
        raise ValueError("reflection.geometry.detection.max_aspect_ratio must be at least 1.")
    for key in ("angular_sector_degrees", "min_angular_separation_degrees", "max_angular_gap_degrees"):
        if key in detection and (not isinstance(detection[key], (int, float)) or not 0 < detection[key] <= 360):
            raise ValueError(f"reflection.geometry.detection.{key} must be in (0, 360].")
    if "min_boundary_exposure_degrees" in detection and (not isinstance(detection["min_boundary_exposure_degrees"], (int, float)) or not 0 < detection["min_boundary_exposure_degrees"] <= 360):
        raise ValueError("reflection.geometry.detection.min_boundary_exposure_degrees must be in (0, 360].")
    if "neighbor_distance_factor" in detection and (not isinstance(detection["neighbor_distance_factor"], (int, float)) or detection["neighbor_distance_factor"] <= 1):
        raise ValueError("reflection.geometry.detection.neighbor_distance_factor must exceed 1.")


def backup_and_write_config(config_path: Path, updated: dict, *, changed_action_states: Iterable[str] = (), changed_template_states: Iterable[str] = (), new_actions: Iterable[dict] = (), moved_templates: dict[str, str] | None = None, replaced_action_names: dict[str, set[str]] | None = None) -> Path:
    """Backup the exact prior file, validate preservation, then atomically write JSON."""
    original_text = config_path.read_text(encoding="utf-8")
    before = json.loads(original_text)
    action_states, template_states = set(changed_action_states), set(changed_template_states)
    actions = list(new_actions)
    _validate_preservation(before, updated, action_states, template_states, actions, moved_templates or {}, replaced_action_names or {})
    _validate_reflection_config(updated)
    backup_dir = config_path.parent / "config_backups"
    backup_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backup_dir / f"config_{stamp}.json"
    suffix = 1
    while backup_path.exists():
        backup_path = backup_dir / f"config_{stamp}_{suffix}.json"
        suffix += 1
    # Do this before creating any replacement file; an error here aborts mutation.
    backup_path.write_text(original_text, encoding="utf-8")
    if not backup_path.exists() or backup_path.read_text(encoding="utf-8") != original_text:
        raise OSError("Config backup verification failed; refusing config mutation.")
    encoded = json.dumps(updated, indent=2, ensure_ascii=False) + "\n"
    json.loads(encoded)  # Validate serialized JSON before replacing the source file.
    with NamedTemporaryFile("w", encoding="utf-8", dir=config_path.parent, prefix=".config_", suffix=".json", delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, config_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return backup_path
