import json
from pathlib import Path

from tools.trajectory_evidence_resolver import resolve_file


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_exact_run_id_has_priority_over_filename_and_timestamp(tmp_path):
    metadata = tmp_path / "index/metadata_enriched.jsonl"
    metadata.parent.mkdir()
    metadata.write_text(json.dumps({
        "image_path": "screenshots/shared.png",
        "run_id": "RUN_B",
        "timestamp": "2026-09-07T04:00:00Z",
    }) + "\n", encoding="utf-8")
    write_json(tmp_path / "trajectories/a.json", {
        "run_id": "RUN_A", "image_path": "screenshots/shared.png",
        "timestamp": "2026-09-07T04:00:01Z", "action": "REST",
    })
    write_json(tmp_path / "trajectories/b.json", {
        "run_id": "RUN_B", "image_path": "other.png",
        "timestamp": "2026-09-07T01:00:00Z", "action": "VOCAL",
        "result": "COMMITTED", "state": "HOME", "phase": "S1W8",
    })
    output = tmp_path / "out.jsonl"
    resolve_file(metadata, tmp_path / "trajectories", tmp_path / "wing_runs", output)
    row = json.loads(output.read_text())
    assert row["action"] == "VOCAL"
    assert row["trajectory_ref"].endswith("trajectories/b.json")


def test_filename_reference_is_used_when_run_id_is_missing(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    metadata.write_text(json.dumps({"image_path": "current/frame.png"}) + "\n")
    write_json(tmp_path / "trajectories/trajectory.json", {
        "image_path": "/historical/current/frame.png",
        "timestamp": "2026-09-07T01:00:00Z", "action": "VOCAL",
    })
    output = tmp_path / "out.jsonl"
    resolve_file(metadata, tmp_path / "trajectories", tmp_path / "wing_runs", output)
    row = json.loads(output.read_text())
    assert row["action"] == "VOCAL"


def test_timestamp_proximity_is_used_as_fallback(tmp_path):
    metadata = tmp_path / "metadata_enriched.jsonl"
    metadata.write_text(json.dumps({
        "image_path": "missing.png", "run_id": "UNKNOWN",
        "timestamp": "2026-09-07T01:00:03Z",
    }) + "\n")
    write_json(tmp_path / "wing_runs/a/one.json", {
        "timestamp": "2026-09-07T01:00:00Z", "action": "NEAR",
    })
    write_json(tmp_path / "wing_runs/a/two.json", {
        "timestamp": "2026-09-07T02:00:00Z", "action": "FAR",
    })
    output = tmp_path / "out.jsonl"
    resolve_file(metadata, tmp_path / "trajectories", tmp_path / "wing_runs", output)
    row = json.loads(output.read_text())
    assert row["action"] == "NEAR"
