"""Observation-failure boundary tests: screenshot timeout is decoupled from
game actions, browser state, and pending business actions.

Offline only: fake captures/probes; the only real production code under test
is the observation contract (screenshot_pipeline) and the goal executor's
single-shot/no-retry behavior (goal_execution) used as the composed boundary.
"""
from __future__ import annotations

import pytest

from goal_execution import GoalContext, execute_goal
from screenshot_pipeline import (
    OBSERVATION_UNAVAILABLE,
    ObservationUnavailableError,
    REASON_CAPTURE_ERROR,
    REASON_STALE_FRAME,
    REASON_TIMEOUT,
    RECOVERY_NEW_CAPTURE_SURFACE,
    ScreenshotPipeline,
    classify_observation_failure,
)


def test_observation_timeout_is_not_game_failure() -> None:
    """A screenshot timeout classifies as OBSERVATION_UNAVAILABLE and never as
    a game/business outcome; it proves nothing about any pending action."""
    release = __import__("threading").Event()

    def hung_capture() -> bytes:
        release.wait(10.0)
        return b"never"

    pipeline = ScreenshotPipeline(hung_capture, timeout_s=0.2)
    result = pipeline.capture()
    release.set()
    assert result.status == OBSERVATION_UNAVAILABLE
    assert result.reason == REASON_TIMEOUT

    verdict = classify_observation_failure(reason=result.reason, probe_alive=True)
    assert verdict.status == OBSERVATION_UNAVAILABLE
    assert verdict.is_game_failure is False
    assert verdict.pending_action_failed is None
    assert verdict.browser_dead is False  # tri-state: probe proves ALIVE, never dead
    assert verdict.retry_safe is True

    # stale frame and capture errors carry the identical decoupling
    for reason in (REASON_STALE_FRAME, REASON_CAPTURE_ERROR):
        stale = classify_observation_failure(reason=reason, probe_alive=True)
        assert stale.is_game_failure is False
        assert stale.pending_action_failed is None
        assert stale.browser_dead is False

    # without a probe, death is NOT proven (None), and recovery is not advised
    unprobed = classify_observation_failure(reason=REASON_TIMEOUT, probe_alive=None)
    assert unprobed.browser_dead is None
    assert unprobed.recovery_required is False

    # unclassifiable reasons are rejected, not silently mapped
    with pytest.raises(ValueError):
        classify_observation_failure(reason="ACTION_FAILED")


def test_observation_timeout_does_not_trigger_recovery() -> None:
    """Timeout on a live page triggers no recovery of any kind; only a
    proven-dead page yields a browser-scope advisory, never a game action."""
    recovery_calls: list[str] = []

    def alive_probe() -> bool:
        return True

    pipeline = ScreenshotPipeline(
        lambda: (_ for _ in ()).throw(__import__("builtins").TimeoutError("capture deadline")),
        probe_fn=alive_probe,
        on_browser_recovery_required=recovery_calls.append,
        timeout_s=0.2,
    )
    for _ in range(3):
        result = pipeline.capture()
        assert result.status == OBSERVATION_UNAVAILABLE
        assert result.reason in {REASON_TIMEOUT, REASON_CAPTURE_ERROR}
        assert result.browser_recovery_required is False
        assert result.recovery_advisory is None
    assert recovery_calls == []

    verdict = classify_observation_failure(reason=REASON_TIMEOUT, probe_alive=True)
    assert verdict.recovery_required is False

    # proven-dead page: BROWSER-scope advisory only; no game surface exists
    def dead_probe() -> bool:
        return False

    dead_pipeline = ScreenshotPipeline(
        lambda: (_ for _ in ()).throw(TimeoutError("capture deadline")),
        probe_fn=dead_probe,
        on_browser_recovery_required=recovery_calls.append,
        timeout_s=0.2,
    )
    dead_result = dead_pipeline.capture()
    assert dead_result.browser_recovery_required is True
    assert dead_result.recovery_advisory == RECOVERY_NEW_CAPTURE_SURFACE
    assert recovery_calls == [RECOVERY_NEW_CAPTURE_SURFACE]  # browser-scope only

    # composed ZCode observation adapter: source failure stays observation-scope
    from zcode_observation_provider import ZCodeObservationProvider

    def raising_source() -> dict:
        raise TimeoutError("capture deadline")

    provider = ZCodeObservationProvider(raising_source)
    try:
        provider.observe()
        raise AssertionError("expected the source exception to propagate")
    except TimeoutError:
        verdict2 = classify_observation_failure(reason=REASON_CAPTURE_ERROR, probe_alive=True)
        assert verdict2.recovery_required is False
        assert verdict2.is_game_failure is False
    assert recovery_calls == [RECOVERY_NEW_CAPTURE_SURFACE]  # unchanged


def test_pending_action_not_retried_after_screenshot_failure() -> None:
    """When the post-action verification screenshot fails, the already-run
    business action is never retried, never labeled failed, and the failure
    classifies as observation-scope."""
    executor_calls: list[int] = []

    def run_executor() -> int:
        executor_calls.append(1)
        return 0  # room ran once (action in flight / possibly committed server-side)

    def broken_verification() -> tuple[str, bool]:
        raise ObservationUnavailableError(REASON_TIMEOUT, "verification screenshot timed out")

    context = GoalContext(goal="VOCAL", success_state="HOME")

    def composed_caller():
        try:
            return ("RESULT", execute_goal(
                context, live=True, executor_name="VOCAL_ROOM",
                run_executor=run_executor,
                verify_terminal_boundary=broken_verification,
            ))
        except ObservationUnavailableError as error:
            return ("OBSERVATION_UNAVAILABLE", classify_observation_failure(
                reason=error.reason, probe_alive=True))

    kind, verdict = composed_caller()
    assert kind == "OBSERVATION_UNAVAILABLE"
    assert executor_calls == [1]  # exactly one execution: NO retry after screenshot failure
    assert verdict.is_game_failure is False
    assert verdict.pending_action_failed is None  # timeout proves nothing about the action
    assert verdict.status == OBSERVATION_UNAVAILABLE

    # contrast: a verification that RETURNS unreadable stays the existing
    # fail-closed BOUNDARY_FAILURE path -- still executed exactly once
    executor_calls.clear()

    def unknown_verification() -> tuple[str, bool]:
        return ("UNKNOWN", False)

    result = execute_goal(
        context, live=True, executor_name="VOCAL_ROOM",
        run_executor=run_executor,
        verify_terminal_boundary=unknown_verification,
    )
    assert executor_calls == [1]
    assert result.status == "BOUNDARY_FAILURE"
    assert result.committed is False
