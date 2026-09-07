#!/usr/bin/env python3
"""Summarize an offline VLM prediction JSONL file."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def confidence_bucket(value: float) -> str:
    if value < 0.2:
        return "0.0-0.19"
    if value < 0.4:
        return "0.2-0.39"
    if value < 0.6:
        return "0.4-0.59"
    if value < 0.8:
        return "0.6-0.79"
    return "0.8-1.0"


def summarize_predictions(path: str | Path) -> dict[str, Any]:
    states: Counter[str] = Counter()
    phases: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    histogram: Counter[str] = Counter({
        "0.0-0.19": 0,
        "0.2-0.39": 0,
        "0.4-0.59": 0,
        "0.6-0.79": 0,
        "0.8-1.0": 0,
    })
    total = 0
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        observation = record.get("observation") or {}
        states[str(observation.get("state", "UNKNOWN"))] += 1
        phases[str(observation.get("phase", "UNKNOWN"))] += 1
        statuses[str(record.get("vlm_status", "UNKNOWN"))] += 1
        confidence = float(record.get("confidence", 0.0))
        histogram[confidence_bucket(confidence)] += 1
        total += 1
    return {
        "total": total,
        "state_distribution": dict(states),
        "phase_distribution": dict(phases),
        "unknown_rate": statuses.get("UNKNOWN", 0) / total if total else 0.0,
        "confidence_histogram": dict(histogram),
    }


def write_report(stats: dict[str, Any], output: str | Path) -> None:
    Path(output).write_text("\n".join([
        "# Local VLM Observation Statistics v0.1",
        "",
        f"- Total predictions: {stats['total']}",
        f"- UNKNOWN rate: {stats['unknown_rate']:.3f}",
        f"- State distribution: {json.dumps(stats['state_distribution'], sort_keys=True)}",
        f"- Phase distribution: {json.dumps(stats['phase_distribution'], sort_keys=True)}",
        f"- Confidence histogram: {json.dumps(stats['confidence_histogram'], sort_keys=True)}",
        "",
    ]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize local VLM observation predictions")
    parser.add_argument("input", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    stats = summarize_predictions(args.input)
    if args.report:
        write_report(stats, args.report)
    print(json.dumps(stats, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
