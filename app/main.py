import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from pathlib import Path

from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, Form, Request, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.status import HTTP_303_SEE_OTHER

from . import auth
from . import database as db
from . import fx
from . import history
from . import site_settings
from .account import router as account_router
from .admin import router as admin_router
from .adapters import adapter_for
from .templating import display_currency_for, templates
from .browser import BrowserUnavailable
from .analysis import analyze, best_price_series, compare_sources, dominant_currency, target_in
from .refresh import refresh_product, refresh_products, refresh_source
from . import scheduler
from .scheduler import start_scheduler, stop_scheduler
from .scraper import ScrapeError, fetch_price
from .search import discover, flag_price_outliers
from .search import site_search
from .search.providers import SearchUnavailable, search_domains

# Discovery limits (listings kept per shop, missing prices looked up per search)
# are admin settings now: see site_settings.discover_per_shop / discover_price_limit.
# Product pages fetched at once for listings whose search card had no price.
# Small on purpose: roughly a person opening three tabs on the same shop.
PRICE_LOOKUP_CONCURRENCY = 3
# Minimum match score allowed to set the headline "best price". Matches the
# "medium confidence" boundary in the UI, so the banner never claims a saving
# based on a listing the page itself marks as a doubtful match.
MIN_HEADLINE_SCORE = 0.45

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    try:
        fx.refresh_rates()
    except Exception:  # conversion is optional; never block startup on it
        logging.getLogger("price_tracker").warning("Could not load FX rates at startup")
    start_scheduler()
    yield
    stop_scheduler()


class SameSitePostGuard:
    """Refuse state-changing requests that another website made the browser send.

    SameSite=Lax cookies are the main defence; this is the second. A browser always
    sends Origin (or at least Referer) on a cross-site form post, so if either names
    a different host, it's refused. Requests with neither (curl, tests) pass.
    Pure ASGI rather than @app.middleware, so the SSE stream is never buffered.
    """

    UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in self.UNSAFE:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                       for k, v in scope["headers"]}
            source = headers.get("origin") or headers.get("referer")
            if source is not None:
                host = urlparse(source).netloc if source != "null" else "null"
                if host != headers.get("host", ""):
                    response = PlainTextResponse(
                        "Refused: this form was submitted from another website.", status_code=403)
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


app = FastAPI(title="Price Drop Decision Tracker", lifespan=lifespan)
app.add_middleware(SameSitePostGuard)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.include_router(account_router)
app.include_router(admin_router)


@app.exception_handler(auth.LoginRequired)
def _to_login(request: Request, exc: auth.LoginRequired):
    return RedirectResponse(url=f"/login?next={quote(auth.local_path(exc.next_path))}",
                            status_code=HTTP_303_SEE_OTHER)


def _latest_per_source(snapshots) -> dict:
    """Last known price per source, plus the error from the most recent attempt.

    Showing the last good price (rather than nothing) keeps a temporarily
    blocked retailer useful, while still surfacing that the last try failed.

    Live checks only. An archived copy can be newer than the last live check, and
    it would then pose as the current price, so archived rows are skipped here.
    They still count in the history (best_price_series).
    """
    latest: dict[int, dict] = {}
    for snap in snapshots:  # ordered oldest -> newest
        if "origin" in snap.keys() and snap["origin"]:
            continue
        entry = latest.setdefault(
            snap["source_id"],
            {"price": None, "currency": None, "fetched_at": None, "error": None},
        )
        if snap["price"] is not None:
            entry["price"] = snap["price"]
            entry["currency"] = snap["currency"]
            entry["fetched_at"] = snap["fetched_at"]
            entry["error"] = None
        else:
            entry["error"] = snap["error"]
    return latest


def display_currency(user=None) -> str | None:
    """The currency this visitor sees prices in (their own choice, else the site
    default), and only if we have rates to convert with."""
    chosen = display_currency_for(user)
    return chosen if chosen and fx.available() else None


def _product_view(product, user=None) -> dict:
    sources = db.get_sources(product["id"])
    snapshots = db.get_snapshots_for_product(product["id"])
    currency = product["currency"] or dominant_currency(snapshots)

    shown_in = display_currency(user)
    to_display = fx.make_converter(shown_in)

    comparison = compare_sources(
        sources, _latest_per_source(snapshots), currency,
        to_display=to_display, display_currency=shown_in,
    )
    series = best_price_series(snapshots, currency, to_display=to_display)
    history_currency = shown_in or currency

    # The target keeps the currency it was entered in; products from before that
    # choice existed have none, meaning "the product's own currency". Restate it
    # in the history's currency before comparing, or a ringgit target would be
    # read as dollars. If it can't be restated, show it but leave it out.
    target_price = product["target_price"]
    target_currency = product["target_currency"] or currency
    target_for_analysis = target_in(target_price, target_currency, history_currency, fx.convert)
    target_not_applied = target_price is not None and target_for_analysis is None

    verdict = analyze(series, target_for_analysis)

    return {
        "product": product,
        "verdict": verdict,
        "comparison": comparison,
        "currency": comparison.comparison_currency or currency,
        "original_currency": currency,
        "target_currency": target_currency,
        # Only worth showing when it differs from the figure the user typed.
        "target_display_price": (
            target_for_analysis if target_currency != history_currency else None
        ),
        "target_not_applied": target_not_applied,
        "display_currency": shown_in,
        "history_currency": history_currency,
        "series": series,
        "num_sources": len(sources),
    }


@app.get("/")
def dashboard(request: Request, refreshing: str = "", user=Depends(auth.require_user)):
    """Only the signed-in user's own products (admins included)."""
    views = [_product_view(p, user) for p in db.get_products_for_user(user["id"])]
    return templates.TemplateResponse("index.html", {
        "request": request, "views": views, "refreshing": refreshing == "1"})


@app.get("/discover")
def discover_page(request: Request, q: str = ""):
    """Public: anyone may search. Tracking the results needs an account."""
    """Render matches straight away; prices stream in afterwards via /discover/stream.

    Pricing is the slow part (browser renders take seconds each), so blocking the
    page on it would mean staring at nothing for half a minute. The search result
    is cached, so the stream re-reads the same candidate list.
    """
    query = q.strip()
    domains = search_domains()

    # Render a section per shop up front, each showing "searching…", and let the
    # stream fill them in. Nothing blocks on the slowest shop.
    shops = [{"domain": domain, "retailer": adapter.name, "searchable": adapter.supports_site_search}
             for adapter, domain in [(adapter_for(f"https://www.{d}/"), d) for d in domains]]

    return templates.TemplateResponse(
        "discover.html",
        {
            "request": request,
            "query": query,
            "shops": shops,
            "price_limit": site_settings.discover_price_limit(),
            "searched_domains": domains,
            "display_currency": display_currency(auth.current_user(request)),
            "browser_available": site_search.playwright_available(),
        },
    )


def _candidate_row(candidate, shown_in: str | None) -> dict:
    """One listing, as the page needs it."""
    return {
        "index": candidate.index,
        "title": candidate.title,
        "url": candidate.url,
        "retailer": candidate.retailer,
        "score": candidate.score,
        "confidence": candidate.confidence,
        "flags": candidate.flags,
        "price": candidate.price,
        "currency": candidate.currency,
        "display_price": fx.convert(candidate.price, candidate.currency, shown_in),
        "display_currency": shown_in,
        "error": candidate.price_error,
    }


@app.get("/discover/stream")
def discover_stream(request: Request, q: str = ""):
    """Server-sent events, one message per shop as that shop's search finishes,
    then a summary.

    Each shop is searched on its own search page, so results arrive site by site
    and you can read one shop while the next is still loading. Ranking, conversion
    and outlier rules stay here rather than being reimplemented in JavaScript.
    Public, like the search page: the visitor's currency is theirs if signed in,
    else the site default.
    """
    # Settled now, in the request, not later inside the generator.
    shown_in = display_currency(auth.current_user(request))
    per_shop = site_settings.discover_per_shop()
    price_limit = site_settings.discover_price_limit()

    def events():
        query = q.strip()
        if not query:
            yield _sse({"type": "done", "priced": 0})
            return

        domains = search_domains()
        found: list = []

        use_site_search = site_search.playwright_available() and site_search.shops_for(domains)

        if use_site_search:
            try:
                for domain, retailer, candidates, error in site_search.search_all(
                    query, domains, per_shop=per_shop
                ):
                    rows = []
                    for candidate in candidates:
                        candidate.index = len(found)
                        found.append(candidate)
                        rows.append(_candidate_row(candidate, shown_in))
                    yield _sse({"type": "shop", "domain": domain, "retailer": retailer,
                                "rows": rows, "error": error})
            except BrowserUnavailable as exc:
                # Say so, rather than dropping the stream and leaving every shop
                # on "searching..." -- which reads as slow, not broken.
                yield _sse({"type": "error", "message": (
                    f"The browser used to search shops couldn't start, so the search "
                    f"stopped. {exc}")})
                return
        else:
            # No browser: fall back to web search, then price each listing.
            yield _sse({"type": "note", "message": (
                "Playwright isn't installed, so shops can't be searched directly. "
                "Falling back to web search, which is slower and gets rate-limited.")})
            try:
                candidates = discover(query)
            except SearchUnavailable as exc:
                yield _sse({"type": "error", "message": str(exc)})
                return
            for candidate in candidates:
                candidate.index = len(found)
                found.append(candidate)
            yield _sse({"type": "shop", "domain": "web search", "retailer": "Web search",
                        "rows": [_candidate_row(c, shown_in) for c in found], "error": None})

        # Shops don't always print a price on the search page (Amazon often
        # doesn't). Spend the remaining budget fetching those product pages, best
        # matches first, so the comparison isn't full of holes.
        # A few at a time, each shown as it lands: one at a time was ~2 s per
        # listing in a row. Candidates are only touched here, never in a worker.
        missing = [c for c in sorted(found, key=lambda c: c.score, reverse=True)
                   if c.price is None][:price_limit]
        pool = ThreadPoolExecutor(max_workers=PRICE_LOOKUP_CONCURRENCY)
        try:
            lookups = {pool.submit(fetch_price, c.url, timeout=30): c for c in missing}
            for lookup in as_completed(lookups):
                candidate = lookups[lookup]
                payload = {"type": "price", "index": candidate.index}
                try:
                    result = lookup.result()
                    candidate.price = result.price
                    candidate.currency = result.currency
                    payload.update(
                        price=result.price,
                        currency=result.currency,
                        display_price=fx.convert(result.price, result.currency, shown_in),
                        display_currency=shown_in,
                    )
                except ScrapeError as exc:
                    candidate.price_error = str(exc)
                    payload["error"] = str(exc)
                except Exception as exc:  # one bad listing must not kill the stream
                    candidate.price_error = f"Unexpected error: {exc}"
                    payload["error"] = str(exc)
                yield _sse(payload)
        finally:
            # If the user leaves mid-search, don't start lookups nobody will see.
            pool.shutdown(wait=False, cancel_futures=True)

        yield _sse(_discovery_summary(found, shown_in))

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _discovery_summary(candidates, shown_in: str | None) -> dict:
    """Outlier flags plus the best price, computed once every price is in.

    The headline price is taken only from listings that plausibly ARE the product
    searched for. Ranking every result by price alone makes a cheaper different
    model the "best price" -- a search for WH-1000XM5 surfaced a WH-CH520 at
    SGD 17.69 and announced a 96% saving. A deal finder that does that is worse
    than useless, so low-confidence matches are excluded from the headline even
    though they stay visible in their shop's list.
    """
    flag_price_outliers(candidates)  # may lower scores, so run before filtering

    def comparable(candidate):
        if shown_in:
            return fx.convert(candidate.price, candidate.currency, shown_in)
        return candidate.price

    # A listing we've already warned about must not become the headline: saying
    # "probably not the same item" and "best price found" about one listing is a
    # contradiction, and the cheap one is the one that fakes a big saving.
    usable = [c for c in candidates
              if comparable(c) is not None
              and c.score >= MIN_HEADLINE_SCORE
              and not c.price_suspect]
    currencies = {c.currency for c in usable if c.currency}
    # Without conversion, differing currencies can't be ranked against each other.
    if not shown_in and len(currencies) > 1:
        usable = []

    summary = {
        "type": "done",
        "priced": sum(1 for c in candidates if c.price is not None),
        "considered": len(usable),
        "mixed_currency": len(currencies) > 1 and not shown_in,
        "flags": {c.index: c.flags for c in candidates if c.flags},
        "scores": {c.index: c.score for c in candidates},
    }
    if usable:
        cheapest = min(usable, key=comparable)
        dearest = max(usable, key=comparable)
        low, high = comparable(cheapest), comparable(dearest)
        summary.update(
            cheapest_index=cheapest.index,
            best_price=low,
            best_retailer=cheapest.retailer,
            currency=shown_in or cheapest.currency,
        )
        if high > low:
            summary.update(
                savings=round(high - low, 2),
                savings_pct=round(100 * (high - low) / high),
                dearest_retailer=dearest.retailer,
            )
    return summary


def _target_currency(target: float | None, choice: str) -> str | None:
    """The currency a target was typed in. '' means "the shop's own currency",
    stored as None. Anything we can't convert is refused rather than stored,
    since a target nobody can compare would just sit there looking applied."""
    code = choice.strip().upper()
    if code and code not in fx.DISPLAY_CURRENCIES:
        raise HTTPException(status_code=400, detail=f"Unsupported target currency: {code}")
    if target is None or not code:
        return None
    return code


@app.post("/discover/track")
def track_from_discovery(
    name: str = Form(...),
    urls: list[str] = Form(default=[]),
    target_price: str = Form(""),
    target_currency: str = Form(""),
    user=Depends(auth.require_user),
):
    """Turn the listings the user confirmed into a product they track."""
    chosen = [u for u in urls if u.strip()]
    if not chosen:
        return RedirectResponse(url="/discover", status_code=HTTP_303_SEE_OTHER)

    target = float(target_price) if target_price.strip() else None
    currency = _target_currency(target, target_currency)
    product_id = db.add_product(name=name, target_price=target, target_currency=currency,
                                user_id=user["id"])
    for url in chosen:
        db.add_source(product_id, url=url, price_selector=None)
    refresh_product(product_id)
    history.schedule_backfill(product_id)  # past prices, in the background
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/products")
def create_product(
    name: str = Form(...),
    url: str = Form(...),
    price_selector: str = Form(""),
    target_price: str = Form(""),
    target_currency: str = Form(""),
    user=Depends(auth.require_user),
):
    target = float(target_price) if target_price.strip() else None
    currency = _target_currency(target, target_currency)
    product_id = db.add_product(name=name, target_price=target, target_currency=currency,
                                user_id=user["id"])
    db.add_source(product_id, url=url, price_selector=price_selector.strip() or None)
    refresh_product(product_id)  # fetch an initial price right away
    history.schedule_backfill(product_id)  # past prices, in the background
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/products/{product_id}/sources")
def create_source(product_id: int, url: str = Form(...), price_selector: str = Form(""),
                  user=Depends(auth.require_user)):
    auth.product_for(user, product_id)  # someone else's product is a 404
    source_id = db.add_source(product_id, url=url, price_selector=price_selector.strip() or None)
    refresh_source(source_id)
    history.schedule_backfill(product_id)  # only the new listing: others are already checked
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/products/{product_id}/history")
def lookup_history(product_id: int, user=Depends(auth.require_user)):
    """Re-check the price archive for every listing of this product."""
    auth.product_for(user, product_id)
    history.schedule_backfill(product_id, only_unchecked=False)
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/sources/{source_id}/delete")
def remove_source(source_id: int, user=Depends(auth.require_user)):
    source = auth.source_for(user, source_id)
    db.delete_source(source_id)
    return RedirectResponse(url=f"/product/{source['product_id']}", status_code=HTTP_303_SEE_OTHER)


@app.post("/products/{product_id}/delete")
def remove_product(product_id: int, user=Depends(auth.require_user)):
    auth.product_for(user, product_id)
    db.delete_product(product_id)
    return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)


@app.post("/products/{product_id}/refresh")
def refresh_one(product_id: int, user=Depends(auth.require_user)):
    auth.product_for(user, product_id)
    refresh_product(product_id)
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/refresh")
def refresh_mine(user=Depends(auth.require_user)):
    """"Refresh my prices": the signed-in user's products only, in the background.

    One job per user: a second click while it's queued or running does nothing.
    It also takes turns with any other batch refresh (refresh._batch_lock), so the
    shops never see two refresh loops at once. An admin refreshes everyone's from
    the admin page.
    """
    product_ids = [p["id"] for p in db.get_products_for_user(user["id"])]
    scheduler.run_once(f"refresh-user-{user['id']}", refresh_products, product_ids)
    return RedirectResponse(url="/?refreshing=1", status_code=HTTP_303_SEE_OTHER)


def _chart_points(snapshots, shown_in: str | None, primary_currency: str | None, convert):
    """One shop's chart line, in exactly one currency: the display currency if one
    is selected, else the product's own. A point that can't be expressed in it is
    left out -- plotting it at face value would put unlike currencies on one axis.
    `convert` has fx.convert's contract."""
    points = []
    for snap in snapshots:
        if snap["price"] is None:
            continue
        if shown_in:
            price = convert(snap["price"], snap["currency"], shown_in)
        elif snap["currency"] and snap["currency"] == primary_currency:
            price = snap["price"]
        else:
            price = None
        if price is not None:
            points.append((snap["fetched_at"], price))
    return points


@app.get("/product/{product_id}")
def product_detail(request: Request, product_id: int, user=Depends(auth.require_user)):
    product = auth.product_for(user, product_id)

    view = _product_view(product, user)
    sources = db.get_sources(product_id)

    # Colour is assigned by source in creation order and never cycled, so the dot
    # in the comparison table always matches that retailer's line in the chart.
    # (8 categorical slots exist; a 9th+ source reuses the last rather than
    # generating a new hue.)
    color_index = {source["id"]: min(i, 7) for i, source in enumerate(sources)}

    # One chart line per source. Two listings on the same shop get numbered so
    # the legend stays unambiguous.
    seen_names: dict[str, int] = {}
    per_source_series = []
    for source in sources:
        points = _chart_points(
            db.get_snapshots(source["id"]),
            view["display_currency"], view["original_currency"], fx.convert,
        )
        if not points:
            continue
        seen_names[source["retailer"]] = seen_names.get(source["retailer"], 0) + 1
        count = seen_names[source["retailer"]]
        per_source_series.append({
            "retailer": source["retailer"] if count == 1 else f"{source['retailer']} #{count}",
            "color_index": color_index[source["id"]],
            "labels": [stamp for stamp, _ in points],
            "prices": [price for _, price in points],
        })

    return templates.TemplateResponse(
        "product.html",
        {
            "request": request,
            **view,
            "sources": sources,
            "history_by_source": {
                s["id"]: {"note": s["history_note"], "checked_at": s["history_checked_at"]}
                for s in sources
            },
            "color_index": color_index,
            "per_source_series": per_source_series,
            "snapshots": list(reversed(db.get_snapshots_for_product(product_id))),
            "history_paused": site_settings.history_paused(),
            "owner": db.get_user(product["user_id"]) if product["user_id"] else None,
        },
    )
