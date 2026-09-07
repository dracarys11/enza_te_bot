"""Resolve mutable Produce progress from the registry-selected run only."""
from __future__ import annotations

import copy
import json
import os
import hashlib
import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping


S3_FLAG_DEFAULTS = {
    "reflection_opening_completed": False,
    "audition_40k_completed": False,
    "audition_50k_completed": False,
}


def clean_run_state(run_id: str | None = None) -> dict[str, object]:
    """Return independent progress for a new run or for ACTIVE_RUN=NONE."""
    return {"run_id": run_id, "season3": dict(S3_FLAG_DEFAULTS)}


def _run_id(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value).name


def _registered_run(registry: Mapping[str, object], run_id: str) -> Mapping[str, object]:
    runs = registry.get("runs", [])
    if not isinstance(runs, list):
        raise ValueError("RUN_REGISTRY_INVALID")
    matches = [item for item in runs if isinstance(item, Mapping) and item.get("id") == run_id]
    if len(matches) != 1:
        raise ValueError(f"RUN_NOT_REGISTERED:{run_id}")
    return matches[0]


def _state_from_payload(payload: Mapping[str, object], run_id: str) -> dict[str, object]:
    if payload.get("run_id") != run_id:
        raise ValueError(f"RUN_STATE_ID_MISMATCH:{run_id}")
    raw = payload.get("run_state")
    if not isinstance(raw, Mapping):
        resume = payload.get("resume_state")
        raw = resume.get("run_state") if isinstance(resume, Mapping) else None
    state = clean_run_state(run_id)
    if not isinstance(raw, Mapping):
        return state
    state.update(copy.deepcopy(dict(raw)))
    state["run_id"] = run_id
    state["season3"] = dict(S3_FLAG_DEFAULTS)
    season3 = raw.get("season3")
    if isinstance(season3, Mapping):
        for flag in S3_FLAG_DEFAULTS:
            if flag in season3:
                if not isinstance(season3[flag], bool):
                    raise ValueError(f"RUN_STATE_FLAG_INVALID:{flag}")
                state["season3"][flag] = season3[flag]
    route_deadline = raw.get("route_deadline")
    if isinstance(route_deadline, Mapping):
        state["route_deadline"] = dict(route_deadline)
    return state


def resolve_run_state(
    registry: Mapping[str, object],
    *,
    base_dir: Path,
    requested_run_id: str | None = None,
) -> dict[str, object]:
    """Load only the active run's local progress, or clean non-authoritative state.

    A missing run-local state file means this is a new run and therefore starts
    clean.  Historical progress embedded in global config is intentionally not
    an input to this function.
    """
    mainline = registry.get("current_mainline", {})
    active_id = _run_id(mainline.get("active_run")) if isinstance(mainline, Mapping) else None
    if active_id is None:
        if requested_run_id is not None:
            raise ValueError("ACTIVE_RUN_NONE:CANNOT_RESUME")
        return clean_run_state()
    if requested_run_id is not None and requested_run_id != active_id:
        raise ValueError(f"ACTIVE_RUN_ID_MISMATCH:{requested_run_id}:{active_id}")

    record = _registered_run(registry, active_id)
    if record.get("resume_allowed") is False:
        raise ValueError(f"ACTIVE_RUN_NOT_RESUMABLE:{active_id}")
    raw_path = record.get("path")
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"RUN_PATH_MISSING:{active_id}")
    run_dir = base_dir / raw_path
    if (run_dir / ".persistence_pending").exists():
        raise ValueError("PERSISTENCE_INCOMPLETE:RECONCILIATION_REQUIRED")
    state_path = run_dir / "runtime_state.json"
    if state_path.is_file():
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"RUN_STATE_INVALID:{active_id}")
        if payload.get("run_closed") is True or payload.get("resume_allowed") is False:
            raise ValueError(f"RUN_CHECKPOINT_NOT_RESUMABLE:{active_id}")
        return _state_from_payload(payload, active_id)

    resume_file = record.get("resume_file")
    if isinstance(resume_file, str) and resume_file:
        checkpoint_path = base_dir / resume_file
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError(f"RUN_CHECKPOINT_INVALID:{active_id}")
        if payload.get("run_closed") is True or payload.get("resume_allowed") is False:
            raise ValueError(f"RUN_CHECKPOINT_NOT_RESUMABLE:{active_id}")
        return _state_from_payload(payload, active_id)
    return clean_run_state(active_id)


def load_runtime_config(
    config_path: Path,
    registry_path: Path,
    *,
    requested_run_id: str | None = None,
) -> dict[str, object]:
    """Combine static config with registry-authorized, run-local progress."""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(registry, Mapping):
        raise ValueError("CONFIG_OR_REGISTRY_INVALID")
    resolved = copy.deepcopy(config)
    resolved["run_state"] = resolve_run_state(
        registry, base_dir=registry_path.parent.parent,
        requested_run_id=requested_run_id,
    )
    return resolved


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable_json(destination: Path, payload: Mapping[str, object]) -> None:
    encoded = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    temporary = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent,
                               prefix=".runtime_state_", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        _sync_directory(destination.parent)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_active_run_state(registry_path: Path, run_state: Mapping[str, object], *,
                          boundary: str = "RUN_STATE_UPDATE",
                          evidence: Mapping[str, object] | None = None,
                          evidence_paths: tuple[Path, ...] = ()) -> Path:
    """Durable event -> existing checkpoint; callers may publish summaries only after return.

    An interrupted flush leaves a durable marker. Loading or writing that run
    then fails closed, including after restart, until explicit reconciliation.
    No registry progress is manufactured here. Evidence files are fsynced and
    digest-bound before the event is persisted.
    """
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    resolved = resolve_run_state(registry, base_dir=registry_path.parent.parent)
    active_id = resolved.get("run_id")
    if not isinstance(active_id, str) or run_state.get("run_id") != active_id:
        raise ValueError("ACTIVE_RUN_ID_REQUIRED_FOR_PROGRESS_WRITE")
    record = _registered_run(registry, active_id)
    directory = registry_path.parent.parent / str(record["path"])
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / ".persistence_pending"
    # Exclusive creation also prevents concurrent progress writers.
    with marker.open("x") as handle:
        handle.write(boundary)
        handle.flush()
        os.fsync(handle.fileno())
    _sync_directory(directory.parent)
    _sync_directory(directory)
    references = []
    for path in evidence_paths:
        with path.open("rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
            os.fsync(handle.fileno())
        _sync_directory(path.parent)
        references.append({"path": str(path), "sha256": digest})
    event_id = uuid.uuid4().hex
    payload = {"run_id": active_id, "run_state": copy.deepcopy(dict(run_state)),
               "event_id": event_id, "boundary": boundary,
               "evidence": copy.deepcopy(dict(evidence or {})), "evidence_files": references}
    events = directory / "boundary_events"
    events.mkdir(exist_ok=True)
    _sync_directory(directory)
    _durable_json(events / (event_id + ".json"), payload)
    destination = directory / "runtime_state.json"
    _durable_json(destination, payload)
    marker.unlink()
    _sync_directory(directory)
    return destination


def persist_session_end(registry_path: Path, *, reason: str) -> Path:
    """Flush the latest durable state at a bounded session/handoff exit."""
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    state = resolve_run_state(registry, base_dir=registry_path.parent.parent)
    return save_active_run_state(registry_path, state, boundary="SESSION_END",
                                 evidence={"reason": reason})
