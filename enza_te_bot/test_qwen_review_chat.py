from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.qwen_review_chat import (
    DEFAULT_ENDPOINT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    QwenReviewChat,
    QwenReviewChatError,
    main,
    parse_args,
    save_conversation,
)


class _Response:
    def __init__(self, events):
        lines = []
        for event in events:
            lines.extend([f"data: {json.dumps(event)}\n".encode(), b"\n"])
        lines.extend([b"data: [DONE]\n", b"\n"])
        self.lines = iter(lines)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def readline(self):
        return next(self.lines, b"")


def _opener_for(events, calls):
    def opener(request, timeout):
        calls.append((request, timeout))
        return _Response(events)

    return opener


def test_streaming_content_preserves_conversation_and_ignores_reasoning(tmp_path: Path):
    calls = []
    opener = _opener_for([
        {"choices": [{"delta": {"reasoning_content": "secret reasoning"}}]},
        {"choices": [{"delta": {"content": "first answer"}}]},
    ], calls)
    chat = QwenReviewChat(opener=opener)
    displayed = []
    answer, metrics = chat.send("Find weaknesses.", output=displayed.append)
    assert answer == "first answer"
    assert "secret reasoning" not in "".join(displayed)
    assert chat.messages[-1] == {"role": "assistant", "content": "first answer"}
    body = json.loads(calls[0][0].data)
    assert body["messages"][1] == {"role": "user", "content": "Find weaknesses."}
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
    assert metrics["tokens"] > 0


def test_follow_up_sends_prior_history(tmp_path: Path):
    calls = []
    events = [{"choices": [{"delta": {"content": "answer"}}]}]
    chat = QwenReviewChat(opener=_opener_for(events, calls))
    chat.send("Find issue 3.", output=lambda _: None)
    chat.opener = _opener_for(events, calls)
    chat.send("Expand issue 3.", output=lambda _: None)
    second_body = json.loads(calls[1][0].data)
    assert [message["role"] for message in second_body["messages"]] == ["system", "user", "assistant", "user"]
    assert second_body["messages"][-2]["content"] == "answer"


def test_save_command_writes_current_conversation(tmp_path: Path):
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "question"}]
    target = save_conversation(messages, tmp_path, now=lambda: __import__("datetime").datetime(2026, 9, 9, tzinfo=__import__("datetime").timezone.utc))
    assert target.name == "qwen_review_chat_20260909T000000Z.json"
    assert json.loads(target.read_text(encoding="utf-8")) == messages


def test_context_file_is_a_system_message(tmp_path: Path):
    context = tmp_path / "context.md"
    context.write_text("evidence", encoding="utf-8")
    chat = QwenReviewChat(context_file=context)
    assert chat.messages[1]["role"] == "system"
    assert "evidence" in chat.messages[1]["content"]


def test_reasoning_only_stream_fails_and_does_not_add_assistant():
    chat = QwenReviewChat(opener=_opener_for([
        {"choices": [{"delta": {"reasoning_content": "only reasoning"}}]},
    ], []))
    with pytest.raises(QwenReviewChatError, match="no answer content"):
        chat.send("Question", output=lambda _: None)
    assert [message["role"] for message in chat.messages] == ["system"]


def test_cli_configuration_arguments():
    args = parse_args(["--endpoint", "http://example/v1", "--model", "model.gguf", "--max-tokens", "123"])
    assert args.endpoint == "http://example/v1"
    assert args.model == "model.gguf"
    assert args.max_tokens == 123
    defaults = parse_args([])
    assert defaults.endpoint == DEFAULT_ENDPOINT
    assert defaults.model == DEFAULT_MODEL
    assert defaults.max_tokens == DEFAULT_MAX_TOKENS


def test_cli_save_and_exit_commands(tmp_path: Path, capsys):
    inputs = iter(["/save", "/clear", "/exit"])
    main(["--save-dir", str(tmp_path)], input_fn=lambda _: next(inputs), output=print,
         opener=lambda *args, **kwargs: pytest.fail("API must not be called"))
    captured = capsys.readouterr().out
    assert "Saved:" in captured
    assert "Conversation cleared." in captured
