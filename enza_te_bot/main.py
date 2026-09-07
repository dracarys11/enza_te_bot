"""Bounded, state-driven UI transitions. Dry-run is always the default."""
from __future__ import annotations

import argparse
import copy
import json
import logging
import statistics
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image as PILImage, ImageDraw

from audition_target_teaching import add_cli_argument as add_audition_target_cli_argument
from audition_target_teaching import capture_audition_target_from_image
from actions import (click_point, fast_transaction_click_points, normalized_box_to_screen,
                     normalized_point_to_screen, point_is_inside_window, random_point)
from browser_target import BrowserTarget, TargetError
from config_store import backup_and_write_config
from home_observation import (HomeObservation, HomeObservationUnreadable, configured_rois,
                              FreshHomeCapture, WeekLearningEvidence, auto_learn_week_digit_from_progression,
                              capture_home_observation_roi, capture_home_week_digit_template,
                              consistently_observed, parse_home_sample, parse_season,
                              smoke_ocr)
from home_policy import decide_home, resolve_policy_state
from home_tick import execute_home_tick
from home_tick import season3_reflection_prephase_status
from reflection import (ReflectionNode, affordable_route_plan,
                        configured_route_nodes, crop_normalized, parse_remaining_sp,
                        may_advance_route_cursor, validate_normalized_box, fixed_route_nodes)
from grounding import resolve_action_target
from perception_models import (ActionResult, ActionTarget, EffectEvidence, FailureReason,
                               NumericObservation)
from reflection_board import reflection_observation
from reflection_canonical import CanonicalBoard, diagnose_board, is_configured_state
from reflection_geometry import GeometryUncertain, analyze_boards, annotate_board_geometry, diagnostic_payload
from room_adapter import (HOME_PROVENANCE_PARAMETER, home_provenance_metadata,
                          issue_home_provenance, valid_home_provenance)
from run_state import load_runtime_config, save_active_run_state, persist_session_end
from states import Detection, State
from teaching_console import teach
from teach_reflection_board import teach_reflection_board
from teach_reflection_fixed_route import teach as teach_reflection_fixed_route
from calibrate_reflection_board import calibrate as calibrate_reflection_board
from vision import (detect_audition_battle_auto, detect_audition_battle_speed, detect_safe_pink_cta, detect_state,
                    dynamic_screenshot, save_action_debug)
from trajectory import trajectory_step
from demo_recorder import record_demo
from demo_compiler import compile_demo, review_demo
from weekly_tools import execute_vocal

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = BASE_DIR / "enza_memory" / "artifact_registry.json"


def load_config_with_run_state() -> dict[str, object]:
    """Load static configuration plus only the registry-authorized run state."""
    return load_runtime_config(BASE_DIR / "config.json", REGISTRY_PATH)

# These are UI capabilities, not inferred business identities.  A capability
# is eligible only after normal state recognition has already produced its
# explicitly taught label *and* the active room lists that label as an
# interruption.  Keeping this small allow-list prevents an arbitrary known
# button, confirmation, or choice from becoming a generic click target.
SAFE_CONTROL_CAPABILITIES = {
    "DIALOGUE_FAST_FORWARD_OFF": {
        "action_name": "dialogue_fast_forward_on",
        "mode": "dialogue_fast_forward_once",
    },
    # This captured control is not enabled in a room yet, but declaring its
    # already-taught once-only continuation semantics here means a future
    # AUDITION_ROOM can reuse it without treating each dialogue portrait as a
    # new business state.
    "AUDITION_RESULT_DIALOGUE": {
        "action_name": "audition_result_dialogue_continue",
        "mode": "continue_once",
    },
}

HIGH_RISK_CAPABILITY_STATES = {
    "CHOICE_REQUIRED",
    "AUDITION_CHOICE",
    "CONFIRM",
    "PROMISE_CHOICE",
    "ERROR_POPUP",
}


@dataclass
class VocalRoomResultContext:
    """Minimal evidence for a one-week template-learning transaction boundary."""
    action_sent: str | None = None
    action_sent_timestamp: str | None = None
    action_associated_with_home_completion: str | None = None
    room_exit_state: str | None = None
    performance: dict[str, object] | None = None


@dataclass
class RoomPerformance:
    """Monotonic, transaction-local timing only; it never affects control flow."""
    room_name: str
    entered_at_monotonic: float
    accelerator_enabled: bool
    action_sent_at: float | None = None
    post_action_observer_started_at: float | None = None
    accelerator_first_burst_at: float | None = None
    accelerator_last_burst_at: float | None = None
    accelerator_burst_count: int = 0
    accelerator_click_count: int = 0

    def record_accelerator_burst(self, burst: dict) -> None:
        if burst.get("status") != "CLICKED" or not burst.get("click_count"):
            return
        started = float(burst["burst_started_at_monotonic"])
        finished = float(burst["burst_finished_at_monotonic"])
        self.accelerator_first_burst_at = self.accelerator_first_burst_at or started
        self.accelerator_last_burst_at = finished
        self.accelerator_burst_count += 1
        self.accelerator_click_count += int(burst["click_count"])

    def finish(self, exit_reason: str, final_state: str, exited_at_monotonic: float | None = None) -> dict[str, object]:
        exited = time.monotonic() if exited_at_monotonic is None else exited_at_monotonic
        stable_destination = exited if self.action_sent_at is not None and final_state != State.UNKNOWN.value else None
        return {
            "room_name": self.room_name,
            "entered_at_monotonic": self.entered_at_monotonic,
            "exited_at_monotonic": exited,
            "room_total_ms": round((exited - self.entered_at_monotonic) * 1000, 3),
            "exit_reason": exit_reason,
            "final_state": final_state,
            "action_sent_at": self.action_sent_at,
            "post_action_observer_started_at": self.post_action_observer_started_at,
            "accelerator_first_burst_at": self.accelerator_first_burst_at,
            "accelerator_last_burst_at": self.accelerator_last_burst_at,
            "stable_destination_at": stable_destination,
            "post_action_transition_ms": (round((stable_destination - self.action_sent_at) * 1000, 3)
                                          if stable_destination is not None and self.action_sent_at is not None else None),
            "accelerator_active_ms": (round((self.accelerator_last_burst_at - self.accelerator_first_burst_at) * 1000, 3)
                                      if self.accelerator_first_burst_at is not None and self.accelerator_last_burst_at is not None else 0.0),
            "accelerator_burst_count": self.accelerator_burst_count,
            "accelerator_click_count": self.accelerator_click_count,
            "accelerator_enabled": self.accelerator_enabled,
            "accelerator_used": self.accelerator_burst_count > 0 or self.accelerator_click_count > 0,
        }


def record_vocal_room_exit(context: VocalRoomResultContext | None, state: str) -> None:
    if context is None:
        return
    context.room_exit_state = state
    if state == State.HOME.value and context.action_sent is not None:
        context.action_associated_with_home_completion = context.action_sent


def save_shot(image, label: str) -> Path:
    path = BASE_DIR / "logs" / f"{datetime.now():%Y%m%d_%H%M%S_%f}_{label}.png"
    image.save(path)
    return path


def setup_logging() -> logging.Logger:
    (BASE_DIR / "logs").mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=[logging.FileHandler(BASE_DIR / "logs" / "automation.log"), logging.StreamHandler()])
    return logging.getLogger("enza_te_bot")


def target_screenshot(target: BrowserTarget, config: dict):
    target.verify_and_focus()
    return dynamic_screenshot(target, config, BASE_DIR)[0]


def configured_action(config: dict, state: str | State, action_name: str | None = None) -> dict:
    """Resolve one shared action; unnamed lookup remains safe only when unique."""
    state_name = state.value if isinstance(state, State) else str(state)
    actions = config["states"][state_name].get("allowed_actions", [])
    if action_name is None:
        if len(actions) != 1:
            raise ValueError(f"{state_name} must have exactly one allowed action unless an action name is requested.")
        action = actions[0]
    else:
        matches = [candidate for candidate in actions if candidate.get("name") == action_name]
        if len(matches) != 1:
            raise ValueError(f"{state_name} must contain exactly one action named {action_name!r}.")
        action = matches[0]
    expected = action.get("expected_next_states")
    # Compatibility for an already-captured Milestone 1 box using the old key.
    if expected is None and action.get("expected_next_state"):
        expected = [action["expected_next_state"]]
    if action.get("type") != "click" or not action.get("name") or not isinstance(expected, list) or not expected:
        raise ValueError(f"{state_name} action is missing name, click type, or expected_next_states.")
    if any(name not in config["states"] for name in expected):
        raise ValueError(f"{state_name} action has an unknown expected state.")
    action["expected_next_states"] = expected
    return action


def known_control_capability(config: dict, detected: Detection, room: dict) -> dict | None:
    """Resolve one explicitly allowed UI control in the current room context.

    Detection still owns state identity.  This function merely asks whether a
    known label has an explicitly registered low-risk control capability;
    unknown and choice-like labels never receive a generic action.
    """
    state = detected.state.value
    if state == State.UNKNOWN.value or state in HIGH_RISK_CAPABILITY_STATES:
        return None
    if state not in room.get("interruptions", []):
        return None
    capability = SAFE_CONTROL_CAPABILITIES.get(state)
    if capability is None:
        return None
    action = configured_action(config, state, capability["action_name"])
    return {"state": state, "action": action, **capability}


def log_detection(log: logging.Logger, label: str, detection: Detection) -> None:
    log.info("%s current_state=%s matched_template=%s confidence=%.3f", label, detection.state.value, detection.template, detection.confidence)


def new_trace_path() -> Path:
    return BASE_DIR / "logs" / f"discovery_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl"


def _json_trace_value(value, location: str = "record"):
    """Make the permitted trace representation explicit; reject unknown objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, PILImage.Image):
        # Pixel data belongs in separately saved PNG evidence, never JSONL.
        return {"image_metadata": {"mode": value.mode, "size": [value.width, value.height]}}
    if isinstance(value, (list, tuple)):
        return [_json_trace_value(item, f"{location}[{index}]") for index, item in enumerate(value)]
    if isinstance(value, dict):
        safe: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"Trace key at {location} must be str, got {type(key).__name__}.")
            safe[key] = _json_trace_value(item, f"{location}.{key}")
        return safe
    raise TypeError(f"Trace value at {location} is not JSON-safe: {type(value).__name__}.")


def write_trace(path: Path, record: dict) -> None:
    payload = dict(record)
    payload["timestamp"] = datetime.now().isoformat(timespec="milliseconds")
    encoded = json.dumps(_json_trace_value(payload), ensure_ascii=False, allow_nan=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(encoded + "\n")


def performance_metrics_path() -> Path:
    return BASE_DIR / "logs" / "performance_metrics.jsonl"


def successful_performance_samples(samples: list[dict]) -> list[dict]:
    """Keep only successful room samples with the measurements needed for medians."""
    return [sample for sample in samples if sample.get("success") is True
            and isinstance(sample.get("room_total_ms"), (int, float))
            and isinstance(sample.get("post_action_transition_ms"), (int, float))]


def compare_performance_samples(samples: list[dict]) -> dict[str, object]:
    """Conservatively compare local successful accelerated and baseline samples."""
    valid = successful_performance_samples(samples)
    accelerated = [sample for sample in valid if sample.get("accelerator_used") is True]
    baseline = [sample for sample in valid if sample.get("accelerator_enabled") is False]
    enabled_not_used = [sample for sample in valid if sample.get("accelerator_enabled") is True
                        and sample.get("accelerator_used") is False]
    if len(accelerated) < 3 or len(baseline) < 3:
        return {"status": "insufficient_evidence", "accelerated_samples": len(accelerated),
                "baseline_samples": len(baseline), "enabled_not_used_samples": len(enabled_not_used)}
    accelerated_room = statistics.median(float(sample["room_total_ms"]) for sample in accelerated)
    baseline_room = statistics.median(float(sample["room_total_ms"]) for sample in baseline)
    accelerated_transition = statistics.median(float(sample["post_action_transition_ms"]) for sample in accelerated)
    baseline_transition = statistics.median(float(sample["post_action_transition_ms"]) for sample in baseline)
    room_improvement = ((baseline_room - accelerated_room) / baseline_room * 100) if baseline_room > 0 else 0.0
    transition_improvement = ((baseline_transition - accelerated_transition) / baseline_transition * 100) if baseline_transition > 0 else 0.0
    return {
        "status": "improved" if room_improvement >= 15.0 else "no_confirmed_improvement",
        "accelerated_samples": len(accelerated), "baseline_samples": len(baseline),
        "enabled_not_used_samples": len(enabled_not_used),
        "accelerated_median_room_total_ms": accelerated_room,
        "baseline_median_room_total_ms": baseline_room,
        "accelerated_median_post_action_transition_ms": accelerated_transition,
        "baseline_median_post_action_transition_ms": baseline_transition,
        "room_total_improvement_percent": round(room_improvement, 3),
        "post_action_transition_improvement_percent": round(transition_improvement, 3),
    }


def load_performance_samples() -> list[dict]:
    path = performance_metrics_path()
    if not path.exists():
        return []
    samples: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            samples.append(record)
    return samples


def persist_successful_room_performance(performance: dict[str, object]) -> dict[str, object]:
    """Append one successful room sample then return the conservative local comparison."""
    sample = {
        "kind": "successful_room_performance",
        "success": True,
        "room_name": performance["room_name"],
        "accelerator_enabled": performance["accelerator_enabled"],
        "accelerator_used": performance["accelerator_used"],
        "room_total_ms": performance["room_total_ms"],
        "post_action_transition_ms": performance["post_action_transition_ms"],
        "accelerator_click_count": performance["accelerator_click_count"],
    }
    write_trace(performance_metrics_path(), sample)
    return compare_performance_samples(load_performance_samples())


def print_room_performance(performance: dict[str, object], comparison: dict[str, object] | None = None) -> None:
    total = float(performance["room_total_ms"]) / 1000
    transition = performance.get("post_action_transition_ms")
    transition_text = f"{float(transition) / 1000:.1f}s" if isinstance(transition, (int, float)) else "n/a"
    active = float(performance["accelerator_active_ms"]) / 1000
    print("Performance:\n"
          f"{performance['room_name']} total={total:.1f}s\n"
          f"post-action transition={transition_text}\n"
          f"accelerator active={active:.1f}s\n"
          f"bursts={performance['accelerator_burst_count']} clicks={performance['accelerator_click_count']}")
    if comparison is not None:
        print(f"Performance comparison: {comparison['status']} "
              f"(accelerated_samples={comparison['accelerated_samples']}, baseline_samples={comparison['baseline_samples']})")


def show_transitions() -> int:
    """Print the single shared config transition source without touching the browser."""
    config = json.loads((BASE_DIR / "config.json").read_text())
    for state_name, spec in config["states"].items():
        actions = spec.get("allowed_actions", [])
        if not actions:
            print(f"{state_name}:\n  no action")
            passive = spec.get("passive_transition")
            if passive:
                print(f"  passive_transition={passive.get('type')}\n  expected_next_states={passive.get('expected_next_states')}")
            continue
        for action in actions:
            expected = action.get("expected_next_states")
            if expected is None and action.get("expected_next_state"):
                expected = [action["expected_next_state"]]
            print(f"{state_name}:\n  {action.get('name', '<invalid>')}\n  expected_next_states={expected}\n  box={action.get('box')}")
    return 0


def show_rooms() -> int:
    """Print room definitions only; this is a read-only configuration diagnostic."""
    config = json.loads((BASE_DIR / "config.json").read_text())
    for name, room in config.get("rooms", {}).items():
        print(name)
        print(f"  entry={room.get('entry_states', [])}")
        print(f"  exit={room.get('exit_states', [])}")
        print("  local_steps:")
        for step in room.get("local_steps", []):
            print(f"    {step.get('source_state')} → {step.get('action')} → {step.get('expected_next_states')}")
        print(f"  local_anchors={room.get('local_anchors', [])}")
        print(f"  interruptions={room.get('interruptions', [])}")
    return 0


def read_validated_home_observation(log: logging.Logger, config: dict) -> HomeObservation | HomeObservationUnreadable:
    """Shared fresh-screenshot perception pipeline; it never clicks or writes."""
    try:
        rois = configured_rois(config)
        observation_config = config["perception"]["home_observation"]
        retries = int(observation_config["retries"])
        interval_seconds = int(observation_config["retry_interval_ms"]) / 1000.0
        if retries < 2 or interval_seconds < 0:
            raise ValueError("HOME observation retries must be at least 2 and retry_interval_ms must be non-negative.")
    except (KeyError, TypeError, ValueError) as error:
        log.error("Safety stop: HOME observation configuration is invalid: %s", error)
        print(f"Safety stop: HOME observation configuration is invalid: {error}")
        return HomeObservationUnreadable({"configuration": str(error)}, [], [])
    valid_samples = []
    raw_samples: list[dict[str, object]] = []
    screenshots: list[str] = []
    reasons: dict[str, str] = {}
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        for attempt in range(1, retries + 1):
            target.verify_and_focus()
            image, _window = dynamic_screenshot(target, config, BASE_DIR)
            detected = detect_state(image, config, BASE_DIR)
            screenshot = save_shot(image, f"HOME_OBSERVATION_SAMPLE_{attempt}" if detected.state == State.HOME else f"HOME_OBSERVATION_NOT_HOME_{attempt}")
            screenshots.append(str(screenshot))
            if detected.state != State.HOME:
                message = (f"Safety stop: --observe-home requires HOME; found {detected.state.value} "
                           f"(confidence={detected.confidence:.3f}, template={detected.template}). Evidence: {screenshot}")
                log.error(message)
                print(message)
                return HomeObservationUnreadable({"state": message}, raw_samples, screenshots)
            raw, ocr_diagnostics = smoke_ocr(
                image, rois,
                weeks_template_matching=observation_config["weeks_remaining"].get("template_matching"),
                fan_target_clear_settings=observation_config["fan_gap_to_target"].get("clear_marker"),
                stamina_settings=observation_config.get("stamina"),
            )
            raw_samples.append({"selected_raw": raw, "ocr": ocr_diagnostics})
            clear_evidence = ocr_diagnostics.get("fan_gap_to_target", {}).get("clear_marker", {})
            stamina_evidence = ocr_diagnostics.get("stamina", {}).get("stamina", {})
            stamina_adequate = stamina_evidence.get("adequate")
            parsed, sample_reasons = parse_home_sample(
                raw, config, fan_target_achieved=bool(clear_evidence.get("visible", False)),
                stamina_adequate=stamina_adequate,
            )
            log.info("HOME observation sample=%d/%d screenshot=%s raw_ocr=%s parsed=%s reasons=%s",
                     attempt, retries, screenshot, ocr_diagnostics, parsed, sample_reasons)
            print(f"HOME sample {attempt}/{retries}: confidence={detected.confidence:.3f}, template={detected.template}")
            for field in rois:
                if field == "weeks_remaining":
                    details = ocr_diagnostics[field]
                    if details.get("method") == "opencv_digit_template":
                        print(f"  raw {field}: template_scores={details['template']['candidate_scores']!r} selected_raw={raw[field]!r} template_error={details['selection_error']!r}")
                    else:
                        print(f"  raw {field}: generic_raw={details['generic_raw']!r} digit_raw={details['digit_raw']!r} preprocessed_raw={details['preprocessed_raw']!r} selected_raw={raw[field]!r}")
                    if details["debug_paths"]:
                        print(f"  weeks OCR debug images: {details['debug_paths']}")
                elif field == "stamina":
                    details = ocr_diagnostics[field]
                    print(f"  raw {field}: selected_raw={raw[field]!r} evidence={details.get('stamina')!r} error={details['selection_error']!r}")
                else:
                    print(f"  raw {field}: {raw[field]!r}")
                    if field == "fan_gap_to_target":
                        print(f"  fan target CLEAR marker: {ocr_diagnostics[field].get('clear_marker')!r}")
            if parsed is None:
                reasons = sample_reasons
                print(f"  parsed: UNREADABLE ({sample_reasons})")
            else:
                valid_samples.append(parsed)
                print(f"  parsed: {parsed}")
                committed = consistently_observed(valid_samples)
                if committed is not None:
                    # Mint provenance only after the shared multi-sample
                    # pipeline has verified HOME and committed a tuple.
                    committed = replace(
                        committed,
                        provenance=issue_home_provenance(str(screenshots[-1])),
                    )
                    log.info("HOME observation committed=%s screenshots=%s", committed, screenshots)
                    print(f"HomeObservation(season={committed.season}, weeks_remaining={committed.weeks_remaining}, fan_gap_to_target={committed.fan_gap_to_target}, fan_target_achieved={committed.fan_target_achieved}, stamina_adequate={committed.stamina_adequate})")
                    print("Consistency: the same complete tuple was observed in at least two successful fresh HOME samples.")
                    return committed
            if attempt < retries:
                time.sleep(interval_seconds)
    unreadable = HomeObservationUnreadable(
        reasons=reasons or {"observation": "no complete tuple repeated across two successful samples"},
        raw_samples=raw_samples,
        screenshots=screenshots,
    )
    log.error("HOME observation UNREADABLE=%s", unreadable)
    print(f"HomeObservation UNREADABLE: {unreadable}")
    return unreadable


def observe_home() -> int:
    """Print the shared validated HOME perception result; never clicks or writes."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    result = read_validated_home_observation(log, config)
    return 0 if isinstance(result, HomeObservation) else 2


def teach_home_roi(field: str) -> int:
    """Interactively re-teach one HOME numeric ROI; never clicks the game."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        target.verify_and_focus()
        image, window = dynamic_screenshot(target, config, BASE_DIR)
        detected = detect_state(image, config, BASE_DIR)
    evidence = save_shot(image, f"HOME_ROI_TEACH_{field.upper()}")
    if detected.state != State.HOME:
        message = (f"Safety stop: --teach-home-roi requires HOME; found {detected.state.value} "
                   f"(confidence={detected.confidence:.3f}, template={detected.template}). Evidence: {evidence}")
        log.error(message)
        print(message)
        return 2

    print(f"HOME verified: confidence={detected.confidence:.3f}, template={detected.template}")
    print(f"Evidence screenshot: {evidence}")
    result = capture_home_observation_roi(image, window, config, field)
    if result is None:
        return 2
    raw, diagnostics = smoke_ocr(
        image, {field: result["roi"]},
        weeks_template_matching=config["perception"]["home_observation"]["weeks_remaining"].get("template_matching"),
        fan_target_clear_settings=config["perception"]["home_observation"].get("fan_gap_to_target", {}).get("clear_marker"),
        stamina_settings=config["perception"]["home_observation"].get("stamina"),
    )
    details = diagnostics[field]
    if field == "stamina":
        print(f"Stamina smoke test: selected_raw={raw[field]!r} evidence={details.get('stamina')!r} error={details['selection_error']!r}")
    else:
        print(f"OCR smoke test {field}: generic_raw={details['generic_raw']!r} digit_raw={details['digit_raw']!r} preprocessed_raw={details['preprocessed_raw']!r} selected_raw={raw[field]!r}")
    return 0


def teach_home_week_digit(digit: str) -> int:
    """Capture one observed HOME week digit from the pre-taught tight ROI."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        target.verify_and_focus()
        image, _window = dynamic_screenshot(target, config, BASE_DIR)
        detected = detect_state(image, config, BASE_DIR)
    evidence = save_shot(image, f"HOME_WEEK_DIGIT_TEACH_{digit}")
    if detected.state != State.HOME:
        message = (f"Safety stop: --teach-home-week-digit requires HOME; found {detected.state.value} "
                   f"(confidence={detected.confidence:.3f}, template={detected.template}). Evidence: {evidence}")
        log.error(message)
        print(message)
        return 2
    result = capture_home_week_digit_template(image, config, digit)
    print(f"HOME week digit template saved: digit={digit} template={result['template']} roi={result['roi']}\n"
          f"evidence={evidence}\nconfig backup: {result['backup']}")
    return 0


def teach_audition_target(amount: int) -> int:
    """Capture a reward marker from a manually positioned AUDITION_SELECT page; never clicks."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    with BrowserTarget(config["browser"]["cdp_url"]) as target:
        target.verify_and_focus()
        image, window = dynamic_screenshot(target, config, BASE_DIR)
        detected = detect_state(image, config, BASE_DIR)
    evidence = save_shot(image, f"AUDITION_TARGET_{amount}_TEACH")
    if detected.state.value != "AUDITION_SELECT":
        message = (f"Safety stop: --teach-audition-target requires AUDITION_SELECT; found "
                   f"{detected.state.value} (confidence={detected.confidence:.3f}, "
                   f"template={detected.template}). Evidence: {evidence}")
        log.error(message)
        print(message)
        return 2
    result = capture_audition_target_from_image(image, window, config, amount, base_dir=BASE_DIR)
    if result is None:
        print("Cancelled: no audition reward marker was saved.")
        return 2
    print(f"Audition target feature saved: amount={amount} state=AUDITION_TARGET_{amount} "
          f"template={result['template']}\nevidence={evidence}\nconfig backup: {result['backup']}")
    return 0


def decide_home_diagnostic() -> int:
    """Read HOME, then print a pure policy decision without entering a room."""
    log = setup_logging()
    config = load_config_with_run_state()
    observation = read_validated_home_observation(log, config)
    if not isinstance(observation, HomeObservation):
        print("HOME decision unavailable: validated HomeObservation was not obtained.")
        return 2
    policy_state = resolve_policy_state(
        season=observation.season,
        weeks_remaining=observation.weeks_remaining,
        route_plan=config.get("run_state", {}).get("route_deadline"),
    )
    decision = decide_home(observation, policy_state=policy_state, config=config)
    log.info("HOME decision observation=%s action=%s reason=%s", observation, decision.action, decision.reason)
    print(f"HomeDecision(action={decision.action!r}, reason={decision.reason!r})")
    return 0


def home_tick_trace_path() -> Path:
    return BASE_DIR / "logs" / f"home_tick_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl"


def read_home_season_from_image(image, config: dict) -> int | None:
    """Read only the existing season field for same-season boundary verification."""
    season_roi = configured_rois(config)["season"]
    raw, _diagnostics = smoke_ocr(image, {"season": season_roi})
    value, _error = parse_season(raw["season"])
    return value


def vocal_lesson_consumes_one_week(config: dict) -> bool:
    actions = config.get("states", {}).get("PRODUCE_MENU", {}).get("allowed_actions", [])
    return any(action.get("name") == "vocal_lesson" and action.get("consumes_one_week") is True for action in actions)


def format_week_template_auto_learning(learning: dict[str, object] | None) -> str | None:
    """Keep the already-persisted learning result visible in the HomeTick summary."""
    if not learning:
        return None
    previous = learning.get("previous_week", "?")
    inferred = learning.get("inferred_week", "?")
    status = learning.get("status", "UNKNOWN")
    score = learning.get("verification_score")
    margin = learning.get("verification_margin")
    suffix = ""
    if isinstance(score, (int, float)):
        suffix += f" score={float(score):.5f}"
    if isinstance(margin, (int, float)):
        suffix += f" margin={float(margin):.4f}"
    if not suffix and learning.get("reason"):
        suffix = f" reason={learning['reason']}"
    return f"WeekTemplateAutoLearn: {previous} -> {inferred} {status}{suffix}"


def reflection_sp_settings(config: dict) -> dict:
    settings = config.get("reflection", {}).get("remaining_sp", {})
    roi = settings.get("roi")
    if not isinstance(roi, list):
        raise ValueError("REFLECTION remaining SP ROI has not been taught.")
    validate_normalized_box(roi)
    retries = int(settings.get("retries", 3))
    interval = int(settings.get("retry_interval_ms", 250))
    if retries < 2 or interval < 0:
        raise ValueError("Invalid REFLECTION remaining SP observation settings.")
    return {"roi": roi, "retries": retries, "interval_seconds": interval / 1000.0}


def read_committed_reflection_sp(target: BrowserTarget, config: dict, *, label: str) -> tuple[int | None, dict]:
    """Read remaining SP twice consistently; unreadable data never drives purchases."""
    settings = reflection_sp_settings(config)
    samples: list[dict] = []
    counts: dict[int, int] = {}
    try:
        import pytesseract
    except ImportError:
        return None, {"reason": "pytesseract unavailable", "samples": samples}
    for number in range(1, settings["retries"] + 1):
        image = target_screenshot(target, config)
        detected = detect_state(image, config, BASE_DIR)
        if detected.state.value != "REFLECTION":
            return None, {"reason": f"REFLECTION no longer detected ({detected.state.value})", "samples": samples,
                          "state": detected.state.value}
        crop = crop_normalized(image, settings["roi"])
        crop_path = save_shot(crop, f"REFLECTION_SP_{label}_{number}")
        generic_raw = pytesseract.image_to_string(crop, config="--psm 7")
        digits_raw = pytesseract.image_to_string(crop, config="--psm 7 -c tessedit_char_whitelist=0123456789,.")
        parsed = parse_remaining_sp(digits_raw if digits_raw.strip() else generic_raw)
        sample = {"attempt": number, "screenshot": str(crop_path), "generic_raw": generic_raw,
                  "digits_raw": digits_raw, "selected_raw": parsed.raw, "value": parsed.value,
                  "reason": parsed.reason}
        samples.append(sample)
        if parsed.value is not None:
            counts[parsed.value] = counts.get(parsed.value, 0) + 1
            if counts[parsed.value] >= 2:
                return parsed.value, {"samples": samples, "committed": parsed.value, "roi": settings["roi"]}
        if number < settings["retries"] and settings["interval_seconds"]:
            time.sleep(settings["interval_seconds"])
    return None, {"reason": "no repeated consistent SP observation", "samples": samples, "roi": settings["roi"]}


def run_home_tick(live: bool, observation_override: HomeObservation | None = None) -> int:
    """Make one HOME decision and, only when live, run at most one supported room."""
    log = setup_logging()
    config = load_config_with_run_state()
    trace = home_tick_trace_path()
    try:
        observation = observation_override or read_validated_home_observation(log, config)
        if not isinstance(observation, HomeObservation):
            write_trace(trace, {"kind": "home_tick", "result": "POLICY_UNREADABLE", "observation": repr(observation)})
            print(f"HomeTick: observation=UNREADABLE\nresult=POLICY_UNREADABLE\ntrace={trace}")
            return 2
        if live and not valid_home_provenance(observation.provenance):
            detail = "live execution requires sealed provenance from a committed fresh HOME observation"
            write_trace(trace, {"kind": "home_tick", "result": "HOME_PROVENANCE_REQUIRED", "detail": detail})
            print(f"HomeTick: {detail}\ntrace={trace}")
            return 2
        if live and config.get("run_state", {}).get("run_id") is None:
            raise ValueError("ACTIVE_RUN_REQUIRED_FOR_PROGRESS_WRITE")
        completed = config.get("run_state", {}).get("season3", {}).get("reflection_opening_completed", False)
        if observation.season == 3 and not completed:
            ready, prephase_reason = season3_reflection_prephase_status(config)
            if not ready:
                write_trace(trace, {"kind": "season3_reflection_prephase", "status": "UNSUPPORTED_REFLECTION",
                                    "reason": prephase_reason})
                print(f"HomeTick: season=3 pre-action reflection phase unavailable: {prephase_reason}\ntrace={trace}")
                return 2
        # Derive the decision boundary from the freshly committed HOME facts;
        # never rely on a caller manually injecting the S1 final-week flag.
        policy_state = resolve_policy_state(
            season=observation.season,
            weeks_remaining=observation.weeks_remaining,
            route_plan=config.get("run_state", {}).get("route_deadline"),
        )
        policy_state["fresh_fields"] = {"season", "weeks_remaining", "fan_gap_to_target", "stamina"}
        decision = decide_home(observation, policy_state=policy_state, config=config)
        write_trace(trace, {"kind": "home_tick_decision", "observation": {
            "season": observation.season, "weeks_remaining": observation.weeks_remaining,
            "fan_gap_to_target": observation.fan_gap_to_target},
            "decision": {"action": decision.action, "reason": decision.reason}, "live": live})
        boundary_evidence: list[str] = []
        boundary_capture: dict[str, object] = {}
        room_context = VocalRoomResultContext()

        def verify_home_boundary() -> tuple[str, bool]:
            with BrowserTarget(config["browser"]["cdp_url"]) as target:
                image = target_screenshot(target, config)
                detected = detect_state(image, config, BASE_DIR)
            path = save_shot(image, "HOME_TICK_FINAL_BOUNDARY")
            boundary_evidence.append(str(path))
            boundary_capture.update({"image": image, "state": detected.state.value, "screenshot": str(path)})
            return detected.state.value, detected.state == State.HOME

        result = execute_home_tick(
            decision,
            live=live,
            tool_registry={
                "VOCAL": lambda context, tool_live: execute_vocal(
                    context,
                    live=tool_live,
                    run_vocal_room_once=lambda: run_vocal_room(
                        dry_run=False, result_context=room_context,
                    ),
                    observe_home_boundary=verify_home_boundary,
                ),
            },
            run_rest_room_once=lambda: run_rest_room(dry_run=False),
            verify_home_boundary=verify_home_boundary,
            # The observation above is the committed, fresh HOME entry for
            # this tick.  REST's Room adapter requires both pieces of
            # evidence before it may invoke the legacy executor.
            home_provenance=observation.provenance,
        )
        if live and result.status == "TICK_SUCCESS":
            durable_state = dict(config["run_state"])
            durable_state["last_completed_week"] = {
                "entry_season": observation.season,
                "entry_weeks_remaining": observation.weeks_remaining,
                "action": decision.action, "final_state": result.final_state,
            }
            save_active_run_state(
                REGISTRY_PATH, durable_state, boundary="COMPLETED_WEEK",
                evidence=durable_state["last_completed_week"],
                evidence_paths=tuple(Path(path) for path in boundary_evidence),
            )
            if isinstance(boundary_capture.get("image"), PILImage.Image):
                completed_season = read_home_season_from_image(boundary_capture["image"], config)
                if completed_season is not None and completed_season != observation.season:
                    durable_state["season_transition"] = {
                        "from_season": observation.season, "to_season": completed_season}
                    save_active_run_state(
                        REGISTRY_PATH, durable_state, boundary="SEASON_TRANSITION",
                        evidence=durable_state["season_transition"],
                        evidence_paths=tuple(Path(path) for path in boundary_evidence),
                    )
            persist_session_end(REGISTRY_PATH, reason="HOME_TICK_COMPLETE")
        learning: dict[str, object] | None = None
        if result.status == "TICK_SUCCESS" and isinstance(boundary_capture.get("image"), PILImage.Image):
            boundary_image = boundary_capture["image"]
            boundary_season = read_home_season_from_image(boundary_image, config)

            def fresh_home_capture() -> FreshHomeCapture:
                with BrowserTarget(config["browser"]["cdp_url"]) as target:
                    fresh_image = target_screenshot(target, config)
                    fresh_detected = detect_state(fresh_image, config, BASE_DIR)
                fresh_path = save_shot(fresh_image, "HOME_TICK_WEEK_TEMPLATE_VERIFY")
                return FreshHomeCapture(
                    image=fresh_image,
                    state=fresh_detected.state.value,
                    season=read_home_season_from_image(fresh_image, config) if fresh_detected.state == State.HOME else None,
                    screenshot=str(fresh_path),
                )

            learning = auto_learn_week_digit_from_progression(
                boundary_image, config,
                WeekLearningEvidence(
                    previous_week=observation.weeks_remaining,
                    previous_season=observation.season,
                    action_name=room_context.action_sent,
                    action_sent=room_context.action_sent == "vocal_lesson",
                    action_completed_at_home=room_context.action_associated_with_home_completion == "vocal_lesson",
                    consumes_one_week=vocal_lesson_consumes_one_week(config),
                    boundary_season=boundary_season,
                ),
                fresh_home_capture,
            )
            write_trace(trace, {"kind": "week_template_auto_learning", "room": result.room,
                                "room_context": {"action_sent": room_context.action_sent,
                                                 "action_sent_timestamp": room_context.action_sent_timestamp,
                                                 "action_associated_with_home_completion": room_context.action_associated_with_home_completion,
                                                 "room_exit_state": room_context.room_exit_state,
                                                 "performance": room_context.performance},
                                "details": learning})
        goal_parameters = dict(result.goal_context.parameters) if result.goal_context else None
        if goal_parameters is not None and HOME_PROVENANCE_PARAMETER in goal_parameters:
            goal_parameters[HOME_PROVENANCE_PARAMETER] = home_provenance_metadata(
                goal_parameters[HOME_PROVENANCE_PARAMETER],
            )
        write_trace(trace, {"kind": "home_tick_result", "status": result.status,
                            "room": result.room, "final_state": result.final_state,
                            "detail": result.detail, "boundary_evidence": boundary_evidence,
                            "goal": ({"type": result.goal_context.goal,
                                      "success_state": result.goal_context.success_state,
                                      "parameters": goal_parameters,
                                      "allowed_events": sorted(result.goal_context.allowed_events)}
                                     if result.goal_context else None),
                            "week_template_learning": learning,
                            "room_performance": room_context.performance})
        learning_summary = format_week_template_auto_learning(learning)
        print(f"HomeTick: observation={observation}\ndecision={decision}\nroom={result.room}\nresult={result.status}\nfinal_state={result.final_state}"
              f"{chr(10) + learning_summary if learning_summary else ''}\ntrace={trace}")
        if result.status in {"TICK_SUCCESS", "DRY_RUN", "UNSUPPORTED_DECISION"}:
            return 0
        return 2
    except (TargetError, ValueError, OSError) as error:
        write_trace(trace, {"kind": "home_tick_result", "status": "SAFETY_ERROR", "detail": str(error)})
        log.error("HOME tick safety stop: %s", error)
        print(f"HomeTick safety stop: {error}\ntrace={trace}")
        return 2


def mark_season3_reflection_complete() -> int:
    """Explicit human attestation; requires a freshly committed Season-3 HOME."""
    log = setup_logging()
    config = load_config_with_run_state()
    try:
        if config.get("run_state", {}).get("run_id") is None:
            raise ValueError("ACTIVE_RUN_REQUIRED_FOR_PROGRESS_WRITE")
        observation = read_validated_home_observation(log, config)
        if not isinstance(observation, HomeObservation) or observation.season != 3:
            print("Refusing mark: committed Season 3 HOME observation required.")
            return 2
        run_state = copy.deepcopy(config["run_state"])
        run_state.setdefault("season3", {})["reflection_opening_completed"] = True
        state_path = save_active_run_state(
            REGISTRY_PATH, run_state, boundary="MANUAL_REFLECTION_COMPLETION",
            evidence={"source": "HUMAN_ATTESTATION", "season": observation.season,
                      "weeks_remaining": observation.weeks_remaining,
                      "fan_gap_to_target": observation.fan_gap_to_target})
        trace = home_tick_trace_path()
        write_trace(trace, {"kind": "manual_season3_reflection_completion", "timestamp": datetime.now().isoformat(),
                            "observation": {"season": observation.season, "weeks_remaining": observation.weeks_remaining,
                                            "fan_gap_to_target": observation.fan_gap_to_target}, "run_state": str(state_path)})
        print(f"Season3 reflection opening marked complete. run_state={state_path}\ntrace={trace}")
        return 0
    except (TargetError, ValueError, OSError) as error:
        print(f"Refusing mark: {error}")
        return 2


def mark_season3_auditions_complete() -> int:
    """Explicit human attestation; requires a freshly committed Season-3 HOME."""
    log = setup_logging()
    config = load_config_with_run_state()
    try:
        if config.get("run_state", {}).get("run_id") is None:
            raise ValueError("ACTIVE_RUN_REQUIRED_FOR_PROGRESS_WRITE")
        observation = read_validated_home_observation(log, config)
        if not isinstance(observation, HomeObservation) or observation.season != 3:
            print("Refusing mark: committed Season 3 HOME observation required.")
            return 2
        run_state = copy.deepcopy(config["run_state"])
        season3 = run_state.setdefault("season3", {})
        season3["audition_40k_completed"] = True
        season3["audition_50k_completed"] = True
        state_path = save_active_run_state(
            REGISTRY_PATH, run_state, boundary="AUDITION_RESULT",
            evidence={"source": "HUMAN_ATTESTATION", "season": observation.season,
                      "weeks_remaining": observation.weeks_remaining,
                      "fan_gap_to_target": observation.fan_gap_to_target})
        trace = home_tick_trace_path()
        write_trace(trace, {"kind": "manual_season3_auditions_completion", "timestamp": datetime.now().isoformat(),
                            "observation": {"season": observation.season, "weeks_remaining": observation.weeks_remaining,
                                            "fan_gap_to_target": observation.fan_gap_to_target}, "run_state": str(state_path)})
        print(f"Season3 auditions (+40k and +50k) marked complete. run_state={state_path}\ntrace={trace}")
        return 0
    except (TargetError, ValueError, OSError) as error:
        print(f"Refusing mark: {error}")
        return 2


def season_trial_trace_path(season: int) -> Path:
    return BASE_DIR / "logs" / f"season_{season}_trial_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl"


def season_trial_summary(*, season: int, ticks: int, reason: str, final_state: str,
                         final_observation: HomeObservation | None, trace: Path) -> None:
    week = final_observation.weeks_remaining if final_observation is not None else None
    observed_season = final_observation.season if final_observation is not None else None
    print(f"Season {season} trial finished\n"
          f"ticks completed={ticks}\n"
          f"stop reason={reason}\n"
          f"final state={final_state}\n"
          f"final season/week={observed_season}/{week}\n"
          f"trace={trace}")


def run_season_trial(season: int, live: bool, max_ticks: int) -> int:
    """Run one bounded season using only decisions executable by HomeTick.

    No route policy is hidden here: this coordinator simply refuses a decision
    that has no verified executable room.  Each iteration starts from a new,
    committed HOME observation and delegates exactly one bounded HOME tick.
    """
    if season != 3:
        raise ValueError("Only Season 3 trial mode is currently supported.")
    if max_ticks < 1:
        raise ValueError("max_ticks must be positive.")
    log = setup_logging()
    config = load_config_with_run_state()
    trace = season_trial_trace_path(season)
    ticks = 0
    final_state = State.UNKNOWN.value
    final_observation: HomeObservation | None = None
    try:
        while ticks < max_ticks:
            observation = read_validated_home_observation(log, config)
            if not isinstance(observation, HomeObservation):
                write_trace(trace, {"kind": "stop", "reason": "POLICY_UNREADABLE",
                                    "observation": repr(observation), "ticks_completed": ticks})
                season_trial_summary(season=season, ticks=ticks, reason="POLICY_UNREADABLE",
                                     final_state=final_state, final_observation=final_observation, trace=trace)
                return 2
            final_observation = observation
            final_state = State.HOME.value
            if observation.season != season:
                if live:
                    durable_state = dict(load_config_with_run_state()["run_state"])
                    durable_state["home_observation"] = {
                        "season": observation.season, "weeks_remaining": observation.weeks_remaining,
                        "fan_gap_to_target": observation.fan_gap_to_target}
                    save_active_run_state(REGISTRY_PATH, durable_state, boundary="SEASON_TRANSITION",
                                          evidence=durable_state["home_observation"])
                    persist_session_end(REGISTRY_PATH, reason="SEASON_CHANGED")
                write_trace(trace, {"kind": "stop", "reason": "SEASON_CHANGED", "ticks_completed": ticks,
                                    "observation": {"season": observation.season,
                                                    "weeks_remaining": observation.weeks_remaining,
                                                    "fan_gap_to_target": observation.fan_gap_to_target,
                                                    "stamina_adequate": observation.stamina_adequate}})
                season_trial_summary(season=season, ticks=ticks, reason="SEASON_CHANGED",
                                     final_state=final_state, final_observation=final_observation, trace=trace)
                return 0 if observation.season == 4 else 2
            policy_state = resolve_policy_state(
                season=observation.season,
                weeks_remaining=observation.weeks_remaining,
                route_plan=config.get("run_state", {}).get("route_deadline"),
            )
            policy_state["fresh_fields"] = {"season", "weeks_remaining", "fan_gap_to_target", "stamina"}
            decision = decide_home(observation, policy_state=policy_state, config=config)
            room = "VOCAL_ROOM" if decision.action == "VOCAL" else ("REST_ROOM" if decision.action == "REST" else None)
            write_trace(trace, {"kind": "season_trial_decision", "tick": ticks + 1,
                                "observation": {"season": observation.season,
                                                "weeks_remaining": observation.weeks_remaining,
                                                "fan_gap_to_target": observation.fan_gap_to_target},
                                "decision": {"action": decision.action, "reason": decision.reason},
                                "room": room, "live": live})
            if room is None:
                detail = ("Season 3 needs explicitly configured route state/counters and a verified mapping "
                          "from that route step to VOCAL or AUDITION; HOME fan_gap_to_target alone is not "
                          "cumulative-fan evidence for this season.")
                write_trace(trace, {"kind": "stop", "reason": "UNSUPPORTED_DECISION", "tick": ticks + 1,
                                    "decision": decision.action, "detail": detail})
                print(f"SeasonTrial tick={ticks + 1} season={observation.season} week={observation.weeks_remaining} "
                      f"fan_gap={observation.fan_gap_to_target} decision={decision.action} room=None "
                      "result=UNSUPPORTED_DECISION duration=0.0s")
                season_trial_summary(season=season, ticks=ticks, reason="UNSUPPORTED_DECISION",
                                     final_state=final_state, final_observation=final_observation, trace=trace)
                return 0
            if not live:
                write_trace(trace, {"kind": "season_trial_tick", "tick": ticks + 1, "room": room,
                                    "result": "DRY_RUN", "duration_ms": 0.0})
                print(f"SeasonTrial tick={ticks + 1} season={observation.season} week={observation.weeks_remaining} "
                      f"fan_gap={observation.fan_gap_to_target} decision={decision.action} room={room} "
                      "result=DRY_RUN duration=0.0s")
                season_trial_summary(season=season, ticks=ticks, reason="DRY_RUN",
                                     final_state=final_state, final_observation=final_observation, trace=trace)
                return 0
            started = time.monotonic()
            # Pass the just-committed observation so the policy decision and
            # executed tick cannot diverge between two independent OCR reads.
            code = run_home_tick(live=True, observation_override=observation)
            duration_ms = round((time.monotonic() - started) * 1000, 3)
            result = "TICK_SUCCESS" if code == 0 else "TICK_FAILURE"
            write_trace(trace, {"kind": "season_trial_tick", "tick": ticks + 1, "room": room,
                                "result": result, "duration_ms": duration_ms})
            print(f"SeasonTrial tick={ticks + 1} season={observation.season} week={observation.weeks_remaining} "
                  f"fan_gap={observation.fan_gap_to_target} decision={decision.action} room={room} "
                  f"result={result} duration={duration_ms / 1000:.1f}s")
            if code != 0:
                season_trial_summary(season=season, ticks=ticks, reason="TICK_FAILURE",
                                     final_state=final_state, final_observation=final_observation, trace=trace)
                return 2
            ticks += 1
        write_trace(trace, {"kind": "stop", "reason": "MAX_TICKS", "ticks_completed": ticks})
        season_trial_summary(season=season, ticks=ticks, reason="MAX_TICKS",
                             final_state=final_state, final_observation=final_observation, trace=trace)
        return 0
    except (TargetError, ValueError, OSError) as error:
        write_trace(trace, {"kind": "stop", "reason": "SAFETY_ERROR", "detail": str(error),
                            "ticks_completed": ticks})
        log.error("Season trial safety stop: %s", error)
        season_trial_summary(season=season, ticks=ticks, reason="SAFETY_ERROR",
                             final_state=final_state, final_observation=final_observation, trace=trace)
        return 2


def room_trace_path(room_name: str) -> Path:
    return BASE_DIR / "logs" / f"room_{room_name.lower()}_{datetime.now():%Y%m%d_%H%M%S_%f}.jsonl"


def room_summary(room_name: str, reason: str, last_state: str, trace: Path, screenshot: Path | None = None) -> None:
    print(f"Room run finished: {room_name}\nReason: {reason}\nLast state: {last_state}\nEvidence: {screenshot or 'none'}\nTrace: {trace}")


def room_step_action(config: dict, step: dict) -> dict:
    """Resolve a room step through the existing shared state action registry."""
    source = step.get("source_state")
    requested_name = step.get("action")
    if not isinstance(requested_name, str) or not requested_name:
        raise ValueError(f"Room step {source} is missing an explicit action name.")
    action = configured_action(config, source, requested_name)
    if action["expected_next_states"] != step.get("expected_next_states"):
        raise ValueError(f"Room step {source}/{action['name']} no longer matches shared transition evidence.")
    return action


def classify_local_transition(state: str, expected_next_states: list[str], interruptions: list[str],
                              exit_states: list[str] = ()) -> str:
    """Classify a local result with room boundaries before step-local evidence."""
    if state in exit_states:
        return "ROOM_EXIT"
    if state in interruptions:
        return "INTERRUPTION"
    if state in expected_next_states:
        return "EXPECTED"
    return "UNEXPECTED_TRANSITION"


def synthetic_local_interruption_outcome(initial_state: str, expected_next_states: list[str], interruptions: list[str],
                                        handler_states: list[str]) -> str:
    """Offline model of bounded interruption chaining at a local boundary."""
    state = initial_state
    seen: set[str] = set()
    for next_state in [state, *handler_states]:
        if next_state == "HOME":
            return "ROOM_EXIT"
        kind = classify_local_transition(next_state, expected_next_states, interruptions, ["HOME"])
        if kind == "ROOM_EXIT":
            return "ROOM_EXIT"
        if kind == "EXPECTED":
            return "LOCAL_RESUME"
        if kind == "UNEXPECTED_TRANSITION":
            return "UNEXPECTED_TRANSITION"
        if next_state in seen:
            return "ROOM_INTERRUPTED"
        seen.add(next_state)
        if next_state == "CHOICE_REQUIRED":
            return "ROOM_INTERRUPTED"
    return "ROOM_INTERRUPTED"


def synthetic_promise_transition_outcome(observations: list[tuple[float | None, str | None]],
                                         threshold: float = 0.995, streak_required: int = 3) -> str:
    """Offline counterpart of Promise's no-click, transition-aware observer."""
    similarities: list[float] = []
    for similarity, known_state in observations:
        if known_state == "HOME":
            return "ROOM_EXIT"
        if known_state is not None:
            return "ROOM_INTERRUPTED" if known_state == "CHOICE_REQUIRED" else "UNEXPECTED_UI"
        if similarity is not None:
            similarities.append(similarity)
            if stable_unknown_streak(similarities, threshold) >= streak_required:
                return "CONFIRMED_UNKNOWN"
    return "TRANSITION_TIMEOUT"


def frame_similarity(first, second) -> float:
    """Deterministic mean-absolute-difference similarity for unknown stability only."""
    a = np.asarray(first.convert("L"), dtype=np.int16)
    b = np.asarray(second.convert("L"), dtype=np.int16)
    if a.shape != b.shape:
        return 0.0
    return max(0.0, 1.0 - float(np.mean(np.abs(a - b))) / 255.0)


def stable_unknown_streak(similarities: list[float], threshold: float) -> int:
    """Return the consecutive stable tail length; earlier transition frames do not matter."""
    streak = 0
    for value in reversed(similarities):
        if value < threshold:
            break
        streak += 1
    return streak


def synthetic_unknown_outcome(observations: list[tuple[float | None, str | None]], threshold: float, streak_required: int) -> str:
    """Pure counterpart of confirmation semantics for offline regression coverage."""
    similarities: list[float] = []
    for similarity, known_state in observations:
        if known_state is not None:
            return f"KNOWN:{known_state}"
        if similarity is None:
            continue
        similarities.append(similarity)
        if stable_unknown_streak(similarities, threshold) >= streak_required:
            return "CONFIRMED_UNKNOWN"
    return "TRANSITION_TIMEOUT"


def synthetic_short_unknown_outcome(observations: list[tuple[float | None, str | None]], *, allow_transition_continue: bool,
                                    threshold: float = 0.995, streak_required: int = 3) -> str:
    """Offline equivalent of the short classifier's context-sensitive terminal result."""
    outcome = synthetic_unknown_outcome(observations, threshold, streak_required)
    if outcome == "TRANSITION_TIMEOUT" and allow_transition_continue:
        return "TRANSITION_IN_PROGRESS"
    return outcome


def synthetic_vocal_pending_path(short_observations: list[tuple[float | None, str | None]],
                                 fallback_observations: list[tuple[float | None, str | None]], room: dict) -> tuple[str, bool]:
    """Regression model for transient post-click frames entering the existing fallback."""
    short = synthetic_short_unknown_outcome(short_observations, allow_transition_continue=True)
    if short == "CONFIRMED_UNKNOWN":
        return short, False
    if short != "TRANSITION_IN_PROGRESS":
        return short, False
    outcome = synthetic_post_vocal_outcome("TIMEOUT", fallback_observations, room)
    return ("ROOM_EXIT" if outcome == "ROOM_EXIT" else outcome), True


def synthetic_accelerated_post_vocal_outcome(classifier_outcomes: list[str], room: dict, *, action_sent: bool,
                                             dry_run: bool = False) -> tuple[str, int, int]:
    """Offline transaction model: unresolved post-Vocal frames may request a burst.

    Returns (outcome, planned_bursts, actual_bursts).  It deliberately receives
    already-classified observer outcomes: destination semantics stay outside the
    accelerator itself.
    """
    planned_bursts = 0
    actual_bursts = 0
    for observed in classifier_outcomes:
        if observed in {State.UNKNOWN.value, "CONFIRMED_UNKNOWN", "TRANSITION_IN_PROGRESS"}:
            if action_sent:
                planned_bursts += 1
                if not dry_run:
                    actual_bursts += 1
            continue
        if observed == "TRANSITION_TIMEOUT":
            return "TRANSITION_TIMEOUT", planned_bursts, actual_bursts
        return post_vocal_outcome(Detection(observed), room), planned_bursts, actual_bursts
    return "TRANSITION_TIMEOUT", planned_bursts, actual_bursts


def synthetic_battle_speed_target(observed_speeds: list[int | None], *,
                                  effects: list[bool] | None = None,
                                  max_clicks: int = 2) -> tuple[str, int]:
    """Offline model for bounded speed cycling toward 3x."""
    if not observed_speeds or observed_speeds[0] not in {1, 2, 3}:
        return "SPEED_UNKNOWN", 0
    speed = observed_speeds[0]
    clicks = 0
    while speed != 3 and clicks < max_clicks:
        if effects is not None and (clicks >= len(effects) or not effects[clicks]):
            return "SPEED_EFFECT_NOT_VERIFIED", clicks + 1
        clicks += 1
        if clicks >= len(observed_speeds) or observed_speeds[clicks] not in {1, 2, 3}:
            return "SPEED_UNKNOWN", clicks
        speed = observed_speeds[clicks]
    return ("SPEED_TARGET_REACHED" if speed == 3 else "SPEED_TARGET_NOT_REACHED"), clicks


def synthetic_audition_battle_outcome(step_states: list[str], completion_outcome: str) -> tuple[str, list[str]]:
    """Offline model: bounded speed targeting, Auto once, then passive completion."""
    actions = ["battle_speed_cycle", "battle_auto_on"]
    if step_states != ["AUDITION_BATTLE", "AUDITION_BATTLE"]:
        return "UNEXPECTED_TRANSITION", actions[:len(step_states)]
    if completion_outcome == "AUDITION_RESULT":
        return "AUDITION_RESULT", actions
    if completion_outcome in {"CONFIRMED_UNKNOWN", "TRANSITION_TIMEOUT"}:
        return completion_outcome, actions
    return "UNEXPECTED_UI", actions


def synthetic_capability_dispatch_outcome(state: str, *, capability_available: bool,
                                          immediate_state: str | None = None) -> str:
    """Offline model: recognised controls are acted on, risky/unknown UI is not."""
    if state == State.UNKNOWN.value or state in HIGH_RISK_CAPABILITY_STATES:
        return "NO_GENERIC_CONTROL"
    if not capability_available:
        return "NO_GENERIC_CONTROL"
    return f"CONTROL_EXECUTED:{immediate_state or state}"


def synthetic_post_audition_cleanup_outcome(observations: list[str]) -> tuple[str, list[str]]:
    """Offline completion model for the bounded post-audition cleanup flow."""
    controls = {
        "AUDITION_RESULT_DIALOGUE": "audition_result_dialogue_continue",
        "DIALOGUE_FAST_FORWARD_OFF": "dialogue_fast_forward_on",
    }
    terminal = {"HOME", "SEASON_RESULT"}
    risky = {"CHOICE_REQUIRED", "AUDITION_CHOICE", "PROMISE_CHOICE", "CONFIRM", "ERROR_POPUP"}
    used: list[str] = []
    for state in observations:
        if state == "CONFIRMED_UNKNOWN":
            return "CONFIRMED_UNKNOWN", used
        if state == "TIMEOUT":
            return "CLEANUP_TIMEOUT", used
        if state in terminal:
            return "CLEANUP_COMPLETE", used
        if state in risky:
            return "ROOM_INTERRUPTED", used
        action = controls.get(state)
        if action is not None:
            if action not in used:
                used.append(action)
            continue
        continue
    return "CLEANUP_TIMEOUT", used


def post_audition_entry_allowed(cleanup: dict, state: str) -> bool:
    """Return whether a known state is an allowed cleanup resume point."""
    return state in cleanup.get("entry_states", [])


def post_audition_generic_advance_action(config: dict) -> dict:
    """Use the already-taught low-risk dialogue advance target as a local fallback."""
    action = configured_action(config, "AUDITION_RESULT_DIALOGUE", "audition_result_dialogue_continue")
    if action.get("type") != "click":
        raise ValueError("Configured post-audition generic advance is not a click action.")
    return action


def synthetic_post_audition_drain_outcome(observations: list[tuple[str, float | None]],
                                         *, max_clicks: int = 12, no_effect_limit: int = 2) -> tuple[str, int]:
    """Offline model of the bounded generic post-audition dialogue drain."""
    clicks = 0
    no_effect = 0
    for state, similarity in observations:
        if state == "HOME":
            return "CLEANUP_COMPLETE", clicks
        if state in {"CHOICE_REQUIRED", "PROMISE_CHOICE", "ERROR_POPUP"}:
            return "ROOM_INTERRUPTED", clicks
        if clicks >= max_clicks:
            return "CAPABILITY_LIMIT", clicks
        clicks += 1
        if similarity is None or similarity >= 0.98:
            no_effect += 1
        else:
            no_effect = 0
        if no_effect >= no_effect_limit:
            return "NO_EFFECT", clicks
    return "CLEANUP_TIMEOUT", clicks


def synthetic_cleanup_transition_drain(observations: list[tuple[str, bool]], *,
                                       source_state: str = "AUDITION_RESULT_DIALOGUE",
                                       max_attempts: int = 5) -> tuple[str, int, int]:
    """Offline model of cleanup-local fast observation and bounded taps."""
    center_taps = 0
    cta_taps = 0
    protected = {"CHOICE_REQUIRED", "AUDITION_CHOICE", "PROMISE_CHOICE", "CONFIRM", "ERROR_POPUP"}
    for state, cta_visible in observations:
        if state == "HOME":
            return "CLEANUP_COMPLETE", center_taps, cta_taps
        if state in protected:
            return "ROOM_INTERRUPTED", center_taps, cta_taps
        if state != State.UNKNOWN.value and state != source_state:
            return f"KNOWN:{state}", center_taps, cta_taps
        if center_taps + cta_taps >= max_attempts:
            return "TRANSITION_DRAIN_EXHAUSTED", center_taps, cta_taps
        if cta_visible:
            cta_taps += 1
        else:
            center_taps += 1
    if center_taps + cta_taps >= max_attempts:
        return "TRANSITION_DRAIN_EXHAUSTED", center_taps, cta_taps
    return "TRANSITION_DRAIN_PENDING", center_taps, cta_taps


def cleanup_transition_drain_points(settings: dict, window: dict) -> tuple[list[tuple[float, float]], list[tuple[int, int]]]:
    """Resolve the deterministic cleanup-only center points and validate their ROI."""
    roi = settings.get("safe_center_roi")
    points = settings.get("normalized_points")
    if not isinstance(roi, list) or len(roi) != 4 or not isinstance(points, list) or not points:
        raise ValueError("Invalid post-audition transition drain geometry.")
    left, top, right, bottom = (float(value) for value in roi)
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("Transition drain safe center ROI must be normalized.")
    normalized: list[tuple[float, float]] = []
    screen: list[tuple[int, int]] = []
    for raw in points:
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError("Transition drain point must be normalized [x, y].")
        point = (float(raw[0]), float(raw[1]))
        if not (left <= point[0] <= right and top <= point[1] <= bottom):
            raise ValueError("Transition drain point lies outside the safe center ROI.")
        resolved = normalized_point_to_screen(point, window)
        if not point_is_inside_window(resolved, window):
            raise ValueError("Transition drain point lies outside game_window.")
        normalized.append(point)
        screen.append(resolved)
    return normalized, screen


def run_cleanup_transition_drain(target: BrowserTarget, config: dict, cleanup: dict, *,
                                 source_state: str, trace: Path, deadline: float,
                                 dry_run: bool, maximum_actions: int | None = None) -> tuple[Detection, object, str, dict]:
    """Bridge one cleanup action to the next meaningful state without global UNKNOWN confirmation."""
    settings = cleanup.get("transition_drain", {})
    configured_maximum = int(settings.get("max_advance_attempts", 0))
    maximum = configured_maximum if maximum_actions is None else min(configured_maximum, maximum_actions)
    wait_seconds = int(settings.get("wait_after_tap_ms", 0)) / 1000.0
    if configured_maximum != 5 or maximum < 1 or wait_seconds < 0:
        raise ValueError("Invalid post-audition transition drain bounds.")
    normalized_points, screen_points = cleanup_transition_drain_points(settings, config["game_window"])
    hard_stops = set(cleanup.get("hard_stop_states", []))
    attempts = 0
    center_taps = 0
    cta_taps = 0
    no_effect = 0
    last_image = None
    last = Detection(State.UNKNOWN)
    while time.monotonic() < deadline:
        image = target_screenshot(target, config)
        last_image = image
        detected = detect_state(image, config, BASE_DIR)
        last = detected
        state = detected.state.value
        cta = detect_safe_pink_cta(image, cleanup.get("safe_pink_cta", {}))
        write_trace(trace, {"kind": "transition_drain_observation", "source_state": source_state,
                            "state": state, "attempts": attempts, "center_taps": center_taps,
                            "cta_taps": cta_taps, "safe_pink_cta": cta is not None})
        # Priority is deliberate and checked again before every possible tap.
        if state == State.HOME.value:
            return detected, image, "CLEANUP_COMPLETE", {"attempts": attempts, "center_taps": center_taps, "cta_taps": cta_taps}
        if state in hard_stops:
            return detected, image, "ROOM_INTERRUPTED", {"attempts": attempts, "center_taps": center_taps, "cta_taps": cta_taps}
        if state != State.UNKNOWN.value and state != source_state:
            return detected, image, "KNOWN", {"attempts": attempts, "center_taps": center_taps, "cta_taps": cta_taps}
        if attempts >= maximum:
            evidence = save_shot(image, "POST_AUDITION_TRANSITION_DRAIN_EXHAUSTED")
            write_trace(trace, {"kind": "transition_drain_stop", "reason": "TRANSITION_DRAIN_EXHAUSTED",
                                "state": state, "attempts": attempts, "screenshot": str(evidence)})
            return detected, image, "TRANSITION_DRAIN_EXHAUSTED", {"attempts": attempts, "center_taps": center_taps, "cta_taps": cta_taps, "screenshot": str(evidence)}
        if cta is not None:
            nx, ny = cta["center"]
            point = normalized_point_to_screen((nx, ny), config["game_window"])
            capability = "SAFE_PINK_CTA"
            cta_taps += 1
        else:
            index = center_taps % len(screen_points)
            point = screen_points[index]
            capability = "TRANSITION_DRAIN_CENTER_ADVANCE"
            center_taps += 1
        if not point_is_inside_window(point, config["game_window"]):
            raise ValueError("Transition drain click lies outside game_window.")
        write_trace(trace, {"kind": "transition_drain_proposal", "source_state": source_state,
                            "capability": capability, "attempt_index": attempts + 1,
                            "point": point, "normalized_points": normalized_points, "dry_run": dry_run})
        if dry_run:
            return detected, image, "DRY_RUN", {"attempts": attempts, "center_taps": center_taps, "cta_taps": cta_taps,
                                                 "proposed_capability": capability, "proposed_point": point}
        target.verify_and_focus()
        fast_transaction_click_points([point], 0)
        attempts += 1
        if wait_seconds:
            time.sleep(wait_seconds)
        post_image = target_screenshot(target, config)
        similarity = frame_similarity(image, post_image)
        if similarity >= float(config.get("defaults", {}).get("significant_change_similarity_max", 0.98)):
            no_effect += 1
        else:
            no_effect = 0
        post_path = save_shot(post_image, f"POST_AUDITION_TRANSITION_DRAIN_{attempts}")
        write_trace(trace, {"kind": "transition_drain_result", "source_state": source_state,
                            "capability": capability, "attempt_index": attempts, "point": point,
                            "frame_similarity": similarity, "no_effect_count": no_effect,
                            "screenshot": str(post_path)})
        if no_effect >= int(cleanup.get("dialogue_no_effect_limit", 2)):
            return detected, post_image, "NO_EFFECT", {"attempts": attempts, "center_taps": center_taps,
                                                         "cta_taps": cta_taps, "frame_similarity": similarity,
                                                         "screenshot": str(post_path)}
    return last, last_image, "CLEANUP_TIMEOUT", {"attempts": attempts, "center_taps": center_taps, "cta_taps": cta_taps}


def synthetic_season_trial_outcome(target_season: int,
                                   observations: list[tuple[int, str, str]]) -> tuple[str, int]:
    """Offline model for the bounded season runner's stop semantics.

    Entries are ``(season, decision_action, tick_result)``.  The runner never
    invents a room for an unsupported decision and never crosses a season
    boundary.
    """
    ticks = 0
    for season, action, tick_result in observations:
        if season != target_season:
            return "SEASON_CHANGED", ticks
        if action not in {"VOCAL", "REST"}:
            return "UNSUPPORTED_DECISION", ticks
        if tick_result == "DRY_RUN":
            return "DRY_RUN", ticks
        if tick_result != "TICK_SUCCESS":
            return "TICK_FAILURE", ticks
        ticks += 1
    return "MAX_TICKS", ticks


def synthetic_safe_unknown_prior_outcome(observations: list[tuple[str, float]], *,
                                         audition_context: bool, max_attempts: int = 3,
                                         stability_similarity_min: float = 0.98) -> tuple[str, int]:
    """Offline model for the narrowly-scoped audition UNKNOWN prior.

    Each observation is the result immediately after one provisional click.
    This helper intentionally has no image-based label inference: a known
    state is reported as-is, while unmatched frames only earn another attempt
    when they changed materially.
    """
    if not audition_context:
        return "NO_PRIOR", 0
    risky = {"CHOICE_REQUIRED", "AUDITION_CHOICE", "CONFIRM", "PROMISE_CHOICE", "ERROR_POPUP"}
    attempts = 0
    for state, similarity in observations:
        if attempts >= max_attempts:
            return "PRIOR_ATTEMPTS_EXHAUSTED", attempts
        attempts += 1
        if state != State.UNKNOWN.value:
            return ("RISKY_STATE" if state in risky else f"KNOWN:{state}"), attempts
        if similarity >= stability_similarity_min:
            return "CONFIRMED_UNKNOWN", attempts
    return ("PRIOR_ATTEMPTS_EXHAUSTED" if attempts >= max_attempts else "PENDING"), attempts


def synthetic_post_vocal_outcome(fast_path: str, observations: list[tuple[float | None, str | None]], room: dict,
                                 threshold: float = 0.995, streak_required: int = 3) -> str:
    """Offline counterpart of the bounded post-Vocal fallback control flow."""
    if fast_path == "VOCAL_RESULT":
        return "FAST_PATH"
    if fast_path != "TIMEOUT":
        return fast_path
    similarities: list[float] = []
    for similarity, known_state in observations:
        if known_state is not None:
            return post_vocal_outcome(Detection(known_state), room)
        if similarity is not None:
            similarities.append(similarity)
            if stable_unknown_streak(similarities, threshold) >= streak_required:
                return "CONFIRMED_UNKNOWN"
    return "TRANSITION_TIMEOUT"


def synthetic_dialogue_outcome(fast_path: str, observations: list[tuple[float | None, str | None]],
                               threshold: float = 0.995, streak_required: int = 3) -> str:
    """Offline counterpart of the one-click generic dialogue observer."""
    if fast_path in {"HOME", "CHOICE_REQUIRED", "SEASON_CLEAR", "SEASON_RESULT"}:
        return {"HOME": "EVENT_COMPLETED", "CHOICE_REQUIRED": "CHOICE_REQUIRED", "SEASON_CLEAR": "SEASON_CLEAR", "SEASON_RESULT": "SEASON_RESULT"}[fast_path]
    if fast_path not in {"TIMEOUT", "UNKNOWN"}:
        return fast_path
    similarities: list[float] = []
    for similarity, known_state in observations:
        if known_state is not None:
            return {"HOME": "EVENT_COMPLETED", "CHOICE_REQUIRED": "CHOICE_REQUIRED", "SEASON_CLEAR": "SEASON_CLEAR", "SEASON_RESULT": "SEASON_RESULT"}.get(known_state, "UNEXPECTED_UI")
        if similarity is not None:
            similarities.append(similarity)
            if stable_unknown_streak(similarities, threshold) >= streak_required:
                return "CONFIRMED_UNKNOWN"
    return "EVENT_TRANSITION_TIMEOUT"


def confirm_room_unknown(target: BrowserTarget, config: dict, room: dict, first_image, deadline: float, *, allow_transition_continue: bool = False) -> tuple[Detection, object, str, dict]:
    """Observe a candidate unknown without clicking; return only a bounded outcome."""
    settings = config.get("unknown_confirmation", {})
    samples = int(settings.get("samples", 3))
    interval = float(settings.get("interval_ms", 300)) / 1000.0
    threshold = float(settings.get("stability_similarity_min", 0.995))
    streak_required = int(settings.get("stable_streak_required", 3))
    extra_windows = int(settings.get("additional_windows", 1))
    if samples < 2 or interval <= 0 or not 0 < threshold <= 1 or streak_required < 1 or extra_windows < 0:
        raise ValueError("Invalid unknown_confirmation configuration.")
    images = [first_image]
    similarities: list[float] = []
    stable_tail_start_index: int | None = None
    print("candidate_unknown sample=1/%d known_match=None frame_similarity=n/a" % samples)
    for window_number in range(extra_windows + 1):
        # The first window already has its candidate frame. Later windows start
        # with a new sample 1 so diagnostics and stability are not silently skipped.
        start_sample = 2 if window_number == 0 else 1
        for sample_number in range(start_sample, samples + 1):
            if time.monotonic() + interval > deadline:
                reason = "TRANSITION_IN_PROGRESS" if allow_transition_continue else "TRANSITION_TIMEOUT"
                return Detection(State.UNKNOWN), images[-1], reason, {"images": images, "similarities": similarities, "threshold": threshold, "stable_tail_start_index": stable_tail_start_index}
            time.sleep(interval)
            image = target_screenshot(target, config)
            detected = detect_state(image, config, BASE_DIR)
            if detected.state != State.UNKNOWN:
                print(f"unknown_cancelled_known_state={detected.state.value}")
                return detected, image, "KNOWN", {"images": images, "similarities": similarities, "threshold": threshold}
            similarity = frame_similarity(images[-1], image)
            similarities.append(similarity)
            images.append(image)
            print(f"candidate_unknown sample={sample_number}/{samples} known_match=None frame_similarity={similarity:.6f}")
            streak = stable_unknown_streak(similarities, threshold)
            if similarity >= threshold and streak == 1:
                # The first stable relation spans the prior and current frames.
                stable_tail_start_index = len(images) - 2
            if streak >= streak_required:
                return Detection(State.UNKNOWN), images[-1], "CONFIRMED_UNKNOWN", {"images": images, "similarities": similarities, "threshold": threshold, "stable_tail_start_index": stable_tail_start_index}
        if window_number < extra_windows:
            print("transition_in_progress; starting one additional unknown observation window")
    reason = "TRANSITION_IN_PROGRESS" if allow_transition_continue else "TRANSITION_TIMEOUT"
    return Detection(State.UNKNOWN), images[-1], reason, {"images": images, "similarities": similarities, "threshold": threshold, "stable_tail_start_index": stable_tail_start_index}


def save_confirmed_unknown_candidates(details: dict) -> tuple[list[str], str | None]:
    """Persist transition frames and identify the first frame in the stable tail."""
    paths = [str(save_shot(frame, f"ROOM_CANDIDATE_UNKNOWN_{index + 1}"))
             for index, frame in enumerate(details.get("images", [])[:-1])]
    index = details.get("stable_tail_start_index")
    first_stable = paths[index] if isinstance(index, int) and 0 <= index < len(paths) else None
    return paths, first_stable


def safe_unknown_prior_attempt(target: BrowserTarget, config: dict, *, room_name: str,
                               context: str, settings: dict, attempt_index: int,
                               source_image, trace: Path | None) -> tuple[Detection, object, str, dict]:
    """Perform one provisional, fixed-point audition continuation click.

    This is deliberately not a generic UNKNOWN action.  Its caller supplies
    the narrowly configured room context, and it only reports what was
    observed after the single click.  Destination semantics remain with the
    existing room observer.
    """
    point_config = settings.get("point")
    maximum = int(settings.get("max_attempts", 0))
    stability_min = float(settings.get("significant_change_similarity_max", 0.98))
    if maximum < 1 or not 0 < stability_min <= 1:
        raise ValueError("Invalid safe_unknown_prior configuration.")
    point = normalized_point_to_screen(point_config, config["game_window"])
    if not point_is_inside_window(point, config["game_window"]):
        raise ValueError("safe_unknown_prior point is outside current game_window.")
    source_path = save_shot(source_image, f"{room_name}_PRIOR_SOURCE_{attempt_index}")
    target.verify_and_focus()
    click_point(point, config["defaults"])
    post_image = target_screenshot(target, config)
    post = detect_state(post_image, config, BASE_DIR)
    post_path = save_shot(post_image, f"{room_name}_PRIOR_POST_{attempt_index}")
    similarity = frame_similarity(source_image, post_image)
    metadata = {
        "room": room_name,
        "context": context,
        "prior_action": "safe_continue_click_once",
        "attempt_index": attempt_index,
        "max_attempts": maximum,
        "source_screenshot": str(source_path),
        "click_point": point,
        "post_screenshot": str(post_path),
        "resulting_state": post.state.value,
        "frame_similarity": similarity,
        "significant_change_similarity_max": stability_min,
    }
    if trace is not None:
        write_trace(trace, {"kind": "safe_unknown_prior_attempt", **metadata})
    if post.state != State.UNKNOWN:
        return post, post_image, "KNOWN", metadata
    if similarity >= stability_min:
        return post, post_image, "CONFIRMED_UNKNOWN", metadata
    return post, post_image, "CHANGED_UNKNOWN", metadata


def wait_for_room_event(target: BrowserTarget, config: dict, room: dict, source_state: str,
                        *, allow_transition_continue: bool = False,
                        safe_unknown_prior: dict | None = None,
                        trace: Path | None = None,
                        prior_context: str = "") -> tuple[Detection, object, str, dict]:
    """Observe only a room exit, interruption, local anchor, stable unknown, or timeout."""
    deadline = time.monotonic() + float(room.get("timeout_seconds", 30))
    last_image = None
    prior_attempts = 0
    while time.monotonic() < deadline:
        image = target_screenshot(target, config)
        detected = detect_state(image, config, BASE_DIR)
        last_image = image
        if detected.state == State.UNKNOWN:
            if safe_unknown_prior and safe_unknown_prior.get("enabled", False):
                maximum = int(safe_unknown_prior.get("max_attempts", 0))
                if prior_attempts >= maximum:
                    return detected, image, "PRIOR_ATTEMPTS_EXHAUSTED", {
                        "prior_attempts": prior_attempts,
                        "prior_context": prior_context,
                    }
                prior_attempts += 1
                prior, prior_image, prior_reason, prior_details = safe_unknown_prior_attempt(
                    target, config, room_name=str(room.get("name", "AUDITION_BATTLE_HANDLER")),
                    context=prior_context, settings=safe_unknown_prior,
                    attempt_index=prior_attempts, source_image=image, trace=trace,
                )
                last_image = prior_image
                if prior_reason == "CONFIRMED_UNKNOWN":
                    return prior, prior_image, "CONFIRMED_UNKNOWN", {
                        "prior_attempts": prior_attempts,
                        "prior_records": [prior_details],
                    }
                if prior_reason == "CHANGED_UNKNOWN":
                    if prior_attempts >= maximum:
                        return prior, prior_image, "PRIOR_ATTEMPTS_EXHAUSTED", {
                            "prior_attempts": prior_attempts,
                            "prior_records": [prior_details],
                        }
                    # A click produced material motion, so re-enter the outer
                    # observer.  It alone decides whether another bounded
                    # provisional attempt is warranted.
                    continue
                # A known state appeared immediately after the one click. Fall
                # through to the established exit/interruption classification.
                detected = prior
                image = prior_image
            if detected.state == State.UNKNOWN:
                unknown, unknown_image, reason, details = confirm_room_unknown(
                    target, config, room, image, deadline,
                    allow_transition_continue=allow_transition_continue,
                )
                if reason == "KNOWN":
                    if unknown.state == source_state:
                        last_image = unknown_image
                        continue
                    if unknown.state in room["exit_states"]:
                        return unknown, unknown_image, "ROOM_EXIT", details
                    if unknown.state in room["interruptions"]:
                        return unknown, unknown_image, "ROOM_INTERRUPTED", details
                    if unknown.state in room["local_anchors"]:
                        last_image = unknown_image
                        continue
                    return unknown, unknown_image, "UNEXPECTED_UI", details
                if reason == "TRANSITION_IN_PROGRESS" and allow_transition_continue:
                    continue
                return unknown, unknown_image, reason, details
        if detected.state == source_state:
            # A click may take time to replace its source UI.  Keep observing;
            # no additional click is issued.
            time.sleep(config["defaults"]["poll_interval_seconds"])
            continue
        if detected.state in room["exit_states"]:
            return detected, image, "ROOM_EXIT", {}
        if detected.state in room["interruptions"]:
            return detected, image, "ROOM_INTERRUPTED", {}
        if detected.state in room["local_anchors"]:
            # A local anchor is evidence that the room remains active, not an exit.
            time.sleep(config["defaults"]["poll_interval_seconds"])
            continue
        return detected, image, "UNEXPECTED_UI", {}
    return Detection(State.UNKNOWN), last_image, "TRANSITION_TIMEOUT", {}


def post_vocal_outcome(detected: Detection, room: dict) -> str:
    """Classify a recognized post-Vocal screen without granting it success implicitly."""
    if detected.state == "VOCAL_RESULT":
        return "VOCAL_RESULT"
    if detected.state in room["exit_states"]:
        return "ROOM_EXIT"
    if detected.state in room["interruptions"]:
        return "ROOM_INTERRUPTED"
    if detected.state == State.LOADING:
        return "LOADING"
    return "UNEXPECTED_UI"


def post_vocal_deadline(now: float, transition_deadline: float, overall_deadline: float,
                         loading_deadline: float | None) -> tuple[float, bool]:
    """Return the hard observation deadline and whether the soft milestone elapsed."""
    return min(loading_deadline or overall_deadline, overall_deadline), now >= transition_deadline


def transition_accelerator_points(settings: dict, window: dict) -> tuple[list[tuple[float, float]], list[tuple[int, int]]]:
    """Return a reproducible center point repeated for one bounded burst."""
    box = settings.get("box")
    if not isinstance(box, list) or len(box) != 4:
        raise ValueError("transition_accelerator.box must be a normalized box.")
    left, top, right, bottom = (float(value) for value in box)
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError("transition_accelerator.box must be contained in [0, 1].")
    every = int(settings.get("detection_every_clicks", 3))
    maximum = int(settings.get("max_clicks_per_burst", 3))
    if every < 1 or maximum < 1:
        raise ValueError("transition_accelerator click limits must be positive.")
    count = min(every, maximum)
    normalized_point = (round((left + right) / 2, 6), round((top + bottom) / 2, 6))
    screen_box = normalized_box_to_screen(box, window)
    center = (round((screen_box[0] + screen_box[2]) / 2), round((screen_box[1] + screen_box[3]) / 2))
    points = [center] * count
    if not all(point_is_inside_window(point, window) for point in points):
        raise ValueError("transition accelerator point is outside current game_window.")
    return [normalized_point] * count, points


def run_transition_accelerator_burst(target: BrowserTarget, config: dict, *, action_sent: bool,
                                     dry_run: bool) -> dict:
    """Click only a deterministic center-safe burst; never classify a destination."""
    settings = config.get("transition_accelerator", {})
    if not action_sent:
        return {"status": "NOT_ARMED", "click_count": 0, "normalized_points": [], "elapsed_ms": 0.0}
    if not settings.get("enabled", False):
        return {"status": "DISABLED", "click_count": 0, "normalized_points": [], "elapsed_ms": 0.0}
    # Reacquire the CDP target and dynamic geometry for every burst. The caller
    # owns detection and all destination semantics.
    target.verify_and_focus()
    image = target_screenshot(target, config)
    before = detect_state(image, config, BASE_DIR)
    if before.state != State.UNKNOWN:
        return {"status": "PRE_BURST_KNOWN", "click_count": 0, "normalized_points": [], "elapsed_ms": 0.0,
                "pre_burst_state": before.state.value, "pre_burst_image": image}
    normalized_points, points = transition_accelerator_points(settings, config["game_window"])
    started = time.monotonic()
    if not dry_run:
        fast_transaction_click_points(points, int(settings.get("click_interval_ms", 100)))
    finished = time.monotonic()
    return {"status": "DRY_RUN" if dry_run else "CLICKED", "click_count": len(points),
            "normalized_points": normalized_points, "screen_points": points,
            "burst_started_at_monotonic": started, "burst_finished_at_monotonic": finished,
            "elapsed_ms": round((finished - started) * 1000, 3)}


def observe_post_vocal_transition(target: BrowserTarget, config: dict, room: dict, *, action_sent: bool,
                                  dry_run: bool = False, trace: Path | None = None,
                                  performance: RoomPerformance | None = None) -> tuple[Detection, object, str, dict]:
    """Bounded post-Vocal fallback after the strict action check is unresolved."""
    transition_deadline = time.monotonic() + float(room.get("post_vocal_transition_timeout_seconds", 20))
    overall_deadline = time.monotonic() + float(room.get("post_vocal_overall_timeout_seconds", 60))
    loading_deadline: float | None = None
    transition_milestone_reported = False
    all_similarities: list[float] = []
    all_images: list[object] = []
    accelerator_burst_index = 0
    while time.monotonic() < overall_deadline:
        # The transition deadline is diagnostic-only. Before a LOADING template
        # exists, visibly changing UI may consume the bounded overall observer.
        deadline, milestone_elapsed = post_vocal_deadline(time.monotonic(), transition_deadline, overall_deadline, loading_deadline)
        if not transition_milestone_reported and milestone_elapsed:
            transition_milestone_reported = True
            print("post_vocal_transition_milestone_elapsed=true; continuing no-click observation until overall deadline")
        if time.monotonic() >= deadline:
            return Detection(State.UNKNOWN), all_images[-1] if all_images else None, "TRANSITION_TIMEOUT", {"similarities": all_similarities, "images": all_images, "loading_detected": loading_deadline is not None, "transition_milestone_elapsed": transition_milestone_reported}
        image = target_screenshot(target, config)
        detected = detect_state(image, config, BASE_DIR)
        if detected.state == State.UNKNOWN:
            all_images.append(image)
            # After vocal_lesson was actually sent, UNKNOWN is an unresolved
            # transition frame. Issue one bounded center-safe burst, then let
            # the outer observer reclassify; this helper never decides the
            # destination.
            print("post_vocal_transition_in_progress=true")
            burst = run_transition_accelerator_burst(target, config, action_sent=action_sent, dry_run=dry_run)
            if performance is not None:
                performance.record_accelerator_burst(burst)
            accelerator_burst_index += 1
            post_image = burst.pop("pre_burst_image", None)
            if post_image is None:
                post_image = target_screenshot(target, config)
            post_detected = detect_state(post_image, config, BASE_DIR)
            burst["accelerator_burst_index"] = accelerator_burst_index
            burst["post_burst_observed_state"] = post_detected.state.value
            if trace is not None:
                write_trace(trace, {"kind": "transition_accelerator_burst", "room": "VOCAL_ROOM", **burst})
            if post_detected.state != State.UNKNOWN:
                outcome = post_vocal_outcome(post_detected, room)
                return post_detected, post_image, outcome, {"similarities": all_similarities, "images": all_images,
                                                            "loading_detected": loading_deadline is not None,
                                                            "transition_milestone_elapsed": transition_milestone_reported,
                                                            "last_accelerator_burst": burst}
            continue
        outcome = post_vocal_outcome(detected, room)
        if outcome == "LOADING":
            if loading_deadline is None:
                loading_deadline = min(time.monotonic() + float(room.get("loading_timeout_seconds", 45)), overall_deadline)
            print("post_vocal_loading_detected=true")
            continue
        return detected, image, outcome, {"similarities": all_similarities, "images": all_images, "loading_detected": loading_deadline is not None, "transition_milestone_elapsed": transition_milestone_reported}
    return Detection(State.UNKNOWN), all_images[-1] if all_images else None, "TRANSITION_TIMEOUT", {"similarities": all_similarities, "images": all_images, "loading_detected": loading_deadline is not None, "transition_milestone_elapsed": transition_milestone_reported}


def dialogue_outcome(detected: Detection) -> str:
    if detected.state == State.HOME:
        return "EVENT_COMPLETED"
    if detected.state == "CHOICE_REQUIRED":
        return "CHOICE_REQUIRED"
    if detected.state in {"SEASON_CLEAR", "SEASON_RESULT"}:
        return detected.state.value
    if detected.state == "DIALOGUE_FAST_FORWARD_OFF":
        return "DIALOGUE_CONTROL"
    return "UNEXPECTED_UI"


def observe_dialogue_transition(target: BrowserTarget, config: dict) -> tuple[Detection, object, str, dict]:
    """Observe the one-click generic dialogue lifecycle; it never issues another click."""
    state_spec = config["states"]["DIALOGUE_FAST_FORWARD_OFF"]
    deadline = time.monotonic() + float(state_spec.get("event_transition_timeout_seconds", 20))
    images: list[object] = []
    similarities: list[float] = []
    while time.monotonic() < deadline:
        image = target_screenshot(target, config)
        detected = detect_state(image, config, BASE_DIR)
        if detected.state == State.UNKNOWN:
            unknown, unknown_image, reason, details = confirm_room_unknown(
                target, config, {"exit_states": ["HOME"], "interruptions": ["CHOICE_REQUIRED"], "local_anchors": []},
                image, deadline, allow_transition_continue=True,
            )
            images.extend(details.get("images", []))
            similarities.extend(details.get("similarities", []))
            if reason == "CONFIRMED_UNKNOWN":
                details.update({"images": images, "similarities": similarities})
                return unknown, unknown_image, reason, details
            if reason == "KNOWN":
                outcome = dialogue_outcome(unknown)
                details.update({"images": images, "similarities": similarities})
                return unknown, unknown_image, outcome, details
            print("dialogue_transition_in_progress=true")
            continue
        return detected, image, dialogue_outcome(detected), {"images": images, "similarities": similarities}
    return Detection(State.UNKNOWN), images[-1] if images else None, "EVENT_TRANSITION_TIMEOUT", {"images": images, "similarities": similarities}


def handle_dialogue_fast_forward_once(target: BrowserTarget, config: dict) -> tuple[Detection, object, str, dict]:
    """Click the taught fast-forward toggle once, then observe only."""
    before_image = target_screenshot(target, config)
    before = detect_state(before_image, config, BASE_DIR)
    if before.state != "DIALOGUE_FAST_FORWARD_OFF":
        return before, before_image, "UNEXPECTED_UI", {}
    action = configured_action(config, "DIALOGUE_FAST_FORWARD_OFF")
    point = random_point(action["box"], config["game_window"], config["defaults"])
    if not point_is_inside_window(point, config["game_window"]):
        raise ValueError("dialogue fast-forward point is outside current game_window.")
    target.verify_and_focus()
    click_point(point, config["defaults"])
    # Keep the existing short verifier as a fast path. It deliberately cannot
    next_state, next_image, reason = wait_for_stable_state(target, config, float(config["states"]["DIALOGUE_FAST_FORWARD_OFF"].get("timeout_seconds", 5)), "DIALOGUE_FAST_FORWARD_OFF")
    if reason is None and next_state.state.value in action["expected_next_states"]:
        return next_state, next_image, dialogue_outcome(next_state), {"fast_path": "KNOWN"}
    # A short verifier can report UNKNOWN for a transient dialogue frame.  It
    # is unresolved rather than a terminal outcome, so enter the same bounded
    # no-click observer used after a verifier timeout.
    if reason in {"TIMEOUT", "UNKNOWN"}:
        observed, observed_image, outcome, details = observe_dialogue_transition(target, config)
        details["fast_path"] = reason
        details["actual_click"] = point
        return observed, observed_image, outcome, details
    return next_state, next_image, reason or "UNEXPECTED_UI", {"fast_path": reason, "actual_click": point}


def handle_safe_continue_once(target: BrowserTarget, config: dict, state: str,
                              action_name: str) -> tuple[Detection, object, str, dict]:
    """Run a taught low-risk continue control once and verify its taught result.

    This is intentionally usable only through ``known_control_capability``;
    it cannot turn a generic confirmation or choice into a default click.
    """
    before_image = target_screenshot(target, config)
    before = detect_state(before_image, config, BASE_DIR)
    if before.state.value != state:
        return before, before_image, "UNEXPECTED_UI", {}
    action = configured_action(config, state, action_name)
    point = random_point(action["box"], config["game_window"], config["defaults"])
    if not point_is_inside_window(point, config["game_window"]):
        raise ValueError("safe continue point is outside current game_window.")
    target.verify_and_focus()
    click_point(point, config["defaults"])
    next_state, next_image, reason = wait_for_expected_local_state(
        target, config, float(config["states"][state].get("timeout_seconds", 5)),
        action["expected_next_states"],
    )
    if reason is None:
        return next_state, next_image, "CONTROL_CONTINUED", {
            "capability": "continue_once", "action": action_name, "actual_click": point,
        }
    return next_state, next_image, reason or "UNEXPECTED_UI", {
        "capability": "continue_once", "action": action_name, "actual_click": point,
    }


def dispatch_known_control_capability(target: BrowserTarget, config: dict, room: dict,
                                      detected: Detection, image) -> tuple[Detection, object, str, dict] | None:
    """Dispatch a context-approved control, otherwise leave room handling inert."""
    capability = known_control_capability(config, detected, room)
    if capability is None:
        return None
    if capability["mode"] == "dialogue_fast_forward_once":
        next_state, next_image, outcome, details = handle_dialogue_fast_forward_once(target, config)
        outcome = "ROOM_EXIT" if outcome == "EVENT_COMPLETED" and next_state.state == State.HOME else outcome
    elif capability["mode"] == "continue_once":
        next_state, next_image, outcome, details = handle_safe_continue_once(
            target, config, capability["state"], capability["action_name"],
        )
    else:  # Static registry entries are code-reviewed, but fail closed if malformed.
        raise ValueError(f"Unknown capability mode {capability['mode']!r}.")
    details = {"capability": capability["mode"], "action": capability["action_name"], **details}
    return next_state, next_image, outcome, details


def promise_decline_is_configured(config: dict) -> bool:
    """A promise choice remains inert until exactly its taught DECLINE action exists."""
    actions = config["states"].get("PROMISE_CHOICE", {}).get("allowed_actions", [])
    return len(actions) == 1 and actions[0].get("name") == "promise_decline" and actions[0].get("expected_next_states") == ["HOME"]


def handle_promise_decline_once(target: BrowserTarget, config: dict) -> tuple[Detection, object, str, dict]:
    """Click the taught DECLINE button once, then observe only until HOME or stop."""
    before_image = target_screenshot(target, config)
    before = detect_state(before_image, config, BASE_DIR)
    if before.state != "PROMISE_CHOICE" or not promise_decline_is_configured(config):
        return before, before_image, "UNEXPECTED_UI", {}
    action = configured_action(config, "PROMISE_CHOICE")
    point = random_point(action["box"], config["game_window"], config["defaults"])
    if not point_is_inside_window(point, config["game_window"]):
        raise ValueError("promise DECLINE point is outside current game_window.")
    target.verify_and_focus()
    click_point(point, config["defaults"])
    short_timeout = float(config["states"]["PROMISE_CHOICE"].get("timeout_seconds", 5))
    next_state, next_image, reason = wait_for_stable_state(target, config, short_timeout, "PROMISE_CHOICE")
    if reason is None and next_state.state == State.HOME:
        return next_state, next_image, "ROOM_EXIT", {"actual_click": point}
    if reason in {"UNKNOWN", "TIMEOUT"}:
        # A promise result can legitimately pass through transient frames before
        # HOME. Reuse the room observer, with a local bounded deadline and no
        # further click, rather than treating the fast verifier as final.
        promise_room = {
            "exit_states": ["HOME"],
            "interruptions": config["rooms"]["VOCAL_ROOM"]["interruptions"],
            "local_anchors": [],
            "timeout_seconds": float(config["states"]["PROMISE_CHOICE"].get("event_transition_timeout_seconds", 20)),
        }
        observed, observed_image, observed_reason, details = wait_for_room_event(
            target, config, promise_room, "PROMISE_CHOICE", allow_transition_continue=True,
        )
        details["actual_click"] = point
        if observed_reason == "ROOM_EXIT" and observed.state == State.HOME:
            return observed, observed_image, "ROOM_EXIT", details
        return observed, observed_image, observed_reason, details
    return next_state, next_image, reason or "UNEXPECTED_UI", {"actual_click": point}


def dispatch_room_interruption(target: BrowserTarget, config: dict, room: dict,
                              detected: Detection, image, expected_next_states: list[str]) -> tuple[Detection, object, str, dict]:
    """Run at most one taught action per distinct interruption, then reclassify."""
    current, current_image = detected, image
    seen: set[str] = set()
    details: dict = {"chain": []}
    while current.state.value in room["interruptions"]:
        state = current.state.value
        if state in seen:
            return current, current_image, "ROOM_INTERRUPTED", details
        seen.add(state)
        capability_result = dispatch_known_control_capability(target, config, room, current, current_image)
        if capability_result is not None:
            current, current_image, outcome, handler_details = capability_result
        elif state == "PROMISE_CHOICE" and promise_decline_is_configured(config):
            current, current_image, outcome, handler_details = handle_promise_decline_once(target, config)
        else:
            return current, current_image, "ROOM_INTERRUPTED", details
        details["chain"].append({"state": state, "outcome": outcome, "details": handler_details})
        if outcome == "ROOM_EXIT" and current.state == State.HOME:
            return current, current_image, "ROOM_EXIT", details
        if current.state.value in room["exit_states"]:
            return current, current_image, "ROOM_EXIT", details
        if current.state.value in expected_next_states:
            return current, current_image, "LOCAL_RESUME", details
        if current.state.value not in room["interruptions"]:
            return current, current_image, outcome if outcome not in {"EVENT_COMPLETED", "ROOM_INTERRUPTED"} else "UNEXPECTED_UI", details
    return current, current_image, "UNEXPECTED_UI", details


def run_vocal_room(dry_run: bool, result_context: VocalRoomResultContext | None = None) -> int:
    """Execute one bounded VOCAL_ROOM attempt using already captured Milestone 1 evidence."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text())
    room_name = "VOCAL_ROOM"
    room = config.get("rooms", {}).get(room_name)
    if not room:
        log.error("%s is not configured.", room_name)
        return 2
    required = ("entry_states", "exit_states", "local_steps", "local_anchors", "interruptions")
    if any(not isinstance(room.get(key), list) for key in required):
        log.error("Invalid %s schema.", room_name)
        return 2
    trace = room_trace_path(room_name)
    last_state = State.UNKNOWN.value
    previous_local_step: str | None = None
    performance = RoomPerformance(
        room_name=room_name,
        entered_at_monotonic=time.monotonic(),
        accelerator_enabled=bool(config.get("transition_accelerator", {}).get("enabled", False)),
    )

    def finish(reason: str, state: str, screenshot: Path | None, code: int) -> int:
        """Persist observational timing for every exit; do not alter room semantics."""
        metrics = performance.finish(reason, state)
        write_trace(trace, {"kind": "room_performance", **metrics})
        if result_context is not None:
            result_context.performance = metrics
        comparison = None
        if reason == "ROOM_EXIT" and state == State.HOME.value:
            comparison = persist_successful_room_performance(metrics)
            write_trace(trace, {"kind": "room_performance_comparison", "comparison": comparison})
        room_summary(room_name, reason, state, trace, screenshot)
        print_room_performance(metrics, comparison)
        return code

    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            image = target_screenshot(target, config)
            current = detect_state(image, config, BASE_DIR)
            last_state = current.state.value
            write_trace(trace, {"kind": "entry", "room": room_name, "state": current.state.value,
                                "template": current.template, "confidence": current.confidence, "dry_run": dry_run})
            if current.state.value not in room["entry_states"]:
                path = save_shot(image, "ROOM_INVALID_ENTRY")
                write_trace(trace, {"kind": "stop", "reason": "INVALID_ENTRY", "state": current.state.value, "screenshot": str(path)})
                return finish("INVALID_ENTRY", current.state.value, path, 2)
            for number, step in enumerate(room["local_steps"], start=1):
                if number > int(room.get("max_local_steps", len(room["local_steps"]))):
                    raise ValueError("Room local-step limit would be exceeded.")
                if current.state.value != step.get("source_state"):
                    path = save_shot(image, "ROOM_UNEXPECTED_LOCAL_STATE")
                    write_trace(trace, {"kind": "stop", "reason": "UNEXPECTED_UI", "state": current.state.value,
                                        "expected_source": step.get("source_state"), "screenshot": str(path)})
                    return finish("UNEXPECTED_UI", current.state.value, path, 2)
                action = room_step_action(config, step)
                previous_local_step = action["name"]
                point = random_point(action["box"], config["game_window"], config["defaults"])
                if not point_is_inside_window(point, config["game_window"]):
                    raise ValueError("Room action point is outside current game_window.")
                debug = save_action_debug(config["game_window"], action["box"], point, BASE_DIR, f"room_{room_name}_{number}_{action['name']}")
                write_trace(trace, {"kind": "proposal", "room": room_name, "step": number, "current_state": current.state.value,
                                    "action": action["name"], "expected_next_states": action["expected_next_states"],
                                    "proposed_click": point, "debug_screenshot": str(debug), "dry_run": dry_run})
                if dry_run:
                    log.info("room=%s step=%d would_click=%s expected=%s point=%s", room_name, number, action["name"], action["expected_next_states"], point)
                    current = Detection(action["expected_next_states"][0])
                    continue
                before_image = target_screenshot(target, config)
                before = detect_state(before_image, config, BASE_DIR)
                if before.state != current.state:
                    path = save_shot(before_image, "ROOM_STATE_CHANGED_BEFORE_CLICK")
                    write_trace(trace, {"kind": "stop", "reason": "STATE_CHANGED_BEFORE_CLICK", "state": before.state.value, "screenshot": str(path)})
                    return finish("STATE_CHANGED_BEFORE_CLICK", before.state.value, path, 2)
                point = random_point(action["box"], config["game_window"], config["defaults"])
                if not point_is_inside_window(point, config["game_window"]):
                    raise ValueError("Revalidated room action point is outside current game_window.")
                target.verify_and_focus()
                action_sent_at = click_point(point, config["defaults"])
                click_timestamp = datetime.now().isoformat(timespec="milliseconds")
                if result_context is not None:
                    result_context.action_sent = action["name"]
                    result_context.action_sent_timestamp = click_timestamp
                if action["name"] == "vocal_lesson":
                    performance.action_sent_at = action_sent_at
                    performance.post_action_observer_started_at = time.monotonic()
                next_state, next_image, reason = wait_for_stable_state(target, config, float(config["states"][current.state.value].get("timeout_seconds", 5)), current.state)
                # A transient unmatched post-click frame is observation, not proof of
                # a new UI. Confirm it without any additional click before failing.
                unknown_details: dict = {}
                if reason == "UNKNOWN" and next_image is not None:
                    allow_transition_continue = action["name"] == "vocal_lesson"
                    next_state, next_image, unknown_reason, unknown_details = confirm_room_unknown(
                        target, config, room, next_image,
                        time.monotonic() + float(config["states"][current.state.value].get("timeout_seconds", 5)),
                        allow_transition_continue=allow_transition_continue,
                    )
                    if unknown_reason == "KNOWN":
                        reason = None
                    else:
                        reason = unknown_reason
                fallback_details: dict = {}
                if action["name"] == "vocal_lesson" and reason in {
                    "UNKNOWN", "CONFIRMED_UNKNOWN", "TIMEOUT", "TRANSITION_IN_PROGRESS",
                }:
                    fast_path_reason = reason
                    write_trace(trace, {"kind": "post_vocal_fallback_entered", "room": room_name, "step": number,
                                        "action": action["name"], "click_timestamp": click_timestamp,
                                        "fast_path_result": fast_path_reason})
                    next_state, next_image, fallback_reason, fallback_details = observe_post_vocal_transition(
                        target, config, room, action_sent=result_context is None or result_context.action_sent == "vocal_lesson",
                        dry_run=dry_run, trace=trace, performance=performance,
                    )
                    if fallback_reason == "VOCAL_RESULT":
                        reason = None
                    elif fallback_reason == "ROOM_EXIT":
                        result_path = save_shot(next_image, "ROOM_POST_VOCAL_EXIT")
                        write_trace(trace, {"kind": "post_vocal_fallback_result", "room": room_name, "action": action["name"],
                                            "fast_path_result": fast_path_reason, "final_reason": fallback_reason,
                                            "state": next_state.state.value, "screenshot": str(result_path), "loading_detected": fallback_details.get("loading_detected"),
                                            "similarities": fallback_details.get("similarities"), "transition_milestone_elapsed": fallback_details.get("transition_milestone_elapsed")})
                        record_vocal_room_exit(result_context, next_state.state.value)
                        return finish("ROOM_EXIT", next_state.state.value, result_path, 0)
                    elif fallback_reason == "ROOM_INTERRUPTED":
                        # Dispatch at the common local-transition boundary below.
                        reason = None
                    else:
                        reason = fallback_reason
                local_kind = None
                if reason is None:
                    local_kind = classify_local_transition(
                        next_state.state.value, action["expected_next_states"], room["interruptions"], room["exit_states"],
                    )
                if reason is None and local_kind == "ROOM_EXIT":
                    if next_image is None:
                        next_image = target_screenshot(target, config)
                    exit_path = save_shot(next_image, "ROOM_LOCAL_EXIT")
                    write_trace(trace, {"kind": "local_room_exit", "room": room_name, "step": number,
                                        "source_state": current.state.value, "action": action["name"],
                                        "state": next_state.state.value, "screenshot": str(exit_path)})
                    record_vocal_room_exit(result_context, next_state.state.value)
                    return finish("ROOM_EXIT", next_state.state.value, exit_path, 0)
                if reason is None and local_kind == "INTERRUPTION":
                    next_state, next_image, interruption_reason, interruption_details = dispatch_room_interruption(
                        target, config, room, next_state, next_image, action["expected_next_states"],
                    )
                    if next_image is None:
                        next_image = target_screenshot(target, config)
                    interruption_path = save_shot(next_image, f"ROOM_INTERRUPTION_{interruption_reason}")
                    write_trace(trace, {"kind": "local_interruption", "room": room_name, "step": number,
                                        "source_state": current.state.value, "action": action["name"],
                                        "interruption_state": next_state.state.value, "result": interruption_reason,
                                        "screenshot": str(interruption_path), "details": interruption_details})
                    if interruption_reason == "ROOM_EXIT":
                        record_vocal_room_exit(result_context, next_state.state.value)
                        return finish("ROOM_EXIT", next_state.state.value, interruption_path, 0)
                    if interruption_reason == "LOCAL_RESUME":
                        reason = None
                    elif interruption_reason in {"SEASON_CLEAR", "SEASON_RESULT"}:
                        cleanup_code = run_post_audition_cleanup(dry_run=dry_run)
                        if cleanup_code == 0:
                            post_img = target_screenshot(target, config)
                            post_det = detect_state(post_img, config, BASE_DIR)
                            if post_det.state == State.HOME:
                                exit_path = save_shot(post_img, "ROOM_SEASON_ENDING_EXIT")
                                record_vocal_room_exit(result_context, post_det.state.value)
                                return finish("ROOM_EXIT", post_det.state.value, exit_path, 0)
                        return finish("SEASON_ENDING_FAILURE", next_state.state.value, None, 2)
                    else:
                        reason = interruption_reason
                if next_image is None:
                    next_image = target_screenshot(target, config)
                result_path = save_shot(next_image, "ROOM_LOCAL_STEP")
                step_candidate_paths = []
                step_first_stable_path = None
                evidence_details = fallback_details or unknown_details
                if reason == "CONFIRMED_UNKNOWN":
                    step_candidate_paths, step_first_stable_path = save_confirmed_unknown_candidates(evidence_details)
                write_trace(trace, {"kind": "local_step", "room": room_name, "step": number, "current_state": current.state.value,
                                    "action": action["name"], "expected_next_states": action["expected_next_states"], "actual_click": point,
                                    "click_timestamp": click_timestamp,
                                    "resulting_state": next_state.state.value, "resulting_confidence": next_state.confidence,
                                    "screenshot": str(result_path), "stop_reason": reason,
                                    "candidate_screenshots": step_candidate_paths,
                                    "first_stable_unknown_screenshot": step_first_stable_path,
                                    "unknown_similarity": evidence_details.get("similarities"),
                                    "unknown_stability_threshold": evidence_details.get("threshold"),
                                    "fast_path_result": fast_path_reason if fallback_details else reason,
                                    "fallback_observer_entered": bool(fallback_details),
                                    "loading_detected": fallback_details.get("loading_detected"),
                                    "transition_milestone_elapsed": fallback_details.get("transition_milestone_elapsed")})
                if reason or next_state.state.value not in action["expected_next_states"]:
                    stop_reason = reason or "UNEXPECTED_TRANSITION"
                    return finish(stop_reason, next_state.state.value, result_path, 2)
                current, image, last_state = next_state, next_image, next_state.state.value
            if dry_run:
                write_trace(trace, {"kind": "stop", "reason": "DRY_RUN", "state": current.state.value})
                return finish("DRY_RUN", current.state.value, None, 0)
            while True:
                observed, observed_image, reason, details = wait_for_room_event(target, config, room, current.state.value)
                if observed_image is None:
                    observed_image = target_screenshot(target, config)
                path = save_shot(observed_image, f"ROOM_{reason}")
                candidate_paths: list[str] = []
                first_stable_path = None
                if reason == "CONFIRMED_UNKNOWN":
                    candidate_paths, first_stable_path = save_confirmed_unknown_candidates(details)
                write_trace(trace, {"kind": "room_observation", "room": room_name, "source_state": current.state.value,
                                    "previous_local_step": previous_local_step,
                                    "state": observed.state.value, "template": observed.template, "confidence": observed.confidence,
                                    "reason": reason, "screenshot": str(path), "candidate_screenshots": candidate_paths,
                                    "first_stable_unknown_screenshot": first_stable_path,
                                    "unknown_similarity": details.get("similarities"), "unknown_stability_threshold": details.get("threshold")})
                if reason == "ROOM_INTERRUPTED":
                    resumed, resumed_image, interruption_reason, interruption_details = dispatch_room_interruption(
                        target, config, room, observed, observed_image, room["local_anchors"],
                    )
                    if resumed_image is None:
                        resumed_image = target_screenshot(target, config)
                    interruption_path = save_shot(resumed_image, f"ROOM_INTERRUPTION_{interruption_reason}")
                    write_trace(trace, {"kind": "room_interruption", "room": room_name,
                                        "source_state": current.state.value, "interruption_state": observed.state.value,
                                        "result": interruption_reason, "state": resumed.state.value,
                                        "screenshot": str(interruption_path), "details": interruption_details})
                    if interruption_reason == "ROOM_EXIT":
                        record_vocal_room_exit(result_context, resumed.state.value)
                        return finish("ROOM_EXIT", resumed.state.value, interruption_path, 0)
                    if interruption_reason == "LOCAL_RESUME":
                        current, image, last_state = resumed, resumed_image, resumed.state.value
                        continue
                    if interruption_reason in {"SEASON_CLEAR", "SEASON_RESULT"}:
                        cleanup_code = run_post_audition_cleanup(dry_run=dry_run)
                        if cleanup_code == 0:
                            post_img = target_screenshot(target, config)
                            post_det = detect_state(post_img, config, BASE_DIR)
                            if post_det.state == State.HOME:
                                exit_path = save_shot(post_img, "ROOM_SEASON_ENDING_EXIT")
                                record_vocal_room_exit(result_context, post_det.state.value)
                                return finish("ROOM_EXIT", post_det.state.value, exit_path, 0)
                        return finish("SEASON_ENDING_FAILURE", resumed.state.value, None, 2)
                    return finish(interruption_reason, resumed.state.value, interruption_path, 2)
                if reason == "ROOM_EXIT":
                    record_vocal_room_exit(result_context, observed.state.value)
                return finish(reason, observed.state.value, path, 0 if reason == "ROOM_EXIT" else 2)
    except KeyboardInterrupt:
        write_trace(trace, {"kind": "stop", "reason": "INTERRUPTED", "last_state": last_state})
        return finish("INTERRUPTED", last_state, None, 130)
    except (TargetError, ValueError) as error:
        log.error("Room safety stop: %s", error)
        write_trace(trace, {"kind": "stop", "reason": "SAFETY_ERROR", "detail": str(error), "last_state": last_state})
        return finish("SAFETY_ERROR", last_state, None, 2)


def run_rest_room(dry_run: bool) -> int:
    """Execute one bounded REST_ROOM attempt."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    room_name = "REST_ROOM"
    room = config.get("rooms", {}).get(room_name)
    if not room:
        log.error("%s is not configured.", room_name)
        return 2
    required = ("entry_states", "exit_states", "local_steps", "local_anchors", "interruptions")
    if any(not isinstance(room.get(key), list) for key in required):
        log.error("Invalid %s schema.", room_name)
        return 2
    trace = room_trace_path(room_name)
    last_state = State.UNKNOWN.value
    previous_local_step: str | None = None
    performance = RoomPerformance(
        room_name=room_name,
        entered_at_monotonic=time.monotonic(),
        accelerator_enabled=bool(config.get("transition_accelerator", {}).get("enabled", False)),
    )

    def finish(reason: str, state: str, screenshot: Path | None, code: int) -> int:
        metrics = performance.finish(reason, state)
        write_trace(trace, {"kind": "room_performance", **metrics})
        comparison = None
        if reason == "ROOM_EXIT" and state == State.HOME.value:
            comparison = persist_successful_room_performance(metrics)
            write_trace(trace, {"kind": "room_performance_comparison", "comparison": comparison})
        room_summary(room_name, reason, state, trace, screenshot)
        print_room_performance(metrics, comparison)
        return code

    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            image = target_screenshot(target, config)
            current = detect_state(image, config, BASE_DIR)
            last_state = current.state.value
            write_trace(trace, {"kind": "entry", "room": room_name, "state": current.state.value,
                                "template": current.template, "confidence": current.confidence, "dry_run": dry_run})
            if current.state.value not in room["entry_states"]:
                path = save_shot(image, "ROOM_INVALID_ENTRY")
                write_trace(trace, {"kind": "stop", "reason": "INVALID_ENTRY", "state": current.state.value, "screenshot": str(path)})
                return finish("INVALID_ENTRY", current.state.value, path, 2)
            for number, step in enumerate(room["local_steps"], start=1):
                if number > int(room.get("max_local_steps", len(room["local_steps"]))):
                    raise ValueError("Room local-step limit would be exceeded.")
                if current.state.value != step.get("source_state"):
                    path = save_shot(image, "ROOM_UNEXPECTED_LOCAL_STATE")
                    write_trace(trace, {"kind": "stop", "reason": "UNEXPECTED_UI", "state": current.state.value,
                                        "expected_source": step.get("source_state"), "screenshot": str(path)})
                    return finish("UNEXPECTED_UI", current.state.value, path, 2)
                action = room_step_action(config, step)
                previous_local_step = action["name"]
                point = random_point(action["box"], config["game_window"], config["defaults"])
                if not point_is_inside_window(point, config["game_window"]):
                    raise ValueError("Room action point is outside current game_window.")
                debug = save_action_debug(config["game_window"], action["box"], point, BASE_DIR, f"room_{room_name}_{number}_{action['name']}")
                write_trace(trace, {"kind": "proposal", "room": room_name, "step": number, "current_state": current.state.value,
                                    "action": action["name"], "expected_next_states": action["expected_next_states"],
                                    "proposed_click": point, "debug_screenshot": str(debug), "dry_run": dry_run})
                if dry_run:
                    log.info("room=%s step=%d would_click=%s expected=%s point=%s", room_name, number, action["name"], action["expected_next_states"], point)
                    current = Detection(action["expected_next_states"][0])
                    continue
                before_image = target_screenshot(target, config)
                before = detect_state(before_image, config, BASE_DIR)
                if before.state != current.state:
                    path = save_shot(before_image, "ROOM_STATE_CHANGED_BEFORE_CLICK")
                    write_trace(trace, {"kind": "stop", "reason": "STATE_CHANGED_BEFORE_CLICK", "state": before.state.value, "screenshot": str(path)})
                    return finish("STATE_CHANGED_BEFORE_CLICK", before.state.value, path, 2)
                point = random_point(action["box"], config["game_window"], config["defaults"])
                if not point_is_inside_window(point, config["game_window"]):
                    raise ValueError("Revalidated room action point is outside current game_window.")
                target.verify_and_focus()
                action_sent_at = click_point(point, config["defaults"])
                click_timestamp = datetime.now().isoformat(timespec="milliseconds")
                performance.action_sent_at = action_sent_at
                performance.post_action_observer_started_at = time.monotonic()
                next_state, next_image, reason = wait_for_stable_state(target, config, float(config["states"][current.state.value].get("timeout_seconds", 5)), current.state)
                unknown_details: dict = {}
                if reason == "UNKNOWN" and next_image is not None:
                    next_state, next_image, unknown_reason, unknown_details = confirm_room_unknown(
                        target, config, room, next_image,
                        time.monotonic() + float(config["states"][current.state.value].get("timeout_seconds", 5)),
                        allow_transition_continue=True,
                    )
                    if unknown_reason == "KNOWN":
                        reason = None
                    else:
                        reason = unknown_reason
                local_kind = None
                if reason is None:
                    local_kind = classify_local_transition(
                        next_state.state.value, action["expected_next_states"], room["interruptions"], room["exit_states"],
                    )
                if reason is None and local_kind == "ROOM_EXIT":
                    if next_image is None:
                        next_image = target_screenshot(target, config)
                    exit_path = save_shot(next_image, "ROOM_LOCAL_EXIT")
                    write_trace(trace, {"kind": "local_room_exit", "room": room_name, "step": number,
                                        "source_state": current.state.value, "action": action["name"],
                                        "state": next_state.state.value, "screenshot": str(exit_path)})
                    return finish("ROOM_EXIT", next_state.state.value, exit_path, 0)
                if reason is None and local_kind == "INTERRUPTION":
                    if next_state.state.value in {"SEASON_CLEAR", "SEASON_RESULT"}:
                        cleanup_code = run_post_audition_cleanup(dry_run=dry_run)
                        if cleanup_code == 0:
                            post_img = target_screenshot(target, config)
                            post_det = detect_state(post_img, config, BASE_DIR)
                            if post_det.state == State.HOME:
                                exit_path = save_shot(post_img, "ROOM_SEASON_ENDING_EXIT")
                                return finish("ROOM_EXIT", post_det.state.value, exit_path, 0)
                        return finish("SEASON_ENDING_FAILURE", next_state.state.value, None, 2)
                    next_state, next_image, interruption_reason, interruption_details = dispatch_room_interruption(
                        target, config, room, next_state, next_image, action["expected_next_states"],
                    )
                    if next_image is None:
                        next_image = target_screenshot(target, config)
                    interruption_path = save_shot(next_image, f"ROOM_INTERRUPTION_{interruption_reason}")
                    write_trace(trace, {"kind": "local_interruption", "room": room_name, "step": number,
                                        "source_state": current.state.value, "action": action["name"],
                                        "interruption_state": next_state.state.value, "result": interruption_reason,
                                        "screenshot": str(interruption_path), "details": interruption_details})
                    if interruption_reason == "ROOM_EXIT":
                        return finish("ROOM_EXIT", next_state.state.value, interruption_path, 0)
                    if interruption_reason == "LOCAL_RESUME":
                        reason = None
                    elif interruption_reason in {"SEASON_CLEAR", "SEASON_RESULT"}:
                        cleanup_code = run_post_audition_cleanup(dry_run=dry_run)
                        if cleanup_code == 0:
                            post_img = target_screenshot(target, config)
                            post_det = detect_state(post_img, config, BASE_DIR)
                            if post_det.state == State.HOME:
                                exit_path = save_shot(post_img, "ROOM_SEASON_ENDING_EXIT")
                                return finish("ROOM_EXIT", post_det.state.value, exit_path, 0)
                        return finish("SEASON_ENDING_FAILURE", next_state.state.value, None, 2)
                    else:
                        reason = interruption_reason
                if next_image is None:
                    next_image = target_screenshot(target, config)
                result_path = save_shot(next_image, "ROOM_LOCAL_STEP")
                evidence_details = unknown_details
                step_candidate_paths, step_first_stable_path = [], None
                if reason == "CONFIRMED_UNKNOWN":
                    step_candidate_paths, step_first_stable_path = save_confirmed_unknown_candidates(evidence_details)
                write_trace(trace, {"kind": "local_step", "room": room_name, "step": number, "current_state": current.state.value,
                                    "action": action["name"], "expected_next_states": action["expected_next_states"], "actual_click": point,
                                    "click_timestamp": click_timestamp,
                                    "resulting_state": next_state.state.value, "resulting_confidence": next_state.confidence,
                                    "screenshot": str(result_path), "stop_reason": reason,
                                    "candidate_screenshots": step_candidate_paths,
                                    "first_stable_unknown_screenshot": step_first_stable_path,
                                    "unknown_similarity": evidence_details.get("similarities"),
                                    "unknown_stability_threshold": evidence_details.get("threshold")})
                if reason or next_state.state.value not in action["expected_next_states"]:
                    stop_reason = reason or "UNEXPECTED_TRANSITION"
                    return finish(stop_reason, next_state.state.value, result_path, 2)
                current, image, last_state = next_state, next_image, next_state.state.value
            if dry_run:
                write_trace(trace, {"kind": "stop", "reason": "DRY_RUN", "state": current.state.value})
                return finish("DRY_RUN", current.state.value, None, 0)
            while True:
                observed, observed_image, reason, details = wait_for_room_event(target, config, room, current.state.value)
                if observed_image is None:
                    observed_image = target_screenshot(target, config)
                path = save_shot(observed_image, f"ROOM_{reason}")
                candidate_paths: list[str] = []
                first_stable_path = None
                if reason == "CONFIRMED_UNKNOWN":
                    candidate_paths, first_stable_path = save_confirmed_unknown_candidates(details)
                write_trace(trace, {"kind": "room_observation", "room": room_name, "source_state": current.state.value,
                                    "previous_local_step": previous_local_step,
                                    "state": observed.state.value, "template": observed.template, "confidence": observed.confidence,
                                    "reason": reason, "screenshot": str(path), "candidate_screenshots": candidate_paths,
                                    "first_stable_unknown_screenshot": first_stable_path,
                                    "unknown_similarity": details.get("similarities"), "unknown_stability_threshold": details.get("threshold")})
                if reason == "ROOM_INTERRUPTED":
                    if observed.state.value in {"SEASON_CLEAR", "SEASON_RESULT"}:
                        cleanup_code = run_post_audition_cleanup(dry_run=dry_run)
                        if cleanup_code == 0:
                            post_img = target_screenshot(target, config)
                            post_det = detect_state(post_img, config, BASE_DIR)
                            if post_det.state == State.HOME:
                                exit_path = save_shot(post_img, "ROOM_SEASON_ENDING_EXIT")
                                return finish("ROOM_EXIT", post_det.state.value, exit_path, 0)
                        return finish("SEASON_ENDING_FAILURE", observed.state.value, None, 2)
                    resumed, resumed_image, interruption_reason, interruption_details = dispatch_room_interruption(
                        target, config, room, observed, observed_image, room["local_anchors"],
                    )
                    if resumed_image is None:
                        resumed_image = target_screenshot(target, config)
                    interruption_path = save_shot(resumed_image, f"ROOM_INTERRUPTION_{interruption_reason}")
                    write_trace(trace, {"kind": "room_interruption", "room": room_name,
                                        "source_state": current.state.value, "interruption_state": observed.state.value,
                                        "result": interruption_reason, "state": resumed.state.value,
                                        "screenshot": str(interruption_path), "details": interruption_details})
                    if interruption_reason == "ROOM_EXIT":
                        return finish("ROOM_EXIT", resumed.state.value, interruption_path, 0)
                    if interruption_reason == "LOCAL_RESUME":
                        current, image, last_state = resumed, resumed_image, resumed.state.value
                        continue
                    if interruption_reason in {"SEASON_CLEAR", "SEASON_RESULT"}:
                        cleanup_code = run_post_audition_cleanup(dry_run=dry_run)
                        if cleanup_code == 0:
                            post_img = target_screenshot(target, config)
                            post_det = detect_state(post_img, config, BASE_DIR)
                            if post_det.state == State.HOME:
                                exit_path = save_shot(post_img, "ROOM_SEASON_ENDING_EXIT")
                                return finish("ROOM_EXIT", post_det.state.value, exit_path, 0)
                        return finish("SEASON_ENDING_FAILURE", resumed.state.value, None, 2)
                    return finish(interruption_reason, resumed.state.value, interruption_path, 2)
                return finish(reason, observed.state.value, path, 0 if reason == "ROOM_EXIT" else 2)
    except KeyboardInterrupt:
        write_trace(trace, {"kind": "stop", "reason": "INTERRUPTED", "last_state": last_state})
        return finish("INTERRUPTED", last_state, None, 130)
    except (TargetError, ValueError) as error:
        log.error("Room safety stop: %s", error)
        write_trace(trace, {"kind": "stop", "reason": "SAFETY_ERROR", "detail": str(error), "last_state": last_state})
        return finish("SAFETY_ERROR", last_state, None, 2)


def wait_for_stable_state(target: BrowserTarget, config: dict, timeout: float, source_state: State) -> tuple[Detection, object, str | None]:
    """Observe a stable known state change, or return UNKNOWN/timeout without clicking."""
    deadline = time.monotonic() + timeout
    candidate: Detection | None = None
    last_image = None
    while time.monotonic() < deadline:
        image = target_screenshot(target, config)
        detected = detect_state(image, config, BASE_DIR)
        last_image = image
        if detected.state == State.UNKNOWN:
            return detected, image, "UNKNOWN"
        if detected.state == source_state:
            candidate = None
            time.sleep(config["defaults"]["poll_interval_seconds"])
            continue
        if candidate is not None and candidate.state == detected.state:
            return detected, image, None
        candidate = detected
        time.sleep(config["defaults"]["poll_interval_seconds"])
    return Detection(State.UNKNOWN), last_image, "TIMEOUT"


def wait_for_expected_local_state(target: BrowserTarget, config: dict, timeout: float,
                                  expected_states: list[str]) -> tuple[Detection, object, str | None]:
    """Require a stable expected state, including an intentionally unchanged source UI."""
    deadline = time.monotonic() + timeout
    candidate: Detection | None = None
    last_image = None
    while time.monotonic() < deadline:
        image = target_screenshot(target, config)
        detected = detect_state(image, config, BASE_DIR)
        last_image = image
        if detected.state == State.UNKNOWN:
            return detected, image, "UNKNOWN"
        if detected.state.value not in expected_states:
            return detected, image, "UNEXPECTED_TRANSITION"
        if candidate is not None and candidate.state == detected.state:
            return detected, image, None
        candidate = detected
        time.sleep(config["defaults"]["poll_interval_seconds"])
    return Detection(State.UNKNOWN), last_image, "TIMEOUT"


def wait_for_battle_speed_effect(target: BrowserTarget, config: dict, before_image,
                                 previous_speed: int, timeout: float) -> tuple[Detection, object, str | None, dict]:
    """Require a changed speed-control ROI and a fresh confidently identified speed."""
    settings = config["states"]["AUDITION_BATTLE"]["speed_feature"]
    before_crop = crop_normalized(before_image, settings["roi"])
    deadline = time.monotonic() + timeout
    last: dict = {}
    last_image = before_image
    while time.monotonic() < deadline:
        image = target_screenshot(target, config)
        last_image = image
        parent = detect_state(image, config, BASE_DIR)
        if parent.state.value != "AUDITION_BATTLE":
            return parent, image, "UNEXPECTED_TRANSITION", last
        evidence = detect_audition_battle_speed(image, config)
        similarity = frame_similarity(before_crop, crop_normalized(image, settings["roi"]))
        last = {**evidence, "frame_similarity": similarity, "previous_speed": previous_speed}
        speed = evidence.get("speed")
        if similarity <= float(settings.get("effect_similarity_max", 0.98)):
            if speed in {1, 2, 3} and speed != previous_speed:
                return parent, image, None, last
            if speed is None:
                return parent, image, "SPEED_UNKNOWN", last
        time.sleep(config["defaults"]["poll_interval_seconds"])
    return Detection("AUDITION_BATTLE"), last_image, "SPEED_EFFECT_NOT_VERIFIED", last


def run_audition_battle(dry_run: bool) -> int:
    """Reach 3x, toggle Auto once, then passively await AUDITION_RESULT."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    room_name = "AUDITION_BATTLE_HANDLER"
    room = config.get("rooms", {}).get(room_name)
    trace = room_trace_path(room_name)
    if not isinstance(room, dict):
        log.error("%s is not configured.", room_name)
        return 2
    completion = room.get("completion", {})
    if (completion.get("type") != "passive_wait" or completion.get("expected_next_states") != room.get("exit_states")
            or room.get("exit_states") != ["AUDITION_RESULT"]):
        log.error("Invalid AUDITION_BATTLE completion contract.")
        return 2
    steps = room.get("local_steps")
    if not isinstance(steps, list) or [step.get("action") for step in steps] != ["battle_speed_cycle", "battle_auto_on"]:
        log.error("Invalid ordered AUDITION_BATTLE action plan.")
        return 2
    used_actions: list[str] = []
    last_state = State.UNKNOWN.value
    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            image = target_screenshot(target, config)
            current = detect_state(image, config, BASE_DIR)
            last_state = current.state.value
            write_trace(trace, {"kind": "entry", "room": room_name, "state": current.state.value,
                                "template": current.template, "confidence": current.confidence, "dry_run": dry_run})
            if current.state.value not in room["entry_states"]:
                path = save_shot(image, "AUDITION_BATTLE_INVALID_ENTRY")
                write_trace(trace, {"kind": "stop", "reason": "INVALID_ENTRY", "state": current.state.value,
                                    "screenshot": str(path)})
                room_summary(room_name, "INVALID_ENTRY", current.state.value, trace, path)
                return 2
            speed_step, auto_step = steps
            speed_action = room_step_action(config, speed_step)
            target_speed = int(speed_step.get("target_speed", 0))
            max_speed_clicks = int(speed_step.get("max_clicks", 0))
            if (target_speed != 3 or max_speed_clicks != 2 or speed_action.get("target_speed") != 3
                    or speed_action.get("max_clicks") != 2):
                raise ValueError("AUDITION_BATTLE speed target contract must be 3x with at most two clicks.")
            speed_evidence = detect_audition_battle_speed(image, config)
            current_speed = speed_evidence.get("speed")
            write_trace(trace, {"kind": "battle_speed_observation", "room": room_name,
                                "target_speed": target_speed, **speed_evidence, "dry_run": dry_run})
            if current_speed not in {1, 2, 3}:
                evidence = save_shot(image, "AUDITION_BATTLE_SPEED_UNKNOWN")
                room_summary(room_name, "SPEED_UNKNOWN", current.state.value, trace, evidence)
                return 2
            if dry_run:
                planned = 0 if current_speed == 3 else (1 if current_speed == 2 else 2)
                write_trace(trace, {"kind": "battle_speed_dry_run", "current_speed": current_speed,
                                    "target_speed": 3, "planned_clicks": planned})
            else:
                speed_clicks = 0
                while current_speed != target_speed and speed_clicks < max_speed_clicks:
                    before_image = target_screenshot(target, config)
                    before = detect_state(before_image, config, BASE_DIR)
                    if before.state.value != "AUDITION_BATTLE":
                        evidence = save_shot(before_image, "AUDITION_BATTLE_STATE_CHANGED_BEFORE_SPEED")
                        room_summary(room_name, "STATE_CHANGED_BEFORE_CLICK", before.state.value, trace, evidence)
                        return 2
                    point = random_point(speed_action["box"], config["game_window"], config["defaults"])
                    if not point_is_inside_window(point, config["game_window"]):
                        raise ValueError("AUDITION_BATTLE speed point is outside current game_window.")
                    debug = save_action_debug(config["game_window"], speed_action["box"], point, BASE_DIR,
                                              f"audition_battle_speed_{speed_clicks + 1}")
                    write_trace(trace, {"kind": "proposal", "room": room_name, "step": "speed",
                                        "action": speed_action["name"], "target_speed": target_speed,
                                        "speed_before": current_speed, "proposed_click": point,
                                        "debug_screenshot": str(debug), "dry_run": False})
                    target.verify_and_focus()
                    click_point(point, config["defaults"])
                    speed_clicks += 1
                    used_actions.append(speed_action["name"])
                    current, image, reason, effect = wait_for_battle_speed_effect(
                        target, config, before_image, int(current_speed),
                        float(config["states"]["AUDITION_BATTLE"].get("timeout_seconds", 5)),
                    )
                    evidence = save_shot(image, f"AUDITION_BATTLE_SPEED_{speed_clicks}")
                    write_trace(trace, {"kind": "battle_speed_step", "click_index": speed_clicks,
                                        "action": speed_action["name"], "speed_before": current_speed,
                                        "speed_after": effect.get("speed"), "effect": effect,
                                        "stop_reason": reason, "screenshot": str(evidence)})
                    if reason is not None:
                        room_summary(room_name, reason, current.state.value, trace, evidence)
                        return 2
                    current_speed = effect.get("speed")
                if current_speed != target_speed:
                    evidence = save_shot(image, "AUDITION_BATTLE_SPEED_TARGET_NOT_REACHED")
                    room_summary(room_name, "SPEED_TARGET_NOT_REACHED", current.state.value, trace, evidence)
                    return 2

            for number, step in enumerate([auto_step], start=2):
                if current.state.value != step.get("source_state") or step.get("repeat") != "once":
                    raise ValueError("AUDITION_BATTLE local step is not a once-only step for the current state.")
                action = room_step_action(config, step)
                auto_evidence = detect_audition_battle_auto(image, config)
                write_trace(trace, {"kind": "battle_auto_observation", "room": room_name,
                                    **auto_evidence, "dry_run": dry_run})
                if auto_evidence.get("auto") == "AUTO_UNKNOWN":
                    evidence = save_shot(image, "AUDITION_BATTLE_AUTO_UNKNOWN")
                    room_summary(room_name, "AUTO_STATE_UNKNOWN", current.state.value, trace, evidence)
                    return 2
                if auto_evidence.get("auto") == "AUTO_ON":
                    write_trace(trace, {"kind": "battle_auto_noop", "reason": "AUTO_ALREADY_ON"})
                    continue
                if action.get("repeat") != "once" or action["name"] in used_actions:
                    raise ValueError("AUDITION_BATTLE toggle action is missing once-only metadata or would repeat.")
                point = random_point(action["box"], config["game_window"], config["defaults"])
                if not point_is_inside_window(point, config["game_window"]):
                    raise ValueError("AUDITION_BATTLE point is outside current game_window.")
                debug = save_action_debug(config["game_window"], action["box"], point, BASE_DIR,
                                          f"audition_battle_{number}_{action['name']}")
                write_trace(trace, {"kind": "proposal", "room": room_name, "step": number,
                                    "action": action["name"], "repeat": "once",
                                    "expected_next_states": action["expected_next_states"], "proposed_click": point,
                                    "debug_screenshot": str(debug), "dry_run": dry_run})
                if dry_run:
                    used_actions.append(action["name"])
                    current = Detection("AUDITION_BATTLE")
                    continue
                before_image = target_screenshot(target, config)
                before = detect_state(before_image, config, BASE_DIR)
                if before.state != current.state:
                    path = save_shot(before_image, "AUDITION_BATTLE_STATE_CHANGED_BEFORE_CLICK")
                    write_trace(trace, {"kind": "stop", "reason": "STATE_CHANGED_BEFORE_CLICK",
                                        "state": before.state.value, "screenshot": str(path)})
                    room_summary(room_name, "STATE_CHANGED_BEFORE_CLICK", before.state.value, trace, path)
                    return 2
                point = random_point(action["box"], config["game_window"], config["defaults"])
                if not point_is_inside_window(point, config["game_window"]):
                    raise ValueError("Revalidated AUDITION_BATTLE point is outside current game_window.")
                target.verify_and_focus()
                click_point(point, config["defaults"])
                used_actions.append(action["name"])
                next_state, next_image, reason = wait_for_expected_local_state(
                    target, config, float(config["states"]["AUDITION_BATTLE"].get("timeout_seconds", 5)),
                    action["expected_next_states"],
                )
                details: dict = {}
                if reason == "UNKNOWN" and next_image is not None:
                    next_state, next_image, unknown_reason, details = confirm_room_unknown(
                        target, config, room, next_image,
                        time.monotonic() + float(config["states"]["AUDITION_BATTLE"].get("timeout_seconds", 5)),
                        allow_transition_continue=True,
                    )
                    reason = None if unknown_reason == "KNOWN" and next_state.state.value in action["expected_next_states"] else unknown_reason
                evidence = save_shot(next_image or before_image, "AUDITION_BATTLE_LOCAL_STEP")
                write_trace(trace, {"kind": "local_step", "room": room_name, "step": number,
                                    "action": action["name"], "repeat": "once", "actual_click": point,
                                    "resulting_state": next_state.state.value, "stop_reason": reason,
                                    "screenshot": str(evidence), "unknown_similarity": details.get("similarities")})
                if reason is not None or next_state.state.value not in action["expected_next_states"]:
                    room_summary(room_name, reason or "UNEXPECTED_TRANSITION", next_state.state.value, trace, evidence)
                    return 2
                auto_verify = detect_audition_battle_auto(next_image, config)
                if auto_verify.get("auto") != "AUTO_ON":
                    evidence = save_shot(next_image, "AUDITION_BATTLE_AUTO_NOT_VERIFIED")
                    room_summary(room_name, "AUTO_TOGGLE_NOT_VERIFIED", next_state.state.value, trace, evidence)
                    return 2
                current = next_state
            if dry_run:
                write_trace(trace, {"kind": "stop", "reason": "DRY_RUN", "state": current.state.value,
                                    "used_actions": used_actions})
                room_summary(room_name, "DRY_RUN", current.state.value, trace)
                return 0
            # Completion is intentionally passive: speed is verified at 3x and
            # the existing once-only Auto action has been spent.
            observed, observed_image, reason, details = wait_for_room_event(
                target, config, room, current.state.value,
                safe_unknown_prior=room.get("safe_unknown_prior"), trace=trace,
                prior_context="AUDITION_BATTLE_COMPLETION",
            )
            evidence = save_shot(observed_image or target_screenshot(target, config), f"AUDITION_BATTLE_{reason}")
            write_trace(trace, {"kind": "completion", "room": room_name, "type": "passive_wait",
                                "used_actions": used_actions, "state": observed.state.value, "reason": reason,
                                "screenshot": str(evidence), "unknown_similarity": details.get("similarities")})
            if reason == "ROOM_EXIT" and observed.state.value == "AUDITION_RESULT":
                room_summary(room_name, "AUDITION_RESULT", observed.state.value, trace, evidence)
                return 0
            room_summary(room_name, reason, observed.state.value, trace, evidence)
            return 2
    except KeyboardInterrupt:
        write_trace(trace, {"kind": "stop", "reason": "INTERRUPTED", "last_state": last_state,
                            "used_actions": used_actions})
        room_summary(room_name, "INTERRUPTED", last_state, trace)
        return 130
    except (TargetError, ValueError) as error:
        log.error("AUDITION_BATTLE safety stop: %s", error)
        write_trace(trace, {"kind": "stop", "reason": "SAFETY_ERROR", "detail": str(error),
                            "last_state": last_state, "used_actions": used_actions})
        room_summary(room_name, "SAFETY_ERROR", last_state, trace)
        return 2


def run_post_audition_cleanup(dry_run: bool) -> int:
    """Boundedly resolve taught post-audition controls until a real boundary.

    This is deliberately not an AUDITION_ROOM. It starts only after a verified
    post-audition boundary and permits its taught safe advance point only
    inside this bounded cleanup transaction.
    """
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    cleanup = config.get("post_audition_cleanup")
    room_name = "POST_AUDITION_CLEANUP"
    trace = room_trace_path(room_name)
    if not isinstance(cleanup, dict):
        log.error("post_audition_cleanup is not configured.")
        return 2
    entry = cleanup.get("entry_states")
    terminal = cleanup.get("terminal_boundaries")
    capabilities = cleanup.get("capability_states")
    hard_stops = cleanup.get("hard_stop_states")
    if not all(isinstance(value, list) for value in (entry, terminal, capabilities, hard_stops)):
        log.error("Invalid post_audition_cleanup schema.")
        return 2
    if any(name not in config["states"] for name in [*entry, *terminal, *capabilities, *hard_stops]):
        log.error("post_audition_cleanup references an unknown state.")
        return 2
    maximum = int(cleanup.get("max_capability_actions", 0))
    timeout = float(cleanup.get("timeout_seconds", 0))
    if maximum < 1 or timeout <= 0:
        log.error("Invalid post_audition_cleanup limits.")
        return 2
    # The dispatcher intentionally receives only capability states as its
    # room-local interruption vocabulary. Hard-stop states bypass it below.
    capability_context = {"interruptions": capabilities}
    observer_context = {"exit_states": terminal, "interruptions": [*capabilities, *hard_stops],
                        "local_anchors": entry}
    used_actions: set[str] = set()
    dialogue_continue_clicks = 0
    dialogue_no_effect_count = 0
    last_state = State.UNKNOWN.value
    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            image = target_screenshot(target, config)
            detected = detect_state(image, config, BASE_DIR)
            last_state = detected.state.value
            write_trace(trace, {"kind": "entry", "flow": room_name, "state": detected.state.value,
                                "template": detected.template, "confidence": detected.confidence,
                                "dry_run": dry_run})
            if not post_audition_entry_allowed(cleanup, detected.state.value):
                path = save_shot(image, "POST_AUDITION_INVALID_ENTRY")
                write_trace(trace, {"kind": "stop", "reason": "INVALID_ENTRY", "state": detected.state.value,
                                    "screenshot": str(path)})
                room_summary(room_name, "INVALID_ENTRY", detected.state.value, trace, path)
                return 2
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                image = target_screenshot(target, config)
                detected = detect_state(image, config, BASE_DIR)
                last_state = detected.state.value
                write_trace(trace, {"kind": "observation", "flow": room_name, "state": detected.state.value,
                                    "template": detected.template, "confidence": detected.confidence,
                                    "used_actions": sorted(used_actions)})
                # UNKNOWN is handled only by the cleanup-local bounded drain
                # below.  Do not run the global multi-sample UNKNOWN classifier
                # between presentation taps.
                state = detected.state.value
                if state == State.HOME.value:
                    evidence = save_shot(image, "POST_AUDITION_TERMINAL")
                    write_trace(trace, {"kind": "stop", "reason": "CLEANUP_COMPLETE", "state": state,
                                        "screenshot": str(evidence), "used_actions": sorted(used_actions)})
                    room_summary(room_name, "CLEANUP_COMPLETE", state, trace, evidence)
                    return 0
                if state in hard_stops:
                    evidence = save_shot(image, "POST_AUDITION_HANDOFF")
                    write_trace(trace, {"kind": "stop", "reason": "ROOM_INTERRUPTED", "state": state,
                                        "screenshot": str(evidence)})
                    room_summary(room_name, "ROOM_INTERRUPTED", state, trace, evidence)
                    return 2
                cta = detect_safe_pink_cta(image, cleanup.get("safe_pink_cta", {}))
                if cta is not None:
                    remaining = int(cleanup.get("max_dialogue_continue_clicks", 12)) - dialogue_continue_clicks
                    if remaining < 1:
                        evidence = save_shot(image, "POST_AUDITION_DIALOGUE_LIMIT")
                        room_summary(room_name, "CAPABILITY_LIMIT", state, trace, evidence)
                        return 2
                    next_state, next_image, outcome, details = run_cleanup_transition_drain(
                        target, config, cleanup, source_state=state, trace=trace, deadline=deadline,
                        dry_run=dry_run, maximum_actions=remaining,
                    )
                    dialogue_continue_clicks += int(details.get("attempts", 0))
                    if outcome == "CLEANUP_COMPLETE":
                        evidence = save_shot(next_image, "POST_AUDITION_TERMINAL")
                        room_summary(room_name, outcome, next_state.state.value, trace, evidence)
                        return 0
                    if outcome == "KNOWN":
                        continue
                    evidence = save_shot(next_image or image, f"POST_AUDITION_{outcome}")
                    room_summary(room_name, outcome, next_state.state.value, trace, evidence)
                    return 0 if outcome == "DRY_RUN" else 2
                if state in terminal:
                    evidence = save_shot(image, "POST_AUDITION_TERMINAL")
                    write_trace(trace, {"kind": "stop", "reason": "CLEANUP_COMPLETE", "state": state,
                                        "screenshot": str(evidence), "used_actions": sorted(used_actions)})
                    room_summary(room_name, "CLEANUP_COMPLETE", state, trace, evidence)
                    return 0
                capability = known_control_capability(config, detected, capability_context)
                if capability is not None:
                    action_name = capability["action_name"]
                    is_result_dialogue_continue = state == "AUDITION_RESULT_DIALOGUE"
                    if action_name in used_actions and not is_result_dialogue_continue:
                        # Toggles/continues are one-shot in this transaction;
                        # wait for a real boundary rather than clicking again.
                        time.sleep(config["defaults"]["poll_interval_seconds"])
                        continue
                    if not is_result_dialogue_continue and len(used_actions) >= maximum:
                        evidence = save_shot(image, "POST_AUDITION_CAPABILITY_LIMIT")
                        write_trace(trace, {"kind": "stop", "reason": "CAPABILITY_LIMIT", "state": state,
                                            "screenshot": str(evidence), "used_actions": sorted(used_actions)})
                        room_summary(room_name, "CAPABILITY_LIMIT", state, trace, evidence)
                        return 2
                    write_trace(trace, {"kind": "capability_proposal", "flow": room_name, "state": state,
                                        "action": action_name, "mode": capability["mode"], "dry_run": dry_run})
                    if dry_run:
                        room_summary(room_name, "DRY_RUN_CAPABILITY_AVAILABLE", state, trace)
                        return 0
                    if dialogue_continue_clicks >= int(cleanup.get("max_dialogue_continue_clicks", 12)):
                        evidence = save_shot(image, "POST_AUDITION_DIALOGUE_LIMIT")
                        room_summary(room_name, "CAPABILITY_LIMIT", state, trace, evidence)
                        return 2
                    # Mark before the click: an attempted once-only capability
                    # is never retried when its transition cannot be verified.
                    used_actions.add(action_name)
                    action = configured_action(config, state, action_name)
                    point = random_point(action["box"], config["game_window"], config["defaults"])
                    if not point_is_inside_window(point, config["game_window"]):
                        raise ValueError("Post-audition capability point is outside game_window.")
                    target.verify_and_focus()
                    click_point(point, config["defaults"])
                    dialogue_continue_clicks += 1
                    write_trace(trace, {"kind": "capability_sent", "flow": room_name,
                                        "source_state": state, "action": action_name,
                                        "actual_click": point, "click_count": dialogue_continue_clicks})
                    remaining = int(cleanup.get("max_dialogue_continue_clicks", 12)) - dialogue_continue_clicks
                    if remaining < 1:
                        evidence = save_shot(image, "POST_AUDITION_DIALOGUE_LIMIT")
                        room_summary(room_name, "CAPABILITY_LIMIT", state, trace, evidence)
                        return 2
                    next_state, next_image, outcome, details = run_cleanup_transition_drain(
                        target, config, cleanup, source_state=state, trace=trace, deadline=deadline,
                        dry_run=False, maximum_actions=remaining,
                    )
                    dialogue_continue_clicks += int(details.get("attempts", 0))
                    action_evidence = save_shot(next_image or image, "POST_AUDITION_CAPABILITY")
                    write_trace(trace, {"kind": "capability_result", "flow": room_name,
                                        "source_state": state, "action": action_name,
                                        "outcome": outcome, "state": next_state.state.value,
                                        "screenshot": str(action_evidence), "details": details,
                                        "used_actions": sorted(used_actions)})
                    if outcome == "CLEANUP_COMPLETE":
                        room_summary(room_name, outcome, next_state.state.value, trace, action_evidence)
                        return 0
                    if outcome == "KNOWN":
                        continue
                    room_summary(room_name, outcome, next_state.state.value, trace, action_evidence)
                    return 2
                remaining = int(cleanup.get("max_dialogue_continue_clicks", 12)) - dialogue_continue_clicks
                if remaining < 1:
                    evidence = save_shot(image, "POST_AUDITION_DIALOGUE_LIMIT")
                    room_summary(room_name, "CAPABILITY_LIMIT", state, trace, evidence)
                    return 2
                next_state, next_image, outcome, details = run_cleanup_transition_drain(
                    target, config, cleanup, source_state=state, trace=trace, deadline=deadline,
                    dry_run=dry_run, maximum_actions=remaining,
                )
                dialogue_continue_clicks += int(details.get("attempts", 0))
                if outcome == "CLEANUP_COMPLETE":
                    evidence = save_shot(next_image, "POST_AUDITION_TERMINAL")
                    room_summary(room_name, outcome, next_state.state.value, trace, evidence)
                    return 0
                if outcome == "KNOWN":
                    continue
                evidence = save_shot(next_image or image, f"POST_AUDITION_{outcome}")
                room_summary(room_name, outcome, next_state.state.value, trace, evidence)
                return 0 if outcome == "DRY_RUN" else 2
            final_image = target_screenshot(target, config)
            final = detect_state(final_image, config, BASE_DIR)
            evidence = save_shot(final_image, "POST_AUDITION_TIMEOUT")
            write_trace(trace, {"kind": "stop", "reason": "CLEANUP_TIMEOUT", "state": final.state.value,
                                "screenshot": str(evidence), "used_actions": sorted(used_actions)})
            room_summary(room_name, "CLEANUP_TIMEOUT", final.state.value, trace, evidence)
            return 2
    except KeyboardInterrupt:
        write_trace(trace, {"kind": "stop", "reason": "INTERRUPTED", "state": last_state,
                            "used_actions": sorted(used_actions)})
        room_summary(room_name, "INTERRUPTED", last_state, trace)
        return 130
    except (TargetError, ValueError) as error:
        log.error("Post-audition cleanup safety stop: %s", error)
        write_trace(trace, {"kind": "stop", "reason": "SAFETY_ERROR", "detail": str(error),
                            "state": last_state, "used_actions": sorted(used_actions)})
        room_summary(room_name, "SAFETY_ERROR", last_state, trace)
        return 2


def reflection_click_and_verify(target: BrowserTarget, config: dict, *, box: list[float] | tuple[float, ...],
                                expected_states: list[str]) -> tuple[Detection, object, str | None, tuple[int, int]]:
    """Click one already-taught REFLECTION control/node and verify a known state."""
    before_image = target_screenshot(target, config)
    before = detect_state(before_image, config, BASE_DIR)
    if before.state.value != "REFLECTION":
        return before, before_image, "STATE_CHANGED_BEFORE_CLICK", (0, 0)
    point = random_point(box, config["game_window"], config["defaults"])
    if not point_is_inside_window(point, config["game_window"]):
        raise ValueError("REFLECTION click point is outside current game_window.")
    target.verify_and_focus()
    click_point(point, config["defaults"])
    detected, image, reason = wait_for_expected_local_state(
        target, config, float(config["states"]["REFLECTION"].get("timeout_seconds", 5)), expected_states,
    )
    if reason == "UNKNOWN" and image is not None:
        unknown, unknown_image, unknown_reason, _details = confirm_room_unknown(
            target, config, {"exit_states": expected_states, "interruptions": [], "local_anchors": []}, image,
            time.monotonic() + float(config["states"]["REFLECTION"].get("timeout_seconds", 5)),
        )
        if unknown_reason == "KNOWN" and unknown.state.value in expected_states:
            return unknown, unknown_image, None, point
        return unknown, unknown_image, unknown_reason, point
    return detected, image, reason, point


def reflection_state_action(target: BrowserTarget, config: dict, action_name: str) -> tuple[Detection, object, str | None, tuple[int, int]]:
    action = configured_action(config, "REFLECTION", action_name)
    return reflection_click_and_verify(target, config, box=action["box"], expected_states=action["expected_next_states"])


def reflection_summary(reason: str, state: str, trace: Path, screenshot: Path | None = None) -> None:
    print(f"Reflection spending finished\nReason: {reason}\nLast state: {state}\n"
          f"Evidence: {screenshot or 'none'}\nTrace: {trace}")


def run_reflection_spending(dry_run: bool) -> int:
    """Spend only an explicit skill-route plan; never infers a node or exit action."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    reflection = config.get("reflection", {})
    trace = room_trace_path("REFLECTION_SPENDING")
    try:
        nodes = fixed_route_nodes(reflection) if reflection.get("fixed_route") else configured_route_nodes(reflection)
    except ValueError as error:
        write_trace(trace, {"kind": "stop", "reason": "INVALID_ROUTE", "detail": str(error)})
        reflection_summary("INVALID_ROUTE", State.UNKNOWN.value, trace)
        return 2
    maximum = int(reflection.get("max_purchase_attempts", 0))
    if maximum < 1:
        write_trace(trace, {"kind": "stop", "reason": "INVALID_MAX_PURCHASE_ATTEMPTS"})
        reflection_summary("INVALID_MAX_PURCHASE_ATTEMPTS", State.UNKNOWN.value, trace)
        return 2
    completed: list[str] = []
    skipped: list[str] = []
    attempts = 0
    last_state = State.UNKNOWN.value
    automatic_geometry = reflection_geometry_is_taught(config)
    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            entry_image = target_screenshot(target, config)
            entry = detect_state(entry_image, config, BASE_DIR)
            last_state = entry.state.value
            write_trace(trace, {"kind": "entry", "state": entry.state.value, "template": entry.template,
                                "confidence": entry.confidence, "dry_run": dry_run,
                                "route": [node.node_id for node in nodes], "automatic_geometry": automatic_geometry})
            if entry.state.value != "REFLECTION":
                path = save_shot(entry_image, "REFLECTION_INVALID_ENTRY")
                reflection_summary("INVALID_ENTRY", entry.state.value, trace, path)
                return 2
            if not nodes and not automatic_geometry:
                path = save_shot(entry_image, "REFLECTION_ROUTE_NOT_TAUGHT")
                write_trace(trace, {"kind": "stop", "reason": "ROUTE_NOT_TAUGHT", "screenshot": str(path)})
                reflection_summary("ROUTE_NOT_TAUGHT", entry.state.value, trace, path)
                return 2
            if dry_run:
                write_trace(trace, {"kind": "proposal", "action": "reflection_zoom_out", "repeat": "once"})
                remaining_sp, sp_details = read_committed_reflection_sp(target, config, label="DRY_RUN")
                affordable, skipped_nodes = affordable_route_plan(nodes, remaining_sp) if remaining_sp is not None else ([], [])
                write_trace(trace, {"kind": "stop", "reason": "DRY_RUN", "remaining_sp": remaining_sp,
                                    "sp_details": sp_details, "next_affordable_node": affordable[0].node_id if affordable else None,
                                    "unaffordable_nodes": [node.node_id for node in skipped_nodes]})
                reflection_summary("DRY_RUN", entry.state.value, trace)
                return 0
            zoomed, zoom_image, zoom_reason, zoom_point = reflection_state_action(target, config, "reflection_zoom_out")
            zoom_path = save_shot(zoom_image or entry_image, "REFLECTION_ZOOM_OUT")
            write_trace(trace, {"kind": "zoom_out", "action": "reflection_zoom_out", "actual_click": zoom_point,
                                "state": zoomed.state.value, "reason": zoom_reason, "screenshot": str(zoom_path)})
            if zoom_reason is not None or zoomed.state.value != "REFLECTION":
                reflection_summary(zoom_reason or "UNEXPECTED_UI", zoomed.state.value, trace, zoom_path)
                return 2
            if automatic_geometry:
                geometry_image = target_screenshot(target, config)
                try:
                    nodes, geometry_details = automatic_reflection_nodes(geometry_image, config)
                except ValueError as error:
                    path = save_shot(geometry_image, "REFLECTION_AUTO_ROUTE_UNCERTAIN")
                    reason = str(error).split(":", 1)[0]
                    write_trace(trace, {"kind": "stop", "reason": reason, "detail": str(error),
                                        "screenshot": str(path)})
                    reflection_summary(reason, "REFLECTION", trace, path)
                    return 2
                write_trace(trace, {"kind": "automatic_route", "route": [node.node_id for node in nodes],
                                    "details": geometry_details})
            remaining_sp, initial_sp_details = read_committed_reflection_sp(target, config, label="INITIAL")
            write_trace(trace, {"kind": "remaining_sp", "stage": "initial", "value": remaining_sp,
                                "details": initial_sp_details})
            if remaining_sp is None:
                reflection_summary("SP_UNREADABLE", "REFLECTION", trace)
                return 2
            for node in nodes:
                if remaining_sp < node.expected_cost:
                    skipped.append(node.node_id)
                    write_trace(trace, {"kind": "route_skip", "node": node.node_id, "route": node.route,
                                        "reason": "UNAFFORDABLE", "remaining_sp": remaining_sp,
                                        "expected_cost": node.expected_cost})
                    continue
                if attempts >= maximum:
                    image = target_screenshot(target, config)
                    path = save_shot(image, "REFLECTION_PURCHASE_LIMIT")
                    write_trace(trace, {"kind": "stop", "reason": "MAX_PURCHASE_ATTEMPTS", "attempts": attempts,
                                        "completed": completed, "skipped": skipped, "screenshot": str(path)})
                    reflection_summary("MAX_PURCHASE_ATTEMPTS", "REFLECTION", trace, path)
                    return 2
                attempts += 1
                expected_after_select = ["APPEAL_REPLACE"] if node.node_type == "appeal" else ["REFLECTION"]
                target_box, grounding_details = resolve_runtime_reflection_node(target, config, node)
                if target_box is None:
                    grounded_image = target_screenshot(target, config)
                    path = save_shot(grounded_image, "REFLECTION_TARGET_UNRESOLVED")
                    failure = grounding_details.get("failure", FailureReason.TARGET_NOT_FOUND.value)
                    write_trace(trace, {"kind": "stop", "reason": failure, "node": node.node_id,
                                        "grounding": grounding_details, "screenshot": str(path)})
                    reflection_summary(str(failure), "REFLECTION", trace, path)
                    return 2
                if node.action_name is not None:
                    action = configured_action(config, "REFLECTION", node.action_name)
                    if action["expected_next_states"] != expected_after_select:
                        raise ValueError(f"Route node {node.node_id} action {node.action_name} has incompatible expected state.")
                    selected, selected_image, select_reason, select_point = reflection_state_action(
                        target, config, node.action_name)
                else:
                    selected, selected_image, select_reason, select_point = reflection_click_and_verify(
                        target, config, box=target_box, expected_states=expected_after_select)
                select_path = save_shot(selected_image or entry_image, f"REFLECTION_NODE_{attempts}")
                write_trace(trace, {"kind": "route_select", "attempt_index": attempts, "node": node.node_id,
                                    "route": node.route, "type": node.node_type, "expected_cost": node.expected_cost,
                                    "action": node.action_name, "target": {
                                        "runtime_element_id": node.runtime_element_id,
                                        "resolved_box": list(target_box), "grounding": grounding_details},
                                    "actual_click": select_point, "state": selected.state.value,
                                    "reason": select_reason, "screenshot": str(select_path)})
                write_trace(trace, trajectory_step(
                    episode="REFLECTION_SPENDING", goal="spend configured route", step=attempts,
                    observation=grounding_details.get("observation", {"legacy_target": True}),
                    action={"name": "reflection_skill_node", "target": {"runtime_element_id": node.runtime_element_id,
                            "fallback_box": list(target_box)}},
                    result=ActionResult("reflection_skill_node", issued=select_point is not None,
                                        destination_verified=select_reason is None and selected.state.value in expected_after_select,
                                        committed=False,
                                        failure=FailureReason.STATE_UNEXPECTED if select_reason is not None else None,
                                        metadata={"node": node.node_id, "node_type": node.node_type}),
                ))
                if node.node_type == "appeal":
                    if select_reason is None and selected.state.value == "APPEAL_REPLACE":
                        reflection_summary("APPEAL_REPLACE_ACTION_REQUIRED", selected.state.value, trace, select_path)
                        return 2
                    reflection_summary(select_reason or "APPEAL_REPLACE_NOT_VERIFIED", selected.state.value, trace, select_path)
                    return 2
                if select_reason is not None or selected.state.value != "REFLECTION":
                    reflection_summary(select_reason or "NODE_SELECTION_NOT_VERIFIED", selected.state.value, trace, select_path)
                    return 2
                purchase = configured_action(config, "REFLECTION", "reflection_purchase")
                before_purchase = target_screenshot(target, config)
                before_crop = crop_normalized(before_purchase, purchase["box"])
                before_crop_path = save_shot(before_crop, f"REFLECTION_PURCHASE_BEFORE_{attempts}")
                purchased, purchased_image, purchase_reason, purchase_point = reflection_state_action(
                    target, config, "reflection_purchase")
                after_image = purchased_image or before_purchase
                after_crop = crop_normalized(after_image, purchase["box"])
                after_crop_path = save_shot(after_crop, f"REFLECTION_PURCHASE_AFTER_{attempts}")
                purchase_path = save_shot(after_image, f"REFLECTION_PURCHASE_{attempts}")
                change = frame_similarity(before_purchase, after_image)
                control_change = frame_similarity(before_crop, after_crop)
                post_sp, post_sp_details = (None, {})
                if purchase_reason is None and purchased.state.value == "REFLECTION":
                    post_sp, post_sp_details = read_committed_reflection_sp(target, config, label=f"AFTER_PURCHASE_{attempts}")
                write_trace(trace, {"kind": "purchase_diagnostic", "attempt_index": attempts, "node": node.node_id,
                                    "state": purchased.state.value, "reason": purchase_reason,
                                    "purchase_button_before": str(before_crop_path), "purchase_button_after": str(after_crop_path),
                                    "screenshot": str(purchase_path), "frame_similarity": change,
                                    "purchase_region_similarity": control_change, "remaining_sp_before": remaining_sp,
                                    "remaining_sp_after": post_sp, "post_sp_details": post_sp_details,
                                    "actual_click": purchase_point})
                if purchase_reason is not None or purchased.state.value != "REFLECTION":
                    reflection_summary("CANDIDATE_EXHAUSTION_NEW_STABLE_STATE", purchased.state.value, trace, purchase_path)
                    return 2
                if post_sp is None:
                    reflection_summary("SP_UNREADABLE_AFTER_PURCHASE", "REFLECTION", trace, purchase_path)
                    return 2
                if not may_advance_route_cursor(node_type=node.node_type, resulting_state=purchased.state.value,
                                                remaining_before=remaining_sp, remaining_after=post_sp):
                    # Could be disabled/unavailable or a selection that did not
                    # purchase; neither is safe to silently classify as spent.
                    reflection_summary("CANDIDATE_EXHAUSTION_OR_PURCHASE_UNVERIFIED", "REFLECTION", trace, purchase_path)
                    return 2
                sp_before_commit = remaining_sp
                completed.append(node.node_id)
                remaining_sp = post_sp
                write_trace(trace, {"kind": "node_committed", "attempt_index": attempts, "node": node.node_id,
                                    "remaining_sp": remaining_sp, "completed": completed})
                write_trace(trace, trajectory_step(
                    episode="REFLECTION_SPENDING", goal="spend configured route", step=attempts,
                    observation={"state": "REFLECTION", "remaining_sp": post_sp},
                    action={"name": "reflection_purchase", "target": {"configured_action": "reflection_purchase"}},
                    result=ActionResult("reflection_purchase", issued=purchase_point is not None,
                                        destination_verified=True,
                                        effect=EffectEvidence(destination_state="REFLECTION", numeric_before=sp_before_commit,
                                                              numeric_after=post_sp, verified=True, detail="SP decreased"),
                                        committed=True, metadata={"node": node.node_id}),
                ))
            path = save_shot(target_screenshot(target, config), "REFLECTION_SPENT_COMPLETE")
            write_trace(trace, {"kind": "stop", "reason": "SKILL_SPENDING_COMPLETE", "remaining_sp": remaining_sp,
                                "completed": completed, "skipped": skipped, "attempts": attempts, "screenshot": str(path)})
            reflection_summary("SKILL_SPENDING_COMPLETE", "REFLECTION", trace, path)
            return 0
    except (TargetError, ValueError) as error:
        log.error("REFLECTION safety stop: %s", error)
        write_trace(trace, {"kind": "stop", "reason": "SAFETY_ERROR", "detail": str(error),
                            "completed": completed, "skipped": skipped, "attempts": attempts})
        reflection_summary("SAFETY_ERROR", last_state, trace)
        return 2


def observe_reflection() -> int:
    """Read-only REFLECTION diagnostic: SP and deterministic route plan only."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    trace = room_trace_path("REFLECTION_OBSERVE")
    try:
        nodes = configured_route_nodes(config.get("reflection", {}))
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            image = target_screenshot(target, config)
            detected = detect_state(image, config, BASE_DIR)
            evidence = save_shot(image, "REFLECTION_OBSERVATION")
            if not is_configured_state(detected.state, "REFLECTION"):
                write_trace(trace, {"kind": "stop", "reason": "INVALID_ENTRY", "state": detected.state.value,
                                    "screenshot": str(evidence)})
                print(f"REFLECTION observation requires REFLECTION; found {detected.state.value}. No click made.")
                return 2
            remaining_sp, details = read_committed_reflection_sp(target, config, label="OBSERVE")
        affordable, skipped = affordable_route_plan(nodes, remaining_sp) if remaining_sp is not None else ([], [])
        progress = {"completed": [], "configured_nodes": [node.node_id for node in nodes],
                    "unaffordable": [node.node_id for node in skipped]}
        write_trace(trace, {"kind": "reflection_observation", "remaining_sp": remaining_sp, "sp_details": details,
                            "route": progress, "next_affordable_node": affordable[0].node_id if affordable else None,
                            "screenshot": str(evidence)})
        print(f"remaining_sp={remaining_sp}\ncurrent configured route={progress['configured_nodes']}\n"
              f"next affordable node={affordable[0].node_id if affordable else None}\nroute progress={progress}\ntrace={trace}")
        return 0 if remaining_sp is not None else 2
    except (TargetError, ValueError) as error:
        log.error("REFLECTION observation safety stop: %s", error)
        write_trace(trace, {"kind": "stop", "reason": "SAFETY_ERROR", "detail": str(error)})
        print(f"REFLECTION observation safety stop: {error}\ntrace={trace}")
        return 2


def analyze_reflection_route(verbose: bool = False) -> int:
    """Read-only geometric diagnostic for the taught zoomed REFLECTION boards."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    trace = room_trace_path("REFLECTION_ROUTE_ANALYSIS")
    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            image = target_screenshot(target, config)
            detected = detect_state(image, config, BASE_DIR)
        evidence = save_shot(image, "REFLECTION_ROUTE_ANALYSIS")
        if detected.state.value != "REFLECTION":
            write_trace(trace, {"kind": "stop", "reason": "INVALID_ENTRY", "state": detected.state.value,
                                "screenshot": str(evidence)})
            print(f"REFLECTION route analysis requires REFLECTION; found {detected.state.value}. No click made.")
            return 2
        observation, rejected = reflection_observation(
            image=image, game_window=config.get("game_window", {}), detection=detected,
            reflection_config=config["reflection"], templates_dir=BASE_DIR / "templates" / "reflection_node_semantics",
            screenshot_path=str(evidence),
        )
        raw_boards, _ = analyze_boards(image, config["reflection"], BASE_DIR / "templates" / "reflection_node_semantics")
        annotated_paths: list[str] = []
        for board in raw_boards:
            annotated = board.pop("annotated_board")
            path = save_shot(annotated, f"REFLECTION_ROUTE_{board['board'].upper()}_ANNOTATED")
            annotated_paths.append(str(path))
        write_trace(trace, {"kind": "reflection_geometry", "observation": observation.as_dict(), "rejected": rejected,
                            "annotated_images": annotated_paths, "screenshot": str(evidence)})
        for board in observation.structures:
            info = board.metadata
            print(f"{board.structure_id}: detected node count={info['candidate_count']} center={info['center']} "
                  f"outer-ring={info['outer_ring_count']} start-anchor rotation={info['start_anchor_rotation']}")
            print(f"  clockwise order={[{'id': node.element_id, 'index': node.metadata['clockwise_index'], 'center': [round(value, 4) for value in node.center], 'radius': round(node.metadata['radius'], 2), 'angle': round(node.metadata['angle'], 4), 'semantic': node.semantic} for node in board.members]}")
        if verbose:
            for board in raw_boards:
                print(f"  {board['board']} candidates={board['candidate_diagnostics']}")
        print(f"annotated_images={annotated_paths}\nrejected/ambiguous candidates={rejected}\ntrace={trace}")
        return 0
    except GeometryUncertain as error:
        annotated_path = None
        if error.board_image is not None:
            annotated = annotate_board_geometry(error.board_image, diagnostics=error.diagnostics,
                                                start_anchor=error.start_anchor, geometry=None)
            annotated_path = save_shot(annotated, f"REFLECTION_ROUTE_{(error.board_name or 'UNKNOWN').upper()}_UNCERTAIN_ANNOTATED")
        payload = diagnostic_payload(error.diagnostics)
        write_trace(trace, {"kind": "stop", "reason": "ROUTE_GEOMETRY_UNCERTAIN", "detail": error.reason,
                            "board": error.board_name, "candidates": payload,
                            "annotated_image": str(annotated_path) if annotated_path else None})
        print(f"ROUTE_GEOMETRY_UNCERTAIN: {error.reason}\nannotated_image={annotated_path or 'none'}")
        if verbose:
            print(f"candidates={payload}")
        print(f"trace={trace}")
        return 2


def diagnose_reflection_canonical(board_name: str) -> int:
    """Read-only projection of a calibrated canonical board onto current REFLECTION."""
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    spec = config.get("reflection", {}).get("canonical", {}).get("boards", {}).get(board_name)
    if not spec:
        print("BOARD_REGISTRATION_UNCERTAIN: canonical board is not calibrated")
        return 2
    reference_path = BASE_DIR / "templates" / "reflection_boards" / f"{board_name}.png"
    if not reference_path.exists():
        print(f"BOARD_REGISTRATION_UNCERTAIN: missing reference crop {reference_path}")
        return 2
    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            image, _window = dynamic_screenshot(target, config, BASE_DIR)
            detected = detect_state(image, config, BASE_DIR)
            # REFLECTION is config-defined/dynamically teachable, not a
            # static member of the State enum.
            if detected.state.value != "REFLECTION":
                print(f"Safety stop: expected REFLECTION, found {detected.state.value}")
                return 2
    except (TargetError, ValueError) as error:
        print(f"Safety stop: {error}")
        return 2
    roi = spec["roi"]
    crop = image.crop((round(roi[0] * image.width), round(roi[1] * image.height),
                       round(roi[2] * image.width), round(roi[3] * image.height)))
    board = CanonicalBoard(board_name, (0.0, 0.0, 1.0, 1.0), tuple(spec["origin"]),
                           tuple(spec["basis_q"]), tuple(spec["basis_r"]), tuple(spec["start_anchor"]),
                           tuple(tuple(p) for p in spec.get("outer_ring", [])))
    try:
        result = diagnose_board(PILImage.open(reference_path), crop, board,
                                tile_size=tuple(spec.get("tile_size", (80.0, 70.0))))
    except (ValueError, KeyError) as error:
        print(str(error))
        return 2
    print(json.dumps({"board": board_name, "dx": result["transform"].dx,
                      "dy": result["transform"].dy, "confidence": result["transform"].confidence,
                      "residual": result["transform"].residual, "route_node_count": result["route_count"],
                      "start_index": result["start_index"], "nodes": result["nodes"],
                      "status": result["status"]}, indent=2))
    annotated = crop.convert("RGB").copy()
    draw = ImageDraw.Draw(annotated)
    draw.ellipse((board.origin[0]-5, board.origin[1]-5, board.origin[0]+5, board.origin[1]+5), outline="cyan", width=2)
    for index, row in enumerate(result["nodes"]):
        x, y = row["transformed_center"]
        color = "lime" if row["verified"] and row["inside_board"] and not row["duplicate"] else "red"
        draw.ellipse((x-10, y-10, x+10, y+10), outline=color, width=3)
        draw.text((x+8, y-8), str(index), fill=color)
    output = BASE_DIR / "logs" / f"{datetime.now():%Y%m%d_%H%M%S}_REFLECTION_CANONICAL_{board_name.upper()}_ANNOTATED.png"
    annotated.save(output)
    print(f"annotation={output}")
    return 0 if result["status"] == "OK" else 2


def reflection_geometry_is_taught(config: dict) -> bool:
    boards = config.get("reflection", {}).get("geometry", {}).get("boards", {})
    return all(isinstance(boards.get(name), dict) and boards[name].get("roi") is not None
               and boards[name].get("start_anchor") is not None for name in ("upper_left", "lower_right"))


def automatic_reflection_nodes(image, config: dict, detection: Detection | None = None) -> tuple[list[ReflectionNode], dict]:
    """Turn runtime board elements plus mapped costs/semantics into route nodes.

    The route stores no per-node coordinates: the element id is resolved again
    immediately before every live node click.
    """
    state = detection or detect_state(image, config, BASE_DIR)
    observation, rejected = reflection_observation(
        image=image, game_window=config.get("game_window", {}), detection=state,
        reflection_config=config["reflection"],
        templates_dir=BASE_DIR / "templates" / "reflection_node_semantics",
    )
    nodes: list[ReflectionNode] = []
    boards: list[dict] = []
    for structure in observation.structures:
        board = structure.structure_id.split(":", 1)[1]
        ordered = list(structure.members)
        costs = list(structure.metadata.get("costs_by_order", []))
        if not isinstance(costs, list) or len(costs) != len(ordered) or not all(isinstance(cost, int) and cost >= 0 for cost in costs):
            raise ValueError(f"AUTO_ROUTE_COST_MAPPING_REQUIRED:{board}")
        rendered: list[dict] = []
        for item, cost in zip(ordered, costs):
            semantic = item.semantic or "unknown"
            order = int(item.metadata["clockwise_index"])
            if semantic == "unknown":
                raise ValueError(f"NODE_SEMANTICS_UNVERIFIED:{board}:{order}")
            if semantic == "unavailable":
                raise ValueError(f"NODE_UNAVAILABLE_EVIDENCE_REQUIRED:{board}:{order}")
            route = "upper_left_ring" if board == "upper_left" else "lower_right_ring"
            nodes.append(ReflectionNode(route, f"{board}_{order:02d}", item.bbox, cost, semantic,
                                        runtime_element_id=item.element_id))
            rendered.append(item.as_dict())
        boards.append({"board": board, "members": rendered, "metadata": dict(structure.metadata)})
    return nodes, {"observation": observation.as_dict(), "boards": boards, "rejected": rejected}


def resolve_runtime_reflection_node(target: BrowserTarget, config: dict, node: ReflectionNode) -> tuple[tuple[float, float, float, float] | None, dict]:
    """Freshly ground an auto-discovered node; manual nodes keep legacy boxes."""
    if node.runtime_element_id is None:
        return node.box, {"source": "legacy_manual_box"}
    image = target_screenshot(target, config)
    detected = detect_state(image, config, BASE_DIR)
    if detected.state.value != "REFLECTION":
        return None, {"failure": FailureReason.STATE_UNEXPECTED.value, "state": detected.state.value}
    observation, rejected = reflection_observation(
        image=image, game_window=config.get("game_window", {}), detection=detected,
        reflection_config=config["reflection"],
        templates_dir=BASE_DIR / "templates" / "reflection_node_semantics",
    )
    resolution = resolve_action_target(observation, ActionTarget(runtime_element_id=node.runtime_element_id))
    detail = {"observation": observation.as_dict(), "rejected": rejected, "resolution": {
        "source": resolution.source, "failure": resolution.failure.value if resolution.failure else None,
        "candidates": list(resolution.candidates), "element": resolution.element.as_dict() if resolution.element else None,
    }}
    return resolution.bbox, detail


def configured_passive_transition(config: dict, state: State) -> dict | None:
    passive = config["states"][state.value].get("passive_transition")
    if passive is None:
        return None
    expected = passive.get("expected_next_states")
    if passive.get("type") != "passive_wait" or not isinstance(expected, list):
        raise ValueError(f"{state.value} passive transition must have type passive_wait and expected_next_states list.")
    if any(name not in config["states"] for name in expected):
        raise ValueError(f"{state.value} passive transition has an unknown expected state.")
    return passive


def discovery_summary(steps: int, reason: str, last_state: State, trace: Path, unknown_path: Path | None = None) -> None:
    print(f"Discovery stopped after {steps} steps.\n\nStop reason:\n{reason}\n\nLast state:\n{last_state.value}\n\nNew unknown screenshot:\n{unknown_path or 'none'}\n\nTrace:\n{trace}")


def discover(dry_run: bool, max_steps: int, repeat_limit: int) -> int:
    """Bounded autonomous discovery using only explicit known-state actions."""
    log = setup_logging()
    trace = new_trace_path()
    config = json.loads((BASE_DIR / "config.json").read_text())
    steps = 0
    repeats: dict[tuple[str, str, str], int] = {}
    last_state = State.UNKNOWN
    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            image = target_screenshot(target, config)
            current = detect_state(image, config, BASE_DIR)
            last_state = current.state
            write_trace(trace, {"kind": "initial", "current_state": current.state.value, "matched_template": current.template, "confidence": current.confidence, "known": current.state != State.UNKNOWN})
            if current.state == State.UNKNOWN:
                path = save_shot(image, "DISCOVERY_UNKNOWN")
                log.error("discovery UNKNOWN screenshot=%s", path)
                write_trace(trace, {"kind": "stop", "reason": "UNKNOWN", "screenshot": str(path)})
                discovery_summary(steps, "UNKNOWN", last_state, trace, path)
                return 2
            while steps < max_steps:
                actions = config["states"][current.state.value].get("allowed_actions", [])
                if not actions:
                    passive = configured_passive_transition(config, current.state)
                    if passive is not None:
                        expected = passive["expected_next_states"]
                        write_trace(trace, {"kind": "passive_wait", "step": steps + 1, "current_state": current.state.value, "matched_template": current.template, "confidence": current.confidence, "transition_type": "passive_wait", "expected_next_states": expected, "dry_run": dry_run})
                        log.info("discovery step=%d passive_wait current_state=%s expected_next_states=%s", steps + 1, current.state.value, expected)
                        if dry_run:
                            write_trace(trace, {"kind": "stop", "reason": "DRY_RUN", "state": current.state.value})
                            discovery_summary(steps, "DRY_RUN", current.state, trace)
                            return 0
                        next_state, next_image, wait_reason = wait_for_stable_state(target, config, float(config["states"][current.state.value].get("timeout_seconds", 5)), current.state)
                        if next_image is None:
                            next_image = target_screenshot(target, config)
                        steps += 1
                        if wait_reason:
                            path = save_shot(next_image, f"TEACH_{wait_reason}")
                            write_trace(trace, {"kind": "stop", "reason": wait_reason, "step": steps, "current_state": current.state.value, "transition_type": "passive_wait", "screenshot": str(path)})
                            discovery_summary(steps, wait_reason, State.UNKNOWN if wait_reason == "UNKNOWN" else current.state, trace, path if wait_reason == "UNKNOWN" else None)
                            return 2
                        result_path = save_shot(next_image, "DISCOVERY_PASSIVE_TRANSITION")
                        write_trace(trace, {"kind": "transition", "step": steps, "current_state": current.state.value, "matched_template": current.template, "confidence": current.confidence, "transition_type": "passive_wait", "action": None, "expected_next_states": expected, "actual_next_state": next_state.state.value, "actual_confidence": next_state.confidence, "screenshot": str(result_path)})
                        if next_state.state.value not in expected:
                            unexpected = save_shot(next_image, "DISCOVERY_UNEXPECTED_PASSIVE")
                            write_trace(trace, {"kind": "stop", "reason": "UNEXPECTED_TRANSITION", "transition_type": "passive_wait", "expected_next_states": expected, "actual_state": next_state.state.value, "screenshot": str(unexpected)})
                            discovery_summary(steps, "UNEXPECTED_TRANSITION", next_state.state, trace)
                            return 2
                        key = (current.state.value, "passive_wait", next_state.state.value)
                        repeats[key] = repeats.get(key, 0) + 1
                        if repeats[key] > repeat_limit:
                            path = save_shot(next_image, "DISCOVERY_REPEAT_LIMIT")
                            write_trace(trace, {"kind": "stop", "reason": "REPEAT_LIMIT", "pair": key, "count": repeats[key], "screenshot": str(path)})
                            discovery_summary(steps, "REPEAT_LIMIT", next_state.state, trace)
                            return 2
                        current, image, last_state = next_state, next_image, next_state.state
                        continue
                    path = save_shot(image, "DISCOVERY_NO_ACTION")
                    reason = "NO_ACTION"
                    detail = "morning_event_choice_rule_unconfigured" if current.state == State.MORNING_EVENT else "known_state_but_no_action"
                    log.warning("discovery %s state=%s screenshot=%s", detail, current.state.value, path)
                    write_trace(trace, {"kind": "stop", "reason": reason, "detail": detail, "state": current.state.value, "screenshot": str(path)})
                    discovery_summary(steps, reason, current.state, trace)
                    return 0
                if len(actions) != 1:
                    path = save_shot(image, "DISCOVERY_AMBIGUOUS_ACTION")
                    log.error("discovery ambiguous_action state=%s action_count=%d screenshot=%s", current.state.value, len(actions), path)
                    write_trace(trace, {"kind": "stop", "reason": "AMBIGUOUS_ACTION", "state": current.state.value, "action_count": len(actions), "screenshot": str(path)})
                    discovery_summary(steps, "AMBIGUOUS_ACTION", current.state, trace)
                    return 2
                action = configured_action(config, current.state)
                if current.state == State.MORNING_EVENT and not action.get("choice_rule_id"):
                    path = save_shot(image, "DISCOVERY_MORNING_UNTAUGHT")
                    log.error("discovery MORNING_EVENT has no explicit choice rule screenshot=%s", path)
                    write_trace(trace, {"kind": "stop", "reason": "NO_ACTION", "detail": "morning_event_choice_rule_unconfigured", "state": current.state.value, "screenshot": str(path)})
                    discovery_summary(steps, "NO_ACTION", current.state, trace)
                    return 2
                point = random_point(action["box"], config["game_window"], config["defaults"])
                proposed_point = point
                if not point_is_inside_window(point, config["game_window"]):
                    path = save_shot(image, "DISCOVERY_INVALID_ACTION")
                    raise ValueError(f"Proposed point {point} is outside game_window; screenshot={path}")
                debug = save_action_debug(config["game_window"], action["box"], point, BASE_DIR, f"discovery_{steps + 1}_{action['name']}")
                expected = action["expected_next_states"]
                write_trace(trace, {"kind": "proposal", "step": steps + 1, "current_state": current.state.value, "matched_template": current.template, "confidence": current.confidence, "action": action["name"], "expected_next_states": expected, "proposed_click": proposed_point, "debug_screenshot": str(debug), "dry_run": dry_run})
                log.info("discovery step=%d current_state=%s template=%s confidence=%.3f action=%s expected=%s proposed_click=%s debug=%s", steps + 1, current.state.value, current.template, current.confidence, action["name"], expected, point, debug)
                if dry_run:
                    write_trace(trace, {"kind": "stop", "reason": "DRY_RUN", "state": current.state.value})
                    discovery_summary(steps, "DRY_RUN", current.state, trace)
                    return 0
                before_image = target_screenshot(target, config)
                before = detect_state(before_image, config, BASE_DIR)
                if before.state != current.state:
                    path = save_shot(before_image, "DISCOVERY_STATE_CHANGED")
                    write_trace(trace, {"kind": "stop", "reason": "UNEXPECTED_TRANSITION", "detail": "state_changed_before_click", "expected_state": current.state.value, "actual_state": before.state.value, "screenshot": str(path)})
                    discovery_summary(steps, "UNEXPECTED_TRANSITION", before.state, trace)
                    return 2
                point = random_point(action["box"], config["game_window"], config["defaults"])
                if not point_is_inside_window(point, config["game_window"]):
                    raise ValueError(f"Revalidated point {point} is outside game_window.")
                target.verify_and_focus()
                click_point(point, config["defaults"])
                steps += 1
                next_state, next_image, wait_reason = wait_for_stable_state(target, config, float(config["states"][current.state.value].get("timeout_seconds", 5)), current.state)
                if next_image is None:
                    next_image = target_screenshot(target, config)
                if wait_reason:
                    path = save_shot(next_image, f"DISCOVERY_{wait_reason}")
                    write_trace(trace, {"kind": "stop", "reason": wait_reason, "step": steps, "current_state": current.state.value, "action": action["name"], "actual_click": point, "screenshot": str(path)})
                    discovery_summary(steps, wait_reason, State.UNKNOWN if wait_reason == "UNKNOWN" else current.state, trace, path if wait_reason == "UNKNOWN" else None)
                    return 2
                result_path = save_shot(next_image, "DISCOVERY_TRANSITION")
                write_trace(trace, {"kind": "transition", "step": steps, "current_state": current.state.value, "matched_template": current.template, "confidence": current.confidence, "action": action["name"], "expected_next_states": expected, "proposed_click": proposed_point, "actual_click": point, "resulting_state": next_state.state.value, "resulting_template": next_state.template, "resulting_confidence": next_state.confidence, "screenshot": str(result_path)})
                if next_state.state.value not in expected:
                    unexpected = save_shot(next_image, "DISCOVERY_UNEXPECTED_TRANSITION")
                    write_trace(trace, {"kind": "stop", "reason": "UNEXPECTED_TRANSITION", "expected_next_states": expected, "actual_state": next_state.state.value, "screenshot": str(unexpected)})
                    discovery_summary(steps, "UNEXPECTED_TRANSITION", next_state.state, trace)
                    return 2
                key = (current.state.value, action["name"], next_state.state.value)
                repeats[key] = repeats.get(key, 0) + 1
                if repeats[key] > repeat_limit:
                    path = save_shot(next_image, "DISCOVERY_REPEAT_LIMIT")
                    write_trace(trace, {"kind": "stop", "reason": "REPEAT_LIMIT", "pair": key, "count": repeats[key], "screenshot": str(path)})
                    discovery_summary(steps, "REPEAT_LIMIT", next_state.state, trace)
                    return 2
                current, image, last_state = next_state, next_image, next_state.state
            path = save_shot(image, "DISCOVERY_MAX_STEPS")
            write_trace(trace, {"kind": "stop", "reason": "MAX_STEPS", "state": current.state.value, "screenshot": str(path)})
            discovery_summary(steps, "MAX_STEPS", current.state, trace)
            return 0
    except KeyboardInterrupt:
        log.info("Discovery stopped by Ctrl+C.")
        write_trace(trace, {"kind": "stop", "reason": "INTERRUPTED", "last_state": last_state.value})
        discovery_summary(steps, "INTERRUPTED", last_state, trace)
        return 130
    except (TargetError, ValueError) as error:
        log.error("Discovery safety stop: %s", error)
        write_trace(trace, {"kind": "stop", "reason": "SAFETY_ERROR", "detail": str(error), "last_state": last_state.value})
        discovery_summary(steps, "SAFETY_ERROR", last_state, trace)
        return 2


def teach_post_vocal(timeout_seconds: float) -> int:
    """Observe one post-Vocal state change without sending any click."""
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text())
    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            initial_image = target_screenshot(target, config)
            previous = detect_state(initial_image, config, BASE_DIR)
            initial_path = save_shot(initial_image, "TEACH_POST_VOCAL_START")
            log.info("teaching previous_state=%s detected_state=%s matched_template=%s confidence=%.3f screenshot=%s known=%s", State.VOCAL_RESULT.value, previous.state.value, previous.template, previous.confidence, initial_path, previous.state != State.UNKNOWN)
            if previous.state != State.VOCAL_RESULT:
                log.error("Teaching mode requires VOCAL_RESULT; no click made.")
                return 2
            deadline = time.monotonic() + timeout_seconds
            candidate: Detection | None = None
            while time.monotonic() < deadline:
                time.sleep(config["defaults"]["poll_interval_seconds"])
                image = target_screenshot(target, config)
                detected = detect_state(image, config, BASE_DIR)
                if detected.state == State.UNKNOWN:
                    path = save_shot(image, "TEACH_UNKNOWN")
                    log.error("teaching previous_state=%s detected_state=UNKNOWN matched_template=None confidence=0.000 screenshot=%s known=false; new state needs teaching", previous.state.value, path)
                    print(f"Unknown post-Vocal state saved at {path}; capture/register a template before any automation.")
                    return 2
                if detected.state == previous.state:
                    candidate = None
                    continue
                # Require two consecutive detections of the same new state before reporting it stable.
                if candidate is None or candidate.state != detected.state:
                    candidate = detected
                    continue
                path = save_shot(image, "TEACH_KNOWN_STATE")
                log.info("teaching previous_state=%s detected_state=%s matched_template=%s confidence=%.3f screenshot=%s known=true", previous.state.value, detected.state.value, detected.template, detected.confidence, path)
                print(f"Known post-Vocal state: {detected.state.value}; screenshot saved at {path}. No click made.")
                return 0
            path = save_shot(target_screenshot(target, config), "TEACH_TIMEOUT")
            log.error("Teaching timed out waiting for a post-Vocal state; screenshot=%s", path)
            return 2
    except (TargetError, ValueError) as error:
        log.error("Teaching safety stop: %s", error)
        return 2


def run(dry_run: bool, max_clicks: int) -> int:
    log = setup_logging()
    config = json.loads((BASE_DIR / "config.json").read_text())
    try:
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            current = detect_state(target_screenshot(target, config), config, BASE_DIR)
            log_detection(log, "detected", current)
            if current.state == State.UNKNOWN:
                path = save_shot(target_screenshot(target, config), "UNKNOWN")
                log.error("UNKNOWN before action; screenshot=%s", path)
                return 2
            for number in range(1, max_clicks + 1):
                action = configured_action(config, current.state)
                point = random_point(action["box"], config["game_window"], config["defaults"])
                if not point_is_inside_window(point, config["game_window"]):
                    raise ValueError(f"Proposed click {point} is outside current game_window.")
                debug = save_action_debug(config["game_window"], action["box"], point, BASE_DIR, f"transition_{number}_{action['name']}")
                expected = action["expected_next_states"]
                log.info("transition=%d action=%s expected_next_states=%s proposed_click=%s debug=%s", number, action["name"], expected, point, debug)
                if dry_run:
                    if number == max_clicks:
                        log.info("Dry-run plan complete; planned transitions after the first are not visually verified.")
                        return 0
                    if len(expected) != 1:
                        log.info("Dry-run cannot plan beyond an action with multiple allowed next states.")
                        return 0
                    current = Detection(expected[0])
                    log.info("dry-run planned_next_state=%s (not visually verified because no click was made)", current.value)
                    continue
                # URL focus plus a fresh visual state are required immediately before click.
                before = detect_state(target_screenshot(target, config), config, BASE_DIR)
                if before.state != current.state:
                    path = save_shot(target_screenshot(target, config), "STATE_CHANGED_BEFORE_CLICK")
                    log.error("state changed before click: expected=%s actual=%s screenshot=%s", current.state.value, before.state.value, path)
                    return 2
                point = random_point(action["box"], config["game_window"], config["defaults"])
                if not point_is_inside_window(point, config["game_window"]):
                    raise ValueError(f"Revalidated click {point} is outside current game_window.")
                debug = save_action_debug(config["game_window"], action["box"], point, BASE_DIR, f"transition_{number}_{action['name']}_revalidated")
                log.info("transition=%d revalidated_proposed_click=%s debug=%s", number, point, debug)
                target.verify_and_focus()
                click_point(point, config["defaults"])
                next_image = target_screenshot(target, config)
                actual = detect_state(next_image, config, BASE_DIR)
                next_path = save_shot(next_image, "TRANSITION_RESULT")
                log.info("transition=%d action=%s expected_next_states=%s actual_next_state=%s next_state_confidence=%.3f screenshot=%s", number, action["name"], expected, actual.state.value, actual.confidence, next_path)
                if actual.state.value not in expected:
                    log.error("transition verification failed: expected_one_of=%s actual=%s", expected, actual.state.value)
                    return 2
                current = actual
                if current.state == State.VOCAL_RESULT:
                    log.info("VOCAL_RESULT verified; bounded milestone complete.")
                    return 0
                if number == max_clicks:
                    log.info("Maximum click bound reached after verified transition.")
                    return 0
            return 0
    except (TargetError, ValueError) as error:
        log.error("Safety stop: %s", error)
        return 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Enable a bounded number of validated clicks.")
    parser.add_argument("--dry-run", action="store_true", help="Explicitly run without clicking.")
    parser.add_argument("--max-clicks", type=int, choices=(1, 2), default=1, help="Bound live execution to one or two clicks.")
    parser.add_argument("--teach-post-vocal", action="store_true", help="Observe a post-Vocal state change without clicking.")
    parser.add_argument("--teach", action="store_true", help="Start an interactive, human-confirmed state teaching console.")
    parser.add_argument("--teach-timeout", type=float, default=60.0, help="Seconds to observe in teaching mode.")
    parser.add_argument("--discover", action="store_true", help="Run only explicitly configured safe transitions until evidence requires a stop.")
    parser.add_argument("--max-steps", type=int, default=50, help="Maximum transitions in discovery mode.")
    parser.add_argument("--repeat-limit", type=int, default=3, help="Stop discovery after this many identical state/action/result observations.")
    parser.add_argument("--show-transitions", action="store_true", help="Print configured transitions without connecting to Chrome.")
    parser.add_argument("--show-rooms", action="store_true", help="Print configured room schemas without connecting to Chrome.")
    parser.add_argument("--observe-home", action="store_true", help="Read taught HOME ROIs with repeated OCR validation; never clicks or changes configuration.")
    parser.add_argument("--observe-reflection", action="store_true", help="Read taught REFLECTION SP and route plan; never clicks.")
    parser.add_argument("--analyze-reflection-route", action="store_true", help="Detect and order taught REFLECTION board geometry; never clicks.")
    parser.add_argument("--diagnose-reflection-canonical", choices=("upper_left", "lower_right"), help="Project canonical REFLECTION board read-only; never clicks.")
    parser.add_argument("--verbose", action="store_true", help="Print full read-only diagnostic detail for supported analysis commands.")
    parser.add_argument("--teach-home-roi", choices=("season", "weeks_remaining", "fan_gap_to_target", "stamina"), help="Interactively re-teach one HOME observation ROI; never clicks the game.")
    parser.add_argument("--teach-reflection-board", choices=("upper_left", "lower_right"), help="Teach one REFLECTION board ROI and clockwise start anchor; never clicks.")
    parser.add_argument("--teach-reflection-fixed-route", action="store_true", help="Teach fixed REFLECTION route centers; never clicks.")
    parser.add_argument("--calibrate-reflection-board", choices=("upper_left", "lower_right"), help="Calibrate a canonical REFLECTION board reference; never clicks.")
    parser.add_argument("--teach-home-week-digit", choices=tuple(str(digit) for digit in range(10)), help="Capture one observed HOME weeks digit from its existing tight ROI; never clicks the game.")
    add_audition_target_cli_argument(parser)
    parser.add_argument("--decide-home", action="store_true", help="Read validated HOME facts and print a deterministic policy diagnostic without clicking.")
    parser.add_argument("--run-home-tick", action="store_true", help="Make one validated HOME decision; only --live may run one supported room.")
    parser.add_argument("--mark-season3-reflection-complete", action="store_true", help="Explicitly attest completed Season 3 reflection at HOME; no clicks.")
    parser.add_argument("--mark-season3-auditions-complete", "--mark-season3-audition-complete", action="store_true", help="Explicitly attest completed Season 3 auditions (+40k and +50k) at HOME; no clicks.")
    parser.add_argument("--run-season-trial", type=int, metavar="SEASON", help="Run one bounded, explicit-policy season trial (currently Season 3 only).")
    parser.add_argument("--max-season-ticks", type=int, default=12, help="Maximum HOME ticks in --run-season-trial.")
    parser.add_argument("--run-room", choices=("VOCAL_ROOM", "REST_ROOM"), help="Run one bounded configured room attempt.")
    parser.add_argument("--run-audition-battle", action="store_true", help="Run only the taught once-only battle toggles and passive completion observer.")
    parser.add_argument("--post-audition-cleanup", action="store_true", help="Boundedly resolve taught post-audition controls from AUDITION_RESULT.")
    parser.add_argument("--run-reflection-spending", action="store_true", help="Run one bounded, configured REFLECTION skill-spending transaction.")
    parser.add_argument("--record-demo", metavar="NAME", help="Record human clicks and observations; never injects input.")
    parser.add_argument("--compile-demo", metavar="NAME", help="Compile the latest recorded demo into a non-executable candidate.")
    parser.add_argument("--review-demo", metavar="NAME", help="Review a compiled demonstration candidate.")
    args = parser.parse_args()
    try:
        if args.max_steps < 1 or args.repeat_limit < 1 or args.max_season_ticks < 1:
            parser.error("--max-steps, --repeat-limit, and --max-season-ticks must be positive.")
        if args.show_transitions:
            sys.exit(show_transitions())
        if args.show_rooms:
            sys.exit(show_rooms())
        if args.observe_home:
            sys.exit(observe_home())
        if args.observe_reflection:
            sys.exit(observe_reflection())
        if args.analyze_reflection_route:
            sys.exit(analyze_reflection_route(verbose=args.verbose))
        if args.diagnose_reflection_canonical:
            sys.exit(diagnose_reflection_canonical(args.diagnose_reflection_canonical))
        if args.teach_home_roi:
            sys.exit(teach_home_roi(args.teach_home_roi))
        if args.teach_reflection_board:
            sys.exit(teach_reflection_board(args.teach_reflection_board))
        if args.teach_reflection_fixed_route:
            sys.exit(teach_reflection_fixed_route())
        if args.calibrate_reflection_board:
            sys.exit(calibrate_reflection_board(args.calibrate_reflection_board))
        if args.teach_home_week_digit:
            sys.exit(teach_home_week_digit(args.teach_home_week_digit))
        if args.teach_audition_target is not None:
            sys.exit(teach_audition_target(args.teach_audition_target))
        if args.decide_home:
            sys.exit(decide_home_diagnostic())
        if args.run_home_tick:
            sys.exit(run_home_tick(live=args.live and not args.dry_run))
        if args.mark_season3_reflection_complete:
            sys.exit(mark_season3_reflection_complete())
        if args.mark_season3_auditions_complete:
            sys.exit(mark_season3_auditions_complete())
        if args.run_season_trial is not None:
            sys.exit(run_season_trial(args.run_season_trial, live=args.live and not args.dry_run,
                                      max_ticks=args.max_season_ticks))
        if args.run_audition_battle:
            sys.exit(run_audition_battle(dry_run=not args.live or args.dry_run))
        if args.post_audition_cleanup:
            sys.exit(run_post_audition_cleanup(dry_run=not args.live or args.dry_run))
        if args.run_reflection_spending:
            sys.exit(run_reflection_spending(dry_run=not args.live or args.dry_run))
        if args.record_demo:
            sys.exit(record_demo(args.record_demo))
        if args.compile_demo:
            print(json.dumps(compile_demo(args.compile_demo), indent=2)); sys.exit(0)
        if args.review_demo:
            sys.exit(review_demo(args.review_demo))
        if args.teach:
            sys.exit(teach())
        if args.teach_post_vocal:
            sys.exit(teach_post_vocal(args.teach_timeout))
        if args.discover:
            sys.exit(discover(dry_run=not args.live or args.dry_run, max_steps=args.max_steps, repeat_limit=args.repeat_limit))
        if args.run_room:
            if args.run_room == "REST_ROOM":
                sys.exit(run_rest_room(dry_run=not args.live or args.dry_run))
            sys.exit(run_vocal_room(dry_run=not args.live or args.dry_run))
        sys.exit(run(dry_run=not args.live or args.dry_run, max_clicks=args.max_clicks))
    except KeyboardInterrupt:
        logging.getLogger("enza_te_bot").info("Stopped by Ctrl+C.")
        sys.exit(130)
