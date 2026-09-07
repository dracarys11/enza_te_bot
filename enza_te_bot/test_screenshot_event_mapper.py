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
        "source": str(trace.resolve()),
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
