from __future__ import annotations

import json
from pathlib import Path

import pytest

from adapters import AdapterError
from adapters.gemini_adapter import adapt_response as adapt_gemini
from adapters.local_vlm_adapter import adapt_response as adapt_local_vlm
from adapters.openai_adapter import adapt_response as adapt_openai
from adapters.zcode_adapter import adapt_response as adapt_zcode
from evaluator.runner import validate_response


ROOT = Path(__file__).parent
CANONICAL = {
    "decision": "blocked",
    "facts": ["fresh trouble_rate=92%"],
    "inferences": ["VOCAL is unsafe"],
    "unknowns": [],
    "action_allowed": False,
    "reason": "hard gate",
    "confidence": 0.9,
}


def encoded() -> str:
    return json.dumps(CANONICAL)


@pytest.mark.parametrize("adapter,raw", [
    (adapt_openai, {"output_text": encoded()}),
    (adapt_openai, {"choices": [{"message": {"content": encoded()}}]}),
    (adapt_gemini, {"candidates": [{"content": {"parts": [{"text": encoded()}]}}]}),
    (adapt_zcode, {"result": encoded()}),
    (adapt_local_vlm, [{"generated_text": encoded()}]),
])
def test_provider_envelopes_normalize_to_response_schema(adapter, raw):
    result = adapter(raw)
    assert result == CANONICAL
    assert validate_response(result) == []


def test_aliases_and_percent_confidence_are_normalized():
    result = adapt_gemini({"text": json.dumps({
        "verdict": "UNKNOWN",
        "observations": "button visible",
        "hypotheses": [],
        "uncertainties": ["state unresolved"],
        "allowed": "denied",
        "rationale": "fresh evidence missing",
        "confidence_score": "35%",
    })})
    assert result == {
        "decision": "UNKNOWN",
        "facts": ["button visible"],
        "inferences": [],
        "unknowns": ["state unresolved"],
        "action_allowed": False,
        "reason": "fresh evidence missing",
        "confidence": 0.35,
    }


def test_missing_action_authority_fails_closed():
    payload = dict(CANONICAL)
    payload.pop("action_allowed")
    with pytest.raises(AdapterError, match="action_allowed"):
        adapt_openai(payload)


def test_adapters_have_no_model_or_execution_dependencies():
    forbidden = ("requests", "urllib", "socket", "subprocess", "pyautogui", "playwright")
    for path in sorted((ROOT / "adapters").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path
