"""Low-cost interaction planning for already-selected room actions.

The planner remains the owner of *what* business action should happen.  This
module only compiles an already-selected action into bounded UI interaction
steps, cheap probes, or a fail-closed escalation.  It performs no perception,
input injection, business planning, or full-screen vision.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import math
import statistics
from typing import Iterable, Mapping, Sequence


BLIND_POLICY_VERSION = "v0.1"
DIALOGUE_NEUTRAL_ZONE = (640, 360)


class ProbeValue(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InteractionDecision(str, Enum):
    EXECUTE = "EXECUTE"
    PROBE = "PROBE"
    WAIT = "WAIT"
    ESCALATE_CROPPED_ROI = "ESCALATE_CROPPED_ROI"
    ESCALATE_FULL_VISION = "ESCALATE_FULL_VISION"
    STOP = "STOP"


@dataclass(frozen=True)
class RoiProbe:
    """One deterministic, bounded question over a named local ROI."""

    probe_id: str
    question: str


@dataclass(frozen=True)
class RoomProfile:
    room_name: str
    version: str
    known_entry_states: tuple[str, ...]
    expected_next_states: tuple[str, ...]
    business_click_targets: tuple[str, ...]
    neutral_click_zone: tuple[int, int] | None
    roi_probes: tuple[str, ...]
    blind_actions: tuple[str, ...]
    max_blind_steps: int
    timeout_ms: int
    escalation_policy: str
    risk_level: RiskLevel

    def __post_init__(self) -> None:
        if self.max_blind_steps < 0 or self.timeout_ms <= 0:
            raise ValueError("room profile bounds must be positive")
        if self.neutral_click_zone is not None:
            if self.room_name != "DIALOGUE" or self.neutral_click_zone != DIALOGUE_NEUTRAL_ZONE:
                raise ValueError("neutral burst geometry is restricted to the taught DIALOGUE center")

    @property
    def room(self) -> str:
        """Compatibility alias for the concise profile spelling."""
        return self.room_name


ROI_MAP: dict[str, tuple[RoiProbe, ...]] = {
    "HOME": (
        RoiProbe("home_week_counter_roi", "week counter readable"),
        RoiProbe("home_fans_gap_roi", "fan gap readable"),
        RoiProbe("home_stamina_roi", "stamina marker readable"),
        RoiProbe("home_topbar_marker_roi", "HOME topbar marker present"),
    ),
    "SCHEDULE": (
        RoiProbe("schedule_current_tab_roi", "expected schedule tab selected"),
        RoiProbe("schedule_vocal_selected_roi", "VOCAL card selected"),
        RoiProbe("schedule_trouble_rate_roi", "failure rate readable"),
        RoiProbe("schedule_kettei_state_roi", "decision control actionable"),
    ),
    "DIALOGUE": (
        RoiProbe("dialogue_skip_button_roi", "SKIP visible"),
        RoiProbe("dialogue_fast_forward_roi", "fast-forward state readable"),
        RoiProbe("dialogue_choice_panel_roi", "choice panel present"),
        RoiProbe("dialogue_home_topbar_roi", "HOME topbar present"),
    ),
    "CHOICE": (
        RoiProbe("choice_panel_roi", "choice panel present"),
        RoiProbe("choice_layout_fingerprint_roi", "choice layout fingerprint known"),
    ),
    "AUDITION_PREP": (
        RoiProbe("audition_list_tab_roi", "expected audition list/tab selected"),
        RoiProbe("audition_page_indicator_roi", "audition preparation identity present"),
        RoiProbe("audition_kettei_roi", "decision control actionable"),
    ),
    "AUDITION_BATTLE": (
        RoiProbe("battle_auto_button_roi", "Auto value and interactability readable"),
        RoiProbe("battle_input_ready_roi", "turn input phase actionable"),
        RoiProbe("battle_result_marker_roi", "battle result marker present"),
    ),
    "AUDITION_RESULT": (
        RoiProbe("audition_result_marker_roi", "audition result visible"),
        RoiProbe("audition_result_next_roi", "result advance control actionable"),
    ),
    "SEASON_TRANSITION": (
        RoiProbe("season_result_roi", "season result visible"),
        RoiProbe("season_next_ok_skip_roi", "next, OK, or SKIP control visible"),
    ),
    "SKILL_BOARD": (
        RoiProbe("skill_board_title_roi", "skill board title marker present"),
        RoiProbe("skill_board_back_roi", "back control visible"),
    ),
    "LESSON": (
        RoiProbe("lesson_page_marker_roi", "lesson page marker present"),
        RoiProbe("lesson_result_roi", "lesson result marker present"),
    ),
    "UNKNOWN": (),
}


def _probe_ids(room: str) -> tuple[str, ...]:
    return tuple(probe.probe_id for probe in ROI_MAP[room])


ROOM_PROFILES: dict[str, RoomProfile] = {
    "HOME": RoomProfile("HOME", BLIND_POLICY_VERSION, ("HOME",),
                        ("SCHEDULE", "AUDITION_PREP", "SKILL_BOARD"),
                        ("VOCAL", "REST", "AUDITION", "SKILL"), None,
                        _probe_ids("HOME"), (), 0, 2000, "ROI_THEN_FULL_VISION", RiskLevel.HIGH),
    "SCHEDULE": RoomProfile("SCHEDULE", BLIND_POLICY_VERSION,
                            ("SCHEDULE", "SCHEDULE_SELECTION"), ("LESSON", "DIALOGUE"),
                            ("VOCAL", "SCHEDULE_TAB", "KETTEI", "BACK"), None,
                            _probe_ids("SCHEDULE"), ("BACK",), 1, 2000,
                            "ROI_THEN_FULL_VISION", RiskLevel.HIGH),
    "LESSON": RoomProfile("LESSON", BLIND_POLICY_VERSION, ("LESSON", "VOCAL_RESULT"),
                          ("DIALOGUE", "HOME"), ("NEXT", "BACK"), None,
                          _probe_ids("LESSON"), ("NEXT", "BACK"), 2, 4000,
                          "ROI_THEN_FULL_VISION", RiskLevel.MEDIUM),
    "DIALOGUE": RoomProfile("DIALOGUE", BLIND_POLICY_VERSION,
                            ("DIALOGUE", "DIALOGUE_FAST_FORWARD_OFF", "MORNING_DIALOGUE"),
                            ("DIALOGUE", "CHOICE", "HOME", "AUDITION_BATTLE", "AUDITION_RESULT"),
                            ("SKIP", "FAST_FORWARD", "BACK"), DIALOGUE_NEUTRAL_ZONE,
                            _probe_ids("DIALOGUE"), ("CENTER_TAP", "SKIP", "FAST_FORWARD"), 4,
                            5000, "ROI_THEN_FULL_VISION", RiskLevel.LOW),
    "CHOICE": RoomProfile("CHOICE", BLIND_POLICY_VERSION,
                          ("CHOICE", "MORNING_CHOICE"), ("DIALOGUE", "HOME", "AUDITION_BATTLE"),
                          ("OPTION_1", "OPTION_2", "OPTION_3"), None, _probe_ids("CHOICE"), (),
                          1, 1500, "CROPPED_ROI_THEN_FULL_VISION", RiskLevel.HIGH),
    "AUDITION_PREP": RoomProfile("AUDITION_PREP", BLIND_POLICY_VERSION,
                                 ("AUDITION_PREP", "AUDITION_SELECTION", "ADVICE"),
                                 ("DIALOGUE", "CHOICE", "AUDITION_BATTLE"),
                                 ("AUDITION_TARGET", "KETTEI", "BACK"), None,
                                 _probe_ids("AUDITION_PREP"), ("BACK",), 8, 12000,
                                 "ROI_THEN_FULL_VISION", RiskLevel.HIGH),
    "AUDITION_BATTLE": RoomProfile("AUDITION_BATTLE", BLIND_POLICY_VERSION,
                                   ("AUDITION_BATTLE",), ("AUDITION_BATTLE", "AUDITION_RESULT"),
                                   ("AUTO", "SPEED", "CARD"), None, _probe_ids("AUDITION_BATTLE"), (),
                                   0, 5000, "ROI_THEN_FULL_VISION", RiskLevel.HIGH),
    "AUDITION_RESULT": RoomProfile("AUDITION_RESULT", BLIND_POLICY_VERSION,
                                   ("AUDITION_RESULT", "AUDITION_RESULT_DIALOGUE"),
                                   ("DIALOGUE", "HOME"), ("NEXT", "SKIP"), None,
                                   _probe_ids("AUDITION_RESULT"), ("NEXT", "SKIP"), 3, 8000,
                                   "ROI_THEN_FULL_VISION", RiskLevel.MEDIUM),
    "SEASON_TRANSITION": RoomProfile("SEASON_TRANSITION", BLIND_POLICY_VERSION,
                                     ("SEASON_TRANSITION", "RESULT"), ("DIALOGUE", "HOME"),
                                     ("NEXT", "OK", "SKIP"), None, _probe_ids("SEASON_TRANSITION"),
                                     ("NEXT", "OK", "SKIP"), 4, 10000,
                                     "ROI_THEN_FULL_VISION", RiskLevel.MEDIUM),
    "SKILL_BOARD": RoomProfile("SKILL_BOARD", BLIND_POLICY_VERSION,
                               ("SKILL_BOARD",), ("SKILL_BOARD", "HOME"),
                               ("SKILL_NODE", "PURCHASE", "BACK"), None, _probe_ids("SKILL_BOARD"),
                               ("BACK",), 1, 3000, "ROI_THEN_FULL_VISION", RiskLevel.HIGH),
    "UNKNOWN": RoomProfile("UNKNOWN", BLIND_POLICY_VERSION, ("UNKNOWN",), (), (), None,
                           (), (), 0, 1000, "STOP", RiskLevel.HIGH),
}


@dataclass(frozen=True)
class InteractionPlan:
    decision: InteractionDecision
    reason: str
    action: str | None = None
    target: str | tuple[int, int] | None = None
    required_probes: tuple[str, ...] = ()
    retry_allowed: bool = False
    wait_ms: int | None = None


def get_room_profile(room: str) -> RoomProfile:
    return ROOM_PROFILES.get(str(room), ROOM_PROFILES["UNKNOWN"])


def dialogue_burst(profile: RoomProfile, *, steps: int) -> InteractionPlan:
    """Compile a bounded dialogue advance; the only coordinate is neutral."""
    if profile.room_name != "DIALOGUE" or profile.neutral_click_zone != DIALOGUE_NEUTRAL_ZONE:
        return InteractionPlan(InteractionDecision.STOP, "NEUTRAL_ZONE_NOT_AUTHORIZED")
    if steps < 1 or steps > profile.max_blind_steps:
        return InteractionPlan(InteractionDecision.STOP, "BLIND_STEP_LIMIT_EXCEEDED")
    return InteractionPlan(InteractionDecision.EXECUTE, "BOUNDED_NEUTRAL_DIALOGUE_BURST",
                           "CENTER_TAP", profile.neutral_click_zone)


def evaluate_action(*, profile: RoomProfile, current_room: str, action: str,
                    risk: RiskLevel, probes: Mapping[str, ProbeValue | str]) -> InteractionPlan:
    """Gate one pre-selected UI action using only caller-supplied ROI facts."""
    if current_room not in profile.known_entry_states:
        return InteractionPlan(InteractionDecision.STOP, "EXPECTED_ROOM_NOT_CONFIRMED")
    if action not in profile.business_click_targets and action not in profile.blind_actions:
        return InteractionPlan(InteractionDecision.STOP, "ACTION_NOT_IN_ROOM_PROFILE")

    values = {key: ProbeValue(value) for key, value in probes.items()}
    if risk is RiskLevel.LOW:
        if action not in profile.blind_actions:
            return InteractionPlan(InteractionDecision.PROBE, "LOW_ACTION_NOT_BLIND_VERIFIED",
                                   required_probes=profile.roi_probes)
        return InteractionPlan(InteractionDecision.EXECUTE, "LOW_RISK_BLIND_ACTION", action)

    relevant = tuple(probe for probe in profile.roi_probes if probe in values)
    if any(values[probe] is ProbeValue.FALSE for probe in relevant):
        # A negative precondition is evidence against the action.  In
        # particular, HIGH actions are never blindly retried after mismatch.
        return InteractionPlan(InteractionDecision.STOP, "ROI_PRECONDITION_MISMATCH",
                               required_probes=profile.roi_probes, retry_allowed=False)
    true_count = sum(values[probe] is ProbeValue.TRUE for probe in relevant)
    if risk is RiskLevel.MEDIUM:
        if true_count >= 1:
            return InteractionPlan(InteractionDecision.EXECUTE, "CHEAP_ROI_PRECONDITION_MET", action)
        return InteractionPlan(InteractionDecision.PROBE, "CHEAP_ROI_PRECONDITION_REQUIRED",
                               required_probes=profile.roi_probes)
    if true_count >= 2:
        return InteractionPlan(InteractionDecision.EXECUTE, "HIGH_RISK_MULTI_PROBE_CONFIRMED", action)
    return InteractionPlan(InteractionDecision.PROBE, "HIGH_RISK_MULTI_PROBE_REQUIRED",
                           required_probes=profile.roi_probes, retry_allowed=False)


@dataclass(frozen=True)
class ChoiceFingerprint:
    fingerprint_id: str
    option_count: int
    selected_index: int
    verification_probe: str = "choice_layout_fingerprint_roi"


KNOWN_CHOICE_FINGERPRINTS: dict[str, ChoiceFingerprint] = {
    "MORNING_3CHOICE_GREEN_V1": ChoiceFingerprint("MORNING_3CHOICE_GREEN_V1", 3, 2),
    "AUDITION_2CHOICE_IIYO_GOMEN_V1": ChoiceFingerprint("AUDITION_2CHOICE_IIYO_GOMEN_V1", 2, 2),
}


def resolve_choice(*, fingerprint_id: str | None, option_count: int | None,
                   registry: Mapping[str, ChoiceFingerprint] = KNOWN_CHOICE_FINGERPRINTS) -> InteractionPlan:
    """Use a learned choice layout or escalate only its cropped ROI."""
    known = registry.get(str(fingerprint_id)) if fingerprint_id is not None else None
    if known is not None and option_count == known.option_count:
        return InteractionPlan(InteractionDecision.EXECUTE, "KNOWN_CHOICE_FINGERPRINT",
                               f"OPTION_{known.selected_index}", f"OPTION_{known.selected_index}")
    return InteractionPlan(InteractionDecision.ESCALATE_CROPPED_ROI,
                           "UNKNOWN_CHOICE_FINGERPRINT", required_probes=("choice_panel_roi",))


@dataclass(frozen=True)
class SequenceStep:
    kind: str
    target: str | tuple[int, int] | None = None
    max_steps: int = 1
    verification_probe: str | None = None


def audition_pre_battle_sequence(*, target_marker_confirmed: bool,
                                 choice_fingerprint_id: str,
                                 option_count: int) -> tuple[SequenceStep, ...] | InteractionPlan:
    """Compile the fixed preparation interaction after AUDITION was selected."""
    if target_marker_confirmed is not True:
        return InteractionPlan(InteractionDecision.PROBE, "AUDITION_TARGET_MARKER_REQUIRED",
                               required_probes=("audition_list_tab_roi", "audition_page_indicator_roi"))
    choice = resolve_choice(fingerprint_id=choice_fingerprint_id, option_count=option_count)
    if choice.decision is not InteractionDecision.EXECUTE:
        return choice
    return (
        SequenceStep("EXACT_CLICK", "AUDITION_TARGET", verification_probe="audition_list_tab_roi"),
        SequenceStep("EXACT_CLICK", "KETTEI", verification_probe="audition_kettei_roi"),
        SequenceStep("DIALOGUE_BURST", DIALOGUE_NEUTRAL_ZONE, max_steps=4),
        SequenceStep("EXACT_CLICK", choice.target, verification_probe="choice_layout_fingerprint_roi"),
        SequenceStep("DIALOGUE_BURST", DIALOGUE_NEUTRAL_ZONE, max_steps=4),
        SequenceStep("VERIFY", verification_probe="battle_input_ready_roi"),
    )


def transition_mask(*, mask_visible: bool, elapsed_ms: int, p95_transition_ms: int) -> InteractionPlan:
    """Treat fades as bounded wait states, never immediate action failures."""
    if mask_visible and elapsed_ms <= p95_transition_ms:
        return InteractionPlan(InteractionDecision.WAIT, "TRANSITION_MASK_ACTIVE",
                               target=None, retry_allowed=False, wait_ms=400)
    if mask_visible:
        return InteractionPlan(InteractionDecision.PROBE, "TRANSITION_P95_EXCEEDED",
                               required_probes=("current_room_identity_roi",), retry_allowed=False)
    return InteractionPlan(InteractionDecision.PROBE, "TRANSITION_MASK_CLEAR",
                           required_probes=("current_room_identity_roi",))


def resolve_random_event(*, choice_panel: ProbeValue | str, skip_visible: ProbeValue | str,
                         fingerprint_id: str | None = None,
                         option_count: int | None = None) -> InteractionPlan:
    """Resolve only the local interaction shape of a random event.

    A known choice fingerprint uses its pre-registered interaction target.  A
    new choice asks cropped-ROI vision, a confirmed skip-only event uses SKIP,
    and ambiguous evidence escalates without inventing page semantics.
    """
    choice = ProbeValue(choice_panel)
    skip = ProbeValue(skip_visible)
    if choice is ProbeValue.TRUE:
        return resolve_choice(fingerprint_id=fingerprint_id, option_count=option_count)
    if choice is ProbeValue.FALSE and skip is ProbeValue.TRUE:
        return InteractionPlan(InteractionDecision.EXECUTE, "SKIP_ONLY_EVENT_CONFIRMED", "SKIP", "SKIP")
    if choice is ProbeValue.UNKNOWN or skip is ProbeValue.UNKNOWN:
        return InteractionPlan(InteractionDecision.ESCALATE_CROPPED_ROI,
                               "EVENT_ROI_AMBIGUOUS", required_probes=("choice_panel_roi",))
    return InteractionPlan(InteractionDecision.ESCALATE_FULL_VISION,
                           "EVENT_LOCAL_PROBES_UNRESOLVED", retry_allowed=False)


@dataclass(frozen=True)
class FastPathSkill:
    skill_id: str
    room: str
    transition: str
    samples: int = 0
    success_count: int = 0
    failure_count: int = 0
    consecutive_successes: int = 0
    timings_ms: tuple[float, ...] = ()
    median_ms: float | None = None
    p90_ms: float | None = None
    p95_ms: float | None = None
    verification_method: str = ""
    fast_path_eligible: bool = False
    last_verified_at: str | None = None
    version: str = BLIND_POLICY_VERSION

    @property
    def FAST_PATH_ELIGIBLE(self) -> bool:
        return self.fast_path_eligible


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


class FastPathSkillRegistry:
    """In-memory evidence registry; persistence remains a caller concern."""

    def __init__(self, skills: Iterable[FastPathSkill] = ()) -> None:
        self._skills = {skill.skill_id: skill for skill in skills}

    def get(self, skill_id: str) -> FastPathSkill:
        return self._skills[skill_id]

    def register(self, skill: FastPathSkill) -> None:
        if skill.skill_id in self._skills:
            raise ValueError("FAST_PATH_SKILL_ALREADY_REGISTERED")
        self._skills[skill.skill_id] = skill

    def record_success(self, skill_id: str, *, duration_ms: float, verified_at: str) -> FastPathSkill:
        skill = self.get(skill_id)
        timings = skill.timings_ms + (float(duration_ms),)
        consecutive = skill.consecutive_successes + 1
        updated = replace(
            skill,
            samples=skill.samples + 1,
            success_count=skill.success_count + 1,
            consecutive_successes=consecutive,
            timings_ms=timings,
            median_ms=float(statistics.median(timings)),
            p90_ms=_percentile(timings, .90),
            p95_ms=_percentile(timings, .95),
            fast_path_eligible=consecutive >= 3 and skill.failure_count == 0,
            last_verified_at=str(verified_at),
        )
        self._skills[skill_id] = updated
        return updated

    def record_deviation(self, skill_id: str, *, verified_at: str) -> FastPathSkill:
        skill = self.get(skill_id)
        updated = replace(skill, samples=skill.samples + 1,
                          failure_count=skill.failure_count + 1,
                          consecutive_successes=0, fast_path_eligible=False,
                          last_verified_at=str(verified_at))
        self._skills[skill_id] = updated
        return updated


ESCALATION_TREE = (
    "BLIND_KNOWN_SKILL",
    "CHEAP_ROI_PROBE",
    "MULTI_ROI_VERIFICATION",
    "CROPPED_ROI_VISION",
    "FULL_SCREEN_VISION",
    "UNKNOWN_STOP",
)


def next_escalation(current: str, *, resolved: bool) -> str:
    if resolved:
        return "RESOLVED"
    try:
        index = ESCALATION_TREE.index(current)
    except ValueError:
        return "UNKNOWN_STOP"
    return ESCALATION_TREE[min(index + 1, len(ESCALATION_TREE) - 1)]


class BlindInteractionPolicy:
    """Small facade suitable for injection after a planner chooses an action."""

    version = BLIND_POLICY_VERSION

    def profile(self, room: str) -> RoomProfile:
        return get_room_profile(room)

    def gate(self, *, room: str, current_room: str, action: str, risk: RiskLevel,
             probes: Mapping[str, ProbeValue | str]) -> InteractionPlan:
        return evaluate_action(profile=self.profile(room), current_room=current_room,
                               action=action, risk=risk, probes=probes)


__all__ = [
    "BLIND_POLICY_VERSION", "DIALOGUE_NEUTRAL_ZONE", "ProbeValue", "RiskLevel",
    "InteractionDecision", "RoiProbe", "RoomProfile", "ROI_MAP", "ROOM_PROFILES",
    "InteractionPlan", "get_room_profile", "dialogue_burst", "evaluate_action",
    "ChoiceFingerprint", "KNOWN_CHOICE_FINGERPRINTS", "resolve_choice", "SequenceStep",
    "audition_pre_battle_sequence", "transition_mask", "FastPathSkill",
    "resolve_random_event", "FastPathSkillRegistry", "ESCALATION_TREE", "next_escalation",
    "BlindInteractionPolicy",
]
