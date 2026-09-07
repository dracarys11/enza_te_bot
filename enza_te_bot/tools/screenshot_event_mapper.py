#!/usr/bin/env python3
"""Map screenshot metadata to semantic trajectory events offline."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


TIMESTAMP_PATTERN = re.compile(r"(?<!\d)(20\d{6})[_-](\d{6})(?!\d)")
SEMANTIC_TOKENS = frozenset({
    "legend", "pass", "fail", "battle", "audition", "choice", "schedule", "lesson",
})


@dataclass
class EventCandidate:
    source: Path
    run_ids: set[str] = field(default_factory=set)
    timestamp: datetime | None = None
    phase: Any = None
    action: Any = None
    result: Any = None
    text: str = ""


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        match = TIMESTAMP_PATTERN.search(value)
        if not match:
            return None
        result = datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _first(value: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        if value.get(key) is not None:
            return value[key]
    return None


def _run_ids(value: dict[str, Any], source: Path) -> set[str]:
    found = set()
    for key in ("run_id", "source_run", "run"):
        if isinstance(value.get(key), str) and value[key].strip():
            found.add(value[key].strip())
    for index, part in enumerate(source.parts):
        if part == "wing_runs" and index + 1 < len(source.parts):
            found.add(source.parts[index + 1])
    return found


def _candidate(source: Path, value: dict[str, Any]) -> EventCandidate:
    timestamp = None
    for key in ("timestamp", "captured_at", "created_at", "at"):
        timestamp = _parse_timestamp(value.get(key))
        if timestamp:
            break
    phase = _first(value, ("phase", "room", "page", "substate", "boundary"))
    action = _first(value, (
        "action", "decision", "action_flow", "intent", "selected_action", "emitted_action",
    ))
    result = _first(value, (
        "result", "action_result", "outcome", "observed_result", "verification", "battle_result",
    ))
    return EventCandidate(
        source=source,
        run_ids=_run_ids(value, source),
        timestamp=timestamp,
        phase=phase,
        action=action,
        result=result,
        text=json.dumps(value, ensure_ascii=False).casefold(),
    )


def load_event_candidates(wing_runs: Path, weekly_trace: Path | None = None) -> list[EventCandidate]:
    paths: list[Path] = []
    if weekly_trace:
        paths.append(weekly_trace)
    if wing_runs.is_dir():
        paths.extend(sorted(wing_runs.rglob("*.jsonl")))
        paths.extend(sorted(wing_runs.rglob("*.json")))
    candidates: list[EventCandidate] = []
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
                candidates.append(_candidate(path, value))
    return candidates


def _row_run(row: dict[str, Any]) -> str | None:
    value = row.get("run_id", row.get("source_run"))
    return value if isinstance(value, str) and value else None


def _filename_semantics(row: dict[str, Any]) -> set[str]:
    image = row.get("image_path", row.get("path", ""))
    name = Path(image).stem.casefold() if isinstance(image, str) else ""
    tokens = {token for token in re.split(r"[^a-z0-9]+", name) if token}
    labels: set[str] = set()
    for token in tokens:
        for semantic in SEMANTIC_TOKENS:
            if token == semantic or token.startswith(semantic):
                labels.add(semantic)
    return labels


def _candidate_semantics(candidate: EventCandidate) -> set[str]:
    text = json.dumps(
        [candidate.phase, candidate.action, candidate.result], ensure_ascii=False
    ).casefold()
    labels: set[str] = set()
    if any(token in text for token in ("pass", "success", "突破", "commit")):
        labels.add("pass")
    if any(token in text for token in ("fail", "failure", "落選", "未達")):
        labels.add("fail")
    if "battle" in text or "audition_battle" in text:
        labels.add("battle")
    if "audition" in text or "審査" in text:
        labels.add("audition")
    if "choice" in text or "選択" in text:
        labels.add("choice")
    if "schedule" in text or "スケジュール" in text:
        labels.add("schedule")
    if "lesson" in text or "レッスン" in text:
        labels.add("lesson")
    if "legend" in text:
        labels.add("legend")
    return labels


def _semantic_payload(labels: set[str]) -> dict[str, Any]:
    phase = (
        "BATTLE" if "battle" in labels
        else "AUDITION" if "audition" in labels
        else "CHOICE" if "choice" in labels
        else "SCHEDULE" if "schedule" in labels
        else "LESSON" if "lesson" in labels
        else None
    )
    action = (
        "AUDITION" if "audition" in labels or "battle" in labels or "legend" in labels
        else "CHOICE" if "choice" in labels
        else "LESSON" if "lesson" in labels
        else None
    )
    result = "PASS" if "pass" in labels else "FAIL" if "fail" in labels else None
    return {"phase": phase, "action": action, "result": result, "source": "screenshot_filename"}


def _semantic_match_score(labels: set[str], candidate: EventCandidate, image_stem: str) -> int:
    candidate_labels = _candidate_semantics(candidate)
    if "pass" in labels and "pass" not in candidate_labels:
        return 0
    if "fail" in labels and "fail" not in candidate_labels:
        return 0
    overlap = labels & candidate_labels
    if not overlap:
        return 0
    score = len(overlap) * 10
    if image_stem and image_stem in candidate.text:
        score += 100
    if candidate.source.name == "weekly_trace.jsonl":
        score += 20
    return score


def resolve_screenshot_event(row: dict[str, Any], candidates: Sequence[EventCandidate]) -> dict[str, Any] | None:
    labels = _filename_semantics(row)
    run_id = _row_run(row)
    same_run = [candidate for candidate in candidates if run_id and run_id in candidate.run_ids]
    pool = same_run or list(candidates)

    if labels:
        image = row.get("image_path", row.get("path", ""))
        image_stem = Path(image).stem.casefold() if isinstance(image, str) else ""
        semantic_matches = [
            candidate for candidate in pool
            if _semantic_match_score(labels, candidate, image_stem) > 0
        ]
        if semantic_matches:
            chosen = max(
                semantic_matches,
                key=lambda candidate: _semantic_match_score(labels, candidate, image_stem),
            )
            payload = _semantic_payload(labels)
            payload.update({
                "phase": chosen.phase or payload["phase"],
                "action": chosen.action or payload["action"],
                "result": chosen.result or payload["result"],
                "source": "filename_semantic_trace_match",
            })
            return payload
        return _semantic_payload(labels)

    row_time = _parse_timestamp(row.get("timestamp"))
    if row_time:
        timestamped = [candidate for candidate in pool if candidate.timestamp]
        if timestamped:
            chosen = min(timestamped, key=lambda candidate: abs(candidate.timestamp - row_time))
            return {"phase": chosen.phase, "action": chosen.action, "result": chosen.result, "source": chosen.source.as_posix()}
    if same_run:
        chosen = same_run[0]
        return {"phase": chosen.phase, "action": chosen.action, "result": chosen.result, "source": chosen.source.as_posix()}
    return None


def map_rows(rows: Sequence[dict[str, Any]], candidates: Sequence[EventCandidate]) -> list[dict[str, Any]]:
    mapped: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        event = resolve_screenshot_event(row, candidates)
        if event is not None:
            enriched["event"] = event
        mapped.append(enriched)
    return mapped


def map_file(metadata: Path, wing_runs: Path, weekly_trace: Path | None = None, output: Path | None = None) -> int:
    with metadata.open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("metadata JSONL must contain objects")
    destination = output or metadata
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidates = load_event_candidates(wing_runs, weekly_trace)
    with destination.open("w", encoding="utf-8") as handle:
        for row in map_rows(rows, candidates):
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return len(rows)


def _parser() -> argparse.ArgumentParser:
    default_metadata = Path.home() / "data/enza_ai/index/metadata_enriched.jsonl"
    root = default_metadata.parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, default=default_metadata)
    parser.add_argument("--wing-runs", type=Path, default=root / "wing_runs")
    parser.add_argument("--weekly-trace", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    count = map_file(args.metadata, args.wing_runs, args.weekly_trace, args.output)
    print(f"mapped {count} screenshot metadata records")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
