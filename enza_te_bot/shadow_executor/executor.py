"""Screenshot-only Python shadow click executor v0.1."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any, Mapping

from PIL import Image

from .authority import assess_hazards, authorize_action
from .detectors import ControlDetection, detect_control, detect_page_state
from .logging import ShadowPredictionLogger
from .skill_board import (SkillActionPlan, SkillBoardObservation, observe_skill_board,
                          plan_skill_action)
from .viewport import VIEWPORT_KNOWN, crop_game_viewport, detect_game_viewport


BUNDLE_A = frozenset({
    "HOME:SCHEDULE", "SCHEDULE:VOCAL", "SCHEDULE:DECIDE", "RESULT:ADVANCE",
    "DIALOGUE:SAFE_TEXTBOX", "DIALOGUE:3_CHOICE_MIDDLE", "SCHEDULE:BACK",
    "HOME:REST",
})

EXPECTED_POSTCONDITIONS = {
    "HOME:SCHEDULE": "fresh loaded SCHEDULE",
    "SCHEDULE:VOCAL": "VOCAL selected and DECIDE actionable",
    "SCHEDULE:DECIDE": "lesson or audition transition begins",
    "RESULT:ADVANCE": "fresh HOME, transition, or next result state after result commit",
    "DIALOGUE:SAFE_TEXTBOX": "fresh next dialogue, choice, or HOME",
    "DIALOGUE:3_CHOICE_MIDDLE": "choice accepted and presentation progresses",
    "SCHEDULE:BACK": "fresh WING_HOME",
    "HOME:REST": "fresh WING_HOME with weeks-1 and stamina recovery",
}


@dataclass(frozen=True)
class ShadowPrediction:
    frame_id: str
    page_state: str
    viewport: dict[str, Any]
    detected_control: str | None
    control_box: tuple[float, float, float, float] | None
    preferred_click_point: tuple[float, float] | None
    geometry_status: str
    action_authority: str
    confidence: float
    expected_postcondition: str | None
    would_click: bool
    reason: str
    blockers: tuple[str, ...]
    screenshot_path: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


class PythonShadowClickExecutor:
    """Produces and logs hypothetical click decisions without input injection."""

    def __init__(self, repo_root: Path, *, log_path: Path | None = None):
        self.repo_root = Path(repo_root).resolve()
        migration = self.repo_root / "enza_memory/migration/python_click_migration"
        distilled = migration / "distilled"
        self.control_regions = _load_json(migration / "control_regions.json")
        self.control_matrix = _load_json(distilled / "control_evidence_matrix.json")
        self.readiness = _load_json(distilled / "python_migration_readiness.json")
        self.hazards = _load_json(distilled / "hazard_map.json")
        self.click_samples_path = migration / "click_samples.jsonl"
        if not self.click_samples_path.is_file():
            raise FileNotFoundError(self.click_samples_path)
        default_log = migration / "shadow/shadow_predictions.jsonl"
        self.logger = ShadowPredictionLogger(log_path or default_log)
        self._memory = self._build_memory()

    def _build_memory(self) -> dict[str, dict[str, Any]]:
        memory: dict[str, dict[str, Any]] = {}
        aliases = {"RESULT:ADVANCE_CYCLE": "RESULT:ADVANCE"}
        for item in self.control_regions.get("controls", []):
            key = aliases.get(item.get("control_key"), item.get("control_key"))
            if not isinstance(key, str):
                continue
            point = item.get("preferred_click_point_norm")
            sequence = item.get("preferred_click_point_sequence_norm")
            if isinstance(point, dict) and isinstance(point.get("x"), (int, float)) and isinstance(point.get("y"), (int, float)):
                point = [point["x"], point["y"]]
            if point is None and isinstance(sequence, list) and sequence:
                point = [sequence[0].get("x"), sequence[0].get("y")]
            box = item.get("visual_box_norm")
            if isinstance(box, dict) and all(isinstance(box.get(key), (int, float)) for key in ("x1", "y1", "x2", "y2")):
                box = [box["x1"], box["y1"], box["x2"], box["y2"]]
            memory[key] = {"preferred_point_norm": point,
                           "visual_box_norm": box}
        for item in self.control_matrix.get("controls", []):
            key = f"{item.get('room')}:{item.get('control')}"
            entry = memory.setdefault(key, {})
            known = item.get("known_click_point")
            if entry.get("preferred_point_norm") is None and isinstance(known, dict):
                normalized = known.get("normalized")
                if isinstance(normalized, dict):
                    entry["preferred_point_norm"] = [normalized.get("x"), normalized.get("y")]
                elif isinstance(known.get("sequence"), list) and known["sequence"]:
                    x, y = known["sequence"][0]
                    entry["preferred_point_norm"] = [x / 1280.0, y / 720.0]
        return memory

    def observe(self, frame: Image.Image | Path | str, *, frame_id: str,
                desired_control: str, authority_evidence: Mapping[str, Any] | None = None,
                screenshot_path: str | None = None) -> ShadowPrediction:
        if desired_control not in BUNDLE_A:
            raise ValueError(f"control is outside Bundle A: {desired_control}")
        source_path: str | None = screenshot_path
        if isinstance(frame, (str, Path)):
            source_path = str(Path(frame).resolve())
            image = Image.open(frame).convert("RGB")
        else:
            image = frame.convert("RGB")
        viewport = detect_game_viewport(image)
        evidence = dict(authority_evidence or {})
        if viewport.status != VIEWPORT_KNOWN:
            prediction = ShadowPrediction(
                frame_id, "UNKNOWN", viewport.as_dict(), None, None, None,
                "VIEWPORT_UNKNOWN", "WOULD_NOT_CLICK", 0.0,
                EXPECTED_POSTCONDITIONS.get(desired_control), False,
                "VIEWPORT_UNKNOWN", (viewport.reason,), source_path,
            )
            self.logger.append(self._log_record(prediction))
            return prediction
        game = crop_game_viewport(image, viewport)
        assert game is not None
        page = detect_page_state(game)
        control = detect_control(game, page, desired_control, self._memory.get(desired_control, {}))
        hazards = assess_hazards(
            control.preferred_point_norm, page.state, self.hazards,
            overlay_present=evidence.get("overlay_present") is True,
            overlap_detected=evidence.get("control_overlap") is True,
        )
        authority = authorize_action(page, control, evidence, hazards)
        confidence = min(viewport.confidence, page.confidence, control.confidence)
        prediction = ShadowPrediction(
            frame_id, page.state, viewport.as_dict(),
            control.control if control.detected else None,
            control.box_norm, control.preferred_point_norm, control.geometry_status,
            "AUTHORIZED" if authority.authorized else "NOT_AUTHORIZED",
            round(confidence, 4), EXPECTED_POSTCONDITIONS.get(desired_control),
            authority.authorized, authority.reason, authority.blockers, source_path,
        )
        self.logger.append(self._log_record(prediction))
        return prediction

    def observe_skill_board(self, frame: Image.Image | Path | str, *,
                            current_sp_override: int | None = None) -> SkillBoardObservation:
        """Expose recovered-frame board perception without adding click authority."""
        return observe_skill_board(frame, current_sp_override=current_sp_override)

    @staticmethod
    def plan_skill_action(observation: SkillBoardObservation, *,
                          allowed_zones: tuple[str, ...],
                          policy_authorized_node_ids: tuple[str, ...]) -> SkillActionPlan:
        return plan_skill_action(
            observation, allowed_zones=allowed_zones,
            policy_authorized_node_ids=policy_authorized_node_ids,
        )

    @staticmethod
    def _log_record(prediction: ShadowPrediction) -> dict[str, Any]:
        return {
            "frame_id": prediction.frame_id,
            "state": prediction.page_state,
            "predicted_control": prediction.detected_control,
            "predicted_box": prediction.control_box,
            "predicted_point": prediction.preferred_click_point,
            "confidence": prediction.confidence,
            "would_click": prediction.would_click,
            "reason": prediction.reason,
            "blockers": prediction.blockers,
            "viewport": prediction.viewport,
        }
