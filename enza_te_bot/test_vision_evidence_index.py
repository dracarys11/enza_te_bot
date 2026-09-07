from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image
import pytest

from tools.build_vision_index import (
    CudaVisionEmbedder,
    ImageRecord,
    build_index,
    build_image_records,
    discover_images,
    update_mode,
)


def save_image(path: Path, color: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), color).save(path)


def test_scan_covers_wing_runs_and_dataset_evidence(tmp_path):
    wing = tmp_path / "wing_runs/RUN_1/screenshots/20260907_120000_home.png"
    evidence = tmp_path / "dataset/evidence/choice/frame.png"
    ignored = tmp_path / "other/screenshots/ignored.png"
    save_image(wing, (1, 2, 3))
    save_image(evidence, (4, 5, 6))
    save_image(ignored, (7, 8, 9))

    assert [path.relative_to(tmp_path).as_posix() for path in discover_images(tmp_path)] == [
        "dataset/evidence/choice/frame.png",
        "wing_runs/RUN_1/screenshots/20260907_120000_home.png",
    ]


def test_metadata_links_trajectory_failure_and_timestamp(tmp_path):
    image = tmp_path / "wing_runs/RUN_1/screenshots/home.png"
    save_image(image, (1, 2, 3))
    trajectory = tmp_path / "trajectories/TRAJ_RUN_1.json"
    trajectory.parent.mkdir()
    trajectory.write_text(json.dumps({
        "run_id": "RUN_1",
        "evidence": {"path": "wing_runs/RUN_1/screenshots/home.png", "captured_at": "2026-09-07T12:00:00Z"},
    }))
    failure = tmp_path / "failures/failure_RUN_1.json"
    failure.parent.mkdir()
    failure.write_text(json.dumps({"run_id": "RUN_1", "screenshot": "home.png"}))

    record = build_image_records(tmp_path)[0]

    assert record.source_run == "RUN_1"
    assert record.timestamp == "2026-09-07T12:00:00Z"
    assert record.timestamp_source == "related_evidence"
    assert record.related_trajectories == ("trajectories/TRAJ_RUN_1.json",)
    assert record.related_failures == ("failures/failure_RUN_1.json",)


def record(path: str, digest: str) -> ImageRecord:
    return ImageRecord(path, digest, "RUN", "2026-09-07T00:00:00Z", "filename", (), ())


def test_incremental_update_appends_only_new_images():
    current = [record("a.png", "a"), record("b.png", "b")]
    existing = [{"path": "a.png", "sha256": "a", "vector_id": 0}]
    state = {"model_id": "model", "normalization": "l2_float32"}

    mode, pending = update_mode(current, existing, model_id="model", state=state, index_total=1)

    assert mode == "append"
    assert pending == [current[1]]


def test_changed_removed_or_inconsistent_data_rebuilds():
    state = {"model_id": "model", "normalization": "l2_float32"}
    existing = [{"path": "a.png", "sha256": "old", "vector_id": 0}]
    current = [record("a.png", "new")]
    assert update_mode(current, existing, model_id="model", state=state, index_total=1)[0] == "rebuild"
    assert update_mode([], existing, model_id="model", state=state, index_total=1)[0] == "rebuild"
    assert update_mode(current, existing, model_id="other", state=state, index_total=1)[0] == "rebuild"
    assert update_mode(current, existing, model_id="model", state=state, index_total=2)[0] == "rebuild"
    assert update_mode(current, existing, model_id="model", state={"model_id": "model"}, index_total=1)[0] == "rebuild"


def test_related_evidence_change_refreshes_metadata_without_reembedding():
    current = [record("a.png", "same")]
    existing = [{
        "path": "a.png",
        "sha256": "same",
        "source_run": "RUN",
        "timestamp": "2026-09-07T00:00:00Z",
        "timestamp_source": "filename",
        "related_trajectories": ["new-trajectory.json"],
        "related_failures": [],
        "vector_id": 0,
    }]

    state = {"model_id": "model", "normalization": "l2_float32"}
    mode, pending = update_mode(current, existing, model_id="model", state=state, index_total=1)

    assert mode == "metadata"
    assert pending == []


def test_embedding_fails_closed_without_cuda():
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    dependencies = (object(), torch, object(), (object(), object()))

    with patch("tools.build_vision_index._load_ml_dependencies", return_value=dependencies):
        with pytest.raises(RuntimeError, match="CUDA is required"):
            CudaVisionEmbedder("model")


def test_build_writes_aligned_metadata_index_and_incremental_noop(tmp_path):
    save_image(tmp_path / "wing_runs/RUN/screenshots/a.png", (1, 2, 3))

    class FakeIndex:
        def __init__(self, dimension):
            self.d = dimension
            self.ntotal = 0

        def add(self, vectors):
            self.ntotal += len(vectors)

    class FakeFaiss:
        def __init__(self):
            self.index = None

        def IndexFlatIP(self, dimension):
            return FakeIndex(dimension)

        def write_index(self, index, path):
            self.index = index
            Path(path).write_bytes(b"fake-faiss")

        def read_index(self, path):
            assert Path(path).read_bytes() == b"fake-faiss"
            return self.index

    class FakeEmbedder:
        gpu_name = "RTX 5080 TEST DOUBLE"

        def __init__(self, model_id, *, device):
            assert (model_id, device) == ("model", 0)

        def embed_images(self, paths, *, batch_size):
            assert batch_size == 8
            return np.ones((len(paths), 4), dtype="float32")

    faiss = FakeFaiss()
    dependencies = (faiss, object(), object(), (object(), object()))
    with patch("tools.build_vision_index._load_ml_dependencies", return_value=dependencies), \
         patch("tools.build_vision_index.CudaVisionEmbedder", FakeEmbedder):
        first = build_index(tmp_path, model_id="model", batch_size=8, device=0)
        second = build_index(tmp_path, model_id="model", batch_size=8, device=0)

    metadata = [json.loads(line) for line in (tmp_path / "index/metadata.jsonl").read_text().splitlines()]
    assert first["mode"] == "rebuild"
    assert first["embedding_dimension"] == 4
    assert first["gpu"] == "RTX 5080 TEST DOUBLE"
    assert metadata[0]["vector_id"] == 0
    assert metadata[0]["path"] == "wing_runs/RUN/screenshots/a.png"
    assert second["mode"] == "noop"
