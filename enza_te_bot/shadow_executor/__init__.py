"""Read-only Python shadow click executor.

The package detects and scores possible controls, but deliberately has no
mouse, keyboard, executor, or ActionBoundary dependency.
"""

from .executor import PythonShadowClickExecutor, ShadowPrediction
from .skill_board import (ReplacementObservation, SkillActionPlan,
                          SkillBoardObservation, SkillNodeObservation,
                          evaluate_sp, observe_replacement,
                          observe_skill_board, plan_skill_action,
                          validate_progressive_unlock)

__all__ = [
    "PythonShadowClickExecutor", "ShadowPrediction", "SkillBoardObservation",
    "SkillNodeObservation", "SkillActionPlan", "ReplacementObservation",
    "observe_skill_board", "observe_replacement", "plan_skill_action",
    "evaluate_sp", "validate_progressive_unlock",
]
