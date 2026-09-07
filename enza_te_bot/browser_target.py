"""Strict CDP targeting for the single allowed Shiny Colors browser page."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

ALLOWED_HOST = "shinycolors.enza.fun"


class TargetError(RuntimeError):
    """Raised when a unique, permitted browser page cannot be established."""


def is_allowed_url(url: str) -> bool:
    return urlparse(url).hostname == ALLOWED_HOST


@dataclass
class BrowserTarget:
    """A CDP attachment that focuses and validates one permitted page only."""

    cdp_url: str
    playwright: Playwright | None = None
    browser: Browser | None = None
    page: Page | None = None

    def __enter__(self) -> "BrowserTarget":
        if not self.cdp_url:
            raise TargetError("browser.cdp_url is not configured; refusing to target a browser tab.")
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.connect_over_cdp(self.cdp_url)
            matches = [page for context in self.browser.contexts for page in context.pages if is_allowed_url(page.url)]
            if len(matches) != 1:
                raise TargetError(f"Expected exactly one {ALLOWED_HOST} page, found {len(matches)}; refusing to automate.")
            self.page = matches[0]
            self.verify_and_focus()
            return self
        except TargetError:
            self.__exit__(None, None, None)
            raise
        except Exception as error:
            self.__exit__(None, None, None)
            raise TargetError(f"Could not connect to Chrome CDP at {self.cdp_url}: {error}") from error

    def __exit__(self, *_unused) -> None:
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()
        self.browser = self.page = self.playwright = None

    def verify_and_focus(self) -> None:
        """Refuse navigation away from the allowed hostname, then foreground the page."""
        if self.page is None or self.page.is_closed() or not is_allowed_url(self.page.url):
            raise TargetError("Target page is closed or is no longer shinycolors.enza.fun; refusing to automate.")
        self.page.bring_to_front()

    def viewport_signature(self) -> dict:
        """Return viewport dimensions used to invalidate a manual fallback after resize."""
        self.verify_and_focus()
        assert self.page is not None
        metrics = self.page.evaluate("() => ({width: innerWidth, height: innerHeight, dpr: devicePixelRatio})")
        return {key: round(float(value), 3) for key, value in metrics.items()}

    def dynamic_game_window(self, config: dict) -> dict:
        """Find one large visible game canvas/iframe and map its DOM box to screen pixels.

        Screen mapping uses Chrome's window and viewport metrics. If the DOM has no
        unique candidate, an explicitly recorded, same-viewport calibration is the
        only fallback; arbitrary fixed coordinates are never silently used.
        """
        self.verify_and_focus()
        assert self.page is not None
        info = self.page.evaluate(
            """() => {
              const visible = [...document.querySelectorAll('canvas, iframe')]
                .map(el => { const r = el.getBoundingClientRect(); return {
                  tag: el.tagName.toLowerCase(), id: el.id, cls: el.className || '', src: el.src || '',
                  left: r.left, top: r.top, width: r.width, height: r.height,
                  visible: r.width >= 160 && r.height >= 90 && getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none'
                }; }).filter(x => x.visible);
              return {visible, screenX, screenY, outerWidth, outerHeight, innerWidth, innerHeight, dpr: devicePixelRatio};
            }"""
        )
        candidates = info["visible"]
        if len(candidates) == 1:
            item = candidates[0]
            # Browser chrome consumes the outer-minus-inner dimensions. Side borders
            # are split evenly; remaining vertical chrome sits above the viewport.
            side_border = max(0.0, (info["outerWidth"] - info["innerWidth"]) / 2)
            top_chrome = max(0.0, info["outerHeight"] - info["innerHeight"] - side_border)
            left = round(info["screenX"] + side_border + item["left"])
            top = round(info["screenY"] + top_chrome + item["top"])
            window = {"left": left, "top": top, "width": round(item["width"]), "height": round(item["height"])}
            if window["width"] > 0 and window["height"] > 0:
                return window
        fallback = config.get("fallback_game_window")
        if fallback and fallback.get("viewport_css") == self.viewport_signature():
            return {key: int(fallback[key]) for key in ("left", "top", "width", "height")}
        raise TargetError("No unique visible game canvas/iframe, and no valid same-viewport calibration; refusing to use stale coordinates.")
