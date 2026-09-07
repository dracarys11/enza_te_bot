"""Observer Mode: watch, record, question — never act.

Allowed:
  - read screenshot, build VisionObservation
  - record candidate actions + uncertainties
  - ask human clarification, record human feedback

Forbidden (enforced, not just promised):
  - any executor invocation, automation call, input synthesis
  - generating ActionBoundary authorization
"""
from __future__ import annotations

from typing import Any, Protocol

from vision_observation_schema import VisionObservation

# Modules the observer must never touch. Checked on every action attempt.
FORBIDDEN_MODULES = frozenset(
    {
        "executor",
        "action_boundary",
        "action_gate",
        "actions",
        "goal_execution",
        "mvp_runtime_runner",
        "home_tick",
    }
)


class ObserverPermissionError(PermissionError):
    """Raised when observer mode is asked to perform a forbidden operation."""


class VisionProvider(Protocol):
    def observe(self, screenshot_path: str) -> dict[str, Any]: ...


class ObserverMode:
    """Observes screenshots and records trajectories of human demonstrations."""

    def __init__(self, vision_provider: VisionProvider, recorder: Any):
        self.vision_provider = vision_provider
        self.recorder = recorder
        self.executed_actions: list[dict[str, Any]] = []  # must stay empty

    # -- the only "action" surface, and it is a guard -------------------
    def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise ObserverPermissionError(
            "observer_mode cannot execute actions: autonomous execution is disabled"
        )

    def request_action_boundary(self, *args: Any, **kwargs: Any) -> Any:
        raise ObserverPermissionError(
            "observer_mode cannot generate ActionBoundary authorization"
        )

    def __setattr__(self, name: str, value: Any) -> None:
        # Refuse to bind executor/boundary objects onto the observer at all.
        module = getattr(value, "__module__", "")
        if isinstance(module, str) and module.split(".")[0] in FORBIDDEN_MODULES:
            raise ObserverPermissionError(
                f"observer_mode refuses attribute bound to forbidden module '{module}'"
            )
        super().__setattr__(name, value)

    # -- observation ----------------------------------------------------
    def observe(self, screenshot_path: str) -> dict[str, Any]:
        """Read a screenshot, produce a VisionObservation-compatible record.

        The provider payload is validated through the existing (unmodified)
        VisionObservation contract; observer output is therefore drop-in
        compatible with everything downstream that consumes observations.
        """
        payload = self.vision_provider.observe(screenshot_path)
        VisionObservation.from_payload(payload)  # raises on contract violation
        # v0.2: no candidate_actions — the observer records visual facts only;
        # action proposal is deferred to the future decision-agent benchmark.
        elements = [
            {"id": t.get("id"), "text": t.get("text"), "bbox": t.get("bbox"),
             "confidence": t.get("confidence")}
            for t in payload.get("text_regions", [])
        ]
        record = self.recorder.record_observation(
            {
                "vision_source": getattr(self.vision_provider, "name", type(self.vision_provider).__name__),
                "provider_metadata": payload.get("capture", {}),
                "elements": elements,
                "uncertainties": payload.get("uncertainties", []),
                "vision_observation": payload,
            },
            screenshot_path,
        )
        return record
