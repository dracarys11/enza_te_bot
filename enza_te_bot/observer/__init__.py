"""Human Demonstration Observer Mode.

Observes and records while a human operates the game/web page.
No autonomous action execution: observer output is never sent to
executor / ActionBoundary authorization.
"""
from observer.observer_mode import ObserverMode, ObserverPermissionError
from observer.trajectory_recorder import TrajectoryRecorder
from observer.human_feedback import HumanFeedbackChannel

__all__ = [
    "ObserverMode",
    "ObserverPermissionError",
    "TrajectoryRecorder",
    "HumanFeedbackChannel",
]
