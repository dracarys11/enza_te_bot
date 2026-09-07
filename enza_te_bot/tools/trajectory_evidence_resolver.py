#!/usr/bin/env python3
"""Resolve enriched evidence rows to durable trajectory records offline."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
TIMESTAMP_PATTERN = re.compile(r"(?<!\d)(20\d{6})[_-](\d{6})(?!\d)")


@dataclass
class TrajectoryRecord:
    source_path: Path
    image_refs: set[str] = field(default_factory=set)
    run_ids: set[str] = field(default_factory=set)
    timestamp: datetime | None = None
    timestamp_text: str | None = None
    action: Any = None
    result: Any = None
    state: Any = None
    phase: Any = None


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        match = TIMESTAMP_PATTERN.search(value)
        if not match:
            return None
        parsed = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _images(value: Any) -> set[str]:
    if isinstance(value, str) and Path(value).suffix.casefold() in IMAGE_SUFFIXES:
        return {value}
    if isinstance(value, dict):
        result: set[str] = set()
        for child in value.values():
            result.update(_images(child))
        return result
    if isinstance(value, list):
        result: set[str] = set()
        for child in value:
            result.update(_images(child))
        return result
    return set()


def _first(mapping: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if mapping.get(key) is not None:
            return mapping[key]
    return None


def _walk(path: Path, value: Any, inherited: TrajectoryRecord | None = None) -> Iterable[TrajectoryRecord]:
    if not isinstance(value, dict):
        return
    record = TrajectoryRecord(source_path=path)
    if inherited:
        record.image_refs.update(inherited.image_refs)
        record.run_ids.update(inherited.run_ids)
        record.timestamp = inherited.timestamp
        record.timestamp_text = inherited.timestamp_text
        record.action = inherited.action
        record.result = inherited.result
        record.state = inherited.state
        record.phase = inherited.phase
    record.image_refs.update(_images(value))
    for key in ("run_id", "source_run", "run"):
        if isinstance(value.get(key), str) and value[key].strip():
            record.run_ids.add(value[key].strip())
    for key in ("timestamp", "captured_at", "created_at", "at"):
        parsed = _timestamp(value.get(key))
        if parsed:
            record.timestamp = parsed
            record.timestamp_text = str(value[key])
            break
    record.action = _first(value, ("action", "intent", "selected_action", "emitted_action")) or record.action
    record.result = _first(value, ("result", "outcome", "observed_result", "verification")) or record.result
    record.state = _first(value, ("state", "page_state", "room", "substate")) or record.state
    record.phase = _first(value, ("phase", "room", "page", "substate")) or record.phase
    yield record
    for child in value.values():
        if isinstance(child, dict):
            yield from _walk(path, child, record)
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, dict):
                    yield from _walk(path, item, record)


def load_trajectory_records(trajectories: Path, wing_runs: Path) -> list[TrajectoryRecord]:
    records: list[TrajectoryRecord] = []
    seen: set[Path] = set()
    for directory in (trajectories, wing_runs):
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            resolved = path.resolve()
            if resolved in seen or not path.is_file() or path.suffix.casefold() not in {".json", ".jsonl"}:
                continue
            seen.add(resolved)
            try:
                text = path.read_text(encoding="utf-8")
                values = ([json.loads(line) for line in text.splitlines() if line.strip()]
                          if path.suffix.casefold() == ".jsonl" else [json.loads(text)])
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            for value in values:
                records.extend(_walk(path, value))
    return records


def _image_match(row: dict[str, Any], record: TrajectoryRecord) -> bool:
    image = row.get("image_path", row.get("path"))
    if not isinstance(image, str):
        return False
    return any(image == ref or Path(image).name == Path(ref).name for ref in record.image_refs)


def _row_run(row: dict[str, Any]) -> str | None:
    value = row.get("run_id", row.get("source_run"))
    return value if isinstance(value, str) and value else None


def _match_key(row: dict[str, Any], record: TrajectoryRecord) -> tuple[int, int, float, str]:
    run_match = int(_row_run(row) is not None and _row_run(row) in record.run_ids)
    image_match = int(_image_match(row, record))
    row_time = _timestamp(row.get("timestamp"))
    if row_time and record.timestamp:
        distance = abs((row_time - record.timestamp).total_seconds())
    else:
        distance = float("inf")
    # Exact run identity is the primary key, then screenshot filename, then time.
    return run_match, image_match, -distance, record.source_path.as_posix()


def resolve_trajectory(row: dict[str, Any], records: Sequence[TrajectoryRecord]) -> TrajectoryRecord | None:
    if not records:
        return None
    candidates = [record for record in records if _match_key(row, record)[:3] != (0, 0, float("-inf"))]
    if not candidates:
        return None
    return max(candidates, key=lambda record: _match_key(row, record))


def load_event_records(paths: Sequence[Path]) -> list[TrajectoryRecord]:
    """Load event-level records from weekly trace and timing JSONL files."""

    records: list[TrajectoryRecord] = []
    seen: set[Path] = set()
    for path in paths:
        path = path.resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            text = path.read_text(encoding="utf-8")
            values = ([json.loads(line) for line in text.splitlines() if line.strip()]
                      if path.suffix.casefold() == ".jsonl" else [json.loads(text)])
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        for value in values:
            if isinstance(value, dict):
                records.append(next(iter(_walk(path, value))))
    return records


def _event_match_key(row: dict[str, Any], event: TrajectoryRecord) -> tuple[int, int, float, str]:
    row_time = _timestamp(row.get("timestamp"))
    exact_timestamp = int(row_time is not None and event.timestamp == row_time)
    if row_time and event.timestamp:
        distance = abs((row_time - event.timestamp).total_seconds())
    else:
        distance = float("inf")
    same_run = int(_row_run(row) is not None and _row_run(row) in event.run_ids)
    # Exact timestamp dominates proximity; same-run is the final fallback.
    return exact_timestamp, int(distance != float("inf")), -distance, str(same_run) + event.source_path.as_posix()


def resolve_event(row: dict[str, Any], events: Sequence[TrajectoryRecord]) -> TrajectoryRecord | None:
    if not events:
        return None
    row_time = _timestamp(row.get("timestamp"))
    row_run = _row_run(row)
    image = row.get("image_path", row.get("path"))
    candidates: list[TrajectoryRecord] = []
    for event in events:
        image_match = isinstance(image, str) and any(
            image == ref or Path(image).name == Path(ref).name for ref in event.image_refs
        )
        same_run = row_run is not None and row_run in event.run_ids
        timestamp_match = row_time is not None and event.timestamp is not None
        if image_match or same_run or timestamp_match:
            candidates.append(event)
    if not candidates:
        return None
    return max(candidates, key=lambda event: _event_match_key(row, event))


def _event_payload(event: TrajectoryRecord) -> dict[str, Any]:
    return {
        "timestamp": event.timestamp_text or (event.timestamp.isoformat() if event.timestamp else None),
        "phase": event.phase,
        "action": event.action,
        "state": event.state,
        "result": event.result,
    }


def enrich_rows(
    rows: Sequence[dict[str, Any]],
    records: Sequence[TrajectoryRecord],
    events: Sequence[TrajectoryRecord] = (),
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        match = resolve_trajectory(row, records)
        event = resolve_event(row, events)
        enriched = dict(row)
        if match:
            enriched.update({
                "action": match.action,
                "result": match.result,
                "state": match.state,
                "phase": match.phase,
            })
            enriched.setdefault("trajectory_ref", match.source_path.as_posix())
        else:
            for key in ("trajectory_ref", "action", "result", "state", "phase"):
                enriched.setdefault(key, None)
        enriched["event"] = _event_payload(event) if event else None
        output.append(enriched)
    return output


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"metadata line {line_number} is not an object")
            rows.append(value)
    return rows


def resolve_file(
    metadata: Path,
    trajectories: Path,
    wing_runs: Path,
    output: Path | None = None,
    weekly_trace: Path | None = None,
    timings: Path | None = None,
) -> int:
    rows = _read_jsonl(metadata)
    records = load_trajectory_records(trajectories, wing_runs)
    event_paths = [path for path in (weekly_trace, timings) if path is not None]
    if not event_paths:
        event_paths = sorted(wing_runs.rglob("weekly_trace.jsonl")) + sorted(wing_runs.rglob("timings.jsonl"))
    events = load_event_records(event_paths)
    destination = output or metadata
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        for row in enrich_rows(rows, records, events):
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def _parser() -> argparse.ArgumentParser:
    default_metadata = Path.home() / "data/enza_ai/index/metadata_enriched.jsonl"
    data_root = default_metadata.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=default_metadata)
    parser.add_argument("--trajectories", type=Path, default=data_root / "trajectories")
    parser.add_argument("--wing-runs", type=Path, default=data_root / "wing_runs")
    parser.add_argument("--weekly-trace", type=Path)
    parser.add_argument("--timings", type=Path)
    parser.add_argument("--output", type=Path, help="Separate output; defaults to updating metadata in place")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    count = resolve_file(
        args.metadata, args.trajectories, args.wing_runs, args.output,
        weekly_trace=args.weekly_trace, timings=args.timings,
    )
    print(f"resolved {count} metadata records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
