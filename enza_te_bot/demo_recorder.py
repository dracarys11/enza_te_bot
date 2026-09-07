"""Passive human demonstration recorder; it never injects application input."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from queue import Empty, Queue
import time
from typing import Callable

import numpy as np

from browser_target import BrowserTarget
from home_observation import configured_rois, parse_home_sample, smoke_ocr
from vision import detect_state, dynamic_screenshot


BASE_DIR = Path(__file__).resolve().parent
CAPTURE_INTERVAL_SECONDS = 0.25
POST_MIN_SECONDS = 0.35
POST_MAX_SECONDS = 1.50
INTERACTION_QUIET_SECONDS = 0.50
STABLE_FRAME_SIMILARITY = 0.985
SNAPSHOT_BUFFER_SIZE = 16
IMPORTANT_DECISION_STATES = frozenset({
    "CHOICE_REQUIRED", "AUDITION_CHOICE", "PROMISE_CHOICE", "CONFIRM", "ERROR_POPUP",
})


@dataclass
class DemoSnapshot:
    captured_at: float
    wall_timestamp: float
    image: object
    window: dict
    state: str
    confidence: float
    template: str | None


@dataclass(frozen=True)
class RawMouseEvent:
    occurred_at: float
    wall_timestamp: float
    x: int
    y: int
    button: str


def _inside(point, window):
    return (window["left"] <= point[0] < window["left"] + window["width"] and
            window["top"] <= point[1] < window["top"] + window["height"])


def make_mouse_callback(events: Queue, *, left_button: object,
                        monotonic: Callable[[], float] = time.monotonic,
                        wall_time: Callable[[], float] = time.time):
    """Return a listener-thread callback that only timestamps and enqueues."""
    def on_click(x, y, button, pressed):
        if not pressed or button != left_button:
            return
        events.put(RawMouseEvent(monotonic(), wall_time(), int(x), int(y), str(button)))
    return on_click


def _frame_similarity(first, second) -> float:
    a = np.asarray(first.convert("L"), dtype=np.int16)
    b = np.asarray(second.convert("L"), dtype=np.int16)
    if a.shape != b.shape:
        return 0.0
    return max(0.0, 1.0 - float(np.mean(np.abs(a - b))) / 255.0)


def _capture_snapshot(target, config: dict) -> DemoSnapshot:
    image, window = dynamic_screenshot(target, config, BASE_DIR)
    detected = detect_state(image, config, BASE_DIR)
    return DemoSnapshot(
        captured_at=time.monotonic(), wall_timestamp=time.time(), image=image, window=dict(window),
        state=detected.state.value, confidence=float(detected.confidence), template=detected.template,
    )


def _available_actions(config: dict, state: str) -> list[dict[str, object]]:
    actions = config.get("states", {}).get(state, {}).get("allowed_actions", [])
    return [
        {"name": action.get("name"), "type": action.get("type"),
         "box": action.get("box"), "expected_next_states": action.get("expected_next_states", [])}
        for action in actions if action.get("name")
    ]


def match_named_action(config: dict, state: str, point: list[float]) -> dict[str, object]:
    """Map a human click only when exactly one current-state action box contains it."""
    matches = []
    for action in _available_actions(config, state):
        box = action.get("box")
        if (isinstance(box, list) and len(box) == 4 and
                float(box[0]) <= point[0] <= float(box[2]) and
                float(box[1]) <= point[1] <= float(box[3])):
            matches.append(action)
    if len(matches) == 1:
        return {"classification": "NAMED_ACTION", **matches[0]}
    return {
        "classification": "UNKNOWN_CLICK", "name": None,
        "candidate_actions": [action["name"] for action in matches],
        "reason": "no matching action box" if not matches else "multiple overlapping action boxes",
    }


def _numeric_observation(snapshot: DemoSnapshot, config: dict) -> dict[str, object]:
    """Reuse existing HOME primitives; unreadable fields remain diagnostic evidence."""
    if snapshot.state != "HOME":
        return {}
    try:
        rois = configured_rois(config)
        settings = config["perception"]["home_observation"]
        raw, diagnostics = smoke_ocr(
            snapshot.image, rois,
            weeks_template_matching=settings.get("weeks_remaining", {}).get("template_matching"),
            fan_target_clear_settings=settings.get("fan_gap_to_target", {}).get("clear_marker"),
            stamina_settings=settings.get("stamina"),
        )
        clear = bool(diagnostics.get("fan_gap_to_target", {}).get("clear_marker", {}).get("visible"))
        stamina = diagnostics.get("stamina", {}).get("stamina", {}).get("adequate")
        observation, reasons = parse_home_sample(
            raw, config, fan_target_achieved=clear, stamina_adequate=stamina,
        )
        return {
            "raw": raw,
            "parsed": ({
                "season": observation.season,
                "weeks_remaining": observation.weeks_remaining,
                "fan_gap_to_target": observation.fan_gap_to_target,
                "fan_target_achieved": observation.fan_target_achieved,
                "stamina_adequate": observation.stamina_adequate,
            } if observation else None),
            "unreadable_reasons": reasons,
        }
    except Exception as error:
        return {"parsed": None, "unreadable_reasons": {"HOME": f"{type(error).__name__}: {error}"}}


def _save_snapshot(snapshot: DemoSnapshot, path: Path, config: dict) -> dict[str, object]:
    snapshot.image.save(path)
    return {
        "captured_at_monotonic": snapshot.captured_at, "timestamp": snapshot.wall_timestamp,
        "state": snapshot.state, "detected_state": snapshot.state,
        "confidence": snapshot.confidence, "template": snapshot.template,
        "screenshot": str(path), "available_actions": _available_actions(config, snapshot.state),
        "numeric": _numeric_observation(snapshot, config),
    }


def _latest_before(snapshots: deque[DemoSnapshot], occurred_at: float) -> DemoSnapshot | None:
    candidates = [snapshot for snapshot in snapshots if snapshot.captured_at <= occurred_at]
    return candidates[-1] if candidates else None


def group_raw_events(events: list[RawMouseEvent], quiet_seconds: float = INTERACTION_QUIET_SECONDS) -> list[list[RawMouseEvent]]:
    """Group a burst of human clicks into interactions without dropping events."""
    groups: list[list[RawMouseEvent]] = []
    for event in sorted(events, key=lambda item: item.occurred_at):
        if not groups or event.occurred_at - groups[-1][-1].occurred_at > quiet_seconds:
            groups.append([event])
        else:
            groups[-1].append(event)
    return groups


def _post_ready(snapshots: deque[DemoSnapshot], event: RawMouseEvent) -> DemoSnapshot | None:
    after = [snapshot for snapshot in snapshots if snapshot.captured_at > event.occurred_at]
    if not after:
        return None
    elapsed = after[-1].captured_at - event.occurred_at
    if elapsed >= POST_MAX_SECONDS:
        return after[-1]
    if elapsed < POST_MIN_SECONDS or len(after) < 2:
        return None
    previous, current = after[-2], after[-1]
    if previous.state == current.state and _frame_similarity(previous.image, current.image) >= STABLE_FRAME_SIMILARITY:
        return current
    return None


def _transition_result(pre: DemoSnapshot, post: DemoSnapshot, action: dict) -> dict[str, object]:
    similarity = _frame_similarity(pre.image, post.image)
    changed = similarity < STABLE_FRAME_SIMILARITY
    expected = action.get("expected_next_states", []) if action.get("classification") == "NAMED_ACTION" else []
    if post.state == "UNKNOWN":
        classification = "POST_STATE_UNKNOWN"
    elif pre.state != post.state and expected and post.state in expected:
        classification = "EXPECTED_TRANSITION"
    elif pre.state != post.state:
        classification = "UNEXPLAINED_STATE_CHANGE"
    elif changed:
        classification = "FRAME_CHANGED_SAME_STATE"
    else:
        classification = "NO_VISUAL_EFFECT"
    return {
        "classification": classification, "state_changed": pre.state != post.state,
        "frame_changed": changed, "frame_similarity": round(similarity, 6),
        "expected_next_states": expected,
    }


def _explanation_question(pre_payload: dict, action: dict, post_payload: dict,
                          transition: dict) -> str | None:
    reasons = []
    if action.get("classification") == "UNKNOWN_CLICK":
        reasons.append("clicked control is not mapped to a known named action")
    if post_payload["state"] == "UNKNOWN":
        reasons.append("the resulting page is UNKNOWN")
    if transition["classification"] == "UNEXPLAINED_STATE_CHANGE":
        reasons.append("the state change is not explained by the taught action contract")
    if pre_payload["state"] in IMPORTANT_DECISION_STATES:
        reasons.append("the click was made at an important or protected decision state")
    if not reasons:
        return None
    context = pre_payload.get("numeric", {}).get("parsed")
    context_text = f" Current observation: {context}." if context else ""
    return (f"Please explain why you performed this action ({'; '.join(reasons)})."
            f" Before={pre_payload['state']}, action={action.get('name') or 'UNKNOWN_CLICK'},"
            f" after={post_payload['state']}.{context_text}")


def build_interaction_record(step: int, events: list[RawMouseEvent], pre: DemoSnapshot,
                             post: DemoSnapshot, config: dict, shots: Path) -> tuple[dict[str, object], dict[str, object] | None]:
    points = [[(event.x - pre.window["left"]) / pre.window["width"],
               (event.y - pre.window["top"]) / pre.window["height"]] for event in events]
    matches = [match_named_action(config, pre.state, point) for point in points]
    named = [match for match in matches if match.get("classification") == "NAMED_ACTION"]
    if named and len(named) == len(matches) and len({match.get("name") for match in named}) == 1:
        action_match = {"classification": "NAMED_ACTION", "name": named[0]["name"],
                        "type": named[0].get("type"), "box": named[0].get("box"),
                        "expected_next_states": named[0].get("expected_next_states", [])}
    elif len(events) > 1:
        action_match = {"classification": "UNKNOWN_CLICK", "name": None,
                        "candidate_actions": sorted({match.get("name") for match in matches if match.get("name")}),
                        "reason": "interaction contains multiple unmapped or mixed clicks"}
    else:
        action_match = matches[0]
    event = events[0]
    action = {
        "type": "human_click", "button": event.button, "click_count": len(events),
        "screen_point": [event.x, event.y], "normalized_point": points[0],
        "normalized_points": points, **action_match,
    }
    pre_payload = _save_snapshot(pre, shots / f"{step:04d}_pre.png", config)
    post_payload = _save_snapshot(post, shots / f"{step:04d}_post.png", config)
    transition = _transition_result(pre, post, action)
    question = _explanation_question(pre_payload, action, post_payload, transition)
    record = {
        "kind": "normalized_interaction", "record_type": "demo_step", "step": step,
        "timestamp": event.wall_timestamp, "raw_event_count": len(events),
        "observation": pre_payload, "screenshot": pre_payload["screenshot"],
        "detected_state": pre.state, "available_actions": pre_payload["available_actions"],
        "human_action": action, "after_observation": post_payload,
        "transition_result": transition,
        # Backward-compatible aliases for the existing deterministic compiler.
        "action": action, "pre": pre_payload, "post": post_payload,
        "controls": pre_payload["available_actions"], "numeric": pre_payload["numeric"],
        "effect_evidence": {"frame_changed": transition["frame_changed"],
                            "frame_similarity": transition["frame_similarity"]},
    }
    need = None
    if question:
        need = {
            "kind": "need_human_explanation", "step": step,
            "before_observation": pre_payload, "action": action,
            "after_observation": post_payload, "question": question,
        }
        record["need_human_explanation"] = need
    return record, need


def build_demo_step(step: int, event: RawMouseEvent, pre: DemoSnapshot, post: DemoSnapshot,
                    config: dict, shots: Path) -> tuple[dict[str, object], dict[str, object] | None]:
    """Backward-compatible single-event helper used by offline callers."""
    return build_interaction_record(step, [event], pre, post, config, shots)


def _append_jsonl(path: Path, record: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_metadata(path: Path, metadata: dict[str, object]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def record_demo(name: str) -> int:
    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    demo_id = f"{name}_{datetime.now():%Y%m%d_%H%M%S}"
    root = BASE_DIR / "logs" / "demos" / demo_id
    shots = root / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    trace = root / "episode.jsonl"
    metadata_path = root / "metadata.json"
    metadata: dict[str, object] = {
        "demo_id": demo_id, "name": name, "status": "RECORDING", "trace": str(trace),
        "started_at": time.time(), "steps": 0, "ignored_outside_clicks": 0,
    }
    _write_metadata(metadata_path, metadata)
    _append_jsonl(trace, {"kind": "session", "status": "RECORDING", "demo_id": demo_id,
                          "timestamp": metadata["started_at"]})
    final_status = "FAILED"
    error_text = None
    listener = None
    events: Queue[RawMouseEvent] | None = None
    pending: deque[RawMouseEvent] = deque()
    raw_event_count = 0
    interaction_count = 0
    decision_point_count = 0
    try:
        from pynput import mouse
        events = Queue()
        callback = make_mouse_callback(events, left_button=mouse.Button.left)
        with BrowserTarget(config["browser"]["cdp_url"]) as target:
            snapshots: deque[DemoSnapshot] = deque(maxlen=SNAPSHOT_BUFFER_SIZE)
            snapshots.append(_capture_snapshot(target, config))
            listener = mouse.Listener(on_click=callback)
            listener.start()
            print(f"Recording {demo_id}. Human clicks are observed only; Ctrl+C stops.")
            home_streak = 0
            home_boundary_open = True
            while True:
                started = time.monotonic()
                snapshot = _capture_snapshot(target, config)
                snapshots.append(snapshot)
                if snapshot.state == "HOME":
                    home_streak += 1
                else:
                    home_streak = 0
                    home_boundary_open = True
                if snapshot.state == "HOME" and home_streak >= 2 and home_boundary_open:
                    decision_path = shots / f"decision_{decision_point_count:04d}.png"
                    decision_payload = _save_snapshot(snapshot, decision_path, config)
                    decision_record = {
                        "kind": "decision_point", "decision_point": decision_point_count,
                        "timestamp": snapshot.wall_timestamp, "detected_state": "HOME",
                        "screenshot": decision_payload["screenshot"],
                        "home_observation": decision_payload["numeric"],
                        "observation": decision_payload,
                    }
                    _append_jsonl(trace, decision_record)
                    print(f"DecisionPoint {decision_point_count}: HOME {decision_payload['numeric'].get('parsed')}")
                    decision_point_count += 1
                    home_boundary_open = False
                while True:
                    try:
                        event = events.get_nowait()
                        raw_event_count += 1
                        pre_for_raw = _latest_before(snapshots, event.occurred_at)
                        inside = bool(pre_for_raw and _inside((event.x, event.y), pre_for_raw.window))
                        raw_record = {
                            "kind": "raw_event", "event_index": raw_event_count - 1,
                            "timestamp": event.wall_timestamp,
                            "occurred_at_monotonic": event.occurred_at,
                            "button": event.button, "screen_point": [event.x, event.y],
                            "inside_game_window": inside,
                        }
                        if inside and pre_for_raw:
                            raw_record["normalized_point"] = [
                                (event.x - pre_for_raw.window["left"]) / pre_for_raw.window["width"],
                                (event.y - pre_for_raw.window["top"]) / pre_for_raw.window["height"],
                            ]
                            pending.append(event)
                        else:
                            metadata["ignored_outside_clicks"] = int(metadata["ignored_outside_clicks"]) + 1
                        _append_jsonl(trace, raw_record)
                    except Empty:
                        break
                if listener is not None and not listener.running:
                    raise RuntimeError("mouse listener stopped unexpectedly")
                while pending:
                    now = time.monotonic()
                    if now - pending[-1].occurred_at <= INTERACTION_QUIET_SECONDS:
                        break
                    groups = group_raw_events(list(pending))
                    batch = groups[0]
                    event = batch[0]
                    pre = _latest_before(snapshots, event.occurred_at)
                    if pre is None:
                        break
                    post = _post_ready(snapshots, batch[-1])
                    if post is None:
                        break
                    for _ in batch:
                        pending.popleft()
                    record, need = build_interaction_record(interaction_count, batch, pre, post, config, shots)
                    _append_jsonl(trace, record)
                    if need:
                        _append_jsonl(trace, need)
                        print(f"NeedHumanExplanation interaction={interaction_count}: {need['question']}")
                    parsed = record["observation"].get("numeric", {}).get("parsed")
                    week = parsed.get("weeks_remaining") if parsed else "?"
                    print(f"Week {week}: Observation={pre.state} Human clicked="
                          f"{record['human_action'].get('name') or 'UNKNOWN_CLICK'} "
                          f"({len(batch)} clicks) Result={post.state} "
                          f"({record['transition_result']['classification']})")
                    interaction_count += 1
                    metadata["steps"] = interaction_count
                    metadata["raw_events"] = raw_event_count
                    metadata["decision_points"] = decision_point_count
                    metadata["interactions"] = interaction_count
                    _write_metadata(metadata_path, metadata)
                remaining = CAPTURE_INTERVAL_SECONDS - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
    except KeyboardInterrupt:
        final_status = "COMPLETED"
    except ImportError as error:
        error_text = f"pynput is required to observe OS mouse clicks: {error}"
        print(f"RECORDER_ERROR: {error_text}")
    except Exception as error:
        error_text = f"{type(error).__name__}: {error}"
        print(f"RECORDER_ERROR: {error_text}")
    finally:
        if listener is not None:
            listener.stop()
            listener.join(timeout=2.0)
        if events is not None:
            while True:
                try:
                    event = events.get_nowait()
                except Empty:
                    break
                raw_event_count += 1
                _append_jsonl(trace, {
                    "kind": "raw_event", "event_index": raw_event_count - 1,
                    "timestamp": event.wall_timestamp,
                    "occurred_at_monotonic": event.occurred_at,
                    "button": event.button, "screen_point": [event.x, event.y],
                    "inside_game_window": None, "discarded_on_shutdown": True,
                })
        metadata["raw_events"] = raw_event_count
        metadata["interactions"] = interaction_count
        metadata["decision_points"] = decision_point_count
        metadata["status"] = final_status
        metadata["finished_at"] = time.time()
        if error_text:
            metadata["error"] = error_text
        _append_jsonl(trace, {"kind": "session", "status": final_status,
                              "timestamp": metadata["finished_at"], "steps": metadata["steps"],
                              "error": error_text})
        _write_metadata(metadata_path, metadata)
    print(f"demo={demo_id}\nstatus={final_status}\ntrace={trace}")
    return 0 if final_status == "COMPLETED" else 2
