#!/usr/bin/env python3
"""Validate enriched evidence metadata without changing the source file."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


EVENT_FIELDS = ("action", "phase", "result", "state")
IMAGE_KEYS = ("image_path", "path")


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    line: int
    code: str
    message: str
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = {
            "level": self.level,
            "line": self.line,
            "code": self.code,
            "message": self.message,
        }
        if self.field is not None:
            value["field"] = self.field
        return value


@dataclass
class ValidationReport:
    rows: int = 0
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "rows": self.rows,
            "errors": [issue.as_dict() for issue in self.errors],
            "warnings": [issue.as_dict() for issue in self.warnings],
        }


def effective_event_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return event fields with nested values taking precedence.

    This is a read-only projection. It never mutates ``row`` and deliberately
    leaves conflict handling to validation so callers cannot lose provenance.
    """
    event = row.get("event")
    return {
        name: event[name] if isinstance(event, Mapping) and name in event else row.get(name)
        for name in EVENT_FIELDS
    }


def validate_row(row: Any, line: int) -> list[ValidationIssue]:
    if not isinstance(row, dict):
        return [ValidationIssue("error", line, "ROW_NOT_OBJECT", "metadata row must be a JSON object")]

    issues: list[ValidationIssue] = []
    if not any(key in row and row[key] not in (None, "") for key in IMAGE_KEYS):
        issues.append(ValidationIssue(
            "error", line, "MISSING_REQUIRED_FIELD",
            "metadata row requires image_path or legacy path", "image_path",
        ))

    event = row.get("event")
    if "event" in row and not isinstance(event, dict):
        issues.append(ValidationIssue(
            "error", line, "EVENT_NOT_OBJECT", "event must be a JSON object when present", "event",
        ))
        return issues

    if isinstance(event, dict):
        for name in EVENT_FIELDS:
            if name in row and name in event and row[name] != event[name]:
                issues.append(ValidationIssue(
                    "warning", line, "CONFLICTING_METADATA",
                    f"event.{name} differs from legacy {name}; event.{name} takes precedence",
                    name,
                ))
    return issues


def validate_metadata(path: Path) -> ValidationReport:
    report = ValidationReport()
    try:
        lines: Iterable[str] = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        report.errors.append(ValidationIssue("error", 0, "READ_ERROR", str(error)))
        return report

    for line, text in enumerate(lines, 1):
        if not text.strip():
            continue
        report.rows += 1
        try:
            row = json.loads(text)
        except json.JSONDecodeError as error:
            report.errors.append(ValidationIssue(
                "error", line, "INVALID_JSON", error.msg,
            ))
            continue
        for issue in validate_row(row, line):
            (report.errors if issue.level == "error" else report.warnings).append(issue)
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("metadata", type=Path, help="metadata JSONL file to validate")
    return parser


def main(argv: list[str] | None = None) -> int:
    report = validate_metadata(_parser().parse_args(argv).metadata)
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0 if report.valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
