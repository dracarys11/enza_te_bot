#!/usr/bin/env python3
"""Interactive human-in-the-loop chat client for the local ENZA Qwen reviewer."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_ENDPOINT = "http://localhost:8080/v1"
DEFAULT_MODEL = "/home/administrator/models/Qwen3.8-27B-GGUF/Qwen3.8-27B-UD-IQ3_S.gguf"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_SYSTEM_PROMPT = (
    "You are an ENZA benchmark adversarial reviewer.\n\n"
    "Your role is to challenge architecture, benchmark validity, evaluator correctness, "
    "reproducibility, and evidence integrity.\n\n"
    "Do not modify files.\n"
    "Do not implement fixes.\n"
    "Focus on finding concrete risks with evidence."
)
DEFAULT_SAVE_DIR = Path("enza_memory/benchmark/reviews/chat_sessions")


class QwenReviewChatError(RuntimeError):
    """A local interactive reviewer failure."""


def _approximate_token_count(text: str) -> int:
    return len(re.findall(r"\w+|[^\w\s]", text, flags=re.UNICODE))


def _read_response(response: Any) -> bytes:
    body = response.read()
    return body if isinstance(body, bytes) else body.encode("utf-8")


def _sse_events(response: Any) -> Iterable[dict[str, Any]]:
    if hasattr(response, "readline"):
        lines = iter(response.readline, b"")
    else:
        lines = iter(_read_response(response).splitlines())
    data_lines: list[str] = []
    completed = False

    def decode(data: str) -> dict[str, Any]:
        try:
            event = json.loads(data)
        except json.JSONDecodeError as exc:
            raise QwenReviewChatError("malformed streaming response") from exc
        if not isinstance(event, dict):
            raise QwenReviewChatError("malformed streaming event")
        return event

    for raw_line in lines:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        line = line.rstrip("\r\n")
        if not line:
            if data_lines:
                data = "\n".join(data_lines).strip()
                data_lines = []
                if data == "[DONE]":
                    completed = True
                    break
                yield decode(data)
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines and not completed:
        data = "\n".join(data_lines).strip()
        if data == "[DONE]":
            completed = True
        else:
            yield decode(data)
    if not completed:
        raise QwenReviewChatError("stream ended before [DONE]")


def _delta_content(event: dict[str, Any]) -> str:
    choices = event.get("choices", [])
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return ""
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        return ""
    content = delta.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(part.get("text", "") for part in content if isinstance(part, dict))
    return ""


def load_context_message(context_file: Path) -> dict[str, str]:
    try:
        content = context_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise QwenReviewChatError(f"cannot read context file: {context_file}") from exc
    return {
        "role": "system",
        "content": f"Context file: {context_file}\n\n{content}",
    }


def save_conversation(messages: list[dict[str, str]], save_dir: Path = DEFAULT_SAVE_DIR,
                      *, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now().strftime("%Y%m%dT%H%M%SZ")
    target = save_dir / f"qwen_review_chat_{timestamp}.json"
    target.write_text(json.dumps(messages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


class QwenReviewChat:
    def __init__(self, *, endpoint: str = DEFAULT_ENDPOINT, model: str = DEFAULT_MODEL,
                 max_tokens: int = DEFAULT_MAX_TOKENS, system_prompt: str = DEFAULT_SYSTEM_PROMPT,
                 context_file: Path | None = None,
                 opener: Callable[..., Any] = urllib.request.urlopen,
                 clock: Callable[[], float] = time.monotonic):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.max_tokens = max_tokens
        self.opener = opener
        self.clock = clock
        self._base_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if context_file is not None:
            self._base_messages.append(load_context_message(context_file))
        self.messages = list(self._base_messages)

    def clear(self) -> None:
        self.messages = list(self._base_messages)

    def send(self, user_text: str, *, output: Callable[[str], None] = print) -> tuple[str, dict[str, float | int]]:
        self.messages.append({"role": "user", "content": user_text})
        payload = {
            "model": self.model,
            "messages": self.messages,
            "temperature": 0.2,
            "max_tokens": self.max_tokens,
            "stream": True,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        request = urllib.request.Request(
            f"{self.endpoint}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = self.clock()
        parts: list[str] = []
        try:
            with self.opener(request, timeout=600) as response:
                for event in _sse_events(response):
                    text = _delta_content(event)
                    if text:
                        parts.append(text)
                        output(text)
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            self.messages.pop()
            raise QwenReviewChatError("local Qwen request failed") from exc
        answer = "".join(parts)
        if not answer.strip():
            self.messages.pop()
            raise QwenReviewChatError("local Qwen returned no answer content")
        self.messages.append({"role": "assistant", "content": answer})
        elapsed = self.clock() - started
        tokens = _approximate_token_count(answer)
        metrics: dict[str, float | int] = {
            "tokens": tokens,
            "elapsed": elapsed,
            "tok_per_sec": tokens / elapsed if elapsed > 0 else 0.0,
        }
        output(f"\n---\ntokens: {tokens}\nelapsed: {elapsed:.2f}s\ntok/s: {metrics['tok_per_sec']:.2f}\n------")
        return answer, metrics


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT)
    parser.add_argument("--context-file", type=Path, default=None)
    parser.add_argument("--save-dir", type=Path, default=DEFAULT_SAVE_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, input_fn: Callable[[str], str] = input,
         output: Callable[[str], None] = print,
         opener: Callable[..., Any] = urllib.request.urlopen) -> None:
    args = parse_args(argv)
    chat = QwenReviewChat(endpoint=args.endpoint, model=args.model, max_tokens=args.max_tokens,
                          system_prompt=args.system_prompt, context_file=args.context_file,
                          opener=opener)
    output("ENZA Local Qwen Review Chat")
    output("Commands: /exit, /clear, /save")
    while True:
        try:
            user_text = input_fn("You: ")
        except EOFError:
            break
        if user_text.strip() in {"/exit", "exit"}:
            break
        if user_text.strip() == "/clear":
            chat.clear()
            output("Conversation cleared.")
            continue
        if user_text.strip() == "/save":
            output(f"Saved: {save_conversation(chat.messages, args.save_dir)}")
            continue
        if not user_text.strip():
            continue
        output("\nQwen:")
        try:
            chat.send(user_text, output=output)
        except QwenReviewChatError as exc:
            output(f"Error: {exc}")


if __name__ == "__main__":
    main()
