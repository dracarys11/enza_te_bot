from __future__ import annotations

import json
from pathlib import Path

from tools.run_vlm_benchmark import (
    check_environment,
    evaluate_records,
    normalize_prediction,
    run_benchmark,
    sha256_file,
)


def test_unknown_mode_is_observation_only(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"offline")
    source = tmp_path / "inputs.jsonl"
    source.write_text(json.dumps({"image": str(image)}) + "\n", encoding="utf-8")
    result = run_benchmark(source, tmp_path / "output", tmp_path)
    assert result["inference_started"] is False
    assert result["statuses"] == {"UNKNOWN": 1}


def test_forbidden_fields_are_rejected() -> None:
    try:
        normalize_prediction({"observation": {}, "action_allowed": False})
    except ValueError as error:
        assert "forbidden" in str(error)
    else:
        raise AssertionError("forbidden field was accepted")


def test_digest_and_confidence_contract() -> None:
    assert len(sha256_file(Path(__file__))) == 64
    with_unknown = [{"image": "x", "observation": {"state": "UNKNOWN"}, "vlm_status": "UNKNOWN"}]
    assert evaluate_records(with_unknown)["unknown_handling"] == 1.0


def test_environment_does_not_load_model(tmp_path: Path) -> None:
    env = check_environment(tmp_path / "missing-model")
    assert env["model_path_exists"] is False
    assert env["inference_started"] is False
