import unittest

from home_observation import HomeObservation
from home_policy import decide_home, required_observation_fields, resolve_policy_state


class RuntimeDecisionBoundaryTests(unittest.TestCase):
    def test_normal_s1_declares_only_minimal_fields_and_vocal(self):
        self.assertEqual(required_observation_fields(season=1, weeks_remaining=4), ("season", "weeks_remaining"))
        state = resolve_policy_state(season=1, weeks_remaining=4)
        state["vocal_failure_rate_observation"] = {"value": 0, "status": "KNOWN", "fresh": True}
        d = decide_home(HomeObservation(1, 4, None), state, {})
        self.assertEqual((d.status, d.action), ("DECISION", "VOCAL"))

    def test_final_s1_missing_gap_requests_fresh_observation(self):
        self.assertEqual(required_observation_fields(season=1, weeks_remaining=1), ("season", "weeks_remaining", "fan_gap_to_target"))
        d = decide_home(HomeObservation(1, 1, None), resolve_policy_state(season=1, weeks_remaining=1), {})
        self.assertEqual(d.status, "NEED_MORE_OBSERVATION")
        self.assertEqual(d.required_fields, ("fan_gap_to_target",))

    def test_stale_gap_cannot_satisfy_final_boundary(self):
        state = resolve_policy_state(season=1, weeks_remaining=1)
        state["fresh_fields"] = {"season", "weeks_remaining"}
        d = decide_home(HomeObservation(1, 1, 0), state, {})
        self.assertEqual(d.status, "NEED_MORE_OBSERVATION")
        self.assertEqual(d.required_fields, ("fan_gap_to_target",))

    def test_final_s1_gap_branches(self):
        state = resolve_policy_state(season=1, weeks_remaining=1)
        state["vocal_failure_rate_observation"] = {"value": 0, "status": "KNOWN", "fresh": True}
        self.assertEqual(decide_home(HomeObservation(1, 1, 0), state, {}).action, "VOCAL")
        self.assertEqual(decide_home(HomeObservation(1, 1, 300), state, {}).action, "NEEDS_VOCAL_FAN_GAIN")
        self.assertEqual(decide_home(HomeObservation(1, 1, 301), state, {}).action, "AUDITION")

    def test_boundary_is_recomputed_after_season_transition(self):
        self.assertFalse(resolve_policy_state(season=1, weeks_remaining=2)["season1_final_actionable_week"])
        self.assertTrue(resolve_policy_state(season=1, weeks_remaining=1)["season1_final_actionable_week"])
        self.assertNotIn("season1_final_actionable_week", resolve_policy_state(season=2, weeks_remaining=1))

    def test_decision_contract_serializes_need_more_observation(self):
        d = decide_home(HomeObservation(1, 1, None), resolve_policy_state(season=1, weeks_remaining=1), {})
        self.assertEqual(d.as_dict(), {"status":"NEED_MORE_OBSERVATION", "decision":None,
                                       "required_fields":["fan_gap_to_target"],
                                       "reason_code":"fan_gap_required_at_s1_final_boundary"})


if __name__ == "__main__":
    unittest.main()
