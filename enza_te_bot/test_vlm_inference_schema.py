import json

import pytest

from tools.run_vlm_observation_inference import normalize_prediction, run_predictions
from tools.vlm_annotation_stats import summarize_predictions


FORBIDDEN = {
    "authority_type",
    "planner_decision",
    "execution_permission",
    "action_allowed",
    "risk_gate",
    "should_click",
    "next_action",
}


def test_output_json_and_unknown_schema(tmp_path):
    source = tmp_path / "observations.jsonl"
    source.write_text(json.dumps({"image": "frame.png", "sha256": "a" * 64}) + "\n")
    output = tmp_path / "predictions.jsonl"
    run_predictions(source, output, tmp_path)
    record = json.loads(output.read_text())
    assert record["observation"]["state"] == "UNKNOWN"
    assert record["vlm_status"] == "UNKNOWN"
    assert set(record["observation"]) == {
        "state", "phase", "event_type", "visible_text", "visible_controls", "layout_family",
    }


def test_forbidden_fields_are_rejected_and_never_emitted():
    for field in FORBIDDEN:
        with pytest.raises(ValueError):
            normalize_prediction({"observation": {"state": "UNKNOWN"}, field: True})


def test_visible_control_is_observation_only(tmp_path):
    source = tmp_path / "observations.jsonl"
    source.write_text(json.dumps({"image": "frame.png", "sha256": "a" * 64}) + "\n")
    output = tmp_path / "predictions.jsonl"
    run_predictions(
        source,
        output,
        tmp_path,
        lambda _: {
            "observation": {"visible_controls": [{"name": "AUTO", "appearance": "visible"}]},
            "confidence": 0.4,
            "vlm_status": "OBSERVED",
        },
    )
    text = output.read_text()
    assert "action_allowed" not in text
    assert json.loads(text)["observation"]["visible_controls"][0]["appearance"] == "visible"


def test_control_authority_claim_is_rejected():
    with pytest.raises(ValueError, match="forbidden authority"):
        normalize_prediction({
            "observation": {"visible_controls": [{"name": "AUTO", "clickable": True}]},
            "confidence": 0.5,
            "vlm_status": "OBSERVED",
        })


def test_stats_include_distributions_and_unknown_rate(tmp_path):
    path = tmp_path / "predictions.jsonl"
    path.write_text("\n".join([
        json.dumps({"observation": {"state": "UNKNOWN", "phase": "UNKNOWN"}, "confidence": 0.0, "vlm_status": "UNKNOWN"}),
        json.dumps({"observation": {"state": "WING_HOME", "phase": "IDLE_ACTIONABLE"}, "confidence": 0.9, "vlm_status": "OBSERVED"}),
    ]) + "\n")
    stats = summarize_predictions(path)
    assert stats["total"] == 2
    assert stats["unknown_rate"] == 0.5
    assert stats["state_distribution"]["UNKNOWN"] == 1
    assert stats["confidence_histogram"]["0.8-1.0"] == 1
