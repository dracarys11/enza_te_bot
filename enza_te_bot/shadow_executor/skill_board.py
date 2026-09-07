"""Recovered-frame skill-board perception for the read-only shadow executor.

The module deliberately separates screenshot facts from policy authority.  A
colour is evidence for a visual state, never permission to buy a node.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

import cv2
import numpy as np
from PIL import Image


VISUAL_STATES = frozenset({"AVAILABLE", "LOCKED", "ACQUIRED", "SELECTED", "UNKNOWN"})
BOARD_SCALE_PROFILES = frozenset({"NORMAL", "ZOOM_OUT", "OTHER"})
POLICY_ZONES = frozenset({"LEFT_BLOCK", "RIGHT_BLOCK", "CENTER", "OTHER"})


@dataclass(frozen=True)
class SkillNodeObservation:
    node_id: str
    bbox_norm: tuple[float, float, float, float]
    center_norm: tuple[float, float]
    board_space_norm: tuple[float, float]
    zone: str
    visual_state: str
    mechanical_state: str
    visual_features: tuple[str, ...]
    confidence: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillBoardObservation:
    room_state: str
    board_scale_profile: str
    nodes: tuple[SkillNodeObservation, ...]
    selected_node_id: str | None
    current_sp: int | None
    required_sp: int | None
    purchase_state: str
    provenance: str
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReplacementSlot:
    slot: int
    bbox_norm: tuple[float, float, float, float]
    select_button_norm: tuple[float, float, float, float]
    center_norm: tuple[float, float]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReplacementObservation:
    state: str
    slots: tuple[ReplacementSlot, ...]
    selected_slot: int | None
    forget_skill_region_norm: tuple[float, float, float, float] | None
    new_skill_region_norm: tuple[float, float, float, float] | None
    ok_box_norm: tuple[float, float, float, float] | None
    cancel_box_norm: tuple[float, float, float, float] | None
    provenance: str
    completeness: str
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SkillActionPlan:
    decision: str
    node_id: str | None
    click_point_norm: tuple[float, float] | None
    reason: str
    blockers: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _open_image(frame: Image.Image | Path | str) -> Image.Image:
    return (Image.open(frame) if isinstance(frame, (str, Path)) else frame).convert("RGB")


def _hsv(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2HSV)


def _fraction(mask: np.ndarray) -> float:
    return float(mask.mean()) if mask.size else 0.0


def _annulus(mask: np.ndarray) -> tuple[float, float, float]:
    """Radial distribution of a colour mask inside one node crop.

    Returns (outer_frac, inner_frac, core_fill): the share of mask pixels in
    the outer annulus (r >= 0.55 of the crop half-diagonal), the share in the
    inner disc (r < 0.45), and the mask fill ratio of the inner disc itself.
    A state ring lives in the annulus and leaves the core hollow; a skill icon
    badge fills the core or spans both bands as one solid blob.
    """
    height, width = mask.shape
    cy, cx = (height - 1) / 2, (width - 1) / 2
    radius = float(np.hypot(max(cx, width - 1 - cx), max(cy, height - 1 - cy)))
    ys, xs = np.nonzero(mask)
    if ys.size == 0 or radius <= 0:
        return 0.0, 0.0, 0.0
    r = np.hypot(xs - cx, ys - cy) / radius
    yy, xx = np.mgrid[0:height, 0:width]
    grid = np.hypot(xx - cx, yy - cy) / radius
    outer, inner = r >= 0.55, r < 0.45
    core = grid < 0.45
    return float(outer.mean()), float(inner.mean()), float(mask[core].mean())


def _ocr_number(image: Image.Image, box: tuple[int, int, int, int]) -> int | None:
    """Read one evidence-region integer; disagreement or missing OCR is UNKNOWN."""
    crop = np.asarray(image.crop(box).convert("RGB"))
    if crop.size == 0:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    gray = cv2.resize(gray, None, fx=6, fy=6, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
    try:
        import pytesseract
        raw = pytesseract.image_to_string(
            binary, lang="eng", config="--psm 11 -c tessedit_char_whitelist=0123456789"
        )
    except (ImportError, OSError, RuntimeError):
        return None
    tokens = re.findall(r"\d+", raw)
    return int(tokens[0]) if len(tokens) == 1 else None


def _current_sp(image: Image.Image) -> int | None:
    if image.size != (1280, 720):
        return None
    return _ocr_number(image, (245, 105, 305, 145))


def _required_sp(image: Image.Image) -> int | None:
    width, height = image.size
    if width == 1280 and height == 720:
        # Selected-node detail panel occupies the lower-right of a full frame.
        return _ocr_number(image, (1160, 548, 1250, 610))
    if width >= 600 and height <= 240:
        return _ocr_number(image, (width - 110, 0, width, min(80, height)))
    return None


def evaluate_sp(current_sp: int | None, required_sp: int | None) -> str:
    if current_sp is None or required_sp is None:
        return "SP_UNKNOWN"
    return "SUFFICIENT_SP" if current_sp >= required_sp else "INSUFFICIENT_SP"


def _hex_candidates(image: Image.Image) -> list[tuple[int, int, int, int]]:
    """Extract visible node hexagons; coordinates remain local to this frame."""
    array = np.asarray(image)
    gray = cv2.cvtColor(array, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 30, 90)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[tuple[int, int, int, int, float]] = []
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
        x, y, width, height = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        if not (5 <= len(polygon) <= 7 and 34 <= width <= 80 and 30 <= height <= 72):
            continue
        if not (0.68 <= width / max(height, 1) <= 1.35 and area >= 800):
            continue
        if image.size == (1280, 720) and not (240 <= x + width / 2 <= 1040 and y + height / 2 <= 705):
            continue
        candidates.append((x, y, width, height, area))
    # Thick cyan/magenta state rings can obscure the underlying hex edge. Add
    # their actual connected-component geometry before center deduplication.
    hsv = _hsv(image)
    ring_mask = (((hsv[:, :, 0] >= 78) & (hsv[:, :, 0] <= 102) & (hsv[:, :, 1] >= 90) & (hsv[:, :, 2] >= 145)) |
                 ((hsv[:, :, 0] >= 145) & (hsv[:, :, 1] >= 105) & (hsv[:, :, 2] >= 135))).astype(np.uint8) * 255
    ring_mask = cv2.morphologyEx(ring_mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
    ring_contours, _ = cv2.findContours(ring_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in ring_contours:
        x, y, width, height = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        if 38 <= width <= 100 and 34 <= height <= 90 and area >= 650:
            if image.size != (1280, 720) or (240 <= x + width / 2 <= 1040 and y + height / 2 <= 705):
                candidates.append((x, y, width, height, area + 10000))
    candidates.sort(key=lambda value: value[4], reverse=True)
    kept: list[tuple[int, int, int, int]] = []
    for x, y, width, height, _ in candidates:
        cx, cy = x + width / 2, y + height / 2
        if any((cx - (kx + kw / 2)) ** 2 + (cy - (ky + kh / 2)) ** 2 < 12 ** 2
               for kx, ky, kw, kh in kept):
            continue
        kept.append((x, y, width, height))
    return sorted(kept, key=lambda value: (value[1], value[0]))


def _scale_profile(image: Image.Image, boxes: Iterable[tuple[int, int, int, int]]) -> str:
    if image.size != (1280, 720):
        return "OTHER"
    heights = [height for _, _, _, height in boxes if height <= 55]
    if len(heights) < 6:
        return "OTHER"
    median = float(np.median(heights))
    return "NORMAL" if median >= 43 else "ZOOM_OUT"


def _zone(center: tuple[float, float]) -> str:
    x, y = center
    if 0.21 <= x <= 0.53 and y <= 0.48:
        return "LEFT_BLOCK"
    if 0.56 <= x <= 0.84 and 0.31 <= y <= 0.94:
        return "RIGHT_BLOCK"
    if 0.40 <= x <= 0.62 and 0.24 <= y <= 0.72:
        return "CENTER"
    return "OTHER"


def _node_visual(image: Image.Image, box: tuple[int, int, int, int]) -> tuple[str, str, tuple[str, ...], float]:
    x, y, width, height = box
    crop = _hsv(image.crop((x, y, x + width, y + height)))
    border = np.zeros(crop.shape[:2], dtype=bool)
    edge = max(2, round(min(width, height) * 0.16))
    border[:edge, :] = border[-edge:, :] = True
    border[:, :edge] = border[:, -edge:] = True
    hue, saturation, value = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    cyan_mask = (hue >= 78) & (hue <= 102) & (saturation >= 90) & (value >= 150)
    magenta_mask = (hue >= 145) & (saturation >= 100) & (value >= 130)
    cyan = _fraction(cyan_mask[border])
    magenta = _fraction(magenta_mask[border])
    pale = _fraction((saturation <= 70) & (value >= 205))
    dark = _fraction(value <= 135)
    mag_outer, mag_inner, _ = _annulus(magenta_mask)
    cyan_outer, _, cyan_core = _annulus(cyan_mask)
    features = (f"cyan_border={cyan:.3f}", f"magenta_border={magenta:.3f}",
                f"pale_fill={pale:.3f}", f"dark_fill={dark:.3f}",
                f"magenta_annulus={mag_outer:.3f}/{mag_inner:.3f}",
                f"cyan_annulus={cyan_outer:.3f}/core={cyan_core:.3f}")
    # A selection ring is a large hollow magenta annulus encircling the node.
    # Pink skill-icon badges inside ordinary nodes are smaller and keep their
    # colour in the core, so magenta share alone is never selection evidence.
    if (width >= 60 and height >= 50 and magenta >= 0.10
            and mag_outer >= 0.90 and mag_inner <= 0.12):
        return "SELECTED", "UNKNOWN", features, min(0.92, 0.65 + magenta)
    # An owned node carries a cyan state ring on the hex border while the
    # interior keeps the skill tile; a solid cyan fill is a generic UI chip.
    if cyan >= 0.12 and cyan_outer >= 0.55 and cyan_core <= 0.30:
        return "ACQUIRED", "ACQUIRED", features, min(0.92, 0.68 + cyan)
    if pale >= 0.42:
        return "AVAILABLE", "AVAILABLE_CANDIDATE", features, min(0.86, 0.55 + pale / 2)
    if dark >= 0.62:
        return "LOCKED", "LOCKED_CANDIDATE", features, min(0.83, 0.52 + dark / 3)
    return "UNKNOWN", "UNKNOWN", features, 0.35


def _panel_state(image: Image.Image, current_sp: int | None, required_sp: int | None) -> tuple[str, tuple[str, ...]]:
    hsv = _hsv(image)
    height, width = hsv.shape[:2]
    if width == 1280 and height == 720:
        crop = hsv[round(height * 0.76):height, round(width * 0.83):width]
    elif width >= 600 and height <= 240:
        crop = hsv[round(height * 0.28):height, round(width * 0.72):width]
    else:
        return "UNKNOWN", ("no selected-node detail panel",)
    hue, saturation, value = crop[:, :, 0], crop[:, :, 1], crop[:, :, 2]
    bright_pink = _fraction((hue >= 145) & (saturation >= 90) & (value >= 155))
    dark_button = _fraction((hue >= 135) & (saturation >= 45) & (value <= 150))
    evidence = (f"bright_pink_button={bright_pink:.3f}", f"dark_button={dark_button:.3f}")
    if evaluate_sp(current_sp, required_sp) == "INSUFFICIENT_SP":
        return "INSUFFICIENT_SP", evidence
    if bright_pink >= 0.18:
        return "AVAILABLE", evidence
    if dark_button >= 0.08:
        return "LOCKED", evidence
    return "UNKNOWN", evidence


def observe_skill_board(frame: Image.Image | Path | str, *, current_sp_override: int | None = None,
                        provenance: str = "ZCODE_SESSION_ARTIFACT_RECOVERED") -> SkillBoardObservation:
    image = _open_image(frame)
    boxes = _hex_candidates(image)
    profile = _scale_profile(image, boxes)
    current_sp = _current_sp(image) if current_sp_override is None else current_sp_override
    required_sp = _required_sp(image)
    panel_state, panel_evidence = _panel_state(image, current_sp, required_sp)
    nodes: list[SkillNodeObservation] = []
    width, height = image.size
    for index, box in enumerate(boxes):
        x, y, node_width, node_height = box
        bbox = (x / width, y / height, (x + node_width) / width, (y + node_height) / height)
        center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
        visual, mechanical, features, confidence = _node_visual(image, box)
        nodes.append(SkillNodeObservation(
            f"node_{index:02d}", bbox, center, center, _zone(center), visual,
            mechanical, features, round(confidence, 4),
        ))
    selected = [node for node in nodes if node.visual_state == "SELECTED"]
    selected_node_id = max(selected, key=lambda node: node.confidence).node_id if selected else None
    room_state = "FURIKAERI_SKILL" if (len(nodes) >= 6 or panel_state != "UNKNOWN") else "UNKNOWN"
    evidence = [f"hex_candidates={len(nodes)}", *panel_evidence]
    if profile == "OTHER":
        evidence.append("crop-only frame; geometry is local and not merged with full-board profiles")
    return SkillBoardObservation(room_state, profile, tuple(nodes), selected_node_id,
                                 current_sp, required_sp, panel_state, provenance, tuple(evidence))


def _pink_button_boxes(image: Image.Image) -> list[tuple[float, float, float, float]]:
    hsv = _hsv(image)
    height, width = hsv.shape[:2]
    mask = ((hsv[:, :, 0] >= 145) & (hsv[:, :, 1] >= 75) & (hsv[:, :, 2] >= 145)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[float, float, float, float]] = []
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        if box_width >= width * 0.10 and box_height >= height * 0.055:
            boxes.append((x / width, y / height, (x + box_width) / width, (y + box_height) / height))
    return sorted(boxes, key=lambda box: (box[1], box[0]))


def observe_replacement(frame: Image.Image | Path | str, *,
                        provenance: str = "ZCODE_SESSION_ARTIFACT_RECOVERED",
                        partial_commit_evidence: bool = False) -> ReplacementObservation:
    image = _open_image(frame)
    buttons = _pink_button_boxes(image)
    hsv = _hsv(image)
    cyan = _fraction((hsv[:, :, 0] >= 82) & (hsv[:, :, 0] <= 105) &
                     (hsv[:, :, 1] >= 70) & (hsv[:, :, 2] >= 130))
    slot_buttons = [box for box in buttons if box[0] >= 0.55 and (box[3] - box[1]) >= 0.07]
    if len(slot_buttons) >= 4:
        slot_buttons = slot_buttons[:4]
        slots = []
        for index, button in enumerate(slot_buttons, 1):
            mid_y = (button[1] + button[3]) / 2
            half_height = max(0.075, (button[3] - button[1]) * 0.85)
            slot_box = (max(0.0, button[0] - 0.39), max(0.0, mid_y - half_height),
                        min(1.0, button[2] + 0.02), min(1.0, mid_y + half_height))
            slots.append(ReplacementSlot(index, slot_box, button,
                                         ((button[0] + button[2]) / 2, mid_y)))
        return ReplacementObservation("SLOT_LIST", tuple(slots), None, None, None, None,
                                      next((box for box in buttons if box[1] >= 0.82), None),
                                      provenance, "COMPLETE", (f"vertical_select_buttons={len(slot_buttons)}",))
    if cyan >= 0.018 and buttons:
        bottom = sorted((box for box in buttons if box[1] >= 0.70), key=lambda box: box[0])
        ok = bottom[-1] if bottom else None
        cancel = (0.35, 0.82, 0.49, 0.95) if image.size == (1280, 720) else None
        return ReplacementObservation(
            "CONFIRM_DIALOG", (), None, (0.28, 0.18, 0.72, 0.38), (0.28, 0.43, 0.72, 0.64),
            ok, cancel, provenance, "COMPLETE", (f"cyan_header_fraction={cyan:.3f}", "pink new-skill header"),
        )
    board = observe_skill_board(image, provenance=provenance)
    if board.room_state == "FURIKAERI_SKILL":
        acquired = sum(node.visual_state == "ACQUIRED" for node in board.nodes)
        state = "PENDING_SELECTION_RING" if board.selected_node_id else "POST_COMMIT_BOARD" if acquired >= 1 else "UNKNOWN"
        completeness = "PARTIAL" if partial_commit_evidence else "COMPLETE"
        return ReplacementObservation(state, (), None, None, None, None, None, provenance,
                                      completeness, (f"acquired_visual_nodes={acquired}",))
    return ReplacementObservation("UNKNOWN", (), None, None, None, None, None, provenance,
                                  "PARTIAL", ("replacement layout not detected",))


def plan_skill_action(observation: SkillBoardObservation, *, allowed_zones: Iterable[str],
                      policy_authorized_node_ids: Iterable[str]) -> SkillActionPlan:
    """Return a hypothetical plan; visual state never grants policy authority."""
    allowed = set(allowed_zones)
    authorized = set(policy_authorized_node_ids)
    blockers: list[str] = []
    if observation.room_state != "FURIKAERI_SKILL":
        blockers.append("ROOM_STATE_UNKNOWN")
    if observation.purchase_state != "AVAILABLE":
        blockers.append(f"NODE_NOT_MECHANICALLY_AVAILABLE:{observation.purchase_state}")
    selected = next((node for node in observation.nodes if node.node_id == observation.selected_node_id), None)
    if selected is None:
        blockers.append("SELECTED_NODE_GEOMETRY_UNKNOWN")
    else:
        if selected.zone not in allowed:
            blockers.append(f"ZONE_POLICY_BLOCKED:{selected.zone}")
        if selected.node_id not in authorized:
            blockers.append("POLICY_DID_NOT_AUTHORIZE_NODE")
    if evaluate_sp(observation.current_sp, observation.required_sp) == "INSUFFICIENT_SP":
        blockers.append("INSUFFICIENT_SP")
    if blockers:
        return SkillActionPlan("NO_ACTION", None, None, "FAIL_CLOSED", tuple(blockers))
    assert selected is not None
    return SkillActionPlan("WOULD_CLICK", selected.node_id, selected.center_norm,
                           "VISUAL_AND_POLICY_GATES_PASS", ())


def validate_progressive_unlock(before: SkillBoardObservation, after: SkillBoardObservation,
                                *, acquired_center_norm: tuple[float, float],
                                tolerance: float = 0.04) -> dict[str, Any]:
    """Validate one transition while sourcing next candidates only from fresh FRAME_B."""
    def near(node: SkillNodeObservation) -> bool:
        return ((node.center_norm[0] - acquired_center_norm[0]) ** 2 +
                (node.center_norm[1] - acquired_center_norm[1]) ** 2) ** 0.5 <= tolerance

    acquired = [node for node in after.nodes if near(node) and node.visual_state == "ACQUIRED"]
    fresh_available = [node for node in after.nodes if node.visual_state == "AVAILABLE"]
    return {
        "available_to_acquired": before.purchase_state == "AVAILABLE" and bool(acquired),
        "fresh_after_frame_used": True,
        "fresh_available_node_ids": [node.node_id for node in fresh_available],
        "acquired_not_reclicked": all(node.node_id not in {n.node_id for n in fresh_available} for node in acquired),
        "locked_not_clicked": True,
        "next_target_source": "FRAME_B_ONLY",
    }
