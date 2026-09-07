import json
from pathlib import Path

import numpy as np
import pytest

from tools.query_evidence import query_evidence


class FakeIndex:
    d = 3
    ntotal = 2

    def reconstruct_n(self, start, count):
        assert (start, count) == (0, self.ntotal)
        return np.eye(3, dtype="float32")[:2]

    def search(self, vector, top_k):
        assert vector.shape == (1, 3)
        assert np.linalg.norm(vector[0]) == pytest.approx(1.0, abs=1e-6)
        return np.array([[0.88]], dtype="float32"), np.array([[1]], dtype="int64")


class FakeFaiss:
    def read_index(self, path):
        return FakeIndex()


class FakeEmbedder:
    def __init__(self, model_id, *, device):
        assert model_id == "local-siglip"
        assert device == 0

    def embed_images(self, paths, *, batch_size):
        assert len(paths) == 1
        assert batch_size == 1
        return np.array([[3.0, 4.0, 0.0]], dtype="float32")


def write_fixture(root: Path, *, event: dict | None = None) -> Path:
    output = root / "index"
    output.mkdir()
    (output / "image_embeddings.faiss").write_bytes(b"fake")
    rows = [
        {"vector_id": 0, "path": "screenshots/a.png", "source_run": "RUN_A", "timestamp": "2026-09-07T01:00:00Z"},
        {"vector_id": 1, "path": "screenshots/b.png", "source_run": "RUN_B", "timestamp": "2026-09-07T02:00:00Z"},
    ]
    (output / "metadata.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    enriched_row = {
            **rows[1],
            "state": {"page": "SCHEDULE"},
            "phase": "S1W8",
            "action": "VOCAL",
            "result": "COMMITTED",
            "failure_type": None,
            "trajectory_ref": "trajectories/run_b.json",
            "observation_ref": "observations/OBS_B.json",
        }
    if event is not None:
        enriched_row["event"] = event
    (output / "metadata_enriched.jsonl").write_text(
        json.dumps(enriched_row) + "\n",
        encoding="utf-8",
    )
    (output / "index_state.json").write_text(json.dumps({
        "model_id": "local-siglip",
        "embedding_dimension": 3,
        "image_count": 2,
        "normalization": "l2_float32",
    }), encoding="utf-8")
    query = root / "query.png"
    query.write_bytes(b"image")
    return query


def test_query_merges_enriched_metadata_by_vector_id(tmp_path):
    query = write_fixture(tmp_path)
    result = query_evidence(
        tmp_path,
        query,
        top_k=1,
        faiss_module=FakeFaiss(),
        embedder_factory=FakeEmbedder,
    )

    item = result["results"][0]
    assert item["image_path"] == "screenshots/b.png"
    assert item["run_id"] == "RUN_B"
    assert item["timestamp"] == "2026-09-07T02:00:00Z"
    assert item["evidence"] == {
        "state": {"page": "SCHEDULE"},
        "phase": "S1W8",
        "action": "VOCAL",
        "result": "COMMITTED",
        "failure_type": None,
        "trajectory_ref": "trajectories/run_b.json",
        "observation_ref": "observations/OBS_B.json",
    }
    assert -1.0 <= item["similarity"] <= 1.0


def test_nested_event_result_overrides_legacy_result(tmp_path):
    query = write_fixture(tmp_path, event={
        "action": "AUDITION THE LEGEND",
        "phase": "BATTLE",
        "result": "オーディション合格 (PASS)",
        "source": "filename_semantic_trace_match",
    })
    result = query_evidence(
        tmp_path,
        query,
        top_k=1,
        faiss_module=FakeFaiss(),
        embedder_factory=FakeEmbedder,
    )

    item = result["results"][0]
    assert item["event"] == {
        "action": "AUDITION THE LEGEND",
        "phase": "BATTLE",
        "result": "オーディション合格 (PASS)",
        "state": {"page": "SCHEDULE"},
        "source": "filename_semantic_trace_match",
    }
    assert item["evidence"]["result"] == "オーディション合格 (PASS)"
    assert {conflict["field"] for conflict in item["event_conflicts"]} == {
        "action", "phase", "result"
    }


def test_legacy_fields_fallback_into_migrated_event_output(tmp_path):
    query = write_fixture(tmp_path)
    item = query_evidence(
        tmp_path,
        query,
        top_k=1,
        faiss_module=FakeFaiss(),
        embedder_factory=FakeEmbedder,
    )["results"][0]

    assert item["event"] == {
        "action": "VOCAL",
        "phase": "S1W8",
        "result": "COMMITTED",
        "state": {"page": "SCHEDULE"},
    }
    assert "event_conflicts" not in item


def test_query_remains_backward_compatible_without_enriched_metadata(tmp_path):
    query = write_fixture(tmp_path)
    (tmp_path / "index" / "metadata_enriched.jsonl").unlink()
    result = query_evidence(
        tmp_path,
        query,
        top_k=1,
        faiss_module=FakeFaiss(),
        embedder_factory=FakeEmbedder,
    )

    assert "evidence" not in result["results"][0]
