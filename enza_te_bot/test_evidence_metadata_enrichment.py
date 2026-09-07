import json
from pathlib import Path

from tools.enrich_evidence_metadata import enrich_file


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_enrichment_matches_image_run_and_timestamp(tmp_path):
    metadata = tmp_path / "index" / "metadata.jsonl"
    metadata.parent.mkdir()
    metadata.write_text(json.dumps({
        "image_path": "wing_runs/RUN_A/screenshots/frame.png",
        "run_id": "RUN_A",
        "timestamp": "2026-09-07T01:00:02Z",
        "similarity": 0.8,
    }) + "\n", encoding="utf-8")
    write_json(tmp_path / "trajectories" / "trajectory.json", {
        "run_id": "RUN_A",
        "steps": [{
            "image_path": "wing_runs/RUN_A/screenshots/frame.png",
            "timestamp": "2026-09-07T01:00:00Z",
            "phase": "SCHEDULE",
            "action": "VOCAL",
            "result": "COMMITTED",
        }],
    })
    write_json(tmp_path / "observations" / "OBS_001.json", {
        "run_id": "RUN_A",
        "screenshot": "wing_runs/RUN_A/screenshots/frame.png",
        "captured_at": "2026-09-07T01:00:01Z",
        "state": {"page": "SCHEDULE", "trouble_rate": 0},
        "phase": "SCHEDULE",
    })
    write_json(tmp_path / "failures" / "failure.json", {
        "run_id": "RUN_A",
        "image_path": "wing_runs/RUN_A/screenshots/frame.png",
        "timestamp": "2026-09-07T01:00:03Z",
        "failure_type": "CAPTURE_TIMEOUT",
    })

    output = tmp_path / "index" / "metadata_enriched.jsonl"
    assert enrich_file(metadata, tmp_path / "trajectories", tmp_path / "failures", tmp_path / "observations", output) == 1
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["state"] == {"page": "SCHEDULE", "trouble_rate": 0}
    assert row["phase"] == "SCHEDULE"
    assert row["action"] == "VOCAL"
    assert row["result"] == "COMMITTED"
    assert row["failure_type"] == "CAPTURE_TIMEOUT"
    assert row["trajectory_ref"].endswith("trajectories/trajectory.json")
    assert row["observation_ref"].endswith("observations/OBS_001.json")


def test_unmatched_metadata_is_preserved_with_null_enrichment(tmp_path):
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text(json.dumps({
        "image_path": "unrelated/other.png",
        "run_id": "RUN_UNKNOWN",
        "timestamp": "2026-09-07T04:00:00Z",
    }) + "\n", encoding="utf-8")
    write_json(tmp_path / "trajectories" / "trajectory.json", {
        "run_id": "RUN_A",
        "image_path": "frame.png",
        "timestamp": "2026-09-07T01:00:00Z",
        "action": "REST",
    })
    output = tmp_path / "metadata_enriched.jsonl"
    enrich_file(metadata, tmp_path / "trajectories", tmp_path / "failures", tmp_path / "observations", output)
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["image_path"] == "unrelated/other.png"
    assert all(row[key] is None for key in (
        "state", "phase", "action", "result", "failure_type", "trajectory_ref", "observation_ref"
    ))


def test_image_path_match_survives_timestamp_gap(tmp_path):
    metadata = tmp_path / "metadata.jsonl"
    metadata.write_text(json.dumps({
        "path": "screenshots/frame.png",
        "source_run": "RUN_A",
        "timestamp": "2026-09-07T04:00:00Z",
    }) + "\n", encoding="utf-8")
    write_json(tmp_path / "failures" / "failure.json", {
        "run_id": "RUN_A",
        "screenshot": "/different/prefix/screenshots/frame.png",
        "timestamp": "2026-09-07T01:00:00Z",
        "classification": "ENVIRONMENT_TOOL_FAILURE",
    })
    output = tmp_path / "metadata_enriched.jsonl"
    enrich_file(metadata, tmp_path / "trajectories", tmp_path / "failures", tmp_path / "observations", output)
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["failure_type"] == "ENVIRONMENT_TOOL_FAILURE"
