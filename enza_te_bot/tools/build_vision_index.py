#!/usr/bin/env python3
"""Build and query a CUDA-backed WING screenshot embedding index."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence


IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
DEFAULT_MODEL = "google/siglip-base-patch16-224"
INDEX_DIRECTORY = "index"
METADATA_FILE = "metadata.jsonl"
FAISS_FILE = "image_embeddings.faiss"
STATE_FILE = "index_state.json"
TIMESTAMP_PATTERN = re.compile(r"(?<!\d)(20\d{6})[_-](\d{6})(?!\d)")
TIMESTAMP_KEYS = ("captured_at", "timestamp", "created_at", "at")


@dataclass(frozen=True)
class ImageRecord:
    path: str
    sha256: str
    source_run: str | None
    timestamp: str
    timestamp_source: str
    related_trajectories: tuple[str, ...]
    related_failures: tuple[str, ...]
    related_observations: tuple[str, ...] = ()
    phase: str | None = None
    state: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReferenceDocument:
    path: str
    kind: str | None
    text: str
    timestamps_by_image: dict[str, tuple[str, ...]]
    values: tuple[Any, ...]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_data_root(argument: str | None = None) -> Path:
    configured = argument or os.environ.get("ENZA_DATA_ROOT", "")
    if not configured.strip():
        raise ValueError("ENZA_DATA_ROOT is required (or pass --data-root)")
    root = Path(configured).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"ENZA_DATA_ROOT is not a directory: {root}")
    return root


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_image(path: Path) -> bool:
    return path.is_file() and not path.is_symlink() and path.suffix.lower() in IMAGE_SUFFIXES


def discover_images(root: Path) -> list[Path]:
    candidates: set[Path] = set()
    wing_runs = root / "wing_runs"
    if wing_runs.is_dir():
        for screenshots in wing_runs.glob("*/screenshots"):
            candidates.update(path for path in screenshots.rglob("*") if _is_image(path))
    evidence = root / "dataset/evidence"
    if evidence.is_dir():
        candidates.update(path for path in evidence.rglob("*") if _is_image(path))
    return sorted(candidates, key=lambda path: path.relative_to(root).as_posix())


def _document_kind(relative: Path) -> str | None:
    lowered = tuple(part.casefold() for part in relative.parts)
    name = relative.name.casefold()
    if "failures" in lowered or "failure" in name or "incident" in name:
        return "failure"
    if "observations" in lowered or "observation" in name or name.startswith("obs_"):
        return "observation"
    if "trajectories" in lowered or "trajectory" in name or name == "timings.jsonl":
        return "trajectory"
    return None


def _timestamp_in_mapping(value: dict[str, Any], inherited: str | None) -> str | None:
    for key in TIMESTAMP_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return inherited


def _collect_image_timestamps(
    value: Any,
    output: dict[str, set[str]],
    inherited_timestamp: str | None = None,
) -> None:
    if isinstance(value, dict):
        timestamp = _timestamp_in_mapping(value, inherited_timestamp)
        for child in value.values():
            _collect_image_timestamps(child, output, timestamp)
    elif isinstance(value, list):
        for child in value:
            _collect_image_timestamps(child, output, inherited_timestamp)
    elif isinstance(value, str) and Path(value).suffix.lower() in IMAGE_SUFFIXES:
        if inherited_timestamp:
            output.setdefault(Path(value).name, set()).add(inherited_timestamp)


def _parse_document(path: Path, root: Path) -> ReferenceDocument | None:
    relative = path.relative_to(root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    timestamps: dict[str, set[str]] = {}
    try:
        if path.suffix.casefold() == ".jsonl":
            values = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            values = [json.loads(text)]
    except (json.JSONDecodeError, ValueError):
        values = []
    for value in values:
        _collect_image_timestamps(value, timestamps)
    return ReferenceDocument(
        path=relative.as_posix(),
        kind=_document_kind(relative),
        text=text,
        timestamps_by_image={key: tuple(sorted(items)) for key, items in timestamps.items()},
        values=tuple(values),
    )


def discover_reference_documents(root: Path) -> list[ReferenceDocument]:
    documents: list[ReferenceDocument] = []
    for directory in ("wing_runs", "observations", "trajectories", "failures", "manifests"):
        base = root / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.suffix.casefold() in {".json", ".jsonl"}:
                document = _parse_document(path, root)
                if document is not None:
                    documents.append(document)
    return documents


def _source_run(relative: Path) -> str | None:
    parts = relative.parts
    if len(parts) >= 2 and parts[0] == "wing_runs":
        return parts[1]
    return None


def _is_primary_observation_image(value: dict[str, Any], relative: Path) -> bool:
    for key in ("screenshot", "preclick_screenshot", "postclick_screenshot"):
        candidate = value.get(key)
        if not isinstance(candidate, str):
            continue
        if candidate == relative.as_posix() or Path(candidate).name == relative.name:
            return True
    return False


def _filename_timestamp(name: str) -> str | None:
    match = TIMESTAMP_PATTERN.search(name)
    if not match:
        return None
    value = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    return value.isoformat(timespec="seconds")


def _related_documents(
    relative: Path,
    source_run: str | None,
    documents: Sequence[ReferenceDocument],
) -> tuple[
    tuple[str, ...], tuple[str, ...], tuple[str, ...], str | None,
    str | None, str | None, dict[str, Any] | None,
]:
    trajectories: set[str] = set()
    failures: set[str] = set()
    observations: set[str] = set()
    timestamps: set[str] = set()
    run_ids: set[str] = set()
    phases: set[str] = set()
    states: dict[str, dict[str, Any]] = {}
    relative_text = relative.as_posix()
    for document in documents:
        if relative_text not in document.text and relative.name not in document.text:
            continue
        if source_run and source_run not in document.text and source_run not in document.path:
            continue
        if document.kind == "trajectory":
            trajectories.add(document.path)
        elif document.kind == "failure":
            failures.add(document.path)
        elif document.kind == "observation":
            observations.add(document.path)
            for value in document.values:
                if not isinstance(value, dict):
                    continue
                run_id = value.get("run_id")
                if isinstance(run_id, str) and run_id:
                    run_ids.add(run_id)
                if not _is_primary_observation_image(value, relative):
                    continue
                state: dict[str, Any] = {}
                for key in ("page_state", "state", "room", "substate", "auto_value", "interactability"):
                    if key in value and value[key] is not None:
                        state[key] = value[key]
                if state:
                    states[json.dumps(state, ensure_ascii=False, sort_keys=True)] = state
                phase = value.get("phase")
                if not isinstance(phase, str):
                    page_state = value.get("page_state")
                    if isinstance(page_state, dict):
                        phase = page_state.get("label")
                    elif isinstance(value.get("room"), str):
                        phase = value["room"]
                if isinstance(phase, str) and phase:
                    phases.add(phase)
        timestamps.update(document.timestamps_by_image.get(relative.name, ()))
    return (
        tuple(sorted(trajectories)),
        tuple(sorted(failures)),
        tuple(sorted(observations)),
        min(timestamps) if timestamps else None,
        next(iter(run_ids)) if len(run_ids) == 1 else None,
        next(iter(phases)) if len(phases) == 1 else None,
        next(iter(states.values())) if len(states) == 1 else None,
    )


def build_image_records(root: Path) -> list[ImageRecord]:
    documents = discover_reference_documents(root)
    records: list[ImageRecord] = []
    for path in discover_images(root):
        relative = path.relative_to(root)
        source_run = _source_run(relative)
        trajectories, failures, observations, evidence_timestamp, related_run, phase, state = _related_documents(
            relative, source_run, documents
        )
        source_run = source_run or related_run
        filename_timestamp = _filename_timestamp(path.name)
        if evidence_timestamp:
            timestamp, timestamp_source = evidence_timestamp, "related_evidence"
        elif filename_timestamp:
            timestamp, timestamp_source = filename_timestamp, "filename"
        else:
            timestamp = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")
            timestamp_source = "file_mtime_utc"
        records.append(ImageRecord(
            path=relative.as_posix(),
            sha256=sha256_file(path),
            source_run=source_run,
            timestamp=timestamp,
            timestamp_source=timestamp_source,
            related_trajectories=trajectories,
            related_failures=failures,
            related_observations=observations,
            phase=phase,
            state=state,
        ))
    return records


def load_metadata(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as error:
                    raise ValueError(f"invalid metadata JSONL at line {line_number}: {error}") from error
    return rows


def update_mode(
    records: Sequence[ImageRecord],
    existing: Sequence[dict[str, Any]],
    *,
    model_id: str,
    state: dict[str, Any] | None,
    index_total: int | None,
) -> tuple[str, list[ImageRecord]]:
    if not existing:
        return "rebuild", list(records)
    if (
        not state
        or state.get("model_id") != model_id
        or state.get("normalization") != "l2_float32"
        or index_total != len(existing)
    ):
        return "rebuild", list(records)
    existing_by_path = {str(row.get("path")): row for row in existing}
    current_by_path = {record.path: record for record in records}
    if not set(existing_by_path).issubset(current_by_path):
        return "rebuild", list(records)
    for path, row in existing_by_path.items():
        if row.get("sha256") != current_by_path[path].sha256:
            return "rebuild", list(records)
    additions = [record for record in records if record.path not in existing_by_path]
    if additions:
        return "append", additions
    metadata_changed = any(
        row.get("source_run") != current_by_path[path].source_run
        or row.get("timestamp") != current_by_path[path].timestamp
        or row.get("timestamp_source") != current_by_path[path].timestamp_source
        or row.get("related_trajectories") != list(current_by_path[path].related_trajectories)
        or row.get("related_failures") != list(current_by_path[path].related_failures)
        or row.get("related_observations") != list(current_by_path[path].related_observations)
        or row.get("phase") != current_by_path[path].phase
        or row.get("state") != current_by_path[path].state
        for path, row in existing_by_path.items()
    )
    return ("metadata", []) if metadata_changed else ("noop", [])


def l2_normalize(vectors: Any) -> Any:
    """Return finite, non-zero row vectors normalized in float32."""
    import numpy as np

    array = np.asarray(vectors, dtype="float32")
    if array.ndim != 2:
        raise ValueError("embedding vectors must be a two-dimensional array")
    if not np.isfinite(array).all():
        raise ValueError("embedding vectors contain non-finite values")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(norms <= 1e-12):
        raise ValueError("embedding vectors contain a zero-length row")
    normalized = array / norms
    if not np.allclose(np.linalg.norm(normalized, axis=1), 1.0, atol=1e-5):
        raise RuntimeError("failed to L2-normalize embedding vectors")
    return normalized


def _load_ml_dependencies() -> tuple[Any, Any, Any, Any]:
    try:
        import faiss
        import torch
        from PIL import Image
        from transformers import AutoModel, AutoProcessor
    except ImportError as error:
        raise RuntimeError(
            "Vision-index dependencies are missing. Install a CUDA build of PyTorch, "
            "then install transformers, Pillow, and faiss-cpu."
        ) from error
    return faiss, torch, Image, (AutoModel, AutoProcessor)


class CudaVisionEmbedder:
    def __init__(self, model_id: str, *, device: int = 0):
        faiss, torch, image_module, transformers = _load_ml_dependencies()
        del faiss
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for embedding; CPU/MPS fallback is disabled")
        if device < 0 or device >= torch.cuda.device_count():
            raise ValueError(f"CUDA device {device} is unavailable")
        auto_model, auto_processor = transformers
        self.torch = torch
        self.image_module = image_module
        self.device = torch.device(f"cuda:{device}")
        self.model_id = model_id
        self.processor = auto_processor.from_pretrained(model_id)
        self.model = auto_model.from_pretrained(model_id, torch_dtype=torch.float16).to(self.device).eval()
        self.gpu_name = torch.cuda.get_device_name(device)

    def _normalize(self, features: Any) -> Any:
        features = features.float()
        return features / features.norm(p=2, dim=-1, keepdim=True).clamp_min(1e-12)

    def embed_images(self, paths: Sequence[Path], *, batch_size: int) -> Any:
        import numpy as np

        batches: list[Any] = []
        for offset in range(0, len(paths), batch_size):
            images = []
            for path in paths[offset:offset + batch_size]:
                with self.image_module.open(path) as image:
                    images.append(image.convert("RGB").copy())
            inputs = self.processor(images=images, return_tensors="pt")
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with self.torch.inference_mode(), self.torch.autocast(device_type="cuda", dtype=self.torch.float16):
                features = self.model.get_image_features(**inputs)
            batches.append(self._normalize(features).float().cpu().numpy())
        vectors = np.concatenate(batches, axis=0) if batches else np.empty((0, 0), dtype="float32")
        return l2_normalize(vectors) if len(vectors) else vectors

    def embed_text(self, text: str) -> Any:
        inputs = self.processor(text=[text], padding="max_length", return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.inference_mode(), self.torch.autocast(device_type="cuda", dtype=self.torch.float16):
            features = self.model.get_text_features(**inputs)
        return l2_normalize(self._normalize(features).cpu().numpy())


def _read_state(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_jsonl_atomic(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build_index(root: Path, *, model_id: str, batch_size: int, device: int) -> dict[str, Any]:
    if batch_size <= 0:
        raise ValueError("batch size must be positive")
    records = build_image_records(root)
    if not records:
        raise RuntimeError("no images found under wing_runs/*/screenshots or dataset/evidence")

    output = root / INDEX_DIRECTORY
    output.mkdir(parents=True, exist_ok=True)
    metadata_path = output / METADATA_FILE
    faiss_path = output / FAISS_FILE
    state_path = output / STATE_FILE
    existing = load_metadata(metadata_path)
    state = _read_state(state_path)

    faiss, _, _, _ = _load_ml_dependencies()
    index = None
    index_total = None
    if faiss_path.is_file():
        try:
            index = faiss.read_index(str(faiss_path))
            index_total = int(index.ntotal)
        except RuntimeError:
            index = None
    mode, pending = update_mode(records, existing, model_id=model_id, state=state, index_total=index_total)
    if mode == "noop":
        return {
            "mode": mode,
            "images": len(records),
            "embedding_dimension": state["embedding_dimension"],
            "gpu": state.get("gpu"),
            "index_size": faiss_path.stat().st_size,
        }

    if mode == "metadata":
        current_by_path = {record.path: record for record in records}
        refreshed = []
        for row in existing:
            updated = dict(row)
            updated.update(asdict(current_by_path[str(row["path"])]))
            refreshed.append(updated)
        _write_jsonl_atomic(metadata_path, refreshed)
        state = dict(state)
        state["updated_at"] = utc_now()
        state_temporary = state_path.with_suffix(state_path.suffix + ".tmp")
        state_temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(state_temporary, state_path)
        return {
            "mode": mode,
            "images": len(records),
            "embedding_dimension": state["embedding_dimension"],
            "gpu": state.get("gpu"),
            "index_size": faiss_path.stat().st_size,
        }

    embedder = CudaVisionEmbedder(model_id, device=device)
    if mode == "rebuild":
        existing = []
        pending = list(records)
        index = None
    vectors = l2_normalize(embedder.embed_images(
        [root / record.path for record in pending], batch_size=batch_size
    ))
    dimension = int(vectors.shape[1])
    if index is None:
        index = faiss.IndexFlatIP(dimension)
    elif index.d != dimension:
        mode = "rebuild"
        existing = []
        pending = list(records)
        vectors = l2_normalize(embedder.embed_images(
            [root / record.path for record in pending], batch_size=batch_size
        ))
        dimension = int(vectors.shape[1])
        index = faiss.IndexFlatIP(dimension)
    index.add(vectors)

    indexed_at = utc_now()
    current_by_path = {record.path: record for record in records}
    rows = []
    for existing_row in existing:
        refreshed = dict(existing_row)
        refreshed.update(asdict(current_by_path[str(existing_row["path"])]))
        rows.append(refreshed)
    next_id = len(rows)
    for record in pending:
        row = asdict(record)
        row.update({
            "vector_id": next_id,
            "model_id": model_id,
            "embedding_dimension": dimension,
            "indexed_at": indexed_at,
        })
        rows.append(row)
        next_id += 1

    index_temporary = faiss_path.with_suffix(faiss_path.suffix + ".tmp")
    faiss.write_index(index, str(index_temporary))
    os.replace(index_temporary, faiss_path)
    _write_jsonl_atomic(metadata_path, rows)
    state_payload = {
        "schema_version": 2,
        "model_id": model_id,
        "normalization": "l2_float32",
        "metric": "inner_product_cosine",
        "embedding_dimension": dimension,
        "image_count": len(rows),
        "gpu": embedder.gpu_name,
        "updated_at": indexed_at,
    }
    state_temporary = state_path.with_suffix(state_path.suffix + ".tmp")
    state_temporary.write_text(json.dumps(state_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(state_temporary, state_path)
    return {
        "mode": mode,
        "images": len(rows),
        "embedded_this_run": len(pending),
        "embedding_dimension": dimension,
        "gpu": embedder.gpu_name,
        "index_size": faiss_path.stat().st_size,
    }


def query_index(root: Path, query: str, *, top_k: int, device: int) -> list[dict[str, Any]]:
    if not query.strip():
        raise ValueError("query text must not be empty")
    output = root / INDEX_DIRECTORY
    rows = load_metadata(output / METADATA_FILE)
    state = _read_state(output / STATE_FILE)
    if not rows or not state:
        raise RuntimeError("index metadata is missing; run the build command first")
    faiss, _, _, _ = _load_ml_dependencies()
    index = faiss.read_index(str(output / FAISS_FILE))
    if index.ntotal != len(rows):
        raise RuntimeError("FAISS index and metadata row counts differ; rebuild the index")
    embedder = CudaVisionEmbedder(str(state["model_id"]), device=device)
    vector = embedder.embed_text(query)
    scores, identifiers = index.search(vector, min(max(1, top_k), len(rows)))
    results: list[dict[str, Any]] = []
    for score, vector_id in zip(scores[0], identifiers[0]):
        row = dict(rows[int(vector_id)])
        results.append({"score": float(score), **row})
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", help="Override ENZA_DATA_ROOT")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan = subparsers.add_parser("scan", help="Scan evidence without loading ML dependencies")
    scan.add_argument("--json", action="store_true", help="Print records as JSON")
    build = subparsers.add_parser("build", help="Build or incrementally update the FAISS index")
    build.add_argument("--model", default=DEFAULT_MODEL)
    build.add_argument("--batch-size", type=int, default=64)
    build.add_argument("--device", type=int, default=0)
    query = subparsers.add_parser("query", help="Query the index with text")
    query.add_argument("text")
    query.add_argument("--top-k", type=int, default=5)
    query.add_argument("--device", type=int, default=0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = resolve_data_root(args.data_root)
        if args.command == "scan":
            records = build_image_records(root)
            result: Any = [asdict(record) for record in records] if args.json else {
                "data_root": str(root),
                "images": len(records),
                "with_trajectory": sum(bool(record.related_trajectories) for record in records),
                "with_failure": sum(bool(record.related_failures) for record in records),
            }
        elif args.command == "build":
            result = build_index(root, model_id=args.model, batch_size=args.batch_size, device=args.device)
        else:
            result = query_index(root, args.text, top_k=args.top_k, device=args.device)
    except (FileNotFoundError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
