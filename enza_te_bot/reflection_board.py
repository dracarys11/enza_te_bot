"""Structured OpenCV perception for taught, zoomed REFLECTION skill boards."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PIL import Image

from perception_models import Observation, UIElement, VisualStructure
from reflection_geometry import analyze_boards
from states import Detection


class ReflectionBoardDetector:
    """Translate the legacy geometry diagnostic into runtime UIElements."""
    detector_name = "opencv_reflection_board_geometry"

    def __init__(self, reflection_config: dict, templates_dir: Path) -> None:
        self.reflection_config = reflection_config
        self.templates_dir = templates_dir

    def detect(self, image: Image.Image) -> tuple[tuple[VisualStructure, ...], list[dict]]:
        boards, rejected = analyze_boards(image, self.reflection_config, self.templates_dir)
        structures: list[VisualStructure] = []
        for board in boards:
            members: list[UIElement] = []
            for item in board["ordered"]:
                semantic = item["semantic"] if item["semantic"] != "unknown" else None
                semantic_details = item.get("semantic_details", {})
                confidence = float(semantic_details.get("top_score", 0.0)) if semantic else 0.0
                members.append(UIElement(
                    element_id=f"reflection:{board['board']}:outer:{item['order']:02d}",
                    bbox=tuple(item["box"]), role="skill_node", semantic=semantic,
                    confidence=confidence, detector=self.detector_name,
                    metadata={"board": board["board"], "clockwise_index": item["order"],
                              "radius": item["radius"], "angle": item["angle"],
                              "semantic_details": semantic_details},
                ))
            structures.append(VisualStructure(
                structure_id=f"reflection:{board['board']}", kind="skill_board", bbox=tuple(board["roi"]),
                members=tuple(members), confidence=1.0, detector=self.detector_name,
                metadata={"center": board["center"], "candidate_count": board["candidate_count"],
                          "outer_ring_count": board["outer_ring_count"],
                          "start_anchor_rotation": board["start_anchor_rotation"],
                          "costs_by_order": board.get("costs_by_order", []),
                          "candidate_diagnostics": board.get("candidate_diagnostics", [])},
            ))
        return tuple(structures), rejected


def reflection_observation(*, image: Image.Image, game_window: dict, detection: Detection,
                           reflection_config: dict, templates_dir: Path,
                           screenshot_path: str | None = None, numerics: Sequence = ()) -> tuple[Observation, list[dict]]:
    """Create one structured REFLECTION observation; no action or policy occurs here."""
    structures, rejected = ReflectionBoardDetector(reflection_config, templates_dir).detect(image)
    elements = tuple(member for structure in structures for member in structure.members)
    observation = Observation.fresh(
        game_window=game_window,
        business_state={"state": detection.state.value, "confidence": detection.confidence,
                        "template": detection.template},
        screenshot_path=screenshot_path, elements=elements, numerics=numerics, structures=structures,
        frame_metadata={"rejected_candidates": rejected},
    )
    return observation, rejected
