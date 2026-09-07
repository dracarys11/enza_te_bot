"""Offline table tests for the v1 HOME policy diagnostic."""
import unittest

from home_observation import HomeObservation
from home_policy import decide_home


class HomePolicyTest(unittest.TestCase):
    FRESH_STAMINA = {
        "stamina_observation": {"ratio": 0.80, "fresh": True},
        "vocal_failure_rate_observation": {"value": 0, "status": "KNOWN", "fresh": True},
    }

    def decide(self, season: int, weeks: int, gap: int, state: dict | None = None, config: dict | None = None):
        merged = dict(self.FRESH_STAMINA)
        if state:
            merged.update(state)
        return decide_home(HomeObservation(season, weeks, gap), merged, config or {})

    def test_season_two_before_final_week_is_default_vocal_without_fan_count_inference(self) -> None:
        decision = self.decide(2, 6, 6721)
        self.assertEqual((decision.action, decision.reason), ("VOCAL", "season_2_default_vocal"))

    def test_season_two_final_week_with_target_met_is_vocal(self) -> None:
        decision = self.decide(2, 1, 0)
        self.assertEqual((decision.action, decision.reason), ("VOCAL", "season_2_target_already_met"))

    def test_season_two_final_week_with_positive_fan_gap_is_audition(self) -> None:
        decision = self.decide(2, 1, 1225)
        self.assertEqual((decision.action, decision.reason), ("AUDITION", "season_2_final_week_fan_gap"))

    def test_season_one_default_is_vocal(self) -> None:
        self.assertEqual(self.decide(1, 4, 900).action, "VOCAL")

    def test_season_one_final_week_gap_met_is_vocal(self) -> None:
        self.assertEqual(self.decide(1, 1, 0, {"season1_final_actionable_week": True}).action, "VOCAL")

    def test_season_one_final_week_large_gap_requires_audition(self) -> None:
        self.assertEqual(self.decide(1, 1, 301, {"season1_final_actionable_week": True}).action, "AUDITION")

    def test_season_one_final_week_small_gap_requires_missing_evidence(self) -> None:
        self.assertEqual(self.decide(1, 1, 300, {"season1_final_actionable_week": True}).action, "NEEDS_VOCAL_FAN_GAIN")

    def test_later_seasons_require_explicit_route_state(self) -> None:
        self.assertEqual(self.decide(3, 6, 0).action, "AUDITION")
        self.assertEqual(self.decide(4, 6, 0).action, "ROUTE_STATE_REQUIRED")

    def test_season_three_40k_and_50k_milestones(self):
        decision = self.decide(3, 3, 31225, config={"run_state": {"season3": {}}})
        self.assertEqual((decision.action, decision.target_tier), ("AUDITION", 40000))
        self.assertEqual(self.decide(3, 3, 31225, config={"run_state": {"season3": {"audition_40k_completed": True}}}).action, "NEED_MORE_OBSERVATION")
        self.assertEqual(self.decide(3, 3, 0, config={"run_state": {"season3": {"audition_40k_completed": True}}}).target_tier, 50000)
        self.assertEqual(self.decide(3, 3, 0, config={"run_state": {"season3": {"audition_40k_completed": True, "audition_50k_completed": True}}}).action, "VOCAL")

    def test_season_three_low_stamina_alone_does_not_force_rest(self) -> None:
        config = {"run_state": {"season3": {"audition_40k_completed": True, "audition_50k_completed": True}}}
        low_stamina = HomeObservation(3, 3, 0, fan_target_achieved=True, stamina_adequate=False)
        warning_only = {"stamina_observation": {"ratio": 0.49, "fresh": True}}
        decision = decide_home(low_stamina, warning_only, config)
        self.assertEqual(decision.action, "NEED_MORE_OBSERVATION")
        self.assertIn("LOW_STAMINA_WARNING", decision.reason)

        allowed = dict(warning_only)
        allowed["vocal_failure_rate_observation"] = {"value": 0, "status": "KNOWN", "fresh": True}
        self.assertEqual(decide_home(low_stamina, allowed, config).action, "VOCAL")

    def test_planner_objective_is_not_replaced_by_vocal_risk_authorization(self) -> None:
        # WINGRUN_20260906_01 had failure_rate=0: that mechanically permits a
        # selected VOCAL objective, but cannot choose VOCAL for the planner.
        state = {
            "stamina_observation": {"ratio": 0.49, "fresh": True},
            "vocal_failure_rate_observation": {"value": 0, "status": "KNOWN", "fresh": True},
        }
        decision = decide_home(
            HomeObservation(3, 3, 31225, stamina_adequate=False), state,
            {"run_state": {"season3": {}}},
        )
        self.assertEqual((decision.action, decision.target_tier), ("AUDITION", 40000))


class VocalRiskGuardTest(unittest.TestCase):
    def decide(self, ratio=None, fr=None, state=None):
        merged = {}
        if ratio is not None:
            merged["stamina_observation"] = {"ratio": ratio, "fresh": True}
        if fr is not None:
            merged["vocal_failure_rate_observation"] = fr
        if state:
            merged.update(state)
        return decide_home(HomeObservation(2, 6, 6721), merged, {})

    def test_low_stamina_alone_is_warning_not_rest(self) -> None:
        d = self.decide(0.49)
        self.assertEqual(d.action, "NEED_MORE_OBSERVATION")
        self.assertIn("LOW_STAMINA_WARNING", d.reason)

    def test_low_stamina_with_low_failure_rate_allows_vocal(self) -> None:
        d = self.decide(0.49, fr={"value": 1, "status": "KNOWN", "fresh": True})
        self.assertEqual(d.action, "VOCAL")

    def test_high_failure_rate_forces_rest_even_with_good_stamina(self) -> None:
        d = self.decide(0.70, fr={"value": 4, "status": "KNOWN", "fresh": True})
        self.assertEqual(d.action, "REST")
        self.assertIn("VOCAL_FAILURE_RATE_EXCEEDED", d.reason)
        self.assertIn("BACK_TO_REST", d.reason)

    def test_vocal_requires_failure_read_even_with_adequate_stamina(self) -> None:
        decision = self.decide(0.80)
        self.assertEqual((decision.action, decision.reason),
                         ("NEED_MORE_OBSERVATION", "FAILURE_RATE_READ_REQUIRED"))

    def test_unknown_failure_rate_with_low_stamina_fails_closed(self) -> None:
        d = self.decide(0.49, fr={"value": None, "status": "UNKNOWN", "fresh": True})
        self.assertEqual(d.action, "REST")
        self.assertIn("FAILURE_RATE_UNKNOWN_FAIL_CLOSED", d.reason)

    def test_unknown_failure_rate_with_good_stamina_needs_escalation(self) -> None:
        d = self.decide(0.70, fr={"value": None, "status": "AMBIGUOUS", "fresh": True})
        self.assertEqual((d.action, d.reason), ("NEED_MORE_OBSERVATION", "FAILURE_RATE_UNKNOWN_ESCALATION_REQUIRED"))

    def test_stale_failure_rate_observation_is_rejected(self) -> None:
        d = self.decide(0.49, fr={"value": 0, "status": "KNOWN", "fresh": False})
        self.assertEqual(d.action, "REST")  # low stamina + rejected read → fail closed

    def test_guard_does_not_touch_non_vocal_decisions(self) -> None:
        merged = {"stamina_observation": {"ratio": 0.10, "fresh": True}}
        d = decide_home(HomeObservation(2, 1, 1225), merged, {})
        self.assertEqual(d.action, "AUDITION")

    def test_config_memory_cannot_satisfy_guard(self) -> None:
        d = decide_home(HomeObservation(2, 6, 6721), {}, {"run_state": {"vocal_failure_rate": 0}})
        self.assertEqual((d.action, d.reason),
                         ("NEED_MORE_OBSERVATION", "FAILURE_RATE_READ_REQUIRED"))


if __name__ == "__main__":
    unittest.main()


class S3FutilityRegressionTests(unittest.TestCase):
    def decide(self, weeks=4, gap=31744, gain=1000, rate=0, **extra):
        state = {
            "season3": {"audition_40k_completed": True},
            "vocal_failure_rate_observation": {"value": rate, "status": "KNOWN", "fresh": True},
            "vocal_fan_gain_projection": {"max_gain_per_week": gain, "fresh": True,
                                          "season": 3, "as_of_weeks_remaining": weeks},
        }
        state.update(extra)
        return decide_home(HomeObservation(3, weeks, gap), state, {})

    def test_safe_rate_alone_cannot_select_vocal(self):
        for rate in (0, 1, 2):
            with self.subTest(rate=rate):
                d = self.decide(rate=rate, vocal_fan_gain_projection=None)
                self.assertEqual(d.status, "NEED_MORE_OBSERVATION")
                self.assertEqual(d.reason, "S3_FAN_GAIN_PROJECTION_REQUIRED")

    def test_safe_vocal_rejected_when_unlock_route_is_infeasible(self):
        # Four training weeks could close this gap, but the required audition
        # must still have its own week after unlocking.
        d = self.decide(gap=3500)
        self.assertIn("ENDGAME_FUTILE", d.reason)
        self.assertIsNone(d.as_dict()["decision"])

    def test_wingrun_20260906_01_repeated_safe_vocal_cannot_silently_exhaust_s3(self):
        for weeks, fans in ((4, 18256), (3, 19360), (2, 20464), (1, 21568), (0, 22672)):
            with self.subTest(weeks=weeks, fans=fans):
                d = self.decide(weeks=weeks, gap=50000-fans, gain=1104)
                self.assertIn("ENDGAME_FUTILE", d.reason)
                self.assertNotEqual(d.action, "VOCAL")
                self.assertEqual(d.status, "NEED_MORE_OBSERVATION")

    def test_reachable_projection_and_exact_boundary_preserve_route(self):
        for gap in (6525, 7500):
            self.assertEqual(self.decide(gap=gap, gain=2500).action, "VOCAL")
        self.assertEqual(self.decide(weeks=1, gap=0).target_tier, 50000)

    def test_projection_requires_current_evidence(self):
        for patch in ({"fresh": False}, {"season": 2}, {"as_of_weeks_remaining": 5},
                      {"max_gain_per_week": None}, {"max_gain_per_week": -1},
                      {"max_gain_per_week": True}):
            projection = {"fresh": True, "season": 3, "as_of_weeks_remaining": 4,
                          "max_gain_per_week": 100000}
            projection.update(patch)
            self.assertEqual(self.decide(vocal_fan_gain_projection=projection).reason,
                             "S3_FAN_GAIN_PROJECTION_REQUIRED")

    def test_explicit_route_capacity_is_reused(self):
        d = self.decide(gap=2500, route_deadline={
            "fresh": True, "season": 3, "as_of_weeks_remaining": 4,
            "mandatory_steps": 1, "retry_budget": 1, "transition_margin": 0,
            "next_route_action": "AUDITION", "next_route_target_tier": 50000})
        self.assertIn("ENDGAME_FUTILE", d.reason)

    def test_planner_and_risk_reasons_survive_allow_and_block(self):
        for rate, action, risk in ((0, "VOCAL", "ALLOW"), (4, "REST", "BLOCK")):
            d = self.decide(gap=1000, rate=rate)
            self.assertEqual(d.action, action)
            self.assertEqual(d.planner_objective, "VOCAL")
            self.assertEqual(d.planner_reason, "season_3_build_to_50k_audition_unlock")
            gate = d.as_dict()["permitting_gates"][0]
            self.assertEqual(gate["risk_decision"], risk)
            self.assertEqual(gate["risk_observation"]["value"], rate)
            self.assertNotEqual(gate["risk_reason"], d.planner_reason)
