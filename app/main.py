import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.status import HTTP_303_SEE_OTHER

from . import database as db
from . import fx
from .adapters import ADAPTERS, adapter_for
from .analysis import analyze, best_price_series, compare_sources, dominant_currency
from .refresh import refresh_all, refresh_product, refresh_source
from .scheduler import start_scheduler, stop_scheduler
from .scraper import ScrapeError, fetch_price
from .search import discover, flag_price_outliers
from .search import site_search
from .search.providers import SearchUnavailable, search_domains

# How many discovered listings we actually fetch prices for. Each fetch is a real
# page load (and a browser render for shops like Lazada), so this is the main
# thing standing between a useful page and a 60-second wait.
DISCOVER_PRICE_LIMIT = int(os.environ.get("DISCOVER_PRICE_LIMIT", "6"))
# Listings kept per shop. Search pages return dozens; only the best few are useful.
DISCOVER_PER_SHOP = int(os.environ.get("DISCOVER_PER_SHOP", "6"))
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


app = FastAPI(title="Price Drop Decision Tracker", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["known_retailers"] = [a.name for a in ADAPTERS]
templates.env.globals["fx_currencies"] = fx.DISPLAY_CURRENCIES
# Callables so every render sees the current setting without each route passing it.
templates.env.globals["current_display_currency"] = lambda: db.get_setting("display_currency")
templates.env.globals["fx_rates_age_hours"] = fx.rates_age_hours


def _latest_per_source(snapshots) -> dict:
    """Last known price per source, plus the error from the most recent attempt.

    Showing the last good price (rather than nothing) keeps a temporarily
    blocked retailer useful, while still surfacing that the last try failed.
    """
    latest: dict[int, dict] = {}
    for snap in snapshots:  # ordered oldest -> newest
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


def display_currency() -> str | None:
    """The currency the user asked to see prices in, if any and if we have rates."""
    chosen = db.get_setting("display_currency")
    return chosen if chosen and fx.available() else None


def _product_view(product) -> dict:
    sources = db.get_sources(product["id"])
    snapshots = db.get_snapshots_for_product(product["id"])
    currency = product["currency"] or dominant_currency(snapshots)

    shown_in = display_currency()
    to_display = fx.make_converter(shown_in)

    comparison = compare_sources(
        sources, _latest_per_source(snapshots), currency,
        to_display=to_display, display_currency=shown_in,
    )
    series = best_price_series(snapshots, currency, to_display=to_display)
    verdict = analyze(series, product["target_price"])

    return {
        "product": product,
        "verdict": verdict,
        "comparison": comparison,
        "currency": comparison.comparison_currency or currency,
        "original_currency": currency,
        "display_currency": shown_in,
        "series": series,
        "num_sources": len(sources),
    }


@app.get("/")
def dashboard(request: Request):
    views = [_product_view(p) for p in db.get_products()]
    return templates.TemplateResponse("index.html", {"request": request, "views": views})


@app.post("/settings/currency")
def set_display_currency(currency: str = Form(""), next_url: str = Form("/")):
    """Pick the currency prices are compared and shown in ('' = leave as quoted)."""
    choice = currency.strip().upper()
    db.set_setting("display_currency", choice or None)
    if choice:
        fx.refresh_rates()
    return RedirectResponse(url=next_url or "/", status_code=HTTP_303_SEE_OTHER)


@app.get("/discover")
def discover_page(request: Request, q: str = ""):
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
            "price_limit": DISCOVER_PRICE_LIMIT,
            "searched_domains": domains,
            "display_currency": display_currency(),
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
def discover_stream(q: str = ""):
    """Server-sent events, one message per shop as that shop's search finishes,
    then a summary.

    Each shop is searched on its own search page, so results arrive site by site
    and you can read one shop while the next is still loading. Ranking, conversion
    and outlier rules stay here rather than being reimplemented in JavaScript.
    """

    def events():
        query = q.strip()
        if not query:
            yield _sse({"type": "done", "priced": 0})
            return

        shown_in = display_currency()
        domains = search_domains()
        found: list = []

        use_site_search = site_search.playwright_available() and site_search.shops_for(domains)

        if use_site_search:
            for domain, retailer, candidates, error in site_search.search_all(
                query, domains, per_shop=DISCOVER_PER_SHOP
            ):
                rows = []
                for candidate in candidates:
                    candidate.index = len(found)
                    found.append(candidate)
                    rows.append(_candidate_row(candidate, shown_in))
                yield _sse({"type": "shop", "domain": domain, "retailer": retailer,
                            "rows": rows, "error": error})
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
        missing = [c for c in sorted(found, key=lambda c: c.score, reverse=True)
                   if c.price is None][:DISCOVER_PRICE_LIMIT]
        for candidate in missing:
            payload = {"type": "price", "index": candidate.index}
            try:
                result = fetch_price(candidate.url, timeout=30)
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


@app.post("/discover/track")
def track_from_discovery(
    name: str = Form(...),
    urls: list[str] = Form(default=[]),
    target_price: str = Form(""),
):
    """Turn the listings the user confirmed into a tracked product."""
    chosen = [u for u in urls if u.strip()]
    if not chosen:
        return RedirectResponse(url="/discover", status_code=HTTP_303_SEE_OTHER)

    target = float(target_price) if target_price.strip() else None
    product_id = db.add_product(name=name, target_price=target)
    for url in chosen:
        db.add_source(product_id, url=url, price_selector=None)
    refresh_product(product_id)
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/products")
def create_product(
    name: str = Form(...),
    url: str = Form(...),
    price_selector: str = Form(""),
    target_price: str = Form(""),
):
    target = float(target_price) if target_price.strip() else None
    product_id = db.add_product(name=name, target_price=target)
    db.add_source(product_id, url=url, price_selector=price_selector.strip() or None)
    refresh_product(product_id)  # fetch an initial price right away
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/products/{product_id}/sources")
def create_source(product_id: int, url: str = Form(...), price_selector: str = Form("")):
    if db.get_product(product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    source_id = db.add_source(product_id, url=url, price_selector=price_selector.strip() or None)
    refresh_source(source_id)
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/sources/{source_id}/delete")
def remove_source(source_id: int):
    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    product_id = source["product_id"]
    db.delete_source(source_id)
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/products/{product_id}/delete")
def remove_product(product_id: int):
    db.delete_product(product_id)
    return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)


@app.post("/products/{product_id}/refresh")
def refresh_one(product_id: int):
    refresh_product(product_id)
    return RedirectResponse(url=f"/product/{product_id}", status_code=HTTP_303_SEE_OTHER)


@app.post("/refresh")
def refresh_everything():
    refresh_all()
    return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)


@app.get("/product/{product_id}")
def product_detail(request: Request, product_id: int):
    product = db.get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    view = _product_view(product)
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
        snaps = [s for s in db.get_snapshots(source["id"]) if s["price"] is not None]
        if not snaps:
            continue
        seen_names[source["retailer"]] = seen_names.get(source["retailer"], 0) + 1
        count = seen_names[source["retailer"]]
        per_source_series.append({
            "retailer": source["retailer"] if count == 1 else f"{source['retailer']} #{count}",
            "color_index": color_index[source["id"]],
            "labels": [s["fetched_at"] for s in snaps],
            "prices": [s["price"] for s in snaps],
        })

    return templates.TemplateResponse(
        "product.html",
        {
            "request": request,
            **view,
            "sources": sources,
            "color_index": color_index,
            "per_source_series": per_source_series,
            "snapshots": list(reversed(db.get_snapshots_for_product(product_id))),
        },
    )
