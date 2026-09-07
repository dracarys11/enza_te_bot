#!/usr/bin/env python3
"""Retrieve historically similar Enza evidence for a screenshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Sequence

try:
    from tools.build_vision_index import (
        CudaVisionEmbedder,
        FAISS_FILE,
        INDEX_DIRECTORY,
        METADATA_FILE,
        STATE_FILE,
        l2_normalize,
        load_metadata,
        resolve_data_root,
    )
except ModuleNotFoundError as error:
    if error.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools.build_vision_index import (
        CudaVisionEmbedder,
        FAISS_FILE,
        INDEX_DIRECTORY,
        METADATA_FILE,
        STATE_FILE,
        l2_normalize,
        load_metadata,
        resolve_data_root,
    )


SIMILARITY_EPSILON = 1e-4
ENRICHED_METADATA_FILE = "metadata_enriched.jsonl"
EVENT_FIELDS = ("action", "phase", "state", "result", "source")
EVIDENCE_FIELDS = ("trajectory_ref", "observation_ref", "failure_type")


def _load_faiss() -> Any:
    try:
        import faiss
    except ImportError as error:
        raise RuntimeError("FAISS is required to query the evidence index") from error
    return faiss


def _load_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"index state is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid index state JSON: {error}") from error
    if not isinstance(value, dict) or not isinstance(value.get("model_id"), str):
        raise ValueError("index state must contain a string model_id")
    return value


def load_evidence_index(root: Path, *, faiss_module: Any | None = None) -> tuple[Any, dict[int, dict[str, Any]], dict[str, Any]]:
    """Load and validate the aligned FAISS, metadata, and state files."""
    output = root / INDEX_DIRECTORY
    faiss_path = output / FAISS_FILE
    metadata_path = output / METADATA_FILE
    if not faiss_path.is_file():
        raise FileNotFoundError(f"FAISS index is missing: {faiss_path}")
    rows = load_metadata(metadata_path)
    if not rows:
        raise RuntimeError(f"index metadata is missing or empty: {metadata_path}")
    state = _load_state(output / STATE_FILE)
    if state.get("normalization") != "l2_float32":
        raise RuntimeError("index normalization is unverified; rebuild the index")

    faiss = faiss_module or _load_faiss()
    index = faiss.read_index(str(faiss_path))
    if int(index.ntotal) != len(rows):
        raise RuntimeError("FAISS index and metadata row counts differ; rebuild the index")
    expected_dimension = state.get("embedding_dimension")
    if expected_dimension is not None and int(index.d) != int(expected_dimension):
        raise RuntimeError("FAISS index dimension differs from index state; rebuild the index")
    try:
        stored_vectors = index.reconstruct_n(0, int(index.ntotal))
    except (AttributeError, RuntimeError) as error:
        raise RuntimeError("FAISS index does not expose vectors for normalization validation") from error
    import numpy as np
    stored_norms = np.linalg.norm(np.asarray(stored_vectors, dtype="float32"), axis=1)
    if not np.isfinite(stored_norms).all() or not np.allclose(stored_norms, 1.0, atol=SIMILARITY_EPSILON):
        raise RuntimeError("stored image embeddings are not L2 normalized; rebuild the index")

    rows_by_vector: dict[int, dict[str, Any]] = {}
    for offset, row in enumerate(rows):
        vector_id = row.get("vector_id", offset)
        if not isinstance(vector_id, int) or vector_id < 0 or vector_id >= int(index.ntotal):
            raise RuntimeError(f"invalid metadata vector_id: {vector_id!r}")
        if vector_id in rows_by_vector:
            raise RuntimeError(f"duplicate metadata vector_id: {vector_id}")
        rows_by_vector[vector_id] = row
    return index, rows_by_vector, state


def _optional_reference(row: dict[str, Any], field: str, related_field: str) -> Any:
    if field in row:
        return row[field]
    related = row.get(related_field)
    if isinstance(related, list) and len(related) == 1:
        return related[0]
    return related or None


def resolve_evidence_contract(metadata: dict[str, Any]) -> dict[str, Any]:
    """Resolve enriched metadata into the event/evidence/provenance contract.

    Nested ``event`` values are authoritative.  Legacy top-level fields remain
    valid fallbacks so older metadata can be queried without migration.
    """
    nested_event = metadata.get("event")
    if not isinstance(nested_event, dict):
        nested_event = {}

    event = {
        field: nested_event[field] if field in nested_event else metadata.get(field)
        for field in EVENT_FIELDS
    }
    evidence = {field: metadata.get(field) for field in EVIDENCE_FIELDS}

    conflicts: list[dict[str, Any]] = []
    for field in EVENT_FIELDS:
        if field in nested_event and field in metadata and nested_event[field] != metadata[field]:
            conflicts.append({
                "field": field,
                "legacy": metadata[field],
                "event": nested_event[field],
            })

    return {
        "event": event,
        "evidence": evidence,
        "provenance": {"conflicts": conflicts},
    }


def _event_value(row: dict[str, Any], field: str) -> Any:
    """Return an event field when present, otherwise its legacy top-level value."""
    return resolve_evidence_contract(row)["event"][field]


def _evidence_package(row: dict[str, Any], similarity: float) -> dict[str, Any]:
    return {
        "image_path": row.get("image_path", row.get("path")),
        "similarity": similarity,
        "run_id": row.get("run_id", row.get("source_run")),
        "timestamp": row.get("timestamp"),
        "trajectory": _optional_reference(row, "trajectory", "related_trajectories"),
        "failure": _optional_reference(row, "failure", "related_failures"),
        "observation": _optional_reference(row, "observation", "related_observations"),
        "phase": _event_value(row, "phase"),
        "state": _event_value(row, "state"),
    }


def _load_enriched_metadata(root: Path, base_rows: dict[int, dict[str, Any]]) -> dict[int, dict[str, Any]] | None:
    """Load optional enrichment without changing the source metadata/index."""

    path = root / INDEX_DIRECTORY / ENRICHED_METADATA_FILE
    if not path.is_file():
        return None
    rows = load_metadata(path)
    enriched: dict[int, dict[str, Any]] = {}
    for offset, row in enumerate(rows):
        vector_id = row.get("vector_id", offset)
        if not isinstance(vector_id, int) or vector_id not in base_rows:
            raise RuntimeError(f"invalid enriched metadata vector_id: {vector_id!r}")
        if vector_id in enriched:
            raise RuntimeError(f"duplicate enriched metadata vector_id: {vector_id}")
        enriched[vector_id] = row
    return enriched


def _evidence_v2(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": _event_value(row, "state"),
        "phase": _event_value(row, "phase"),
        "action": _event_value(row, "action"),
        "result": _event_value(row, "result"),
        "failure_type": row.get("failure_type"),
        "trajectory_ref": row.get("trajectory_ref"),
        "observation_ref": row.get("observation_ref"),
    }


def query_evidence(
    root: Path,
    image_path: Path,
    *,
    top_k: int,
    device: int = 0,
    faiss_module: Any | None = None,
    embedder_factory: Callable[..., Any] = CudaVisionEmbedder,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top-k must be positive")
    query_image = image_path.expanduser().resolve()
    if not query_image.is_file():
        raise FileNotFoundError(f"query image is missing: {query_image}")

    index, rows_by_vector, state = load_evidence_index(root, faiss_module=faiss_module)
    enriched_by_vector = _load_enriched_metadata(root, rows_by_vector)
    embedder = embedder_factory(str(state["model_id"]), device=device)
    vector = l2_normalize(embedder.embed_images([query_image], batch_size=1))
    if getattr(vector, "ndim", None) != 2 or vector.shape[0] != 1 or vector.shape[1] != int(index.d):
        raise RuntimeError("query embedding shape does not match the FAISS index")

    scores, identifiers = index.search(vector, min(top_k, int(index.ntotal)))
    results: list[dict[str, Any]] = []
    for score, vector_id in zip(scores[0], identifiers[0]):
        identifier = int(vector_id)
        if identifier < 0:
            continue
        base_row = rows_by_vector.get(identifier)
        if base_row is None:
            raise RuntimeError(f"FAISS returned unknown vector_id: {identifier}")
        row = dict(base_row)
        if enriched_by_vector is not None:
            row.update(enriched_by_vector.get(identifier, {}))
        similarity = float(score)
        if similarity > 1.0 + SIMILARITY_EPSILON or similarity < -1.0 - SIMILARITY_EPSILON:
            raise RuntimeError(f"similarity outside cosine bounds: {similarity}")
        similarity = max(-1.0, min(1.0, similarity))
        package = _evidence_package(row, similarity)
        if enriched_by_vector is not None:
            contract = resolve_evidence_contract(row)
            # Keep the established v2 evidence shape for consumers that read
            # event fields from it, while exposing the migrated contract next
            # to it. Values still come from the authoritative nested event.
            package["evidence"] = _evidence_v2(row)
            package["event"] = {
                field: contract["event"][field]
                for field in ("action", "phase", "result", "state")
            }
            if contract["event"]["source"] is not None:
                package["event"]["source"] = contract["event"]["source"]
            package["provenance"] = contract["provenance"]
            if contract["provenance"]["conflicts"]:
                package["event_conflicts"] = contract["provenance"]["conflicts"]
        results.append(package)
    return {"query_image": str(query_image), "results": results}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Current screenshot to retrieve evidence for")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--data-root", help="Override ENZA_DATA_ROOT")
    parser.add_argument("--device", type=int, default=0, help="CUDA device index")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = query_evidence(
            resolve_data_root(args.data_root),
            Path(args.image),
            top_k=args.top_k,
            device=args.device,
        )
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
