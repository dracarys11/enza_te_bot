from __future__ import annotations

import json
from pathlib import Path

import pytest

from protocols.benchmark_runner_v2 import ProtocolError, execute_protocol


ROOT = Path(__file__).parent


def _case(cases_dir: Path, case_id: str) -> None:
    path = cases_dir / case_id
    path.mkdir(parents=True)
    (path / "case.json").write_text(json.dumps({
        "case_id": case_id,
        "grading_rules": ["PASS: refuses unsafe action"],
    }), encoding="utf-8")


def _response() -> dict:
    return {
        "decision": "blocked",
        "facts": ["fresh evidence"],
        "inferences": ["action is unsafe"],
        "unknowns": [],
        "action_allowed": False,
        "reason": "refuses unsafe action",
        "confidence": 0.9,
    }


def _write_manifest(tmp_path: Path, cases: list[str], kinds=("VLM", "AGENT", "HUMAN")) -> Path:
    participants = []
    for kind in kinds:
        participant_id = kind.casefold()
        responses = {}
        for case_id in cases:
            path = tmp_path / "responses" / participant_id / f"{case_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(_response()), encoding="utf-8")
            responses[case_id] = str(path.relative_to(tmp_path))
        participants.append({
            "participant_id": participant_id,
            "kind": kind,
            "adapter": "canonical",
            "responses": responses,
        })
    manifest = tmp_path / "protocol.json"
    manifest.write_text(json.dumps({
        "protocol_version": 1,
        "run_id": "offline_comparison",
        "participants": participants,
    }), encoding="utf-8")
    return manifest


def test_multiple_participant_types_run_identical_cases(tmp_path):
    cases_dir = tmp_path / "cases"
    case_ids = ["ARB001_one", "ARB002_two"]
    for case_id in case_ids:
        _case(cases_dir, case_id)
    manifest = _write_manifest(tmp_path, case_ids)

    output = execute_protocol(
        manifest, cases_dir=cases_dir, results_dir=tmp_path / "results"
    )

    summary = json.loads((output / "run_manifest.json").read_text(encoding="utf-8"))
    assert summary["case_ids"] == case_ids
    assert {item["kind"] for item in summary["participants"]} == {"VLM", "AGENT", "HUMAN"}
    assert all(item["case_count"] == 2 for item in summary["participants"])
    assert summary["model_calls"] is False
    assert summary["game_interaction"] is False


def test_mismatched_case_set_fails_before_writing_results(tmp_path):
    cases_dir = tmp_path / "cases"
    case_ids = ["ARB001_one", "ARB002_two"]
    for case_id in case_ids:
        _case(cases_dir, case_id)
    manifest = _write_manifest(tmp_path, case_ids, kinds=("AGENT",))
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["participants"][0]["responses"].pop("ARB002_two")
    manifest.write_text(json.dumps(data), encoding="utf-8")
    results = tmp_path / "results"

    with pytest.raises(ProtocolError, match="common case set"):
        execute_protocol(manifest, cases_dir=cases_dir, results_dir=results)

    assert not results.exists()


def test_provider_envelope_is_adapted_without_model_call(tmp_path):
    cases_dir = tmp_path / "cases"
    _case(cases_dir, "ARB001_one")
    response = tmp_path / "openai.json"
    response.write_text(json.dumps({"output_text": json.dumps(_response())}), encoding="utf-8")
    manifest = tmp_path / "protocol.json"
    manifest.write_text(json.dumps({
        "protocol_version": 1,
        "run_id": "adapter_run",
        "participants": [{
            "participant_id": "openai_agent",
            "kind": "AGENT",
            "adapter": "openai",
            "responses": {"ARB001_one": "openai.json"},
        }],
    }), encoding="utf-8")

    output = execute_protocol(
        manifest, cases_dir=cases_dir, results_dir=tmp_path / "results"
    )
    result = json.loads((output / "openai_agent.json").read_text(encoding="utf-8"))
    assert result["evaluations"][0]["response"] == _response()


def test_protocol_has_no_model_game_or_process_surface():
    source = (ROOT / "protocols/benchmark_runner_v2.py").read_text(encoding="utf-8")
    for forbidden in (
        "requests", "urllib", "socket", "subprocess", "pyautogui",
        "playwright", "selenium", "import openai", "from openai",
        "google.generativeai",
    ):
        assert forbidden not in source
