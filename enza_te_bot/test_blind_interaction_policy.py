import unittest

from blind_interaction_policy import (
    DIALOGUE_NEUTRAL_ZONE,
    ROOM_PROFILES,
    BlindInteractionPolicy,
    ChoiceFingerprint,
    FastPathSkill,
    FastPathSkillRegistry,
    InteractionDecision,
    ProbeValue,
    RiskLevel,
    RoomProfile,
    audition_pre_battle_sequence,
    dialogue_burst,
    next_escalation,
    resolve_choice,
    resolve_random_event,
    transition_mask,
)


class RoomProfileTest(unittest.TestCase):
    def test_dialogue_burst_uses_only_taught_center_neutral_zone(self):
        plan = dialogue_burst(ROOM_PROFILES["DIALOGUE"], steps=4)
        self.assertEqual(plan.decision, InteractionDecision.EXECUTE)
        self.assertEqual(plan.target, DIALOGUE_NEUTRAL_ZONE)

    def test_home_business_region_cannot_be_neutral_burst(self):
        self.assertIsNone(ROOM_PROFILES["HOME"].neutral_click_zone)
        with self.assertRaises(ValueError):
            RoomProfile("HOME", "v0.1", ("HOME",), (), ("VOCAL",), (640, 650), (),
                        ("CENTER_TAP",), 1, 1000, "STOP", RiskLevel.LOW)

    def test_schedule_requires_current_tab_probe(self):
        profile = ROOM_PROFILES["SCHEDULE"]
        self.assertIn("schedule_current_tab_roi", profile.roi_probes)
        result = BlindInteractionPolicy().gate(
            room="SCHEDULE", current_room="SCHEDULE", action="VOCAL", risk=RiskLevel.MEDIUM,
            probes={},
        )
        self.assertEqual(result.decision, InteractionDecision.PROBE)


class TransitionAndRiskTest(unittest.TestCase):
    def test_transition_mask_is_wait_not_failure(self):
        plan = transition_mask(mask_visible=True, elapsed_ms=350, p95_transition_ms=900)
        self.assertEqual(plan.decision, InteractionDecision.WAIT)
        self.assertFalse(plan.retry_allowed)
        self.assertGreaterEqual(plan.wait_ms, 300)
        self.assertLessEqual(plan.wait_ms, 500)

    def test_high_action_single_roi_mismatch_is_not_retried(self):
        plan = BlindInteractionPolicy().gate(
            room="SCHEDULE", current_room="SCHEDULE", action="KETTEI", risk=RiskLevel.HIGH,
            probes={"schedule_current_tab_roi": ProbeValue.FALSE},
        )
        self.assertEqual(plan.decision, InteractionDecision.STOP)
        self.assertEqual(plan.reason, "ROI_PRECONDITION_MISMATCH")
        self.assertFalse(plan.retry_allowed)


class ChoiceAndSequenceTest(unittest.TestCase):
    def test_known_three_choice_selects_middle(self):
        plan = resolve_choice(fingerprint_id="MORNING_3CHOICE_GREEN_V1", option_count=3)
        self.assertEqual(plan.decision, InteractionDecision.EXECUTE)
        self.assertEqual(plan.action, "OPTION_2")

    def test_unknown_choice_escalates_only_cropped_roi(self):
        plan = resolve_choice(fingerprint_id="new-layout", option_count=3)
        self.assertEqual(plan.decision, InteractionDecision.ESCALATE_CROPPED_ROI)
        self.assertNotEqual(plan.decision, InteractionDecision.ESCALATE_FULL_VISION)

    def test_skip_only_random_event_uses_local_skip(self):
        plan = resolve_random_event(choice_panel=ProbeValue.FALSE, skip_visible=ProbeValue.TRUE)
        self.assertEqual((plan.decision, plan.action), (InteractionDecision.EXECUTE, "SKIP"))

    def test_custom_known_fingerprint_is_data_not_planner_logic(self):
        registry = {"known": ChoiceFingerprint("known", 3, 2)}
        self.assertEqual(resolve_choice(fingerprint_id="known", option_count=3,
                                        registry=registry).action, "OPTION_2")

    def test_audition_fixed_prebattle_sequence_ends_in_cheap_probe(self):
        steps = audition_pre_battle_sequence(
            target_marker_confirmed=True,
            choice_fingerprint_id="AUDITION_2CHOICE_IIYO_GOMEN_V1",
            option_count=2,
        )
        self.assertIsInstance(steps, tuple)
        self.assertEqual(steps[-1].verification_probe, "battle_input_ready_roi")
        self.assertEqual([step.target for step in steps if step.kind == "DIALOGUE_BURST"],
                         [DIALOGUE_NEUTRAL_ZONE, DIALOGUE_NEUTRAL_ZONE])


class FastPathRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = FastPathSkillRegistry([
            FastPathSkill("s1", "DIALOGUE", "DIALOGUE->HOME",
                          verification_method="home_topbar_roi")
        ])

    def test_three_consecutive_successes_make_skill_eligible(self):
        for index in range(3):
            skill = self.registry.record_success("s1", duration_ms=100 + index,
                                                 verified_at=f"t{index}")
        self.assertTrue(skill.fast_path_eligible)
        self.assertEqual(skill.success_count, 3)
        self.assertIsNotNone(skill.p95_ms)

    def test_deviation_immediately_demotes(self):
        for index in range(3):
            self.registry.record_success("s1", duration_ms=100, verified_at=f"t{index}")
        skill = self.registry.record_deviation("s1", verified_at="deviation")
        self.assertFalse(skill.fast_path_eligible)
        self.assertEqual(skill.consecutive_successes, 0)

    def test_unknown_escalation_finally_stops(self):
        level = "BLIND_KNOWN_SKILL"
        for _ in range(10):
            level = next_escalation(level, resolved=False)
        self.assertEqual(level, "UNKNOWN_STOP")


if __name__ == "__main__":
    unittest.main()
