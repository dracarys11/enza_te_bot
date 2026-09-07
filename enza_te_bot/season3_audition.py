"""Small deterministic Season-3 audition transaction helpers."""
from __future__ import annotations

from collections.abc import Callable, Mapping

def required_reward(run_state: dict) -> int | None:
    s3 = run_state.get("season3", {})
    if not s3.get("audition_40k_completed", False): return 40000
    if not s3.get("audition_50k_completed", False): return 50000
    return None

def target_is_locked(*, target_reward: int, current_fans: int | None, min_fans: dict[int, int] | None = None) -> bool:
    if current_fans is None: return True
    thresholds = min_fans or {50000: 50000, 100000: 100000}
    return current_fans < thresholds.get(target_reward, 0)

def _explicit_outcome(evidence: Mapping[str, object] | None) -> str | None:
    if not isinstance(evidence, Mapping):
        return None
    outcome = evidence.get("outcome")
    evidence_class = evidence.get("evidence_class")
    if outcome == "PASS" and evidence_class == "EXPLICIT_PASS":
        return "PASS"
    if outcome == "FAIL" and evidence_class == "EXPLICIT_FAIL":
        return "FAIL"
    return None


def commit_result(
    run_state: dict, reward: int, *, evidence: Mapping[str, object] | None,
    persist_evidence: Callable[[Mapping[str, object]], object] | None = None,
    result_id: str | None = None,
) -> str:
    """Validate and commit one explicit audition result exactly once.

    The evidence callback is the existing durability/attestation boundary. It
    runs before the in-memory business flag changes. Result identity makes
    replayed PASS observations harmless. RESULT/HOME/reward screens alone are
    intentionally insufficient.
    """
    outcome = _explicit_outcome(evidence)
    if reward not in {40000, 50000} or outcome is None:
        return "UNKNOWN"
    if outcome == "FAIL":
        return "FAIL_RECORDED"
    if result_id:
        committed = run_state.setdefault("committed_result_ids", [])
        if result_id in committed:
            return "ALREADY_COMMITTED"
    if persist_evidence is not None:
        persist_evidence(dict(evidence))
    s3 = run_state.setdefault("season3", {})
    key = "audition_40k_completed" if reward == 40000 else "audition_50k_completed"
    if s3.get(key) is True:
        return "ALREADY_COMMITTED"
    s3[key] = True
    if result_id:
        run_state.setdefault("committed_result_ids", []).append(result_id)
    return "COMMITTED"


def commit_success(run_state: dict, reward: int, *, success_evidence: bool) -> bool:
    """Legacy compatibility wrapper; only an explicit PASS boolean is accepted."""
    if not success_evidence:
        return False
    return commit_result(
        run_state, reward,
        evidence={"outcome": "PASS", "evidence_class": "EXPLICIT_PASS"},
    ) == "COMMITTED"


def commit_named_result(
    run_state: dict, result_name: str, *, evidence: Mapping[str, object] | None,
    persist_evidence: Callable[[Mapping[str, object]], object] | None = None,
    result_id: str | None = None,
) -> str:
    """Commit a non-audition result only from explicit PASS/FAIL evidence."""
    if not isinstance(result_name, str) or not result_name.strip():
        return "UNKNOWN"
    outcome = _explicit_outcome(evidence)
    if outcome is None:
        return "UNKNOWN"
    if outcome == "FAIL":
        return "FAIL_RECORDED"
    committed = run_state.setdefault("committed_named_results", {})
    if result_id and result_id in committed:
        return "ALREADY_COMMITTED"
    if result_name in committed:
        return "ALREADY_COMMITTED"
    if persist_evidence is not None:
        persist_evidence(dict(evidence))
    committed[result_name] = {"result_id": result_id, "evidence_class": "EXPLICIT_PASS"}
    return "COMMITTED"

def missing_audition_actions(states: dict) -> list[str]:
    """Report the currently absent executable selection controls."""
    select = states.get("AUDITION_SELECT", {})
    names = {a.get("name") for a in select.get("allowed_actions", [])}
    return [name for name in ("audition_confirm",) if name not in names]
