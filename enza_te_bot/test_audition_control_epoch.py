import unittest
from audition_control_epoch import *


class EpochTests(unittest.TestCase):
    def setUp(self):
        self.e = ControlEpoch()

    def obs(self, frame, auto=AutoState.UNKNOWN, speed=SpeedState.UNKNOWN):
        return self.e.fresh(frame, auto=auto, speed=speed)

    def test_auto_on_no_click(self):
        self.assertEqual(auto_action(self.obs("f1", AutoState.ON), self.e), ("NOOP", "AUTO_ALREADY_ON"))

    def test_auto_off_one_click_then_verify(self):
        self.assertEqual(auto_action(self.obs("f1", AutoState.OFF), self.e)[0], "CLICK_AUTO")
        self.assertEqual(verify_auto(self.obs("f2", AutoState.ON), self.e), (True, "AUTO_ON_VERIFIED"))

    def test_auto_still_off_stops_and_unknown_reobserve_stops(self):
        auto_action(self.obs("f1", AutoState.OFF), self.e)
        self.assertEqual(verify_auto(self.obs("f2", AutoState.OFF), self.e)[0], False)
        self.assertEqual(auto_action(self.obs("f3", AutoState.UNKNOWN), self.e)[0], "STOP")

    def test_new_epoch_invalidates_all_state(self):
        self.e.auto_state = AutoState.ON; self.e.speed_state = SpeedState.X3
        self.e.current_turn = 2; self.e.selected_card_state = "VOCAL"
        new = new_epoch(self.e)
        self.assertEqual((new.auto_state, new.speed_state, new.current_turn, new.selected_card_state),
                         (AutoState.UNKNOWN, SpeedState.UNKNOWN, None, None))
        self.assertEqual(auto_action(ControlObservation("f", self.e.control_epoch_id, True, AutoState.ON), new)[0], "STOP")

    def test_same_frame_cannot_double_toggle(self):
        auto_action(self.obs("f1", AutoState.OFF), self.e)
        self.assertEqual(auto_action(self.obs("f1", AutoState.OFF), self.e)[0], "STOP")

    def test_pause_owns_frame_and_resume_creates_epoch(self):
        o = self.obs("p1", AutoState.ON, SpeedState.X3)
        self.assertEqual(pause_owner(o, self.e, overlay_visible=True), "PAUSE_OVERLAY")
        resumed, reason = overlay_resume(self.e, "p1")
        self.assertEqual(reason, "FRESH_BATTLE_REQUIRED")
        self.assertNotEqual(resumed.control_epoch_id, self.e.control_epoch_id)
        self.assertEqual(auto_action(resumed.fresh("b1", auto=AutoState.ON), resumed)[0], "NOOP")

    def test_overlay_blocks_other_handlers(self):
        o = self.obs("p1", AutoState.OFF, SpeedState.X2)
        self.assertEqual(pause_owner(o, self.e, overlay_visible=True), "PAUSE_OVERLAY")
        self.assertEqual(auto_action(o, self.e)[0], "STOP")
        self.assertEqual(speed_action(o, self.e)[0], "STOP")

    def test_speed_epoch_rules(self):
        self.assertEqual(speed_action(self.obs("s1", speed=SpeedState.X3), self.e)[0], "HOLD")
        n = new_epoch(self.e)
        self.assertEqual(speed_action(n.fresh("s2", speed=SpeedState.X3), n)[0], "HOLD")
        self.assertEqual(speed_action(n.fresh("s3", speed=SpeedState.X2), n)[0], "HOLD")
        self.assertEqual(speed_action(n.fresh("s4", speed=SpeedState.UNKNOWN), n)[0], "STOP")

    def test_auto_requires_input_ready_and_enabled(self):
        animation = self.e.fresh("a", auto=AutoState.OFF, phase=BattlePhase.ANIMATION,
                                  auto_interactability=AutoInteractability.DISABLED)
        self.assertEqual(auto_action(animation, self.e), ("STOP", "AUTO_INPUT_NOT_READY"))
        unknown = self.e.fresh("u", auto=AutoState.OFF,
                               auto_interactability=AutoInteractability.UNKNOWN)
        self.assertEqual(auto_action(unknown, self.e), ("STOP", "AUTO_CONTROL_NOT_INTERACTABLE"))

    def test_auto_postclick_requires_fresh_on_and_does_not_duplicate(self):
        self.assertEqual(auto_action(self.e.fresh("a", auto=AutoState.OFF), self.e)[0], "CLICK_AUTO")
        self.assertEqual(auto_action(self.e.fresh("b", auto=AutoState.OFF), self.e),
                         ("STOP", "AUTO_POSTCONDITION_REQUIRED"))
        self.assertEqual(verify_auto(self.e.fresh("c", auto=AutoState.ON), self.e),
                         (True, "AUTO_ON_VERIFIED"))

    def test_fresh_off_can_rearm_only_after_postcondition_path_is_reconciled(self):
        self.assertEqual(auto_action(self.e.fresh("a", auto=AutoState.OFF), self.e)[0], "CLICK_AUTO")
        self.assertEqual(verify_auto(self.e.fresh("b", auto=AutoState.OFF), self.e)[0], False)
        self.assertEqual(auto_action(self.e.fresh("c", auto=AutoState.OFF), self.e)[0], "STOP")

    def test_speed_display_without_grounded_authority_holds(self):
        self.assertEqual(speed_action(self.e.fresh("s", speed=SpeedState.X2), self.e),
                         ("HOLD", "SPEED_TOGGLE_UNGROUNDED"))
        grounded = self.e.fresh("g", speed=SpeedState.X2, speed_actionable=True)
        self.assertEqual(speed_action(grounded, self.e)[0], "CLICK_SPEED")

    def test_stale_epoch_rejected(self):
        old = self.obs("x", AutoState.ON)
        n = new_epoch(self.e)
        self.assertEqual(auto_action(old, n)[0], "STOP")

    def test_lifecycle_priority_and_single_owner(self):
        life = BattleControlLifecycle()
        overlay = life.epoch.fresh("p", auto=AutoState.OFF, speed=SpeedState.X2)
        self.assertEqual(life.dispatch(overlay, pause_overlay=True)[0], "PAUSE_RESUME")
        self.assertEqual(life.dispatch(overlay)[0], "STOP")
        life.resume("p")
        fresh = life.epoch.fresh("b", auto=AutoState.OFF, speed=SpeedState.X2)
        self.assertEqual(life.dispatch(fresh)[0], "CLICK_AUTO")


if __name__ == "__main__": unittest.main()
