"""Detector calibration regressions for the recovered skill-board corpus.

Ground truth comes from recovered_frame_manifest.jsonl and the recovered
visual sequences (RECOVERED_REVIEW_PENDING): frames carry operator-recorded
selection rings, acquisition events, SP readings, and replacement states.
Colour is evidence, never authority: ordinary pink/gold/cyan icon art must
not produce SELECTED/ACQUIRED claims, and locked misclick frames
(live_csm_020..023 / rf_sb_g1..g4) must fail closed even with full policy
authorization offered.
"""
from __future__ import annotations

from pathlib import Path

from shadow_executor.skill_board import (evaluate_sp, observe_replacement,
                                          observe_skill_board, plan_skill_action)


ROOT = Path(__file__).resolve().parent
FRAMES = ROOT / "enza_memory/migration/python_click_migration/recovered_frames"


def board(frame: str):
    return observe_skill_board(FRAMES / frame)


def replacement(frame: str):
    return observe_replacement(FRAMES / frame)


def node_near(observation, cx: float, cy: float, tolerance: float = 0.04):
    """Match by normalized center; crop frames keep their local geometry."""
    return [node for node in observation.nodes
            if abs(node.center_norm[0] - cx) <= tolerance
            and abs(node.center_norm[1] - cy) <= tolerance]


# ---------------------------------------------------------------- SELECTED

def test_pink_skill_icon_is_not_selected():
    # Vocal-owned nodes carry pink circular icon badges (magenta border share
    # 0.2-0.34 at ~41px); they are icon art, not selection rings.
    for frame in ("skill_board/rf_sb_f6_right_chain_sp23.png",
                  "skill_board/rf_sb_a1_board_entry_sp548.png",
                  "skill_board/rf_sb_c2_locked_panel_gold.png"):
        observation = board(frame)
        selected = [node for node in observation.nodes if node.visual_state == "SELECTED"]
        assert selected == [], (frame, [(n.node_id, n.visual_features) for n in selected])
    f6 = board("skill_board/rf_sb_f6_right_chain_sp23.png")
    for cx, cy in ((582 / 1280, 50 / 720), (582 / 1280, 118 / 720), (698 / 1280, 456 / 720)):
        for node in node_near(f6, cx, cy):
            assert node.visual_state != "SELECTED", (cx, cy, node.visual_features)


def test_selection_ring_positives_detected_once_at_recorded_geometry():
    cases = (
        # (frame, normalized center of the recorded ring; crop frames keep
        # local normalized geometry, e.g. e1 is a 660x300 crop)
        ("skill_board/rf_sb_e2_pink_ring_selected.png", 935 / 1280, 325 / 720),
        ("replacement/rf_rp_t4_pending_ring.png", 699 / 1280, 462 / 720),
        ("skill_board/rf_sb_e1_operator_selected_ctx.png", 0.792, 0.48),
        ("skill_board/rf_sb_g1_misclick_590_145.png", 0.702, 0.191),
    )
    for frame, cx, cy in cases:
        observation = board(frame)
        selected = [node for node in observation.nodes if node.visual_state == "SELECTED"]
        assert len(selected) == 1, (frame, len(selected))
        assert node_near(observation, cx, cy), (frame, cx, cy)


def test_ring_moved_misclick_selection_is_visual_only():
    # g1 (live_csm_020): the ring moved onto a locked node — visual SELECTED
    # must not become a mechanically available purchase candidate.
    observation = board("skill_board/rf_sb_g1_misclick_590_145.png")
    assert observation.selected_node_id is not None
    selected = next(node for node in observation.nodes
                    if node.node_id == observation.selected_node_id)
    assert selected.mechanical_state == "UNKNOWN"
    plan = plan_skill_action(observation, allowed_zones=("LEFT_BLOCK", "RIGHT_BLOCK", "CENTER"),
                             policy_authorized_node_ids=[selected.node_id])
    assert plan.decision == "NO_ACTION" and plan.reason == "FAIL_CLOSED"


# --------------------------------------------------------------- ACQUIRED

def test_gold_and_bright_yellow_are_not_acquired():
    # gold colouring = node type, NOT ownership; bright yellow SP:0 ownership
    # needs dedicated evidence and must not be claimed from colour alone.
    for frame in ("skill_board/rf_sb_c2_locked_panel_gold.png",
                  "skill_board/rf_sb_b1b_lefttop_white_avail.png",
                  "skill_board/rf_sb_d1_acquired_first_sp538.png"):
        observation = board(frame)
        acquired = [node for node in observation.nodes if node.visual_state == "ACQUIRED"]
        assert acquired == [], (frame, [(n.node_id, n.visual_features) for n in acquired])


def test_solid_cyan_ui_chips_outside_board_are_not_acquired():
    for frame in ("dialogue/rf_dl_skip_story_audition_fail.png",
                  "dialogue/rf_dl_afsoushi_rest.png",
                  "event_choice/rf_ec1_three_choice_present.png"):
        observation = board(frame)
        acquired = [node for node in observation.nodes if node.visual_state == "ACQUIRED"]
        assert acquired == [], (frame, [(n.node_id, n.visual_features) for n in acquired])
        assert observation.room_state != "FURIKAERI_SKILL"


def test_cyan_state_ring_positive_is_retained():
    # Vocal220%-chain owned node at (524,153): cyan border ring with a hollow
    # core — the one recovered ACQUIRED positive the detector must keep.
    observation = board("replacement/rf_rp_t2_post_commit.png")
    hits = [node for node in node_near(observation, 524 / 1280, 153 / 720)
            if node.visual_state == "ACQUIRED"]
    assert len(hits) == 1 and hits[0].mechanical_state == "ACQUIRED"


# --------------------------------------------------------------------- SP

def test_sp23_below_required45_regression():
    chain_end = board("skill_board/rf_sb_f6_right_chain_sp23.png")
    assert chain_end.current_sp == 23
    insufficient = board("skill_board/rf_sb_j_sp_insufficient.png")
    assert insufficient.required_sp == 45
    assert evaluate_sp(23, 45) == "INSUFFICIENT_SP"
    stalled = observe_skill_board(FRAMES / "skill_board/rf_sb_j_sp_insufficient.png",
                                  current_sp_override=23)
    assert stalled.purchase_state == "INSUFFICIENT_SP"
    plan = plan_skill_action(stalled, allowed_zones=("LEFT_BLOCK", "RIGHT_BLOCK", "CENTER"),
                             policy_authorized_node_ids=[node.node_id for node in stalled.nodes])
    assert plan.decision == "NO_ACTION" and "INSUFFICIENT_SP" in plan.blockers


def test_full_frame_sp_counter_readings_match_recorded_values():
    recorded = {
        "skill_board/rf_sb_a1_board_entry_sp548.png": 548,
        "skill_board/rf_sb_d1_acquired_first_sp538.png": 538,
        "skill_board/rf_sb_d2_white_glow_after_buy.png": 253,
        "skill_board/rf_sb_e2_pink_ring_selected.png": 268,
        "skill_board/rf_sb_f4_after_second_right_buy.png": 228,
        "skill_board/rf_sb_f6_right_chain_sp23.png": 23,
        "replacement/rf_rp_t1_post_commit.png": 308,
        "replacement/rf_rp_t2_post_commit.png": 268,
        "replacement/rf_rp_t4_pending_ring.png": 203,
    }
    for frame, expected in recorded.items():
        assert board(frame).current_sp == expected, frame


# ------------------------------------------------------------ REPLACEMENT

def test_replacement_states_match_recovered_transactions():
    expected = {
        "replacement/rf_rp_t1_confirm_dialog.png": "CONFIRM_DIALOG",
        "replacement/rf_rp_t2_confirm_dialog.png": "CONFIRM_DIALOG",
        "replacement/rf_rp_t2_slot_list.png": "SLOT_LIST",
        "replacement/rf_rp_t2_slot_list_preselect.png": "SLOT_LIST",
        "replacement/rf_rp_t3_slot_list.png": "SLOT_LIST",
        "replacement/rf_rp_t4_slot_list.png": "SLOT_LIST",
        "replacement/rf_rp_t1_post_commit.png": "POST_COMMIT_BOARD",
        "replacement/rf_rp_t2_post_commit.png": "POST_COMMIT_BOARD",
        "replacement/rf_rp_t4_pending_ring.png": "PENDING_SELECTION_RING",
    }
    for frame, state in expected.items():
        assert replacement(frame).state == state, frame


def test_replacement_states_do_not_fire_outside_replacement_room():
    for frame in ("dialogue/rf_dl_skip_story_audition_fail.png",
                  "event_choice/rf_ec1_three_choice_present.png",
                  "skill_board/rf_sb_acquire_confirm_dialog.png",
                  "skill_board/rf_sb_a1_board_entry_sp548.png"):
        assert replacement(frame).state not in {"SLOT_LIST", "CONFIRM_DIALOG"}, frame


# ------------------------------------------------- live_csm_020..023 gate

def test_locked_misclick_frames_fail_closed_even_when_policy_authorizes():
    # rf_sb_g1..g4 (live_csm_020..023): even offering full zone permission,
    # every node id as policy-authorized, and abundant SP, no purchase target
    # may be produced.
    zones = ("LEFT_BLOCK", "RIGHT_BLOCK", "CENTER", "OTHER")
    for frame in ("skill_board/rf_sb_g1_misclick_590_145.png",
                  "skill_board/rf_sb_g2_misclick_585_200.png",
                  "skill_board/rf_sb_g3_misclick_465_115.png",
                  "skill_board/rf_sb_g4_misclick_645_205.png"):
        observation = observe_skill_board(FRAMES / frame, current_sp_override=9999)
        plan = plan_skill_action(observation, allowed_zones=zones,
                                 policy_authorized_node_ids=[node.node_id for node in observation.nodes])
        assert plan.decision == "NO_ACTION", frame
        assert plan.reason == "FAIL_CLOSED", frame
        assert plan.blockers, frame
