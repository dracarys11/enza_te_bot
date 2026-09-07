import hashlib
import json

from tools.build_vlm_annotation_dataset import build_dataset


FORBIDDEN = {"authority_type", "planner_decision", "execution_permission", "action_allowed", "risk_gate", "should_click", "next_action"}


def test_generated_jsonl_schema_valid(tmp_path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"image")
    output = tmp_path / "out"
    result = build_dataset(tmp_path, output, tmp_path / "benchmark_cases")
    assert result["annotations_created"] == 0  # no allowed corpus roots in the isolated fixture
    assert (output / "observations.jsonl").read_text() == ""


def test_annotation_record_contract_for_declared_image(tmp_path):
    root = tmp_path
    image = root / "enza_memory/wing_runs/RUN/screenshots/frame.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    output = root / "out"
    build_dataset(root, output, root / "benchmark_cases")
    record = json.loads((output / "observations.jsonl").read_text())
    assert set(record) == {"image", "sha256", "observation", "confidence", "vlm_status", "metadata"}
    assert record["observation"]["state"] == "UNKNOWN"
    assert record["vlm_status"] == "UNKNOWN"
    assert record["metadata"]["run_id"] == "RUN"


def test_forbidden_authority_fields_absent(tmp_path):
    image = tmp_path / "enza_memory/wing_runs/RUN/frame.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    output = tmp_path / "out"
    build_dataset(tmp_path, output, tmp_path / "benchmark_cases")
    text = (output / "observations.jsonl").read_text()
    assert not FORBIDDEN.intersection(json.loads(text))
    assert not any(field in text for field in FORBIDDEN)


def test_unknown_and_visible_control_do_not_grant_permission(tmp_path):
    image = tmp_path / "enza_memory/migration/python_click_migration/frame.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    output = tmp_path / "out"
    build_dataset(tmp_path, output, tmp_path / "benchmark_cases")
    record = json.loads((output / "observations.jsonl").read_text())
    assert record["observation"]["state"] == "UNKNOWN"
    assert record["observation"]["visible_controls"] == []
    assert "action_allowed" not in record


def test_sha256_matches_image(tmp_path):
    image = tmp_path / "enza_memory/wing_runs/RUN/frame.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    output = tmp_path / "out"
    build_dataset(tmp_path, output, tmp_path / "benchmark_cases")
    record = json.loads((output / "observations.jsonl").read_text())
    assert record["sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()


def test_existing_trajectory_and_failure_metadata_is_attached(tmp_path):
    root = tmp_path
    image = root / "enza_memory/wing_runs/RUN/screenshots/frame.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"image")
    trajectory = root / "enza_memory/trajectories/trajectory.json"
    trajectory.parent.mkdir(parents=True)
    trajectory.write_text(json.dumps({"evidence_references": [{"path": "enza_memory/wing_runs/RUN/screenshots/frame.png"}]}))
    failure = root / "enza_memory/failures/failure.json"
    failure.parent.mkdir(parents=True)
    failure.write_text(json.dumps({
        "failure_category": "OBSERVATION_UNAVAILABLE",
        "evidence": "enza_memory/wing_runs/RUN/screenshots/frame.png",
    }))
    output = root / "out"
    build_dataset(root, output, root / "benchmark_cases")
    record = json.loads((output / "observations.jsonl").read_text())
    assert record["metadata"]["trajectory"] == "enza_memory/trajectories/trajectory.json"
    assert record["metadata"]["failure"] == "enza_memory/failures/failure.json"
    assert record["metadata"]["failure_category"] == "OBSERVATION_UNAVAILABLE"
