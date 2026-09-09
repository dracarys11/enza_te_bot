from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.run_local_review import CONTEXT_FILES, LocalReviewError, build_context_bundle, run_review


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


def _context_root(tmp_path: Path) -> Path:
    for relative in CONTEXT_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"evidence for {relative}\n", encoding="utf-8")
    return tmp_path


def test_context_bundle_contains_all_labeled_documents(tmp_path: Path):
    root = _context_root(tmp_path)
    bundle = build_context_bundle(root)
    for relative in CONTEXT_FILES:
        assert f"BEGIN {relative}" in bundle
        assert f"evidence for {relative}" in bundle


def test_missing_llama_server_is_explicit(tmp_path: Path):
    def unavailable(*args, **kwargs):
        raise OSError("offline")

    with pytest.raises(LocalReviewError, match="LLAMA_SERVER_UNAVAILABLE"):
        run_review(_context_root(tmp_path), opener=unavailable)


def test_mocked_api_response_creates_markdown(tmp_path: Path):
    root = _context_root(tmp_path)
    calls = []
    review = "# Critical Findings\n\nID: F-001\nSeverity: P1\n\n# Questions Before Release\n\nNone\n\n# Final Verdict\n\nNOT READY"

    def opener(request, timeout):
        calls.append((request.method, request.full_url, timeout, request.data))
        if request.method == "GET":
            return _Response({"data": [{"id": "Qwen3.8-27B-GGUF"}]})
        return _Response({"choices": [{"message": {"content": review}}]})

    output = tmp_path / "enza_memory/benchmark/reviews/qwen_v0.4_attack_review.md"
    result = run_review(root, output_path=output, opener=opener)
    assert result == output
    assert output.read_text(encoding="utf-8") == review + "\n"
    assert [call[0] for call in calls] == ["GET", "POST"]
    assert "/v1/models" in calls[0][1]
    assert "/v1/chat/completions" in calls[1][1]
    request_body = json.loads(calls[1][3])
    assert request_body["model"] == "Qwen3.8-27B-GGUF"
    assert "Attack the benchmark design" in request_body["messages"][0]["content"]


def test_context_missing_document_blocks_before_api(tmp_path: Path):
    root = _context_root(tmp_path)
    (root / CONTEXT_FILES[0]).unlink()

    def unexpected(*args, **kwargs):
        raise AssertionError("API must not be called")

    with pytest.raises(LocalReviewError, match="missing review context"):
        run_review(root, opener=lambda *args, **kwargs: _Response({"data": []}))
