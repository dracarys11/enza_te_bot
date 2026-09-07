"""Replay OB-001 through grounding and non-executing decision evaluation."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from decision_agent.grounded_decision import GroundedDecisionAgent
from grounded_element import build_grounded_elements


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "test_data" / "ob001" / "fused_observation.json"
DEFAULT_OUTPUT = ROOT / "test_data" / "ob001" / "action_candidate.json"
OB001_GOAL = "Enter W.I.N.G. mode"


def run(input_path: str | Path = DEFAULT_INPUT,
        output_path: str | Path = DEFAULT_OUTPUT,
        *, user_goal: str = OB001_GOAL) -> dict[str, Any]:
    observation = json.loads(Path(input_path).read_text(encoding="utf-8"))
    elements = build_grounded_elements(observation)
    agent = GroundedDecisionAgent({OB001_GOAL: "次へ"})
    candidate = agent.decide(elements, user_goal)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return candidate


if __name__ == "__main__":
    run()
