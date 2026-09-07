"""Fail-closed lifecycle for local AUDITION_BATTLE controls.

This module owns no input injection.  Callers provide fresh detector results
and perform at most the returned action, then create a new observation frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
import uuid


class AutoState(str, Enum):
    ON = "AUTO_ON"
    OFF = "AUTO_OFF"
    UNKNOWN = "AUTO_UNKNOWN"


class SpeedState(str, Enum):
    X1 = "X1"
    X2 = "X2"
    X3 = "X3"
    UNKNOWN = "SPEED_UNKNOWN"


class BattlePhase(str, Enum):
    INPUT_READY = "INPUT_READY"
    ANIMATION = "ANIMATION"
    RESULT = "RESULT"
    UNKNOWN = "UNKNOWN"


class AutoInteractability(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ControlObservation:
    frame_id: str
    control_epoch_id: str
    fresh: bool
    auto_state: AutoState = AutoState.UNKNOWN
    speed_state: SpeedState = SpeedState.UNKNOWN
    battle_phase: BattlePhase = BattlePhase.INPUT_READY
    auto_interactability: AutoInteractability = AutoInteractability.ENABLED
    speed_actionable: bool = False
    current_turn: int | None = None
    selected_card_state: str | None = None


@dataclass
class ControlEpoch:
    control_epoch_id: str = field(default_factory=lambda: "epoch_" + uuid.uuid4().hex)
    auto_state: AutoState = AutoState.UNKNOWN
    speed_state: SpeedState = SpeedState.UNKNOWN
    current_turn: int | None = None
    selected_card_state: str | None = None
    pending_control_target: str | None = None
    consumed_frames: set[str] = field(default_factory=set)

    def invalidate(self) -> None:
        self.auto_state = AutoState.UNKNOWN
        self.speed_state = SpeedState.UNKNOWN
        self.current_turn = None
        self.selected_card_state = None
        self.pending_control_target = None
        self.consumed_frames.clear()

    def consume(self, frame_id: str, owner: str) -> None:
        if frame_id in self.consumed_frames:
            raise ValueError("FRAME_ALREADY_CONSUMED")
        self.consumed_frames.add(frame_id)
        self.pending_control_target = owner

    def fresh(self, frame_id: str, *, auto: AutoState = AutoState.UNKNOWN,
              speed: SpeedState = SpeedState.UNKNOWN, turn: int | None = None,
              selected_card: str | None = None,
              phase: BattlePhase = BattlePhase.INPUT_READY,
              auto_interactability: AutoInteractability = AutoInteractability.ENABLED,
              speed_actionable: bool = False) -> ControlObservation:
        return ControlObservation(frame_id, self.control_epoch_id, True, auto, speed,
                                  phase, auto_interactability, speed_actionable,
                                  turn, selected_card)


@dataclass
class BattleControlLifecycle:
    """Small orchestration facade enforcing one owner per fresh frame."""
    epoch: ControlEpoch = field(default_factory=ControlEpoch)
    last_frame_id: str | None = None

    def begin_epoch(self) -> ControlEpoch:
        self.epoch = new_epoch(self.epoch)
        self.last_frame_id = None
        return self.epoch

    def dispatch(self, obs: ControlObservation, *, pause_overlay: bool = False) -> tuple[str, str]:
        """Return one action decision according to PAUSE>AUTO>SPEED priority."""
        owner = pause_owner(obs, self.epoch, overlay_visible=pause_overlay)
        if owner == "PAUSE_OVERLAY":
            return "PAUSE_RESUME", "PAUSE_OVERLAY_OWNER"
        if owner == "STALE_OBSERVATION":
            return "STOP", owner
        if obs.battle_phase is not BattlePhase.INPUT_READY:
            return "STOP", "BATTLE_PHASE_NOT_ACTIONABLE"
        action, reason = auto_action(obs, self.epoch)
        if action == "CLICK_AUTO":
            return action, reason
        if obs.auto_state is AutoState.UNKNOWN:
            return "STOP", reason
        # AUTO_ON is a verified no-op; speed may now own this frame.
        return speed_action(obs, self.epoch)

    def resume(self, frame_id: str) -> str:
        self.epoch, reason = overlay_resume(self.epoch, frame_id)
        return reason


def new_epoch(previous: ControlEpoch | None = None) -> ControlEpoch:
    """Create a new epoch; no local battle state crosses the boundary."""
    return ControlEpoch()


def validate_observation(obs: ControlObservation, epoch: ControlEpoch) -> bool:
    return obs.fresh and obs.control_epoch_id == epoch.control_epoch_id and obs.frame_id not in epoch.consumed_frames


def pause_owner(obs: ControlObservation, epoch: ControlEpoch, *, overlay_visible: bool) -> str | None:
    if not validate_observation(obs, epoch):
        return "STALE_OBSERVATION"
    if overlay_visible:
        epoch.consume(obs.frame_id, "PAUSE_OVERLAY")
        return "PAUSE_OVERLAY"
    return None


def auto_action(obs: ControlObservation, epoch: ControlEpoch) -> tuple[str, str]:
    """Return (action, reason); action is NOOP, CLICK_AUTO, or STOP."""
    if not validate_observation(obs, epoch):
        return "STOP", "STALE_AUTO_OBSERVATION"
    if obs.battle_phase is not BattlePhase.INPUT_READY:
        return "STOP", "AUTO_INPUT_NOT_READY"
    if obs.auto_interactability is not AutoInteractability.ENABLED:
        return "STOP", "AUTO_CONTROL_NOT_INTERACTABLE"
    if obs.auto_state is AutoState.ON:
        epoch.auto_state = AutoState.ON
        return "NOOP", "AUTO_ALREADY_ON"
    if obs.auto_state is AutoState.OFF:
        if epoch.pending_control_target == "AUTO":
            return "STOP", "AUTO_POSTCONDITION_REQUIRED"
        epoch.consume(obs.frame_id, "AUTO")
        epoch.auto_state = AutoState.OFF
        return "CLICK_AUTO", "AUTO_OFF_REQUIRES_ONE_TOGGLE"
    return "STOP", "AUTO_STATE_UNKNOWN"


def verify_auto(obs: ControlObservation, epoch: ControlEpoch) -> tuple[bool, str]:
    if not validate_observation(obs, epoch):
        return False, "STALE_AUTO_OBSERVATION"
    if obs.auto_state is AutoState.ON:
        epoch.auto_state = AutoState.ON
        if epoch.pending_control_target == "AUTO":
            epoch.pending_control_target = None
        return True, "AUTO_ON_VERIFIED"
    return False, "AUTO_TOGGLE_NOT_VERIFIED"


def speed_action(obs: ControlObservation, epoch: ControlEpoch, *, target: SpeedState = SpeedState.X3) -> tuple[str, str]:
    if not validate_observation(obs, epoch):
        return "STOP", "STALE_SPEED_OBSERVATION"
    if obs.speed_state is SpeedState.UNKNOWN:
        return "STOP", "SPEED_STATE_UNKNOWN"
    if not obs.speed_actionable:
        return "HOLD", "SPEED_TOGGLE_UNGROUNDED"
    epoch.speed_state = obs.speed_state
    if obs.speed_state is target:
        return "NOOP", "SPEED_TARGET_ALREADY_SET"
    epoch.consume(obs.frame_id, "SPEED")
    return "CLICK_SPEED", "SPEED_TOGGLE_REQUIRED"


def overlay_resume(epoch: ControlEpoch, frame_id: str) -> tuple[ControlEpoch, str]:
    """Resume consumes the overlay frame and starts a fresh control epoch."""
    if frame_id not in epoch.consumed_frames:
        epoch.consume(frame_id, "PAUSE_OVERLAY")
    return new_epoch(epoch), "FRESH_BATTLE_REQUIRED"


__all__ = ["AutoState", "SpeedState", "BattlePhase", "AutoInteractability", "ControlObservation", "ControlEpoch", "BattleControlLifecycle", "new_epoch",
           "validate_observation", "pause_owner", "auto_action", "verify_auto",
           "speed_action", "overlay_resume"]
