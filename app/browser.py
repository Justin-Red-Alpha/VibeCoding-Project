"""The one place Chromium is started and pages are opened.

Why this exists: Playwright's sync API builds its event loop from the process-wide
asyncio policy, and `uvicorn --reload` on Windows sets that policy to the Selector
loop, which cannot start subprocesses. Launching Chromium then died with
NotImplementedError and every search sat on "searching..." forever. `run()` gives
Playwright a loop it creates itself, whatever the server configured.

Pages also skip images, fonts and media. Titles and prices are text, and those
downloads were most of a search page's load time (Amazon ~9.6 s -> ~1.3 s).
"""

import asyncio
import sys
from contextlib import asynccontextmanager

from .scraper import BROWSER_HEADERS

# Never needed to read a title or a price. Scripts, XHR and CSS still load, so
# prices that shops paint with JavaScript (Lazada) still appear.
SKIPPED_RESOURCES = frozenset({"image", "font", "media"})


class BrowserUnavailable(RuntimeError):
    """Chromium could not be started, so nothing can be rendered."""


def run(coro):
    """Run `coro` to completion on a fresh loop that can start subprocesses.

    Call it from a thread with no running loop -- a threadpool worker, the
    scheduler, or a thread of our own -- never from inside async code.
    """
    factory = asyncio.ProactorEventLoop if sys.platform == "win32" else None
    return asyncio.run(coro, loop_factory=factory)


@asynccontextmanager
async def chromium():
    """A headless Chromium for the duration of the block."""
    from playwright.async_api import async_playwright

    try:
        playwright = await async_playwright().start()
    except Exception as exc:
        raise BrowserUnavailable(f"Could not start the browser driver: {exc}") from exc
    try:
        try:
            browser = await playwright.chromium.launch(headless=True)
        except Exception as exc:
            raise BrowserUnavailable(f"Could not start Chromium: {exc}") from exc
        try:
            yield browser
        finally:
            await browser.close()
    finally:
        await playwright.stop()


async def _skip_heavy(route):
    if route.request.resource_type in SKIPPED_RESOURCES:
        await route.abort()
    else:
        await route.continue_()


async def new_page(browser):
    """A page in its own context that looks like an ordinary desktop visitor.
    Close it with `await page.context.close()`."""
    context = await browser.new_context(
        user_agent=BROWSER_HEADERS["User-Agent"],
        locale="en-SG",
        viewport={"width": 1366, "height": 900},
    )
    await context.route("**/*", _skip_heavy)
    return await context.new_page()
