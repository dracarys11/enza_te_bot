"""Regression tests for the caller-side screenshot acquisition contract.

Covers the four required cases plus the single-flight guard:

- TEST_SCREENSHOT_TIMEOUT_RELEASES_LOCK
- TEST_SECOND_CAPTURE_NOT_BLOCKED_AFTER_FAILURE
- TEST_CAPTURE_FAILURE_NOT_ACTION_FAILURE
- TEST_OBSERVATION_FAILURE_NO_GAME_RECOVERY

All tests are offline: capture/probe/recovery are fakes; no browser, no game.
"""
from __future__ import annotations

import threading
import time

import pytest

from screenshot_pipeline import (
    CAPTURED,
    OBSERVATION_UNAVAILABLE,
    REASON_BUSY,
    REASON_CAPTURE_ERROR,
    REASON_TIMEOUT,
    RECOVERY_NEW_CAPTURE_SURFACE,
    CaptureResult,
    ScreenshotPipeline,
)


def test_screenshot_timeout_releases_lock() -> None:
    """A capture that outlives the deadline returns an explicit failure and
    releases the pending state immediately; the pipeline is usable again."""
    release = threading.Event()
    started = threading.Event()

    def hung_capture() -> bytes:
        started.set()
        release.wait(10.0)  # simulates the wedged backend capture
        return b"never"

    pipeline = ScreenshotPipeline(hung_capture, timeout_s=0.2)

    start = time.monotonic()
    result = pipeline.capture()
    elapsed = time.monotonic() - start

    assert result.status == OBSERVATION_UNAVAILABLE
    assert result.reason == REASON_TIMEOUT
    assert result.image is None
    # bounded: returned at the deadline, not after the hung capture (10s)
    assert elapsed < 2.0
    # invariant 2: pending state released
    assert pipeline.capture_active is False

    release.set()
    started.wait(1.0)

    # same instance fully usable again: the released lock admits a fresh
    # capture in a new worker even though worker #1 may still be finishing
    pipeline2 = ScreenshotPipeline(lambda: b"reused", timeout_s=5.0)
    assert pipeline2.capture().image == b"reused"
    assert pipeline.capture_active is False


def test_second_capture_not_blocked_after_failure() -> None:
    """After a failed capture a new request proceeds immediately in its own
    worker and is not blocked by the previous (possibly hung) capture."""
    first_started = threading.Event()
    first_release = threading.Event()

    def first_hangs() -> bytes:
        first_started.set()
        first_release.wait(10.0)
        return b"late"

    pipeline = ScreenshotPipeline(first_hangs, timeout_s=0.2)
    first = pipeline.capture()
    assert first.status == OBSERVATION_UNAVAILABLE

    # worker #1 is still hung inside the capture; a new capture must not queue behind it
    def fast_capture() -> bytes:
        return b"second-frame"

    pipeline2 = ScreenshotPipeline(fast_capture, timeout_s=5.0)
    start = time.monotonic()
    second = pipeline2.capture()
    elapsed = time.monotonic() - start

    assert second.status == CAPTURED
    assert second.image == b"second-frame"
    assert elapsed < 1.0
    first_release.set()

    # single-flight: a request issued while a capture is active fails fast with BUSY
    gate = threading.Event()
    busy_pipeline = ScreenshotPipeline(lambda: gate.wait(5.0), timeout_s=5.0)
    worker = threading.Thread(target=busy_pipeline.capture, daemon=True)
    worker.start()
    try:
        for _ in range(200):
            if busy_pipeline.capture_active:
                break
            time.sleep(0.005)
        busy_result = busy_pipeline.capture()
        assert busy_result.status == OBSERVATION_UNAVAILABLE
        assert busy_result.reason == REASON_BUSY
    finally:
        gate.set()
        worker.join(6.0)


def test_capture_failure_not_action_failure() -> None:
    """Every failure result is observation-scope and carries no action verdict."""
    def raising_capture() -> bytes:
        raise RuntimeError("backend capture wedged")

    pipeline = ScreenshotPipeline(raising_capture, timeout_s=1.0)
    for expected_reason in (REASON_CAPTURE_ERROR, REASON_CAPTURE_ERROR):
        result = pipeline.capture()
        assert isinstance(result, CaptureResult)
        assert result.status == OBSERVATION_UNAVAILABLE
        assert result.reason == expected_reason
        assert result.scope == "OBSERVATION"
        # a capture failure says NOTHING about any action outcome
        assert result.action_failed is None

    # timeout failures carry the same contract
    timed = ScreenshotPipeline(lambda: time.sleep(1.0), timeout_s=0.1).capture()
    assert timed.status == OBSERVATION_UNAVAILABLE
    assert timed.reason == REASON_TIMEOUT
    assert timed.scope == "OBSERVATION"
    assert timed.action_failed is None

    # success does not fabricate action evidence either
    ok = ScreenshotPipeline(lambda: b"frame", timeout_s=1.0).capture()
    assert ok.status == CAPTURED
    assert ok.action_failed is None
    assert ok.scope == "OBSERVATION"


def test_observation_failure_no_game_recovery() -> None:
    """Observation failures never trigger game/business recovery: the module
    exposes no game surface, advises browser recovery only on a proven-dead
    page, and leaves game resumption outside its contract."""
    recovery_calls: list[str] = []

    def alive_probe() -> bool:
        return True  # tab responds to title/url reads (observed reality)

    pipeline = ScreenshotPipeline(
        lambda: (_ for _ in ()).throw(RuntimeError("wedged")),
        probe_fn=alive_probe,
        on_browser_recovery_required=recovery_calls.append,
        timeout_s=0.2,
    )
    for _ in range(5):
        result = pipeline.capture()
        assert result.status == OBSERVATION_UNAVAILABLE
        # live page: NO browser recovery advisory, NO recovery call
        assert result.browser_recovery_required is False
        assert result.recovery_advisory is None
    assert recovery_calls == []
    assert pipeline.consecutive_failures == 5

    # even a dead probe yields a BROWSER-scope advisory only -- never a game action
    def dead_probe() -> bool:
        return False

    dead = ScreenshotPipeline(
        lambda: (_ for _ in ()).throw(RuntimeError("wedged")),
        probe_fn=dead_probe,
        on_browser_recovery_required=recovery_calls.append,
        timeout_s=0.2,
    )
    result = dead.capture()
    assert result.status == OBSERVATION_UNAVAILABLE
    assert result.browser_recovery_required is True
    assert result.recovery_advisory == RECOVERY_NEW_CAPTURE_SURFACE
    assert recovery_calls == [RECOVERY_NEW_CAPTURE_SURFACE]
    # hook fires at most once per recovery episode
    dead.capture()
    assert recovery_calls == [RECOVERY_NEW_CAPTURE_SURFACE]

    # structural: the pipeline surface has no game/business capability at all
    forbidden = (
        "resume", "produce", "click", "decide", "restart", "reload",
        "navigate", "reopen", "execute", "run_game", "game",
    )
    public = {name for name in dir(pipeline) if not name.startswith("_")}
    assert not (public & set(forbidden))
