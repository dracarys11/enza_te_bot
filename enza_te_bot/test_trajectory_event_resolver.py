import json
from pathlib import Path

from tools.trajectory_evidence_resolver import resolve_file


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")


def write_metadata(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_exact_timestamp_resolves_closest_event_not_run_final(tmp_path):
    metadata = tmp_path / "index/metadata_enriched.jsonl"
    write_metadata(metadata, {
        "image_path": "screenshots/w6.png",
        "run_id": "RUN_A",
        "timestamp": "2026-09-07T01:00:00Z",
        "trajectory_ref": "trajectories/run_a.json",
    })
    write_json(tmp_path / "trajectories/run_a.json", {
        "run_id": "RUN_A", "result": "FINAL_RUN_RESULT",
    })
    write_jsonl(tmp_path / "wing_runs/RUN_A/weekly_trace.jsonl", [
        {"run_id": "RUN_A", "timestamp": "2026-09-07T01:00:00Z", "phase": "S1W6", "action": "VOCAL", "state": "SCHEDULE", "result": "COMMITTED"},
        {"run_id": "RUN_A", "timestamp": "2026-09-07T02:00:00Z", "phase": "FINAL", "action": "REST", "state": "HOME", "result": "FINAL_RUN_RESULT"},
    ])
    output = tmp_path / "out.jsonl"
    resolve_file(
        metadata, tmp_path / "trajectories", tmp_path / "wing_runs", output,
        weekly_trace=tmp_path / "wing_runs/RUN_A/weekly_trace.jsonl",
    )
    row = json.loads(output.read_text())
    assert row["trajectory_ref"].endswith("trajectories/run_a.json")
    assert row["event"] == {
        "timestamp": "2026-09-07T01:00:00Z",
        "phase": "S1W6",
        "action": "VOCAL",
        "state": "SCHEDULE",
        "result": "COMMITTED",
    }


def test_timestamp_proximity_selects_nearest_timing_event(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    write_metadata(metadata, {
        "image_path": "unknown.png",
        "run_id": "UNKNOWN",
        "timestamp": "2026-09-07T03:00:04Z",
    })
    timings = tmp_path / "timings.jsonl"
    write_jsonl(timings, [
        {"timestamp": "2026-09-07T03:00:00Z", "phase": "NEAR", "action": "VOCAL", "result": "A"},
        {"timestamp": "2026-09-07T03:01:00Z", "phase": "FAR", "action": "REST", "result": "B"},
    ])
    output = tmp_path / "out.jsonl"
    resolve_file(metadata, tmp_path / "trajectories", tmp_path / "wing_runs", output, timings=timings)
    row = json.loads(output.read_text())
    assert row["event"]["phase"] == "NEAR"


def test_same_run_is_final_fallback_when_timestamp_is_missing(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    write_metadata(metadata, {"image_path": "missing.png", "run_id": "RUN_A"})
    timings = tmp_path / "timings.jsonl"
    write_jsonl(timings, [{"run_id": "RUN_A", "phase": "RECOVERY", "action": "RECONCILE", "result": "STABLE"}])
    output = tmp_path / "out.jsonl"
    resolve_file(metadata, tmp_path / "trajectories", tmp_path / "wing_runs", output, timings=timings)
    row = json.loads(output.read_text())
    assert row["event"]["action"] == "RECONCILE"
