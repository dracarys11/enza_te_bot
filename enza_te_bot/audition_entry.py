"""Pure bounded Season-3 audition entry decisions; no clicking or OCR."""
from __future__ import annotations

def target_reward(run_state: dict) -> int | None:
    s3 = run_state.get("season3", {})
    if not s3.get("audition_40k_completed", False): return 40000
    if not s3.get("audition_50k_completed", False): return 50000
    return None

def bounded_navigation(current_reward: int | None, target: int, attempts: int, max_attempts: int = 8) -> str:
    if current_reward == target: return "TARGET_VERIFIED"
    if attempts >= max_attempts: return "TARGET_NOT_FOUND"
    return "NEXT_PAGE"

def confirm_destination(state: str, expected: str = "PRE_AUDITION_CHOICE") -> bool:
    return state == expected

def middle_choice_only(choice: str) -> bool:
    return choice == "middle"
