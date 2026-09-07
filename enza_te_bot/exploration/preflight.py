"""Read-only startup preflight: structured checks, no bare tracebacks.

Each probe reports {"status": "ok"|"fail"|"skipped", "detail": ...} without
performing any mutation beyond a probe write into the memory root (removed
afterwards). The driver runs this before touching the live pipeline so a
misconfigured machine fails with one structured report instead of a stack
trace on frame one.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any, Callable


CHECK_IDS = (
    "agy_executable",
    "config_parse",
    "memory_writable",
    "paddle_available",
    "cdp_reachable",
    "game_tab_unique",
    "write_boundary_protection",
    "staging_allowlist",
    "unexpected_write_detection",
)


def _probe(check_id: str) -> Callable[[Callable[[], str | None]], dict[str, Any]]:
    def wrap(fn: Callable[[], str | None]) -> dict[str, Any]:
        try:
            detail = fn()
        except Exception as error:  # every probe failure is data, not a crash
            return {"check": check_id, "status": "fail",
                    "detail": f"{type(error).__name__}: {error}"}
        if detail is None:
            return {"check": check_id, "status": "ok", "detail": ""}
        return {"check": check_id, "status": "fail", "detail": detail}
    return wrap


def check_agy_executable(executable: str = "agy") -> dict[str, Any]:
    @_probe("agy_executable")
    def run() -> str | None:
        resolved = shutil.which(executable)
        if resolved is None:
            return (f"'{executable}' not found on PATH; the AGY CLI runner cannot "
                    f"dispatch. Install it or pass an absolute executable.")
        return None
    return run


def check_config_parse(config_path: Path, required_keys: tuple[str, ...] = ()) -> dict[str, Any]:
    @_probe("config_parse")
    def run() -> str | None:
        if not config_path.is_file():
            return f"config file missing: {config_path}"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        for key in required_keys:
            node = config
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return f"required config key missing: {key}"
                node = node[part]
        return None
    return run


def check_memory_writable(memory_root: Path) -> dict[str, Any]:
    @_probe("memory_writable")
    def run() -> str | None:
        memory_root.mkdir(parents=True, exist_ok=True)
        probe = memory_root / ".preflight_probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return None
    return run


def check_paddle_available() -> dict[str, Any]:
    @_probe("paddle_available")
    def run() -> str | None:
        try:
            import paddleocr  # noqa: F401
        except Exception as error:
            return f"PaddleOCR import failed (first-run model download may be pending): {error}"
        return None
    return run


def check_write_boundary_protection() -> dict[str, Any]:
    @_probe("write_boundary_protection")
    def run() -> str | None:
        from vision_agent.agy_vision_bridge import _write_boundary_snapshot
        return None if callable(_write_boundary_snapshot) else "snapshot guard unavailable"
    return run


def check_staging_allowlist() -> dict[str, Any]:
    @_probe("staging_allowlist")
    def run() -> str | None:
        from vision_agent.agy_vision_bridge import vision_request
        return None if callable(vision_request) else "staging allowlist unavailable"
    return run


def check_unexpected_write_detection() -> dict[str, Any]:
    @_probe("unexpected_write_detection")
    def run() -> str | None:
        from vision_agent.agy_vision_bridge import REASON_UNEXPECTED_ARTIFACT_WRITE
        return None if REASON_UNEXPECTED_ARTIFACT_WRITE else "reason code unavailable"
    return run


def check_cdp_and_tab(cdp_url: str | None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    if not cdp_url:
        results.append({"check": "cdp_reachable", "status": "skipped",
                        "detail": "no cdp_url configured for preflight"})
        results.append({"check": "game_tab_unique", "status": "skipped",
                        "detail": "depends on cdp_reachable"})
        return results

    @_probe("cdp_reachable")
    def probe_cdp() -> str | None:
        from browser_target import BrowserTarget

        with BrowserTarget(cdp_url):
            return None
    results.append(probe_cdp())

    @_probe("game_tab_unique")
    def probe_tab() -> str | None:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(cdp_url)
            try:
                matches = [
                    page for context in browser.contexts for page in context.pages
                    if "shinycolors.enza.fun" in page.url
                ]
            finally:
                browser.close()
        if len(matches) != 1:
            return (f"expected exactly one shinycolors.enza.fun tab, found "
                    f"{len(matches)}; refuse ambiguous targeting")
        return None
    results.append(probe_tab())
    return results


def run_preflight(
    *,
    executable: str = "agy",
    config_path: Path,
    memory_root: Path,
    cdp_url: str | None,
    required_config_keys: tuple[str, ...] = ("perception.home_observation",),
    include_paddle: bool = True,
    include_cdp: bool = True,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = [
        check_agy_executable(executable),
        check_config_parse(config_path, required_config_keys),
        check_memory_writable(memory_root),
        check_write_boundary_protection(),
        check_staging_allowlist(),
        check_unexpected_write_detection(),
    ]
    if include_paddle:
        checks.append(check_paddle_available())
    if include_cdp:
        checks.extend(check_cdp_and_tab(cdp_url))
    failed = [c["check"] for c in checks if c["status"] == "fail"]
    return {
        "preflight": "startup_preflight@1",
        "status": "PASS" if not failed else "FAIL",
        "failed_checks": failed,
        "checks": checks,
    }


__all__ = [
    "CHECK_IDS",
    "run_preflight",
]
