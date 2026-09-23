# Price Drop Decision Tracker

A local deal-hunting web app. Type a product **name**, and it searches the shops,
prices up the matches, shows you where it's cheapest — then tracks the ones you
keep and **automatically decides** whether now is a good time to buy.

1. **Find** — search by product name, or paste a shop URL directly.
2. **Match** — candidate listings are scored against your query, so a *carrying
   case* doesn't get compared against the headphones.
3. **Confirm** — you tick the listings that are genuinely the same product.
4. **Track** — each becomes a source, re-priced automatically every few hours.
5. **Decide** — the app works out where it's cheapest *and* whether the best
   available price is good by historical standards: **BUY NOW**, **WAIT**,
   **NEUTRAL**, or **NOT ENOUGH DATA**.

Prices stream in one at a time as each shop is checked, grouped by shop, so you
can start reading results while the rest are still loading. Pick a currency in
**Show prices in** and listings from different countries are converted and ranked
together.

## Reality check — read this first

Most price-tracker tutorials skip this part. Measured from a normal connection in
September 2026:

### Getting prices

| Shop | Works? | Detail |
|---|---|---|
| **eBay**, **Qoo10**, schema.org sites | Usually | Server-rendered or publish JSON-LD. |
| **Any shop + your CSS selector** | Usually | You point at the price element. |
| **Lazada** | Yes, **needs Playwright** | See the warning below — this one is subtle. |
| **Amazon** | Often blocked | Serves a bot-check page disguised as a 404/503/200. |
| **Shopee** | Usually blocked | Item API returns 403 to most non-app traffic. |

> ### ⚠️ The Lazada list-price trap
> Lazada's server HTML contains a `pdt_price` field. It is **the crossed-out list
> price, not what you'd pay.** On a test listing it read **$589.00** while the page
> actually sold the item for **$345.50**.
>
> Scraping that field — the obvious thing to do — would inflate every price by 70%
> and invent savings that don't exist. This app deliberately ignores it and renders
> the page in a real browser to read the true price (`SGD 345.50`, verified).
> **Install Playwright or Lazada won't work.**

### Finding products by name

**Each shop is searched on its own search page**, rendered in a real browser. That
needs Playwright, and it's much better than going through a web search engine:
no shared query budget, and the shop's result cards already carry prices, so one
page render prices a whole shop's results.

Results stream **per shop**, so the page fills in site by site instead of waiting
for the slowest one.

| Shop | Site search |
|---|---|
| **Amazon** | works well (~48 cards) — note its *search* renders fine in a browser even when its *product* pages serve bot checks |
| **Lazada** | works, but **intermittent** — repeated searches sometimes return 0 |
| **eBay** | blocked, returns an error page |
| **Shopee / Qoo10** | not configured |

Without Playwright the app falls back to DuckDuckGo's HTML endpoint, which needs no
setup but **rate-limits** after roughly 15–20 queries and stays blocked a while. It
uses one broad query per search plus a 15-minute cache to stretch that.

Either way, when a shop or the search engine blocks us the app **says so** rather
than showing "no products found" — a silent block that looks like an empty result
is the worst possible failure here.

**For heavy use, plug in a real search API** (SerpAPI, Brave Search, or eBay's free
Browse API). `app/search/providers.py` is structured so a new provider is a single
function. I could not test keyed providers without credentials.

**Terms of service:** these marketplaces restrict automated access. Occasional
personal price checks on things you're actually considering buying are a different
matter from bulk harvesting, but it's your call. The app pauses between requests
and only fetches pages you add. Don't crank the refresh interval down.

## 1. Install Python

Python 3.11+ from [python.org/downloads](https://www.python.org/downloads/)
(tick "Add python.exe to PATH"), then reopen your terminal. Verify with
`python --version`.

## 2. Set up

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Strongly recommended** (required for Lazada, helps any JS-rendered shop):

```powershell
pip install playwright
playwright install chromium
```

## 3. Run

```powershell
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**.

## 4. Use it

**Hunt by name:** type e.g. `Sony WH-1000XM5` into *Find Deals*. You'll get scored
matches with prices, the cheapest highlighted, and the saving versus the priciest.
Tick the ones that are really the same product and press **Track These**.

Matches are labelled **high / medium / low** confidence, with reasons when
something looks off — `looks like an accessory (case, cover)`,
`model-number-missing`, `used/refurbished`, `price far below the others`. High
confidence ones are pre-ticked; everything else is your call.

Each shop gets its own section, filled in the moment that shop's search finishes —
Amazon typically lands around 5s, the next a few seconds later. A full run across
three shops takes **30–60 seconds**, mostly browser rendering. Lower
`DISCOVER_PER_SHOP` / `DISCOVER_PRICE_LIMIT` to speed it up.

The **best price** headline only ever uses listings that plausibly are the product
you searched for. A cheaper *different* model, or a listing flagged
"price far below the others", stays visible in its shop's list but never sets the
headline — otherwise the page would invent savings of 90%+ against the wrong item.

**Or add a URL yourself** from the home page, then attach the same product on
other shops from its detail page. For a recognised shop, leave the selector blank.

**Practice site** (built for scraping, no ToS concerns):
`https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html`
with selector `.price_color`.

### How a price gets found

First strategy that yields a number wins:

1. **Retailer API** — Shopee's ids come from the URL itself.
2. **Your CSS selector**, if you gave one.
3. **Known selectors** for that retailer.
4. **JSON-LD** (`schema.org` Product/offers).
5. **Meta tags** (`og:price:amount`, `itemprop=price`).
6. **Embedded JSON** in script blobs, escaped or not.
7. **Headless browser** (Playwright), if installed.

## 5. How the decision is made

Two questions, deliberately separate ([app/analysis.py](app/analysis.py)):

**Where's it cheapest?** Latest price per source, ranked. With a display currency
chosen, every listing is converted and they all compete; without one, only listings
sharing the product's currency are ranked (comparing 4,000 PHP against 95 SGD by
magnitude is meaningless). A currency with no available rate is shown but never
declared cheapest.

**Is now a good time to buy?** Computed on the *best price across shops over time*
(snapshots bucketed hourly, minimum per bucket), since that's what you'd pay:

- Target price met → `BUY NOW`
- Under 3 observations → `NOT ENOUGH DATA`
- Price never varied → `NEUTRAL` (percentile is meaningless when all values tie)
- Else by percentile of the current best price: bottom 25% → `BUY NOW`,
  top 25% → `WAIT`, middle → `NEUTRAL`

## 6. Currency conversion

Pick a currency from **Show prices in** (top right) and every price is restated in
it, so a Malaysian and a Singaporean listing can be ranked against each other. The
original is always shown underneath (`SGD 345.50 as quoted`) because that's what
the shop actually charges you.

Two rules the code enforces deliberately:

- **Snapshots are stored in the shop's own currency, never converted on the way
  in.** Converting at write time would bake today's rate into permanent history,
  and tomorrow's rate change would silently rewrite what past prices "were".
- **Conversion happens only at compare/display time**, so you can change display
  currency freely and nothing stored is affected.

Rates come from `open.er-api.com` (no key, 160+ currencies, VND and TWD included),
fall back to `frankfurter.app`, and are cached in SQLite — so the app keeps working
offline and tells you how old its rates are. A currency with no rate available is
shown but never declared cheapest, rather than being silently mis-ranked.

Converted history uses **today's** rate throughout, including for old snapshots.
Within one currency that leaves the history's shape untouched; across currencies it
means the series reflects today's rate, not the rate on the day each price was seen.

> Converted figures are mid-market and **indicative only** — they exclude shipping,
> card FX fees and import duty, so a foreign purchase really costs more than the
> number shown.

## 7. Settings

| Variable | Default | Purpose |
|---|---|---|
| `REFRESH_INTERVAL_HOURS` | 6 | How often tracked sources are re-priced |
| `SEARCH_DOMAINS` | SG shops | Which shops to search, e.g. `lazada.com.my,shopee.com.my` |
| `DISCOVER_PRICE_LIMIT` | 6 | How many un-priced matches get a product-page fetch |
| `DISCOVER_PER_SHOP` | 6 | Listings kept per shop |
| `SEARCH_CACHE_TTL` | 900 | Seconds to cache search results |
| `SEARCH_PER_SHOP_FALLBACK` | 1 | Set `0` to never spend extra queries |

```powershell
$env:SEARCH_DOMAINS = "lazada.com.my,shopee.com.my,amazon.sg"
uvicorn app.main:app --reload
```

## 8. Tests

```powershell
python -m tests.test_extraction   # extraction, comparison, decisions
python -m tests.test_search       # matching, URL filtering, throttle detection
```

Covers every extraction strategy against fixtures, multi-currency parsing
(`Rp1.234.567` vs `1,234.56`), bot-wall and throttle detection, product-vs-accessory
matching, price outliers, cross-retailer comparison, currency conversion (including
that originals stay untouched and unconvertible currencies never win) and every
verdict branch.

## Adding a shop

One entry in `ADAPTERS` ([app/adapters.py](app/adapters.py)): domains, currency per
domain, price selectors, a product-URL pattern and a search domain. Shops with no
adapter still work via JSON-LD, meta tags or your selector, and are labelled by
hostname.

## Project layout

```
app/
  main.py         Routes: dashboard, discovery, product detail, sources
  adapters.py     Per-retailer knowledge
  scraper.py      Price extraction strategies + multi-currency parsing
  analysis.py     Comparison, best-price series, buy/wait decision
  fx.py           Currency conversion + cached exchange rates
  database.py     SQLite (products / sources / snapshots / settings / fx) + migration
  refresh.py      Fetch + store
  scheduler.py    Background interval job
  search/
    providers.py  Product discovery + throttle handling + caching
    matching.py   Scoring a listing against what you asked for
    base.py       Candidate type
  templates/      Jinja2 HTML
  static/         CSS
tests/            Fixture-based tests
data/app.db       SQLite (created on first run)
```

## Known limits

- **FX rates are indicative** — mid-market, up to 12h old, and they exclude
  shipping, card FX fees and import duty. The real cost of a foreign purchase is
  higher than the converted figure.
- **Amazon and Shopee are usually blocked**; their official APIs are the real fix.
- **Discovery only searches shops with an adapter**, so it can tell a product page
  from a category page.
- **Matching ranks, it doesn't decide** — you confirm before anything is tracked.
