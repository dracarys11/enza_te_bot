"""Markdown report generation for already-computed offline evaluations."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any


def generate_report(results: list[dict[str, Any]], agent: str, report_date: str | None = None) -> str:
    scores = [item.get("score", {}).get("total", 0) for item in results]
    average = sum(scores) / len(scores) if scores else 0
    lines = ["# ENZA Reliability Benchmark", "", f"Agent: {agent}", f"Date: {report_date or date.today().isoformat()}", "", "Cases:"]
    lines += [f"{item.get('case_id', 'UNKNOWN')}: {item.get('status', 'UNKNOWN')} {item.get('score', {}).get('total', 0)}" for item in results]
    lines += ["", f"Average: {average:.1f}", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text())
    results = payload if isinstance(payload, list) else payload.get("results", [payload])
    output = args.output or Path("reports") / f"{args.agent}_{date.today().isoformat()}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generate_report(results, args.agent))


if __name__ == "__main__":
    main()
