import json
from pathlib import Path

from evaluator.runner import validate_response


ROOT = Path(__file__).parent


def test_schema_contract_is_valid_json_and_rejects_missing_fields():
    schema = json.loads((ROOT / "schemas/response.schema.json").read_text())
    assert set(schema["required"]) == {"decision", "facts", "inferences", "unknowns", "action_allowed", "reason", "confidence"}
    assert validate_response({"decision": "blocked"})


def test_schema_contract_accepts_minimal_valid_response():
    response = {"decision": "blocked", "facts": ["trouble_rate=92%"], "inferences": [], "unknowns": [], "action_allowed": False, "reason": "hard gate", "confidence": 1}
    assert validate_response(response) == []
