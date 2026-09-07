"""Optional canonical episode-step adapter over the existing JSONL storage."""
from __future__ import annotations

from typing import Any, Callable

from perception_models import ActionResult, Observation


def trajectory_step(*, episode: str, step: int, observation: Observation | dict[str, Any],
                    action: dict[str, Any] | None, result: ActionResult | None,
                    goal: str = "") -> dict[str, Any]:
    """Build a JSON-safe record without changing legacy trace records."""
    observed = observation.as_dict() if isinstance(observation, Observation) else dict(observation)
    return {"kind": "trajectory_step", "episode": episode, "goal": goal, "step": step,
            "observation": observed, "action": action,
            "action_result": result.as_dict() if result else None}


def emit_trajectory_step(writer: Callable[[dict[str, Any]], None], **kwargs: Any) -> None:
    writer(trajectory_step(**kwargs))
