from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.run_local_review import (
    CONTEXT_FILES,
    DEFAULT_MAX_TOKENS,
    LocalReviewError,
    build_context_bundle,
    run_review,
)


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class _StreamingResponse:
    def __init__(self, events):
        lines = []
        for event in events:
            lines.extend([f"data: {json.dumps(event)}\n".encode("utf-8"), b"\n"])
        lines.extend([b"data: [DONE]\n", b"\n"])
        self.lines = iter(lines)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def readline(self):
        return next(self.lines, b"")


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
        return _StreamingResponse([
            {"choices": [{"delta": {"content": review}}]},
            {"choices": [], "usage": {"completion_tokens": 17}},
        ])

    output = tmp_path / "enza_memory/benchmark/reviews/qwen_v0.4_attack_review.md"
    result = run_review(root, output_path=output, opener=opener)
    assert result == output
    assert output.read_text(encoding="utf-8") == review + "\n"
    assert [call[0] for call in calls] == ["GET", "POST"]
    assert "/v1/models" in calls[0][1]
    assert "/v1/chat/completions" in calls[1][1]
    request_body = json.loads(calls[1][3])
    assert request_body["model"] == "Qwen3.8-27B-GGUF"
    assert request_body["stream"] is True
    assert request_body["max_tokens"] == DEFAULT_MAX_TOKENS == 8192
    assert "Attack the benchmark design" in request_body["messages"][0]["content"]
    assert "After reasoning, provide the final Markdown review in the answer field." in request_body["messages"][0]["content"]
    assert "Do not stop after analysis." in request_body["messages"][0]["content"]


def test_configurable_max_tokens_is_passed_to_request(tmp_path: Path):
    root = _context_root(tmp_path)
    captured = {}

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        captured.update(json.loads(request.data))
        return _StreamingResponse([
            {"choices": [{"delta": {"content": "# Final Verdict\n\nREADY"}}]},
        ])

    run_review(root, output_path=tmp_path / "review.md", opener=opener, max_tokens=12288)
    assert captured["max_tokens"] == 12288


def test_nonpositive_max_tokens_fails_before_generation(tmp_path: Path):
    root = _context_root(tmp_path)

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        raise AssertionError("completion request must not be sent")

    with pytest.raises(LocalReviewError, match="max_tokens must be positive"):
        run_review(root, output_path=tmp_path / "review.md", opener=opener, max_tokens=0)


@pytest.mark.parametrize(
    "choice",
    [
        {"message": {"role": "assistant", "content": "# Final Verdict\n\nREADY", "reasoning_content": "ignore me"}},
        {"text": "# Final Verdict\n\nREADY", "reasoning_content": "ignore me"},
    ],
)
def test_nonstream_chat_response_formats_create_markdown(tmp_path: Path, choice):
    root = _context_root(tmp_path)

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        return _Response({"choices": [choice]})

    output = tmp_path / "review.md"
    run_review(root, output_path=output, opener=opener)
    assert output.read_text(encoding="utf-8") == "# Final Verdict\n\nREADY\n"


def test_empty_chat_content_is_clear_error(tmp_path: Path):
    root = _context_root(tmp_path)

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        return _Response({"choices": [{"message": {"content": "", "reasoning_content": "not output"}}]})

    with pytest.raises(LocalReviewError, match="empty Markdown"):
        run_review(root, output_path=tmp_path / "review.md", opener=opener)


def test_streaming_response_reports_progress(tmp_path: Path, capsys):
    root = _context_root(tmp_path)

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": [{"id": "Qwen3.8-27B-GGUF"}]})
        return _StreamingResponse([
            {"choices": [{"delta": {"content": "# Final Verdict\n\nREADY"}}]},
            {"choices": [], "usage": {"completion_tokens": 4}},
        ])

    run_review(root, output_path=tmp_path / "review.md", opener=opener)
    progress = capsys.readouterr().out
    assert "Model: Qwen3.8-27B-GGUF" in progress
    assert "Endpoint: http://localhost:8080/v1" in progress
    assert "Context loaded: yes" in progress
    assert "Starting generation..." in progress
    assert "Generating review..." in progress
    assert "tokens: 4" in progress
    assert "speed:" in progress
    assert "elapsed:" in progress
    assert "first token latency:" in progress
    assert "generated tokens: " in progress
    assert "tokens/sec:" in progress
    assert "elapsed:" in progress


def test_multiple_stream_chunks_report_client_side_metrics(tmp_path: Path, capsys):
    root = _context_root(tmp_path)

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        return _StreamingResponse([
            {"choices": [{"delta": {"role": "assistant"}}]},
            {"choices": []},
            {"choices": [{"delta": {"content": "# Final "}}]},
            {"choices": [{"delta": {"content": "Verdict\n\n"}}]},
            {"choices": [{"text": "READY"}]},
        ])

    output = tmp_path / "review.md"
    run_review(root, output_path=output, opener=opener)
    progress = capsys.readouterr().out
    assert output.read_text(encoding="utf-8") == "# Final Verdict\n\nREADY\n"
    assert progress.count("Generating review...") == 3
    assert "tokens: 2" in progress
    assert "speed:" in progress
    assert "elapsed:" in progress


def test_reasoning_stream_reports_thinking_without_persisting_reasoning(tmp_path: Path, capsys):
    root = _context_root(tmp_path)
    reasoning = "PRIVATE_REASONING_MUST_NOT_BE_WRITTEN"

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        return _StreamingResponse([
            {"choices": [{"delta": {"reasoning_content": reasoning}}]},
            {"choices": [{"delta": {"reasoning_content": " more reasoning"}}]},
            {"choices": [{"delta": {"content": "# Final Verdict\n\nREADY"}}]},
        ])

    output = tmp_path / "review.md"
    run_review(root, output_path=output, opener=opener)
    progress = capsys.readouterr().out
    assert "phase: THINKING" in progress
    assert "phase: ANSWERING" in progress
    assert "reasoning tokens: ~" in progress
    assert "answer tokens: 4" in progress
    assert reasoning not in output.read_text(encoding="utf-8")
    assert output.read_text(encoding="utf-8") == "# Final Verdict\n\nREADY\n"


def test_reasoning_only_stream_fails_without_creating_review(tmp_path: Path):
    root = _context_root(tmp_path)

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        return _StreamingResponse([
            {"choices": [{"delta": {"reasoning_content": "thinking only"}}]},
        ])

    output = tmp_path / "review.md"
    with pytest.raises(LocalReviewError, match="empty Markdown"):
        run_review(root, output_path=output, opener=opener)
    assert not output.exists()


def test_content_only_stream_writes_answer(tmp_path: Path):
    root = _context_root(tmp_path)

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        return _StreamingResponse([
            {"choices": [{"delta": {"content": "# Final Verdict\n\nREADY"}}]},
        ])

    output = tmp_path / "review.md"
    run_review(root, output_path=output, opener=opener)
    assert output.read_text(encoding="utf-8") == "# Final Verdict\n\nREADY\n"


def test_interrupted_stream_is_explicit(tmp_path: Path):
    root = _context_root(tmp_path)

    response = _StreamingResponse([])
    response.lines = iter([b'data: {"choices":[{"delta":{"content":"partial"}}]}\n'])

    def interrupted_opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        return response

    with pytest.raises(LocalReviewError, match="streaming response interrupted"):
        run_review(root, output_path=tmp_path / "review.md", opener=interrupted_opener)


def test_malformed_stream_chunk_is_explicit(tmp_path: Path):
    root = _context_root(tmp_path)

    class MalformedResponse(_StreamingResponse):
        def __init__(self):
            self.lines = iter([b"data: not-json\n", b"\n", b"data: [DONE]\n", b"\n"])

    def opener(request, timeout):
        if request.method == "GET":
            return _Response({"data": []})
        return MalformedResponse()

    with pytest.raises(LocalReviewError, match="invalid streaming JSON"):
        run_review(root, output_path=tmp_path / "review.md", opener=opener)


def test_context_missing_document_blocks_before_api(tmp_path: Path):
    root = _context_root(tmp_path)
    (root / CONTEXT_FILES[0]).unlink()

    def unexpected(*args, **kwargs):
        raise AssertionError("API must not be called")

    with pytest.raises(LocalReviewError, match="missing review context"):
        run_review(root, opener=lambda *args, **kwargs: _Response({"data": []}))
