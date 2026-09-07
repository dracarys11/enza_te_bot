from __future__ import annotations

import json
import ast
from pathlib import Path

import numpy as np
from PIL import Image

from shadow_executor.authority import assess_hazards
from shadow_executor.detectors import detect_auto_state, detect_input_ready
from shadow_executor.executor import BUNDLE_A, PythonShadowClickExecutor
from shadow_executor.viewport import VIEWPORT_KNOWN, VIEWPORT_UNKNOWN, detect_game_viewport


ROOT = Path(__file__).resolve().parent
HOME = ROOT / "enza_memory/wing_runs/WINGVAL_20260905_01/screenshots/v0_state_check.png"
SCHEDULE = ROOT / "enza_memory/wing_runs/WINGVAL_20260905_01/screenshots/vA_schedule_guard.png"
RESULT = ROOT / "enza_memory/wing_runs/WINGVAL_20260905_01/screenshots/vA_after_confirm.png"
CHOICE = ROOT / "enza_memory/wing_runs/WINGRUN_20260905_01/screenshots/wk6_choice_options.png"
DIALOGUE = ROOT / "enza_memory/wing_runs/WINGRUN_20260905_01/screenshots/wk5_dialogue_textbox_click.png"


def executor(tmp_path: Path) -> PythonShadowClickExecutor:
    return PythonShadowClickExecutor(ROOT, log_path=tmp_path / "shadow_predictions.jsonl")


def test_viewport_exact_frame_is_freshly_calibrated():
    result = detect_game_viewport(Image.open(HOME))
    assert result.status == VIEWPORT_KNOWN
    assert (result.game_left, result.game_top, result.game_width, result.game_height) == (0, 0, 1280, 720)
    assert result.viewport_profile_id == "MAC_CURRENT_V1"
    assert result.normalized_mapping is not None


def test_viewport_detector_does_not_assume_zero_origin():
    frame = Image.open(HOME).convert("RGB")
    screen = Image.new("RGB", (1600, 1000), (8, 8, 8))
    screen.paste(frame, (123, 141))
    result = detect_game_viewport(screen)
    assert result.status == VIEWPORT_KNOWN
    assert abs(result.game_left - 123) <= 2
    assert abs(result.game_top - 141) <= 2
    assert abs(result.game_width - 1280) <= 3
    assert abs(result.game_height - 720) <= 3


def test_viewport_unknown_fails_closed():
    uniform = Image.fromarray(np.zeros((700, 1100, 3), dtype=np.uint8))
    assert detect_game_viewport(uniform).status == VIEWPORT_UNKNOWN


def test_home_schedule_uses_reverified_memory_box_without_clicking(tmp_path):
    prediction = executor(tmp_path).observe(
        HOME, frame_id="home-1", desired_control="HOME:SCHEDULE",
        authority_evidence={"fresh": True, "policy_authorized": True},
    )
    assert prediction.page_state == "HOME"
    assert prediction.detected_control == "HOME:SCHEDULE"
    assert prediction.control_box is not None
    assert prediction.geometry_status == "FRESH_ANCHOR_VERIFIED_MEMORY_BOX"
    assert prediction.would_click is True


def test_schedule_vocal_visual_detection_and_authority_are_separate(tmp_path):
    runner = executor(tmp_path)
    allowed = runner.observe(
        SCHEDULE, frame_id="schedule-1", desired_control="SCHEDULE:VOCAL",
        authority_evidence={"fresh": True, "policy_authorized": True,
                            "failure_rate_fresh": True, "failure_rate_percent": 1},
    )
    assert allowed.detected_control == "SCHEDULE:VOCAL"
    assert allowed.control_box is not None
    assert allowed.would_click is True
    blocked = runner.observe(
        SCHEDULE, frame_id="schedule-2", desired_control="SCHEDULE:VOCAL",
        authority_evidence={"fresh": True, "policy_authorized": True,
                            "failure_rate_fresh": True, "failure_rate_percent": 27},
    )
    assert blocked.detected_control == "SCHEDULE:VOCAL"
    assert blocked.would_click is False
    assert "FAILURE_RATE_ABOVE_AUTHORIZED_THRESHOLD" in blocked.blockers


def test_result_advance_detected_but_boxless_geometry_fails_closed(tmp_path):
    prediction = executor(tmp_path).observe(
        RESULT, frame_id="result-1", desired_control="RESULT:ADVANCE",
        authority_evidence={"fresh": True, "policy_authorized": True, "result_committed": True},
    )
    assert prediction.page_state == "RESULT"
    assert prediction.detected_control == "RESULT:ADVANCE"
    assert prediction.control_box is None
    assert prediction.would_click is False
    assert "GEOMETRY_INCOMPLETE" in prediction.blockers


def test_three_choice_middle_gets_fresh_box_and_shadow_authority(tmp_path):
    prediction = executor(tmp_path).observe(
        CHOICE, frame_id="choice-1", desired_control="DIALOGUE:3_CHOICE_MIDDLE",
        authority_evidence={"fresh": True, "policy_authorized": True, "choice_count": 3},
    )
    assert prediction.page_state == "CHOICE_3"
    assert prediction.control_box is not None
    assert prediction.geometry_status == "FRESH_VISUAL_BOX"
    assert prediction.would_click is True
    left, _, right, _ = prediction.control_box
    assert 0.30 < left < right < 0.70


def test_choice_count_uncertain_blocks_middle(tmp_path):
    prediction = executor(tmp_path).observe(
        CHOICE, frame_id="choice-2", desired_control="DIALOGUE:3_CHOICE_MIDDLE",
        authority_evidence={"fresh": True, "policy_authorized": True, "choice_count": 2},
    )
    assert prediction.would_click is False
    assert "CHOICE_COUNT_NOT_THREE" in prediction.blockers


def test_safe_textbox_is_detected_but_boxless_geometry_stays_closed(tmp_path):
    prediction = executor(tmp_path).observe(
        DIALOGUE, frame_id="dialogue-1", desired_control="DIALOGUE:SAFE_TEXTBOX",
        authority_evidence={"fresh": True, "policy_authorized": True,
                            "dialogue_fresh": True, "choice_count": 0},
    )
    assert prediction.page_state == "DIALOGUE"
    assert prediction.detected_control == "DIALOGUE:SAFE_TEXTBOX"
    assert prediction.would_click is False
    assert "GEOMETRY_INCOMPLETE" in prediction.blockers


def test_known_home_furikaeri_region_is_hazard(tmp_path):
    runner = executor(tmp_path)
    blockers = assess_hazards((0.1602, 0.9097), "HOME", runner.hazards,
                              overlay_present=False, overlap_detected=False)
    assert any("WRONG_TARGET" in blocker for blocker in blockers)


def test_known_schedule_support_skill_region_is_hazard(tmp_path):
    runner = executor(tmp_path)
    blockers = assess_hazards((0.7695, 0.9208), "SCHEDULE", runner.hazards,
                              overlay_present=False, overlap_detected=False)
    assert any("WRONG_TARGET" in blocker for blocker in blockers)


def test_overlay_blocks_otherwise_authorized_control(tmp_path):
    prediction = executor(tmp_path).observe(
        HOME, frame_id="home-overlay", desired_control="HOME:SCHEDULE",
        authority_evidence={"fresh": True, "policy_authorized": True, "overlay_present": True},
    )
    assert prediction.would_click is False
    assert "OVERLAY_PRESENT" in prediction.blockers


def test_shadow_logging_has_required_comparison_fields(tmp_path):
    runner = executor(tmp_path)
    runner.observe(HOME, frame_id="log-1", desired_control="HOME:SCHEDULE",
                   authority_evidence={"fresh": True, "policy_authorized": True})
    records = [json.loads(line) for line in (tmp_path / "shadow_predictions.jsonl").read_text().splitlines()]
    assert len(records) == 1
    assert {"frame_id", "state", "predicted_control", "predicted_box",
            "predicted_point", "confidence", "would_click", "reason"} <= records[0].keys()


def test_bundle_a_only_and_auto_interfaces_are_deferred():
    assert "AUDITION_BATTLE:AUTO" not in BUNDLE_A
    frame = Image.open(HOME)
    assert detect_input_ready(frame)["state"] == "UNKNOWN"
    assert detect_auto_state(frame)["auto_state"] == "AUTO_UNKNOWN"


def test_shadow_package_has_no_input_injection_dependency():
    imported: set[str] = set()
    for path in (ROOT / "shadow_executor").glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
    assert not ({"pyautogui", "pynput", "action_gate", "action_boundary"} & imported)
