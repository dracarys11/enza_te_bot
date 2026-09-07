from pathlib import Path


ROOT = Path(__file__).resolve().parent
GATES = ROOT / ".agent-harness" / "GATES.md"


def test_live_observation_invariants_are_canonical_and_scoped():
    text = GATES.read_text(encoding="utf-8")
    promoted = text.split("Live runtime observation invariants:", 1)[1].split(
        "Promotion provenance", 1
    )[0]
    required = (
        "INTERACTABILITY_MUST_BE_OBSERVED_SEPARATELY_FROM_CONTROL_VALUE",
        "CONTROL_ACTION_REQUIRES_ACTIONABLE_PHASE",
        "POST_TRANSACTION_STATE_MUST_BE_RECONCILED_FROM_FRESH_STABLE_STATE",
    )
    for invariant in required:
        assert promoted.count(invariant) == 1
    assert "SPEED_FIRST_THEN_AUTO" not in promoted


def test_ordering_dependency_remains_hold_and_domain_rules_stay_out():
    text = GATES.read_text(encoding="utf-8")
    held = text.split("Held system-level candidate:", 1)[1]
    assert "CONTROL_ORDERING_DEPENDENCY_MUST_BE_RESPECTED" in held
    assert "`HOLD`" in held
    assert "SPEED_FIRST_THEN_AUTO" in held
    assert "stamina < 0.50" not in text
    assert "vocal failure rate >2%" not in text


def test_actionable_phase_does_not_become_global_no_click_rule():
    text = GATES.read_text(encoding="utf-8")
    actionable = text.split("CONTROL_ACTION_REQUIRES_ACTIONABLE_PHASE", 1)[1].split(
        "POST_TRANSACTION_STATE_MUST_BE_RECONCILED_FROM_FRESH_STABLE_STATE", 1
    )[0]
    assert "semantic control action" in actionable
    assert "does not prohibit every click" in actionable
    held = text.split("Held system-level candidate:", 1)[1]
    assert "SAFE_TRANSIENT_ACTION_MAY_BE_ANTICIPATORY" in held
    assert "`HOLD` candidate" in held
    assert "OBSERVE" in held and "PROBE" in held
    assert "300ms" not in text


def test_batch_execution_uses_measured_tool_latency_without_runtime_constants():
    text = GATES.read_text(encoding="utf-8")
    batching = text.split("Execution batching invariant:", 1)[1].split(
        "Held system-level candidate:", 1
    )[0]
    assert batching.count("BATCH_EXECUTION_MUST_RESPECT_MEASURED_TOOL_LATENCY") == 1
    assert "measured end-to-end latency" in batching
    assert "split the batch before execution" in batching
    for runtime_constant in ("5s", "30s", "120s", "12 clicks"):
        assert runtime_constant not in batching
