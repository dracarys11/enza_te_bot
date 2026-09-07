from __future__ import annotations

import json

from tools.validate_evidence_metadata import (
    effective_event_fields,
    validate_metadata,
)


def write_metadata(tmp_path, row):
    path = tmp_path / "metadata_enriched.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    return path


def test_nested_event_priority(tmp_path):
    row = {
        "image_path": "screenshots/legend_battle3_pass.png",
        "result": "ABANDONED_BY_OPERATOR",
        "event": {"result": "PASS", "source": "filename_semantic_trace_match"},
    }

    assert effective_event_fields(row)["result"] == "PASS"


def test_legacy_fallback(tmp_path):
    row = {
        "path": "screenshots/legacy.png",
        "action": "VOCAL",
        "phase": "BATTLE",
        "result": "COMMITTED",
        "state": {"page": "RESULT"},
    }

    assert effective_event_fields(row) == {
        "action": "VOCAL",
        "phase": "BATTLE",
        "result": "COMMITTED",
        "state": {"page": "RESULT"},
    }
    assert validate_metadata(write_metadata(tmp_path, row)).valid


def test_conflicting_metadata_warning(tmp_path):
    path = write_metadata(tmp_path, {
        "image_path": "screenshots/result.png",
        "result": "ABANDONED_BY_OPERATOR",
        "event": {"result": "PASS"},
    })

    report = validate_metadata(path)

    assert report.valid
    assert [(issue.code, issue.field) for issue in report.warnings] == [
        ("CONFLICTING_METADATA", "result"),
    ]
    assert json.loads(path.read_text(encoding="utf-8"))["result"] == "ABANDONED_BY_OPERATOR"


def test_missing_required_fields(tmp_path):
    report = validate_metadata(write_metadata(tmp_path, {"result": "PASS"}))

    assert not report.valid
    assert report.errors[0].code == "MISSING_REQUIRED_FIELD"
