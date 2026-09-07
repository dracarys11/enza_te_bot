import json
from pathlib import Path

import pytest

from tools.run_vlm_observation_inference import normalize_prediction, run_predictions


def test_forbidden_fields_absent_and_schema_valid(tmp_path):
    source = tmp_path / "observations.jsonl"
    source.write_text(json.dumps({"image": "frame.png", "sha256": "a" * 64}) + "\n")
    output = tmp_path / "predictions.jsonl"
    run_predictions(source, output, tmp_path, lambda _: {"observation": {"state": "UNKNOWN"}, "confidence": 0, "vlm_status": "UNKNOWN"})
    row = json.loads(output.read_text())
    assert set(row) == {"image", "sha256", "observation", "confidence", "vlm_status"}
    assert set(row["observation"]) == {"state", "phase", "event_type", "visible_text", "visible_controls", "layout_family"}
    assert not any(field in output.read_text() for field in ("authority_type", "planner_decision", "execution_permission", "action_allowed", "risk_gate", "should_click"))


def test_unknown_prediction_is_accepted(tmp_path):
    source = tmp_path / "observations.jsonl"
    source.write_text(json.dumps({"image": "missing.png", "sha256": None}) + "\n")
    output = tmp_path / "predictions.jsonl"
    stats = run_predictions(source, output, tmp_path)
    row = json.loads(output.read_text())
    assert row["observation"]["state"] == "UNKNOWN"
    assert row["vlm_status"] == "UNKNOWN"
    assert stats["unknown_rate"] == 1.0


def test_model_cannot_emit_authority_fields():
    with pytest.raises(ValueError, match="forbidden authority"):
        normalize_prediction({"observation": {"state": "WING_HOME"}, "action_allowed": True})
