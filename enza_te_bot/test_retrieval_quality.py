from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from tools.build_vision_index import build_image_records, l2_normalize
from tools.query_evidence import query_evidence


class FakeIndex:
    d = 2
    ntotal = 2

    def __init__(self, score=1.0):
        self.score = score

    def reconstruct_n(self, start, count):
        assert (start, count) == (0, 2)
        return np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")

    def search(self, vector, top_k):
        assert np.linalg.norm(vector[0]) == pytest.approx(1.0)
        return (
            np.array([[self.score, 0.5]], dtype="float32")[:, :top_k],
            np.array([[0, 1]], dtype="int64")[:, :top_k],
        )


class FakeFaiss:
    def __init__(self, score=1.0):
        self.index = FakeIndex(score)

    def read_index(self, path):
        assert path.endswith("image_embeddings.faiss")
        return self.index


class UnnormalizedEmbedder:
    def __init__(self, model_id, *, device):
        assert (model_id, device) == ("siglip", 0)

    def embed_images(self, paths, *, batch_size):
        assert batch_size == 1
        return np.array([[3.0, 4.0]], dtype="float16")


def prepare(root: Path, rows=None) -> Path:
    rows = rows or [
        {"vector_id": 0, "path": "wing_runs/RUN/screenshots/a.png", "source_run": "RUN"},
        {"vector_id": 1, "path": "wing_runs/OTHER/screenshots/b.png"},
    ]
    output = root / "index"
    output.mkdir()
    (output / "image_embeddings.faiss").write_bytes(b"fake")
    (output / "metadata.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    (output / "index_state.json").write_text(json.dumps({
        "model_id": "siglip",
        "embedding_dimension": 2,
        "image_count": 2,
        "normalization": "l2_float32",
        "metric": "inner_product_cosine",
    }), encoding="utf-8")
    query = root / "query.png"
    query.write_bytes(b"fixture")
    return query


def test_l2_normalize_uses_float32_unit_rows():
    vectors = l2_normalize(np.array([[3.0, 4.0], [5.0, 12.0]], dtype="float16"))

    assert vectors.dtype == np.float32
    assert np.linalg.norm(vectors, axis=1) == pytest.approx([1.0, 1.0])


def test_query_result_schema_is_stable(tmp_path):
    query = prepare(tmp_path)

    item = query_evidence(
        tmp_path, query, top_k=1, faiss_module=FakeFaiss(),
        embedder_factory=UnnormalizedEmbedder,
    )["results"][0]

    assert set(item) == {
        "image_path", "similarity", "run_id", "timestamp", "trajectory",
        "failure", "observation", "phase", "state",
    }


def test_missing_metadata_is_returned_as_null(tmp_path):
    query = prepare(tmp_path)

    item = query_evidence(
        tmp_path, query, top_k=2, faiss_module=FakeFaiss(),
        embedder_factory=UnnormalizedEmbedder,
    )["results"][1]

    assert item["run_id"] is None
    assert item["trajectory"] is None
    assert item["failure"] is None
    assert item["observation"] is None
    assert item["state"] is None


def test_rounding_above_one_within_epsilon_is_clamped(tmp_path):
    query = prepare(tmp_path)

    item = query_evidence(
        tmp_path, query, top_k=1, faiss_module=FakeFaiss(1.00001),
        embedder_factory=UnnormalizedEmbedder,
    )["results"][0]

    assert item["similarity"] == 1.0


def test_similarity_above_cosine_tolerance_fails_closed(tmp_path):
    query = prepare(tmp_path)

    with pytest.raises(RuntimeError, match="outside cosine bounds"):
        query_evidence(
            tmp_path, query, top_k=1, faiss_module=FakeFaiss(1.01),
            embedder_factory=UnnormalizedEmbedder,
        )


def test_metadata_enrichment_uses_only_explicit_evidence(tmp_path):
    image = tmp_path / "wing_runs/RUN/screenshots/frame.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"fixture")
    for directory in ("observations", "trajectories", "failures"):
        (tmp_path / directory).mkdir()
    (tmp_path / "observations/OBS.json").write_text(json.dumps({
        "run_id": "RUN",
        "screenshot": "wing_runs/RUN/screenshots/frame.png",
        "page_state": {"label": "WING_HOME", "classification": "FACT"},
        "captured_at": "2026-09-07T01:02:03Z",
    }), encoding="utf-8")
    (tmp_path / "trajectories/TRAJ.json").write_text(json.dumps({
        "run_id": "RUN", "evidence": "frame.png",
    }), encoding="utf-8")
    (tmp_path / "failures/FAIL.json").write_text(json.dumps({
        "run_id": "RUN", "evidence": ["frame.png"],
    }), encoding="utf-8")

    record = build_image_records(tmp_path)[0]

    assert record.source_run == "RUN"
    assert record.related_observations == ("observations/OBS.json",)
    assert record.related_trajectories == ("trajectories/TRAJ.json",)
    assert record.related_failures == ("failures/FAIL.json",)
    assert record.phase == "WING_HOME"
    assert record.state == {"page_state": {"label": "WING_HOME", "classification": "FACT"}}
