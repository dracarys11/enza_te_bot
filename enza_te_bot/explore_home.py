"""WING Exploration Phase A: HOME observation (read-only).

Runs the full outsourcing pipeline and nothing else:

    capture screenshot
      -> local PaddleOCR
      -> AGY CLI / Gemini Vision (vision_agent.agy_vision_bridge)
      -> perception fusion + validation          (inside the bridge)
      -> GroundedElements
      -> HOME field projection (exploration.home_projection)
      -> Observer v0.2 trajectory + clarifications

Zero automatic actions: no clicking, no typing, no popup dismissal, no
navigation. If the screen is not a parseable HOME the driver reports
UNKNOWN / NEED_HUMAN and stops. Perception failures fail closed as
UNKNOWN_PERCEPTION; missing or ambiguous HOME fields fail closed as
UNKNOWN_DEPENDENCY plus a recorded human clarification request.

Offline rehearsal flags (--screenshot, --fake-agy, --fake-paddle) exist so
the whole pipeline can be validated without a browser or an AGY call.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
from typing import Any

from exploration.home_identity import (
    HOME_CONFIRMED,
    evaluate_home_identity,
)
from exploration.preflight import run_preflight
from exploration.home_projection import (
    FIELDS,
    apply_clarification_answers,
    project_home_fields,
)
from grounded_element import build_grounded_elements
from observer.human_feedback import HumanFeedbackChannel
from observer.trajectory_recorder import TrajectoryRecorder
from vision_agent.agy_vision_bridge import (
    DEFAULT_APPROVED_LIVE_MODEL,
    FakeAgyRunner,
    AgyVisionConfig,
    RUNNER_MODE_LIVE,
    RUNNER_MODE_OFFLINE_FAKE,
    STATUS_SUCCESS,
    vision_request,
)
from vision_agent.artifact_harness import VisionArtifactHarness
from vision_observation_schema import VisionObservation


BASE_DIR = Path(__file__).resolve().parent
NUMERIC_FIELDS = ("season", "weeks_remaining", "fan_gap_to_target")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_UNKNOWN_PERCEPTION = 2
EXIT_UNKNOWN_DEPENDENCY = 3

OVERALL_SUCCESS = "SUCCESS"
OVERALL_INCOMPLETE_FRAMES = "INCOMPLETE_FRAMES"
OVERALL_UNKNOWN_PERCEPTION = "UNKNOWN_PERCEPTION"
OVERALL_UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"
OVERALL_DUPLICATE_FRAME = "DUPLICATE_FRAME"


OVERALL_SENSOR_BLIND = "SENSOR_BLIND"


def _boxes_intersect(a: list[float], b: list[float]) -> bool:
    ax, ay, aw, ah = (float(v) for v in a)
    bx, by, bw, bh = (float(v) for v in b)
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def load_home_identity_spec(config_path: Path) -> dict[str, Any]:
    """Load the human-authored HOME_IDENTITY_SPEC (empty spec = never confirm)."""
    if not config_path.is_file():
        return {}
    config = json.loads(config_path.read_text(encoding="utf-8"))
    spec = (config.get("perception") or {}).get("home_identity") or {}
    return spec if isinstance(spec, dict) else {}


def load_home_anchors(config_path: Path) -> dict[str, dict[str, Any]]:
    """Load human-taught normalized ROIs from the legacy config, if present."""
    if not config_path.is_file():
        return {}
    config = json.loads(config_path.read_text(encoding="utf-8"))
    section = (config.get("perception") or {}).get("home_observation") or {}
    anchors: dict[str, dict[str, Any]] = {}
    for name in FIELDS:
        entry = section.get(name) or {}
        if isinstance(entry.get("roi"), list):
            anchor: dict[str, Any] = {"roi": entry["roi"]}
            if isinstance(entry.get("range"), list):
                anchor["range"] = entry["range"]
            anchors[name] = anchor
    return anchors


def capture_live_screenshot(destination: Path, cdp_url: str | None) -> dict[str, Any]:
    """Capture the game window through the existing read-only channel.

    Imports are deferred so offline rehearsal never needs the browser stack.
    This captures pixels only; no input injection exists on this path.
    """
    from browser_target import BrowserTarget  # sanctioned capture channel only
    from vision import dynamic_screenshot

    config = json.loads((BASE_DIR / "config.json").read_text(encoding="utf-8"))
    url = cdp_url or (config.get("browser") or {}).get("cdp_url")
    with BrowserTarget(url) as target:
        image, window = dynamic_screenshot(target, config, BASE_DIR)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    return {"window": window, "size": [image.width, image.height]}


def parse_clarify_argument(raw: str | None) -> dict[str, str]:
    answers: dict[str, str] = {}
    if not raw:
        return answers
    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(f"--clarify expects field=value pairs, got {chunk!r}")
        field, value = chunk.split("=", 1)
        field = field.strip()
        if field not in FIELDS:
            raise ValueError(f"unknown HOME field in --clarify: {field!r}")
        answers[field] = value.strip()
    return answers


def request_clarified_values(
    unresolved: list[str],
    projection: dict[str, Any],
    observation_id: str,
    feedback: HumanFeedbackChannel,
    provided: dict[str, str],
    interactive: bool,
) -> tuple[dict[str, str], dict[str, str]]:
    """Collect human answers for unresolved fields; every question is recorded.

    Even without a TTY the open question is persisted so the trajectory shows
    the UNKNOWN_DEPENDENCY ask; answers only ever come from a human.
    """
    answers: dict[str, str] = {}
    question_ids: dict[str, str] = {}
    for field in unresolved:
        field_record = projection["fields"][field]
        options = [{"id": f"provide_{field}", "label": f"provide {field}"}]
        for value in field_record.get("candidate_values", []) or []:
            options.append({"id": f"{field}={value}", "label": str(value)})
        record = feedback.ask_clarification(
            observation_id=observation_id,
            options=options,
            question=(
                f"Field {field!r} is {field_record['status']} "
                f"({field_record.get('note', '')}). Provide the value."
            ),
        )
        question_ids[field] = record["question_id"]
        if field in provided:
            answers[field] = provided[field]
            feedback.answer(observation_id, chosen=provided[field])
        elif interactive:
            reply = input(f"  value for {field} (from your screen): ").strip()
            if reply:
                answers[field] = reply
                feedback.answer(observation_id, chosen=reply)
    return answers, question_ids


def run_exploration(
    *,
    frames: int,
    case_id_base: str,
    data_root: Path,
    suite: str,
    trajectory_root: Path | None,
    screenshot_sources: list[Path] | None,
    cdp_url: str | None,
    agy_fixture: Path | None,
    paddle_fixture: Path | None,
    fake_paddle: bool,
    agy_timeout_seconds: int,
    skill_version: str,
    resume_conversation_id: str | None,
    clarify: str | None,
    config_path: Path | None,
    identity_spec: dict[str, Any] | None = None,
    model: str = DEFAULT_APPROVED_LIVE_MODEL,
    agy_runner_override: Any = None,
    paddle_runner_override: Any = None,
) -> dict[str, Any]:
    harness = VisionArtifactHarness(data_root, suite=suite)
    anchors = load_home_anchors(config_path or BASE_DIR / "config.json")
    identity_spec = identity_spec if identity_spec is not None else load_home_identity_spec(
        config_path or BASE_DIR / "config.json")
    provided_answers = parse_clarify_argument(clarify)
    interactive = sys.stdin.isatty()
    recorder = TrajectoryRecorder(root=trajectory_root) if trajectory_root else TrajectoryRecorder()
    feedback = HumanFeedbackChannel(recorder)

    frame_results: list[dict[str, Any]] = []
    overall = OVERALL_SUCCESS

    for index in range(1, frames + 1):
        case_id = f"{case_id_base}_f{index:02d}"
        if screenshot_sources:
            if len(screenshot_sources) < index:
                raise ValueError(
                    f"--screenshot sources ({len(screenshot_sources)}) fewer than frames ({frames})"
                )
            frame_screenshot = screenshot_sources[index - 1]
            if not frame_screenshot.is_file():
                raise ValueError(f"screenshot not found: {frame_screenshot}")
        else:
            frame_screenshot = BASE_DIR / "logs" / f"{case_id}.png"
            capture_live_screenshot(frame_screenshot, cdp_url)

        if agy_runner_override is not None:
            agy_runner = agy_runner_override
        elif agy_fixture is not None:
            agy_runner = _fixture_text_runner(agy_fixture)
        else:
            from vision_agent.agy_cli_runner import build_agy_cli_runner

            agy_runner = build_agy_cli_runner(
                resume_conversation_id=resume_conversation_id,
            )
        if paddle_runner_override is not None:
            paddle_runner = paddle_runner_override
        elif paddle_fixture is not None:
            paddle_runner = _fixture_paddle_runner(paddle_fixture)
        elif fake_paddle:
            paddle_runner = (
                lambda path: {"source_image": path, "method": "PaddleOCR", "text_regions": []}
            )
        else:
            paddle_runner = None

        # Live runs must pin the approved model before any AGY call; offline
        # rehearsal (injected/fixture runner) stays in the lax fake mode.
        offline_rehearsal = agy_runner_override is not None or agy_fixture is not None
        bridge_config = AgyVisionConfig(
            skill_version=skill_version,
            runner_mode=RUNNER_MODE_OFFLINE_FAKE if offline_rehearsal else RUNNER_MODE_LIVE,
            expected_model=None if offline_rehearsal else model,
            timeout_seconds=float(agy_timeout_seconds),
        )

        result = vision_request(
            frame_screenshot,
            case_id,
            test_data_root=data_root,
            suite=suite,
            agy_runner=agy_runner,
            paddle_runner=paddle_runner,
            config=bridge_config,
        )
        if result.status != STATUS_SUCCESS:
            overall = OVERALL_UNKNOWN_PERCEPTION
            frame_results.append(
                {
                    "case_id": case_id,
                    "status": OVERALL_UNKNOWN_PERCEPTION,
                    "reason_code": result.reason_code,
                    "detail": result.detail,
                    "resumable_conversation_id": None,
                }
            )
            break

        fused_path = Path(result.fused_artifact or "")
        fused = json.loads(fused_path.read_text(encoding="utf-8"))
        VisionObservation.from_payload(fused)  # belt and braces; bridge validated already
        grounded = build_grounded_elements(fused)

        # P0-4: a blind sensor can never be rescued into a visual SUCCESS by
        # human clarification. Record the ask, then fail closed.
        sensor_status = fused.get("sensor_status") or {}
        sensor_blind = bool(sensor_status.get("paddle_ocr_empty")) or \
            sensor_status.get("text_sensor") == "none"
        if sensor_blind:
            feedback.ask_clarification(
                observation_id=fused.get("observation_id", case_id),
                options=[{"id": "sensor_blind", "label": "sensor blind"}],
                question="Paddle OCR returned no text; the sensor may be blind.",
            )
            overall = OVERALL_UNKNOWN_PERCEPTION
            frame_results.append(
                {
                    "case_id": case_id,
                    "status": OVERALL_SENSOR_BLIND,
                    "reason_code": "sensor_blind",
                    "detail": "paddle OCR empty: refuse clarification rescue",
                    "observation_id": fused.get("observation_id", ""),
                }
            )
            break

        projection = project_home_fields(fused, grounded, anchors)

        # P0-2: overlay-contaminated field evidence can never be KNOWN.
        overlay_boxes = [o["bbox"] for o in fused.get("overlay_regions", []) or []
                         if isinstance(o, dict) and o.get("bbox")]
        contaminated_fields: list[str] = []
        if overlay_boxes:
            for name in FIELDS:
                field = projection["fields"][name]
                if field["status"] != "KNOWN":
                    continue
                evidence_ids = set(field.get("evidence_ids", []))
                hits = []
                for region in fused.get("text_regions", []) or []:
                    if str(region.get("id")) not in evidence_ids:
                        continue
                    rb = region.get("bbox")
                    if rb and any(_boxes_intersect(rb, ob) for ob in overlay_boxes):
                        hits.append(str(region.get("id", "")))
                if hits:
                    field["status"] = "AMBIGUOUS"
                    field["value"] = None
                    field["note"] = f"overlay contaminated evidence {hits}"
                    field["overlay_ids"] = sorted({str(o.get("id", "")) for o in
                                                   fused.get("overlay_regions", [])
                                                   if isinstance(o, dict) and o.get("bbox")})
                    contaminated_fields.append(name)
            if contaminated_fields:
                projection["missing_fields"] = [f for f in projection["missing_fields"]
                                                if f not in contaminated_fields]
                projection["ambiguous_fields"] = sorted(set(
                    projection["ambiguous_fields"]) | set(contaminated_fields))
                projection["status"] = "INCOMPLETE"
                projection["overlay_contaminated_fields"] = contaminated_fields

        unresolved = list(projection["missing_fields"]) + list(projection["ambiguous_fields"])
        if unresolved:
            answers, question_ids = request_clarified_values(
                unresolved, projection, fused["observation_id"], feedback, provided_answers, interactive
            )
            projection = apply_clarification_answers(projection, answers, question_ids)
        fused_case_dir = fused_path.parent
        (fused_case_dir / "home_projection.json").write_text(
            json.dumps(projection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

        if projection["status"] != "COMPLETE":
            overall = OVERALL_UNKNOWN_DEPENDENCY
            frame_results.append(
                {
                    "case_id": case_id,
                    "status": OVERALL_UNKNOWN_DEPENDENCY,
                    "missing_fields": projection["missing_fields"],
                    "ambiguous_fields": projection["ambiguous_fields"],
                    "observation_id": fused["observation_id"],
                    "projection": projection,
                }
            )
            break

        # P0-1: identity gate before any business consumption. A non-CONFIRMED
        # frame never yields HOME business facts, whatever the projection says.
        identity = evaluate_home_identity(fused, grounded, identity_spec, projection)
        (fused_path.parent / "home_identity.json").write_text(
            json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        projection["home_identity"] = {
            "verdict": identity["verdict"],
            "reasons": identity["reasons"],
        }
        if identity["verdict"] != HOME_CONFIRMED:
            overall = OVERALL_UNKNOWN_DEPENDENCY
            frame_results.append(
                {
                    "case_id": case_id,
                    "status": "HOME_IDENTITY_UNCONFIRMED",
                    "verdict": identity["verdict"],
                    "reasons": identity["reasons"],
                    "observation_id": fused.get("observation_id", ""),
                    "projection_recorded": True,
                }
            )
            break

        case_source = harness.case_directory(case_id) / "source_screenshot.png"
        observation_record = recorder.record_observation(
            {
                "vision_source": "AGY Vision Bridge (Paddle + AGY fusion)",
                "provider_metadata": fused.get("capture", {}),
                "elements": grounded,
                "uncertainties": fused.get("uncertainties", []),
                "vision_observation": fused,
            },
            case_source,
        )
        frame_results.append(
            {
                "case_id": case_id,
                "status": "OK",
                "observation_id": observation_record["observation_id"],
                "screenshot_sha256": observation_record["screenshot_sha256"],
                "fused_artifact": str(fused_path),
                "home_projection": projection,
            }
        )

    if overall == OVERALL_SUCCESS:
        hashes = [frame.get("screenshot_sha256") for frame in frame_results]
        if len(frame_results) < 2:
            overall = OVERALL_INCOMPLETE_FRAMES
        elif len(set(hashes)) != len(hashes):
            overall = OVERALL_DUPLICATE_FRAME
        else:
            values_by_frame = [
                {name: frame["home_projection"]["fields"][name]["value"] for name in FIELDS}
                for frame in frame_results
            ]
            if any(values != values_by_frame[0] for values in values_by_frame[1:]):
                overall = OVERALL_UNKNOWN_DEPENDENCY
                for frame in frame_results:
                    frame["status"] = "UNSTABLE"

    summary = {
        "status": overall,
        "frames": frames,
        "frames_collected": len(frame_results),
        "case_id_base": case_id_base,
        "trajectory_dir": str(recorder.dir),
        "human_actions_recorded": len(recorder.human_actions()),
        "clarifications": [c.get("question_id") for c in recorder.clarifications()],
        "frame_results": frame_results,
    }
    return summary


def _fixture_text_runner(fixture_path: Path):
    return FakeAgyRunner(fixture_path)


def _fixture_paddle_runner(fixture_path: Path):
    def run(_screenshot_path: str) -> dict[str, Any]:
        payload = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
        payload.setdefault("source_image", _screenshot_path)
        payload.setdefault("method", "PaddleOCR")
        payload.setdefault("text_regions", [])
        return payload

    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase A HOME exploration (read-only; zero automatic actions)"
    )
    parser.add_argument("--frames", type=int, default=1,
                        help="number of consecutive frames (default 1; 2 required for SUCCESS)")
    parser.add_argument("--case-id", default=None,
                        help="case id base (default: OBS_<timestamp>_explore_home)")
    parser.add_argument("--data-root", type=Path, default=BASE_DIR / "test_data")
    parser.add_argument("--suite", default="ob003")
    parser.add_argument("--trajectory-root", type=Path, default=None)
    parser.add_argument("--cdp-url", default=None)
    parser.add_argument("--screenshot", type=Path, action="append", default=None,
                        help="offline rehearsal: reuse this PNG instead of capturing "
                             "(one per frame when combined with --frames N)")
    parser.add_argument("--fake-agy", type=Path, default=None,
                        help="offline rehearsal: AGY artifact fixture JSON")
    parser.add_argument("--paddle-fixture", type=Path, default=None,
                        help="offline rehearsal: PaddleOCR result fixture JSON")
    parser.add_argument("--fake-paddle", action="store_true",
                        help="offline rehearsal: deterministic empty Paddle result")
    parser.add_argument("--agy-timeout", type=int, default=1500)
    parser.add_argument("--skill", default="gemini_vision_v1")
    parser.add_argument("--model", default=DEFAULT_APPROVED_LIVE_MODEL,
                        help="expected AGY model for live runs; must match the "
                             "approved pinned model")
    parser.add_argument("--resume-conversation-id", default=None,
                        help="continue the same AGY conversation after a timeout")
    parser.add_argument("--clarify", default=None,
                        help="human-provided values: field=value;field=value")
    parser.add_argument("--config", type=Path, default=BASE_DIR / "config.json")
    parser.add_argument("--preflight", action="store_true",
                        help="run read-only startup checks (agy on PATH, config keys, "
                             "memory writable, Paddle import, CDP endpoint, unique game tab) "
                             "and exit without exploring")
    arguments = parser.parse_args(argv)

    if arguments.preflight:
        live = not (arguments.fake_agy or arguments.screenshot)
        preflight = run_preflight(
            executable="agy",
            config_path=arguments.config,
            memory_root=BASE_DIR / "enza_memory",
            cdp_url=arguments.cdp_url if live else None,
            required_config_keys=("perception.home_observation", "browser.cdp_url") if live
            else ("perception.home_observation",),
            include_paddle=True,
            include_cdp=live,
        )
        print(json.dumps(preflight, ensure_ascii=False, indent=2))
        raise SystemExit(0 if preflight["status"] == "PASS" else 2)

    case_id_base = arguments.case_id or (
        f"OBS_{datetime.now().strftime('%Y%m%d%H%M%S')}_explore_home"
    )
    data_root = (arguments.data_root if arguments.data_root.is_absolute()
                 else BASE_DIR / arguments.data_root).resolve()
    trajectory_root = (None if arguments.trajectory_root is None else
                       (arguments.trajectory_root if arguments.trajectory_root.is_absolute()
                        else BASE_DIR / arguments.trajectory_root).resolve())
    summary = run_exploration(
        frames=arguments.frames,
        case_id_base=case_id_base,
        data_root=data_root,
        suite=arguments.suite,
        trajectory_root=trajectory_root,
        screenshot_sources=arguments.screenshot,
        cdp_url=arguments.cdp_url,
        agy_fixture=arguments.fake_agy,
        paddle_fixture=arguments.paddle_fixture,
        fake_paddle=arguments.fake_paddle,
        agy_timeout_seconds=arguments.agy_timeout,
        skill_version=arguments.skill,
        resume_conversation_id=arguments.resume_conversation_id,
        clarify=arguments.clarify,
        config_path=arguments.config,
        identity_spec=None,
        model=arguments.model,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if any(frame.get("reason_code") == "EVIDENCE_PERSISTENCE_FAILURE"
           for frame in summary.get("frame_results", [])):
        print("EVIDENCE_PERSISTENCE_FAILURE: terminal evidence could not be persisted", file=sys.stderr)
    if summary["status"] == OVERALL_SUCCESS:
        return EXIT_OK
    if summary["status"] == OVERALL_UNKNOWN_PERCEPTION:
        return EXIT_UNKNOWN_PERCEPTION
    if summary["status"] in (OVERALL_UNKNOWN_DEPENDENCY, OVERALL_DUPLICATE_FRAME):
        return EXIT_UNKNOWN_DEPENDENCY
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
