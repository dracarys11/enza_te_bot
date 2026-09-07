#!/usr/bin/env python3
"""Enrich evidence metadata from durable trajectories, failures, and observations.

This tool only reads the source artifacts and writes a separate JSONL file.  It
does not read or write FAISS indexes and never changes the source metadata.
"""

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
TIMESTAMP_KEYS = ("timestamp", "captured_at", "created_at", "at")
RUN_KEYS = ("run_id", "source_run", "run")


@dataclass
class EvidenceContext:
    source_path: Path
    kind: str
    image_paths: set[str] = field(default_factory=set)
    run_ids: set[str] = field(default_factory=set)
    timestamp: datetime | None = None
    state: Any = None
    phase: Any = None
    action: Any = None
    result: Any = None
    failure_type: Any = None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        match = TIMESTAMP_PATTERN.search(text)
        if not match:
            return None
        parsed = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _image_strings(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str) and Path(value).suffix.casefold() in IMAGE_SUFFIXES:
        found.add(value)
    elif isinstance(value, dict):
        for child in value.values():
            found.update(_image_strings(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_image_strings(child))
    return found


def _kind_for(path: Path) -> str:
    lowered = {part.casefold() for part in path.parts}
    name = path.name.casefold()
    if "failure" in lowered or "failure" in name or "incident" in name:
        return "failure"
    if "observation" in lowered or "observation" in name or name.startswith("obs"):
        return "observation"
    return "trajectory"


def _load_values(path: Path) -> list[Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.casefold() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [json.loads(text)]


def _first(mapping: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _walk_contexts(path: Path, kind: str, value: Any, inherited: EvidenceContext | None = None) -> Iterable[EvidenceContext]:
    if not isinstance(value, dict):
        return
    context = EvidenceContext(source_path=path, kind=kind)
    if inherited:
        context.image_paths.update(inherited.image_paths)
        context.run_ids.update(inherited.run_ids)
        context.timestamp = inherited.timestamp
        for name in ("state", "phase", "action", "result", "failure_type"):
            setattr(context, name, getattr(inherited, name))

    context.image_paths.update(_image_strings(value))
    for key in RUN_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            context.run_ids.add(candidate.strip())
    for key in TIMESTAMP_KEYS:
        parsed = _parse_timestamp(value.get(key))
        if parsed:
            context.timestamp = parsed
            break
    if "state" in value:
        context.state = value["state"]
    elif "page_state" in value:
        context.state = value["page_state"]
    context.phase = _first(value, ("phase", "room", "page", "page_state")) or context.phase
    context.action = _first(value, ("action", "intent", "selected_action", "emitted_action")) or context.action
    context.result = _first(value, ("result", "observed_result", "outcome", "verification")) or context.result
    context.failure_type = _first(value, ("failure_type", "failure_class", "classification", "failure_id")) or context.failure_type
    yield context
    for key, child in value.items():
        if isinstance(child, dict):
            yield from _walk_contexts(path, kind, child, context)
        elif isinstance(child, list):
            for item in child:
                if isinstance(item, dict):
                    yield from _walk_contexts(path, kind, item, context)


def load_contexts(directory: Path) -> list[EvidenceContext]:
    if not directory.is_dir():
        return []
    contexts: list[EvidenceContext] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.casefold() not in {".json", ".jsonl"}:
            continue
        try:
            values = _load_values(path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        kind = _kind_for(path)
        for value in values:
            contexts.extend(_walk_contexts(path, kind, value))
    return contexts


def _same_image(left: str, right: str) -> bool:
    if left == right:
        return True
    try:
        return Path(left).name == Path(right).name
    except (TypeError, ValueError):
        return False


def _match_score(row: dict[str, Any], context: EvidenceContext, tolerance_seconds: float) -> float:
    image = row.get("image_path", row.get("path"))
    row_run = row.get("run_id", row.get("source_run"))
    row_time = _parse_timestamp(row.get("timestamp"))
    score = 0.0
    if isinstance(image, str) and any(_same_image(image, candidate) for candidate in context.image_paths):
        score += 100.0
    if isinstance(row_run, str) and row_run in context.run_ids:
        score += 25.0
    if row_time and context.timestamp:
        delta = abs((row_time - context.timestamp).total_seconds())
        if delta <= tolerance_seconds:
            score += 20.0 * (1.0 - delta / max(tolerance_seconds, 1.0))
        elif score < 100.0:
            return 0.0
    return score


def _best(row: dict[str, Any], contexts: Sequence[EvidenceContext], kind: str, tolerance_seconds: float) -> EvidenceContext | None:
    candidates = [context for context in contexts if context.kind == kind]
    scored = [(score, context) for context in candidates if (score := _match_score(row, context, tolerance_seconds)) > 0]
    if not scored:
        return None
    return max(scored, key=lambda item: item[0])[1]


def enrich_rows(rows: Sequence[dict[str, Any]], contexts: Sequence[EvidenceContext], *, tolerance_seconds: float = 300.0) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for row in rows:
        trajectory = _best(row, contexts, "trajectory", tolerance_seconds)
        observation = _best(row, contexts, "observation", tolerance_seconds)
        failure = _best(row, contexts, "failure", tolerance_seconds)
        result = dict(row)
        result.update({
            "state": (observation or trajectory).state if (observation or trajectory) else None,
            "phase": (observation or trajectory or failure).phase if (observation or trajectory or failure) else None,
            "action": (trajectory or observation or failure).action if (trajectory or observation or failure) else None,
            "result": (trajectory or observation or failure).result if (trajectory or observation or failure) else None,
            "failure_type": failure.failure_type if failure else None,
            "trajectory_ref": trajectory.source_path.as_posix() if trajectory else None,
            "observation_ref": observation.source_path.as_posix() if observation else None,
        })
        enriched.append(result)
    return enriched


def _read_metadata(path: Path) -> list[dict[str, Any]]:
    values = _load_values(path)
    if any(not isinstance(value, dict) for value in values):
        raise ValueError("metadata JSONL must contain one object per line")
    return values  # type: ignore[return-value]


def enrich_file(metadata: Path, trajectories: Path, failures: Path, observations: Path, output: Path, *, tolerance_seconds: float = 300.0) -> int:
    rows = _read_metadata(metadata)
    contexts = load_contexts(trajectories) + load_contexts(failures) + load_contexts(observations)
    enriched = enrich_rows(rows, contexts, tolerance_seconds=tolerance_seconds)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in enriched:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(enriched)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", required=True, type=Path)
    parser.add_argument("--trajectories", required=True, type=Path)
    parser.add_argument("--failures", required=True, type=Path)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timestamp-tolerance-seconds", type=float, default=300.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.output or args.metadata.with_name("metadata_enriched.jsonl")
    count = enrich_file(
        args.metadata, args.trajectories, args.failures, args.observations, output,
        tolerance_seconds=args.timestamp_tolerance_seconds,
    )
    print(f"enriched {count} metadata records: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
