import json
from pathlib import Path

from tools.screenshot_event_mapper import map_file


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")


def test_filename_semantics_map_pass_battle_event(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    write_jsonl(metadata, [{"image_path": "screenshots/battle_pass.png", "run_id": "RUN_A"}])
    trace = tmp_path / "wing_runs/RUN_A/weekly_trace.jsonl"
    write_jsonl(trace, [{"run_id": "RUN_A", "phase": "AUDITION_BATTLE", "action": "AUDITION", "result": "PASS"}])
    output = tmp_path / "out.jsonl"
    map_file(metadata, tmp_path / "wing_runs", trace, output)
    row = json.loads(output.read_text())
    assert row["event"] == {
        "phase": "AUDITION_BATTLE", "action": "AUDITION", "result": "PASS",
        "source": "filename_semantic_trace_match",
    }


def test_timestamp_is_used_when_filename_has_no_semantic_token(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    write_jsonl(metadata, [{"image_path": "screenshots/frame_01.png", "run_id": "RUN_A", "timestamp": "2026-09-07T01:00:03Z"}])
    trace = tmp_path / "weekly_trace.jsonl"
    write_jsonl(trace, [{"timestamp": "2026-09-07T01:00:00Z", "phase": "S1W2", "action": "VOCAL", "result": "COMMITTED"}])
    output = tmp_path / "out.jsonl"
    map_file(metadata, tmp_path / "wing_runs", trace, output)
    assert json.loads(output.read_text())["event"]["action"] == "VOCAL"


def test_run_id_is_final_fallback(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    write_jsonl(metadata, [{"image_path": "screenshots/frame.png", "run_id": "RUN_A"}])
    trace = tmp_path / "wing_runs/RUN_A/timings.jsonl"
    write_jsonl(trace, [{"run_id": "RUN_A", "phase": "RECOVERY", "action": "RECONCILE", "result": "STABLE"}])
    output = tmp_path / "out.jsonl"
    map_file(metadata, tmp_path / "wing_runs", trace, output)
    assert json.loads(output.read_text())["event"]["result"] == "STABLE"


def test_existing_metadata_is_preserved(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    write_jsonl(metadata, [{"image_path": "screenshots/ordinary.png", "run_id": "UNKNOWN", "custom": "keep"}])
    output = tmp_path / "out.jsonl"
    map_file(metadata, tmp_path / "wing_runs", None, output)
    row = json.loads(output.read_text())
    assert row["custom"] == "keep"
    assert "event" not in row


def test_legend_battle3_pass_prefers_matching_weekly_trace_event(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    write_jsonl(metadata, [{
        "image_path": "screenshots/legend_battle3_pass.png", "run_id": "RUN_A"
    }])
    trace = tmp_path / "wing_runs/RUN_A/weekly_trace.jsonl"
    write_jsonl(trace, [
        {"run_id": "RUN_A", "phase": "RUN_FINAL", "action_result": "FINAL FAIL"},
        {
            "run_id": "RUN_A", "phase": "AUDITION_BATTLE",
            "decision": "AUDITION THE LEGEND",
            "action_result": "PASS battle AUDITION",
            "evidence": ["screenshots/legend_battle3_pass.png"],
        },
    ])
    output = tmp_path / "out.jsonl"
    map_file(metadata, tmp_path / "wing_runs", trace, output)
    event = json.loads(output.read_text())["event"]
    assert event["result"] == "PASS battle AUDITION"
    assert event["source"] == "filename_semantic_trace_match"


def test_legend_battle_failure_prefers_failure_event(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    write_jsonl(metadata, [{
        "image_path": "screenshots/legend_battle5_fail.png", "run_id": "RUN_A"
    }])
    trace = tmp_path / "wing_runs/RUN_A/weekly_trace.jsonl"
    write_jsonl(trace, [
        {"run_id": "RUN_A", "decision": "AUDITION THE LEGEND", "action_result": "PASS"},
        {
            "run_id": "RUN_A", "phase": "AUDITION_BATTLE",
            "decision": "AUDITION THE LEGEND", "action_result": "FAIL battle AUDITION",
            "evidence": "screenshots/legend_battle5_fail.png",
        },
    ])
    output = tmp_path / "out.jsonl"
    map_file(metadata, tmp_path / "wing_runs", trace, output)
    event = json.loads(output.read_text())["event"]
    assert event["result"] == "FAIL battle AUDITION"
    assert event["source"] == "filename_semantic_trace_match"


def test_no_semantic_trace_match_keeps_run_fallback(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    write_jsonl(metadata, [{
        "image_path": "screenshots/ordinary_frame.png", "run_id": "RUN_A"
    }])
    trace = tmp_path / "wing_runs/RUN_A/weekly_trace.jsonl"
    write_jsonl(trace, [{
        "run_id": "RUN_A", "phase": "RUN_FINAL", "action": "CLOSE", "result": "FINAL"
    }])
    output = tmp_path / "out.jsonl"
    map_file(metadata, tmp_path / "wing_runs", trace, output)
    event = json.loads(output.read_text())["event"]
    assert event["result"] == "FINAL"
    assert event["source"] == str(trace.resolve())
