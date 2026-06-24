"""
MARK III — Browser Executor (Phase 12B)

Handles:
  open_url    (SAFE)   — open URL in default browser
  web_search  (SAFE)   — search the web (opens results page)
  browser_click (CAUTION) — click DOM element via Chrome extension or CDP
  browser_fill  (CAUTION) — fill form field via Chrome extension or CDP

For browser_click / browser_fill, integration with the Claude-in-Chrome
MCP is the preferred path.  Without it, we fall back to a simpler
webbrowser.open() + warning approach.

Optional packages:
  playwright  — headless browser automation (pip install playwright)
"""

from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
import webbrowser
from typing import Optional

from app.services.actions.base_action import Action, ActionResult, ActionType

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False


# Search engine URL templates
_SEARCH_ENGINES: dict[str, str] = {
    "google":    "https://www.google.com/search?q={query}",
    "bing":      "https://www.bing.com/search?q={query}",
    "duckduckgo":"https://duckduckgo.com/?q={query}",
    "brave":     "https://search.brave.com/search?q={query}",
}
_DEFAULT_ENGINE = "google"


class BrowserExecutor:

    async def run(self, action: Action) -> ActionResult:
        t0 = time.monotonic()
        try:
            result = await self._dispatch(action)
        except Exception as exc:
            result = ActionResult(success=False, error=str(exc))
        result.latency_ms = (time.monotonic() - t0) * 1000
        return result

    async def _dispatch(self, action: Action) -> ActionResult:
        t = action.action_type
        p = action.parameters

        if t == ActionType.OPEN_URL:
            return await asyncio.to_thread(self._open_url, p["url"])
        if t == ActionType.WEB_SEARCH:
            return await asyncio.to_thread(self._web_search, p["query"], p.get("engine"))
        if t == ActionType.BROWSER_CLICK:
            return await self._browser_click(p["selector"], p.get("url"))
        if t == ActionType.BROWSER_FILL:
            return await self._browser_fill(p["selector"], p["value"], p.get("url"))
        return ActionResult(success=False, error=f"Unknown browser action: {t}")

    # ------------------------------------------------------------------
    # SAFE: open URL
    # ------------------------------------------------------------------

    def _open_url(self, url: str) -> ActionResult:
        if not url.startswith(("http://", "https://", "ftp://")):
            url = "https://" + url
        try:
            webbrowser.open(url)
            return ActionResult(success=True, output=f"Opened {url}")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # SAFE: web search
    # ------------------------------------------------------------------

    def _web_search(self, query: str, engine: Optional[str] = None) -> ActionResult:
        template = _SEARCH_ENGINES.get(
            (engine or _DEFAULT_ENGINE).lower(),
            _SEARCH_ENGINES[_DEFAULT_ENGINE],
        )
        url = template.format(query=urllib.parse.quote_plus(query))
        try:
            webbrowser.open(url)
            return ActionResult(
                success  = True,
                output   = f"Searching for '{query}'",
                metadata = {"url": url, "engine": engine or _DEFAULT_ENGINE},
            )
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # CAUTION: browser click
    # ------------------------------------------------------------------

    async def _browser_click(
        self, selector: str, url: Optional[str] = None
    ) -> ActionResult:
        if _PLAYWRIGHT_AVAILABLE:
            return await self._playwright_click(selector, url)
        # Graceful degrade: open the page and tell the user what to click
        hint = f"Please click '{selector}' on the page manually."
        if url:
            await asyncio.to_thread(self._open_url, url)
        return ActionResult(
            success  = False,
            error    = "Playwright not installed — automated clicking unavailable.",
            metadata = {"hint": hint, "selector": selector},
            output   = hint,
        )

    async def _playwright_click(
        self, selector: str, url: Optional[str]
    ) -> ActionResult:
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
                page    = browser.contexts[0].pages[0] if browser.contexts else await browser.new_page()
                if url:
                    await page.goto(url, wait_until="networkidle", timeout=15000)
                await page.click(selector, timeout=10000)
                return ActionResult(success=True, output=f"Clicked '{selector}'")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # CAUTION: browser fill
    # ------------------------------------------------------------------

    async def _browser_fill(
        self, selector: str, value: str, url: Optional[str] = None
    ) -> ActionResult:
        if _PLAYWRIGHT_AVAILABLE:
            return await self._playwright_fill(selector, value, url)
        return ActionResult(
            success = False,
            error   = "Playwright not installed — automated form filling unavailable.",
            metadata = {"hint": f"Fill '{selector}' with the value manually.", "selector": selector},
        )

    async def _playwright_fill(
        self, selector: str, value: str, url: Optional[str]
    ) -> ActionResult:
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.connect_over_cdp("http://localhost:9222")
                page    = browser.contexts[0].pages[0] if browser.contexts else await browser.new_page()
                if url:
                    await page.goto(url, wait_until="networkidle", timeout=15000)
                await page.fill(selector, value, timeout=10000)
                return ActionResult(success=True, output=f"Filled '{selector}' with value")
        except Exception as exc:
            return ActionResult(success=False, error=str(exc))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_executor: Optional[BrowserExecutor] = None

def get_browser_executor() -> BrowserExecutor:
    global _executor
    if _executor is None:
        _executor = BrowserExecutor()
    return _executor
