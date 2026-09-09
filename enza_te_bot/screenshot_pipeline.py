"""Caller-side screenshot acquisition contract for the ZCode IAB surface.

Diagnosed failure (WINGRUN_20260907_02, 4 occurrences; see
enza_memory/failures/iab_screenshot_pipeline_stall_001.json): the ZCode host
backend holds per-tab pending-screenshot state that is NOT released when a
capture times out.  The host applies a 30s capture timeout, but the next
capture on the same tab is then rejected ("A previous screenshot for this
browser tab is still completing after timeout") across fresh JS kernels,
which proves the latch is backend-side; the tab itself stayed alive for
url/title reads.  The host is not modifiable from this repository and the
plugin client (browser-client.mjs) only forwards the command.

This module is the normative caller-side contract so an observation failure
can never wedge the agent loop or leak into business behavior:

1. a new screenshot request never blocks forever on a previous capture
   (single-flight: concurrent requests fail fast with BUSY);
2. a timed-out capture releases the caller-side pending state immediately;
3. every failure returns an explicit OBSERVATION_UNAVAILABLE result with a
   reason -- the pipeline never leaves the caller believing a capture is
   still running;
4. an observation failure is never an action failure: results carry
   scope=OBSERVATION and no action outcome;
5. the pipeline performs no game interaction and exposes no business
   recovery.  A browser-scope recovery advisory (new capture surface) is
   attached ONLY when a liveness probe proves the page dead; repeated
   failures on a live page are recorded and retried safely instead -- they
   never trigger browser recovery by themselves, and game resumption after
   any browser recovery remains a separate operator/agent business decision.

Live-usage mirror (IAB surface, no equivalent of this wrapper exists in JS):
emit at most one screenshot per observation cycle; on timeout do NOT retry
the capture immediately and do NOT treat it as an action failure; probe tab
liveness with a title/url read; consider a new capture surface only when the
probe proves the page dead -- never reload the game as an automatic
consequence of an observation failure.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

CAPTURED = "CAPTURED"
OBSERVATION_UNAVAILABLE = "OBSERVATION_UNAVAILABLE"

REASON_TIMEOUT = "TIMEOUT"
REASON_BUSY = "BUSY"
REASON_CAPTURE_ERROR = "CAPTURE_ERROR"
REASON_PAGE_DEAD = "PAGE_DEAD"

SCOPE_OBSERVATION = "OBSERVATION"
RECOVERY_NEW_CAPTURE_SURFACE = "NEW_CAPTURE_SURFACE"
REASON_STALE_FRAME = "STALE_FRAME"


class ObservationUnavailableError(Exception):
    """Typed observation failure; carries no game-action verdict.

    Raised by observation boundaries when a screenshot cannot be obtained or
    trusted (timeout / capture error / stale frame).  Callers must classify
    it with :func:`classify_observation_failure` instead of treating it as a
    game, action, or browser-death signal.
    """

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(detail or reason)
        self.reason = reason
        self.detail = detail or reason
        self.scope = SCOPE_OBSERVATION


@dataclass(frozen=True)
class ObservationVerdict:
    """Explicit decoupled classification of one observation failure.

    The three decoupling invariants are structural:

    - ``is_game_failure`` is always False: an observation failure never
      classifies as a game/business outcome;
    - ``pending_action_failed`` is always None: a capture failure proves
      nothing about any in-flight or pending business action (TIMEOUT is not
      ACTION_FAILED);
    - ``browser_dead`` is None unless a liveness probe PROVED the page dead.
    """

    reason: str
    is_game_failure: bool = False
    pending_action_failed: bool | None = None
    browser_dead: bool | None = None
    recovery_required: bool = False
    retry_safe: bool = True

    @property
    def status(self) -> str:
        return OBSERVATION_UNAVAILABLE


def classify_observation_failure(
    *,
    reason: str,
    probe_alive: bool | None = None,
) -> ObservationVerdict:
    """Classify one observation failure without inventing unproven causes.

    ``probe_alive``: True/False from an independent liveness probe, or None
    when no proof exists.  Browser recovery is advised only on proof of death.
    """
    if reason not in {REASON_TIMEOUT, REASON_CAPTURE_ERROR, REASON_STALE_FRAME, REASON_PAGE_DEAD}:
        raise ValueError(f"UNCLASSIFIED_OBSERVATION_FAILURE_REASON:{reason}")
    browser_dead = True if probe_alive is False else None if probe_alive is None else False
    recovery_required = probe_alive is False or reason == REASON_PAGE_DEAD
    return ObservationVerdict(
        reason=reason,
        browser_dead=browser_dead,
        recovery_required=recovery_required,
    )


@dataclass(frozen=True)
class CaptureResult:
    """One acquisition outcome; observation-scope only, never an action verdict."""

    status: str
    image: Any = None
    reason: str | None = None
    scope: str = SCOPE_OBSERVATION
    action_failed: bool | None = None
    page_alive: bool | None = None
    browser_recovery_required: bool = False
    recovery_advisory: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == CAPTURED


class ScreenshotPipeline:
    """Single-flight, timeout-bounded screenshot acquisition wrapper.

    ``capture_fn`` is any zero-argument callable returning the image payload
    (live surface: ``await tab.screenshot()`` behind a sync bridge).
    ``probe_fn`` is an optional fast liveness probe (live surface: tab
    title/url read) that must be independent of the capture path.
    ``on_browser_recovery_required`` is an optional notification hook that
    fires at most once per recovery episode with a browser-scope advisory;
    the pipeline itself never touches the game.
    """

    def __init__(
        self,
        capture_fn: Callable[[], Any],
        *,
        probe_fn: Callable[[], bool] | None = None,
        on_browser_recovery_required: Callable[[str], None] | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self._capture_fn = capture_fn
        self._probe_fn = probe_fn
        self._recovery_hook = on_browser_recovery_required
        self._timeout_s = timeout_s
        self._active = threading.Event()
        self._consecutive_failures = 0
        self._recovery_notified = False
        self._lock = threading.Lock()

    @property
    def capture_active(self) -> bool:
        return self._active.is_set()

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def capture(self) -> CaptureResult:
        """Acquire one screenshot under the reliability contract."""
        with self._lock:
            if self._active.is_set():
                return CaptureResult(
                    status=OBSERVATION_UNAVAILABLE,
                    reason=REASON_BUSY,
                )
            self._active.set()
        try:
            return self._run_bounded_capture()
        finally:
            # Invariant 2: the pending flag is always released, success or not.
            self._active.clear()

    def _run_bounded_capture(self) -> CaptureResult:
        outcome: dict[str, Any] = {}
        done = threading.Event()

        def runner() -> None:
            try:
                outcome["image"] = self._capture_fn()
            except BaseException as error:  # noqa: BLE001 - failure is a result, never a raise
                outcome["error"] = error
            finally:
                done.set()

        worker = threading.Thread(target=runner, daemon=True, name="screenshot-capture")
        worker.start()
        if not done.wait(self._timeout_s):
            # Timed out: pending state is released by the caller's finally.
            # The abandoned daemon worker exits whenever the backend call
            # eventually returns; at most one such worker can exist because
            # of the single-flight guard.
            return self._failure(REASON_TIMEOUT)
        if "error" in outcome:
            return self._failure(REASON_CAPTURE_ERROR)
        self._consecutive_failures = 0
        self._recovery_notified = False
        return CaptureResult(status=CAPTURED, image=outcome.get("image"))

    def _failure(self, reason: str) -> CaptureResult:
        self._consecutive_failures += 1
        page_alive = self._probe()
        recovery_required = self._evaluate_recovery(page_alive)
        advisory = None
        if recovery_required:
            advisory = RECOVERY_NEW_CAPTURE_SURFACE
            hook = self._recovery_hook
            if hook is not None and not self._recovery_notified:
                hook(advisory)
                self._recovery_notified = True
        return CaptureResult(
            status=OBSERVATION_UNAVAILABLE,
            reason=reason,
            page_alive=page_alive,
            browser_recovery_required=recovery_required,
            recovery_advisory=advisory,
        )

    def _probe(self) -> bool | None:
        if self._probe_fn is None:
            return None
        try:
            return bool(self._probe_fn())
        except Exception:  # noqa: BLE001 - probe failure means liveness UNKNOWN
            return None

    def _evaluate_recovery(self, page_alive: bool | None) -> bool:
        # Invariant 4: browser recovery is advised only when the page is
        # PROVEN dead.  Repeated failures on a live (or liveness-unknown)
        # page are recorded (consecutive_failures) and retried safely; they
        # never trigger recovery by themselves.
        return page_alive is False


__all__ = [
    "CAPTURED",
    "OBSERVATION_UNAVAILABLE",
    "CaptureResult",
    "ObservationUnavailableError",
    "ObservationVerdict",
    "REASON_BUSY",
    "REASON_CAPTURE_ERROR",
    "REASON_PAGE_DEAD",
    "REASON_STALE_FRAME",
    "REASON_TIMEOUT",
    "RECOVERY_NEW_CAPTURE_SURFACE",
    "SCOPE_OBSERVATION",
    "ScreenshotPipeline",
    "classify_observation_failure",
]
