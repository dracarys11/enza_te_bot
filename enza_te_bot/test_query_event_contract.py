from __future__ import annotations

from tools.query_evidence import resolve_evidence_contract


def test_event_overrides_legacy():
    output = resolve_evidence_contract({"result": "FAIL", "event": {"result": "PASS"}})

    assert output["event"]["result"] == "PASS"


def test_legacy_fallback():
    output = resolve_evidence_contract({"result": "PASS"})

    assert output["event"]["result"] == "PASS"


def test_conflict_detection():
    output = resolve_evidence_contract({"result": "FAIL", "event": {"result": "PASS"}})

    assert {"field": "result", "legacy": "FAIL", "event": "PASS"} in output["provenance"]["conflicts"]
