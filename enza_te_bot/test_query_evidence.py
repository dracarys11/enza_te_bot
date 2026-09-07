from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from tools.query_evidence import load_evidence_index, query_evidence


class FakeIndex:
    d = 3
    ntotal = 3

    def __init__(self, scores=None, identifiers=None):
        self.scores = np.array([scores or [0.9, 0.8, 0.7]], dtype="float32")
        self.identifiers = np.array([identifiers or [0, 1, 2]], dtype="int64")

    def search(self, vector, top_k):
        assert vector.shape == (1, self.d)
        return self.scores[:, :top_k], self.identifiers[:, :top_k]


class FakeFaiss:
    def __init__(self, index):
        self.index = index
        self.loaded_path = None

    def read_index(self, path):
        self.loaded_path = path
        return self.index


class FakeEmbedder:
    def __init__(self, model_id, *, device):
        assert model_id == "local-siglip"
        assert device == 0

    def embed_images(self, paths, *, batch_size):
        assert len(paths) == 1
        assert paths[0].name == "query.png"
        assert batch_size == 1
        return np.array([[1.0, 0.0, 0.0]], dtype="float32")


def write_index_files(root: Path, rows: list[dict]) -> None:
    output = root / "index"
    output.mkdir()
    (output / "image_embeddings.faiss").write_bytes(b"fake")
    (output / "metadata.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (output / "index_state.json").write_text(json.dumps({
        "model_id": "local-siglip",
        "embedding_dimension": 3,
        "image_count": len(rows),
    }), encoding="utf-8")


def rows() -> list[dict]:
    return [
        {
            "vector_id": 0,
            "path": "wing_runs/RUN_A/screenshots/a.png",
            "source_run": "RUN_A",
            "timestamp": "2026-09-07T01:00:00Z",
            "related_trajectories": ["trajectories/a.json"],
            "related_failures": ["failures/a.json"],
            "state": {"phase": "BATTLE", "auto_value": "OFF", "interactability": "ENABLED"},
        },
        {
            "vector_id": 1,
            "path": "wing_runs/RUN_B/screenshots/b.png",
            "source_run": "RUN_B",
            "timestamp": "2026-09-07T02:00:00Z",
        },
        {"vector_id": 2, "path": "dataset/evidence/result/c.png"},
    ]


def test_fake_faiss_index_loading_works(tmp_path):
    write_index_files(tmp_path, rows())
    faiss = FakeFaiss(FakeIndex())

    index, rows_by_vector, state = load_evidence_index(tmp_path, faiss_module=faiss)

    assert index is faiss.index
    assert faiss.loaded_path == str(tmp_path / "index/image_embeddings.faiss")
    assert rows_by_vector[1]["source_run"] == "RUN_B"
    assert state["model_id"] == "local-siglip"


def test_metadata_lookup_returns_evidence_package(tmp_path):
    write_index_files(tmp_path, rows())
    query = tmp_path / "query.png"
    query.write_bytes(b"image fixture")

    result = query_evidence(
        tmp_path, query, top_k=1,
        faiss_module=FakeFaiss(FakeIndex(scores=[0.91], identifiers=[0])),
        embedder_factory=FakeEmbedder,
    )

    assert result["results"] == [{
        "image_path": "wing_runs/RUN_A/screenshots/a.png",
        "similarity": pytest.approx(0.91),
        "run_id": "RUN_A",
        "timestamp": "2026-09-07T01:00:00Z",
        "trajectory": "trajectories/a.json",
        "failure": "failures/a.json",
        "state": {"phase": "BATTLE", "auto_value": "OFF", "interactability": "ENABLED"},
    }]


def test_missing_optional_fields_return_null(tmp_path):
    write_index_files(tmp_path, rows())
    query = tmp_path / "query.png"
    query.write_bytes(b"image fixture")

    result = query_evidence(
        tmp_path, query, top_k=1,
        faiss_module=FakeFaiss(FakeIndex(scores=[0.75], identifiers=[2])),
        embedder_factory=FakeEmbedder,
    )["results"][0]

    assert result["run_id"] is None
    assert result["timestamp"] is None
    assert result["trajectory"] is None
    assert result["failure"] is None
    assert result["state"] is None


def test_cuda_unavailable_fails_closed(tmp_path):
    write_index_files(tmp_path, rows())
    query = tmp_path / "query.png"
    query.write_bytes(b"image fixture")
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
    dependencies = (object(), torch, object(), (object(), object()))

    with patch("tools.build_vision_index._load_ml_dependencies", return_value=dependencies):
        with pytest.raises(RuntimeError, match="CUDA is required"):
            query_evidence(tmp_path, query, top_k=1, faiss_module=FakeFaiss(FakeIndex()))


def test_top_k_order_follows_faiss_similarity_order(tmp_path):
    write_index_files(tmp_path, rows())
    query = tmp_path / "query.png"
    query.write_bytes(b"image fixture")
    index = FakeIndex(scores=[0.99, 0.88, 0.1], identifiers=[2, 0, 1])

    result = query_evidence(
        tmp_path, query, top_k=2,
        faiss_module=FakeFaiss(index), embedder_factory=FakeEmbedder,
    )

    assert [item["image_path"] for item in result["results"]] == [
        "dataset/evidence/result/c.png",
        "wing_runs/RUN_A/screenshots/a.png",
    ]
    assert [item["similarity"] for item in result["results"]] == pytest.approx([0.99, 0.88])
