"""Pure deterministic HOME policy diagnostic; no OCR, browser, or clicks."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from home_observation import HomeObservation


SEASON1_LARGE_GAP_AUDITION_THRESHOLD = 300

# Operator-specified policies (2026-09-05 live findings).
# STAMINA_RATIO_MIN_FOR_VOCAL: low stamina is a RISK SIGNAL (warning) only;
# it must never by itself force REST.  VOCAL authorization separately requires
# a fresh failure-rate read, regardless of the planner's chosen objective.
STAMINA_RATIO_MIN_FOR_VOCAL = 0.50
# VOCAL_FAILURE_RATE_GATE: operator-specified decision threshold.
VOCAL_FAILURE_RATE_MAX_PERCENT = 2  # >2 → REST; 0/1/2 → VOCAL allowed
ROUTE_CAPACITY_FIELDS = ("mandatory_steps", "retry_budget", "transition_margin")


@dataclass(frozen=True)
class HomeDecision:
    action: str
    reason: str
    target_tier: int | None = None
    status: str = "DECISION"
    required_fields: tuple[str, ...] = ()
    route_deadline: Mapping[str, object] | None = None

    planner_objective: str | None = None
    planner_reason: str | None = None
    permitting_gates: tuple[Mapping[str, object], ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "decision": self.action if self.status == "DECISION" else None,
            "required_fields": list(self.required_fields),
            "reason_code": self.reason,
            "planner_objective": self.planner_objective,
            "planner_reason": self.planner_reason,
            "permitting_gates": [dict(gate) for gate in self.permitting_gates],
        }


def required_observation_fields(*, season: int, weeks_remaining: int) -> tuple[str, ...]:
    """Return only fresh HOME fields consumed at the current policy boundary."""
    if season == 3:
        return ("season", "weeks_remaining", "fan_gap_to_target")
    if season == 1 and weeks_remaining == 1:
        return ("season", "weeks_remaining", "fan_gap_to_target")
    return ("season", "weeks_remaining")


def resolve_policy_state(*, season: int, weeks_remaining: int,
                         route_plan: Mapping[str, object] | None = None) -> dict[str, object]:
    """Bind policy state to one fresh HOME season/week observation.

    A route plan is accepted as input, but is not silently rebased. Its own
    ``season`` and ``as_of_weeks_remaining`` fields must match the observation
    when the decision is evaluated.
    """
    state: dict[str, object] = {
        "fresh_fields": set(required_observation_fields(
            season=season, weeks_remaining=weeks_remaining,
        )),
    }
    if season == 1:
        state["season1_final_actionable_week"] = weeks_remaining == 1
    if route_plan is not None:
        state["route_deadline"] = dict(route_plan)
    return state


def _deadline_unknown(reason: str) -> HomeDecision:
    return HomeDecision(
        "NEED_MORE_OBSERVATION",
        reason,
        status="NEED_MORE_OBSERVATION",
        required_fields=ROUTE_CAPACITY_FIELDS,
    )


def route_capacity_from_state(route_state: Mapping[str, object]) -> dict[str, int]:
    """Derive safe capacity from explicit current-route components.

    ``remaining_required_route_steps`` is deliberately output-only. Accepting
    it as an input would restore the run-local constant that this contract is
    intended to eliminate.
    """
    if "remaining_required_route_steps" in route_state or "safe_required_steps" in route_state:
        raise ValueError("ROUTE_CAPACITY_DERIVED_FIELD_MUST_NOT_BE_SUPPLIED")
    values: dict[str, int] = {}
    for field_name in ROUTE_CAPACITY_FIELDS:
        value = route_state.get(field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"ROUTE_CAPACITY_COMPONENT_INVALID:{field_name}")
        values[field_name] = value
    safe_required_steps = sum(values.values())
    return {
        **values,
        "safe_required_steps": safe_required_steps,
        "remaining_required_route_steps": safe_required_steps,
    }


def _validated_route_deadline(observation: HomeObservation,
                              policy_state: Mapping[str, object]) -> tuple[dict[str, object] | None, HomeDecision | None]:
    """Validate a route deadline without turning stale planner state into fact."""
    raw = policy_state.get("route_deadline")
    if raw is None:
        return None, None
    if not isinstance(raw, Mapping):
        return None, _deadline_unknown("ROUTE_DEADLINE_STATE_INVALID")
    if raw.get("fresh") is not True:
        return None, _deadline_unknown("ROUTE_DEADLINE_STATE_NOT_FRESH")
    if raw.get("season") != observation.season:
        return None, _deadline_unknown("SEASON_TRANSITION_RECONCILIATION_REQUIRED")
    if raw.get("as_of_weeks_remaining") != observation.weeks_remaining:
        return None, _deadline_unknown("ROUTE_DEADLINE_WEEK_RECONCILIATION_REQUIRED")
    try:
        capacity = route_capacity_from_state(raw)
    except ValueError as error:
        return None, _deadline_unknown(str(error))
    normalized = dict(raw)
    normalized.update(capacity)
    normalized["remaining_weeks"] = observation.weeks_remaining
    normalized["latest_safe_start_week"] = capacity["safe_required_steps"]
    return normalized, None


def _apply_route_deadline(observation: HomeObservation,
                          policy_state: Mapping[str, object],
                          base_decision: HomeDecision) -> HomeDecision:
    deadline, invalid = _validated_route_deadline(observation, policy_state)
    if invalid is not None:
        return invalid
    if deadline is None:
        return base_decision
    remaining_steps = int(deadline["remaining_required_route_steps"])
    if remaining_steps == 0:
        return base_decision
    if observation.weeks_remaining > remaining_steps:
        return HomeDecision(
            base_decision.action,
            base_decision.reason,
            base_decision.target_tier,
            base_decision.status,
            base_decision.required_fields,
            deadline,
        )
    route_action = deadline.get("next_route_action")
    if not isinstance(route_action, str) or not route_action or route_action == "UNKNOWN":
        return _deadline_unknown("NEXT_REQUIRED_ROUTE_ACTION_UNKNOWN")
    raw_tier = deadline.get("next_route_target_tier")
    target_tier = raw_tier if isinstance(raw_tier, int) and not isinstance(raw_tier, bool) else None
    boundary = "MISSED" if observation.weeks_remaining < remaining_steps else "REACHED"
    return HomeDecision(
        route_action,
        f"ROUTE_DEADLINE_{boundary}:LOW_PRIORITY_TRAINING_FORBIDDEN",
        target_tier,
        route_deadline=deadline,
    )


def apply_vocal_risk_guard(decision: HomeDecision, policy_state: Mapping[str, object]) -> HomeDecision:
    """Gate VOCAL on a fresh failure-rate observation from the SCHEDULE ROI.

    - ``stamina_observation.ratio < STAMINA_RATIO_MIN_FOR_VOCAL`` (fresh) is a
      LOW_STAMINA_WARNING: it makes the failure-rate read mandatory, it never
      directly forces REST.
    - ``vocal_failure_rate_observation`` must be
      ``{"value": 0..100, "status": "KNOWN", "fresh": True}`` from the taught
      VOCAL failure ROI.  value > VOCAL_FAILURE_RATE_MAX_PERCENT → REST with a
      back-to-schedule path.  0/1/2 → VOCAL allowed.
    - Every VOCAL objective requires this fresh read.  An absent observation
      requests it; an attempted-but-unreadable observation fails closed: REST
      preferred when stamina is low, escalation required otherwise.  A stale
      observation is rejected (never treated as 0%).
    """
    if decision.action != "VOCAL":
        return decision
    ratio = None
    stamina = policy_state.get("stamina_observation")
    if isinstance(stamina, Mapping) and stamina.get("fresh") is True:
        raw = stamina.get("ratio")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            ratio = float(raw)
    low = ratio is not None and ratio < STAMINA_RATIO_MIN_FOR_VOCAL

    fr = policy_state.get("vocal_failure_rate_observation")
    if not isinstance(fr, Mapping):
        prefix = "LOW_STAMINA_WARNING:" if low else ""
        return HomeDecision("NEED_MORE_OBSERVATION",
                            f"{prefix}FAILURE_RATE_READ_REQUIRED")
    readable = (
        fr.get("fresh") is True
        and fr.get("status") == "KNOWN"
        and isinstance(fr.get("value"), (int, float))
        and not isinstance(fr.get("value"), bool)
    )
    if readable:
        if float(fr["value"]) > VOCAL_FAILURE_RATE_MAX_PERCENT:
            return HomeDecision("REST",
                                "VOCAL_FAILURE_RATE_EXCEEDED:DO_NOT_START_VOCAL:BACK_TO_REST")
        return decision
    # attempted but unreadable / ambiguous / stale
    if low:
        return HomeDecision("REST", "LOW_STAMINA_WARNING:FAILURE_RATE_UNKNOWN_FAIL_CLOSED")
    return HomeDecision("NEED_MORE_OBSERVATION", "FAILURE_RATE_UNKNOWN_ESCALATION_REQUIRED")


def _decide_home_base(observation: HomeObservation, policy_state: Mapping[str, object], config: Mapping[str, object]) -> HomeDecision:
    """Choose only a diagnostic action label from validated facts.

    ``policy_state`` is intentionally external to perception. It currently only
    permits a future verified indication that Season 1 is on its final
    actionable week; no route state is inferred from HOME fields.
    """
    configured_run = config.get("run_state", {}) if isinstance(config, Mapping) else {}
    season3 = configured_run.get("season3", {}) if isinstance(configured_run, Mapping) else {}
    # Allow callers that already carry a run-state snapshot to provide it
    # through policy_state without creating a second route system.
    if isinstance(policy_state.get("season3"), Mapping):
        season3 = policy_state["season3"]
    if observation.season == 1:
        final_week = bool(policy_state.get("season1_final_actionable_week", False))
        if not final_week:
            return HomeDecision("VOCAL", "season_1_default_vocal")
        gap = observation.fan_gap_to_target
        fresh_fields = policy_state.get("fresh_fields")
        if fresh_fields is not None and "fan_gap_to_target" not in set(fresh_fields):
            return HomeDecision("NEED_MORE_OBSERVATION", "fan_gap_required_at_s1_final_boundary",
                                status="NEED_MORE_OBSERVATION", required_fields=("fan_gap_to_target",))
        if gap is None:
            return HomeDecision("NEED_MORE_OBSERVATION", "fan_gap_required_at_s1_final_boundary",
                                status="NEED_MORE_OBSERVATION", required_fields=("fan_gap_to_target",))
        if gap <= 0:
            return HomeDecision("VOCAL", "season_1_final_week_fan_gap_met")
        if gap > SEASON1_LARGE_GAP_AUDITION_THRESHOLD:
            return HomeDecision("AUDITION", "season_1_final_week_fan_gap_requires_audition")
        return HomeDecision("NEEDS_VOCAL_FAN_GAIN", "season_1_final_week_small_positive_gap_requires_vocal_fan_gain")
    if observation.season == 2:
        if observation.weeks_remaining > 1:
            return HomeDecision("VOCAL", "season_2_default_vocal")
        if observation.weeks_remaining == 1 and observation.fan_gap_to_target <= 0:
            return HomeDecision("VOCAL", "season_2_target_already_met")
        if observation.weeks_remaining == 1 and observation.fan_gap_to_target > 0:
            return HomeDecision("AUDITION", "season_2_final_week_fan_gap")
        return HomeDecision("UNSUPPORTED_SEASON", "season_2_weeks_remaining_is_not_supported")
    if observation.season == 3:
        if not bool(season3.get("audition_40k_completed", False)):
            return HomeDecision("AUDITION", "season_3_40k_audition_pending", 40000)
        if not bool(season3.get("audition_50k_completed", False)):
            # HOME currently exposes the gap to the 50k target.  Use it only
            # to determine whether the 50k audition is unlocked; it does not
            # mark the 40k audition complete.
            if observation.fan_gap_to_target is None:
                return HomeDecision("NEED_MORE_OBSERVATION", "S3_FAN_GAP_REQUIRED",
                                    status="NEED_MORE_OBSERVATION",
                                    required_fields=("fan_gap_to_target",))
            current_fans = 50000 - observation.fan_gap_to_target
            if current_fans < 50000:
                return HomeDecision("VOCAL", "season_3_build_to_50k_audition_unlock")
            return HomeDecision("AUDITION", "season_3_50k_audition_pending", 50000)
        # The planner selects the weekly objective.  Stamina does not replace
        # that objective with REST; if this objective is VOCAL, the separate
        # fresh-evidence risk guard below owns authorization.
        return HomeDecision("VOCAL", "season_3_milestones_complete_vocal_objective")
    if observation.season == 4:
        deadline, invalid = _validated_route_deadline(observation, policy_state)
        if invalid is not None:
            return invalid
        if deadline is not None and observation.weeks_remaining > int(deadline["remaining_required_route_steps"]):
            pre_deadline_action = deadline.get("pre_deadline_action")
            if isinstance(pre_deadline_action, str) and pre_deadline_action:
                return HomeDecision(
                    pre_deadline_action,
                    "season_4_pre_deadline_action",
                    route_deadline=deadline,
                )
        return HomeDecision("ROUTE_STATE_REQUIRED", f"season_{observation.season}_requires_explicit_route_state")
    return HomeDecision("UNSUPPORTED_SEASON", f"season_{observation.season}_is_not_supported")


def _season_futility_check(observation: HomeObservation,
                           policy_state: Mapping[str, object],
                           config: Mapping[str, object],
                           decision: HomeDecision) -> HomeDecision:
    """Check the existing S3 unlock path; never choose an alternative route.

    The caller supplies a current, evidence-backed upper bound, not an average
    or a default gain. Reserve the pending 50k audition AFTER reaching its fan
    unlock threshold. Reuse any larger explicit route capacity (including retries
    and transition margin). The 40k-pending branch remains the existing audition.
    """
    if observation.season != 3 or decision.action != "VOCAL":
        return decision
    gap = observation.fan_gap_to_target
    fresh = policy_state.get("fresh_fields")
    if gap is None or (fresh is not None and "fan_gap_to_target" not in fresh):
        return HomeDecision("NEED_MORE_OBSERVATION", "S3_FAN_GAP_REQUIRED",
                            status="NEED_MORE_OBSERVATION",
                            required_fields=("fan_gap_to_target",))
    if gap <= 0:
        return decision
    run_state = config.get("run_state", {})
    season3 = policy_state.get("season3", run_state.get("season3", {}))
    reserved = int(not bool(season3.get("audition_50k_completed", False)))
    if decision.route_deadline is not None:
        reserved = max(reserved, int(decision.route_deadline["remaining_required_route_steps"]))
    training_weeks = observation.weeks_remaining - reserved
    if training_weeks <= 0:
        return HomeDecision("NEED_MORE_OBSERVATION", "ENDGAME_FUTILE:S3_UNLOCK_ROUTE_CAPACITY",
                            status="NEED_MORE_OBSERVATION")
    projection = policy_state.get("vocal_fan_gain_projection")
    if (not isinstance(projection, Mapping)
            or projection.get("fresh") is not True
            or projection.get("season") != observation.season
            or projection.get("as_of_weeks_remaining") != observation.weeks_remaining
            or not isinstance(projection.get("max_gain_per_week"), int)
            or isinstance(projection.get("max_gain_per_week"), bool)
            or projection["max_gain_per_week"] < 0):
        return HomeDecision("NEED_MORE_OBSERVATION", "S3_FAN_GAIN_PROJECTION_REQUIRED",
                            status="NEED_MORE_OBSERVATION",
                            required_fields=("vocal_fan_gain_projection",))
    if training_weeks * projection["max_gain_per_week"] < gap:
        return HomeDecision("NEED_MORE_OBSERVATION", "ENDGAME_FUTILE:S3_FAN_TARGET_UNREACHABLE",
                            status="NEED_MORE_OBSERVATION")
    return decision


def decide_home(observation: HomeObservation, policy_state: Mapping[str, object], config: Mapping[str, object]) -> HomeDecision:
    """Select a feasible business objective, then separately record its risk gate."""
    decision = _decide_home_base(observation, policy_state, config)
    decision = _apply_route_deadline(observation, policy_state, decision)
    decision = _season_futility_check(observation, policy_state, config, decision)
    result = apply_vocal_risk_guard(decision, policy_state)
    gates = ()
    if decision.action == "VOCAL":
        gates = ({
            "risk_gate": "VOCAL_FAILURE_RATE",
            "risk_observation": policy_state.get("vocal_failure_rate_observation"),
            "risk_decision": "ALLOW" if result.action == "VOCAL" else "BLOCK",
            "risk_reason": ("FRESH_FAILURE_RATE_WITHIN_LIMIT" if result.action == "VOCAL"
                            else result.reason),
        },)
    return replace(result, planner_objective=decision.action,
                   planner_reason=decision.reason, permitting_gates=gates)
