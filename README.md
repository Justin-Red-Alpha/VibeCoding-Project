# Price Drop Decision Tracker

[![CI](https://github.com/Justin-Red-Alpha/VibeCoding-Project/actions/workflows/ci.yml/badge.svg)](https://github.com/Justin-Red-Alpha/VibeCoding-Project/actions/workflows/ci.yml)

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

All shops are searched **at the same time** and each one appears the moment it
finishes, so a slow or blocked shop never holds the others up. Pages load without
images, fonts or video, since prices and titles are text. That alone cut Amazon's
page load from ~9.6s to ~1.3s.

| Shop | Site search |
|---|---|
| **Amazon** | works well (~48 cards) — note its *search* renders fine in a browser even when its *product* pages serve bot checks |
| **Lazada** | works, but **intermittent** — repeated searches sometimes return 0 |
| **eBay** | blocked: answers with a tiny error page, reported as "refusing automated searches" in about a second |
| **Shopee / Qoo10** | no site search yet, shown as "not searched" |

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

Python 3.12+ from [python.org/downloads](https://www.python.org/downloads/)
(tick "Add python.exe to PATH"), then reopen your terminal. Verify with
`python --version`. The project and CI use 3.14.

## 2. Set up

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
```

If activation is blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Chromium is what renders JavaScript-only shops (Lazada's real price) and runs
each shop's own search page. `requirements.txt` also installs the Postgres
driver, which is only used when `DATABASE_URL` is set (the hosted site).

## 3. Run

```powershell
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000**.

### First run: register first

Click **Register** (top right). **The first account becomes the site's admin**, and
any products tracked before accounts existed become yours. Everyone who registers
after that is a normal user.

| | Can do |
|---|---|
| **Anyone** (not signed in) | Search deals (*Find deals*) and see prices |
| **User** | Everything above, plus track products, see *only their own* tracked products, choose their own "Prices in" currency |
| **Admin** | Everything above, plus the **Admin** page and opening any user's product |

The **Admin** page (top bar, admins only) has:
- **Users:** make admin or user, disable (which signs them out), delete (which also
  deletes their products). The site always keeps at least one admin.
- **Site settings:**
  - the default currency for visitors and for users who haven't picked one;
  - the shops *Find deals* searches (untick a shop to switch it off; shops added
    to the app later are switched on automatically);
  - the refresh interval (1–168 h);
  - listings kept per shop;
  - missing prices looked up per search.

  They apply immediately, with no restart. If any field is invalid, nothing is
  saved. Saving only records what you actually changed, so untouched fields keep
  following their environment variables (see [Settings](#7-settings)).
- **Maintenance:** refresh everyone's prices now, refresh exchange rates (it tells
  you if the fetch failed and older rates are still in use), and pause or resume
  the Internet Archive lookups. Pausing also stops lookups already running.

**Refresh my prices** (on your dashboard) runs in the background. Reload after a
minute or two to see the new prices.

Passwords are stored as salted scrypt hashes, never in plain text. After 5 wrong
passwords, that username is locked for 15 minutes. There's no password reset
(there's no email): an admin can delete an account so the person can register
again.

### Or run it in Docker

The same image the hosted site runs (`Dockerfile.vercel`: Python 3.14, Chromium,
a non-root user):

```powershell
docker build -f Dockerfile.vercel -t price-tracker .
docker run --rm -p 8080:80 price-tracker
```

Open **http://127.0.0.1:8080**. With no `DATABASE_URL` it keeps its data in a
SQLite file *inside the container*, which is gone when the container is. Check
it's up with `curl http://127.0.0.1:8080/healthz`, which answers
`{"app":"ok","database":"ok"}`.

## 4. Use it

**Hunt by name:** type e.g. `Sony WH-1000XM5` into *Find Deals*. You'll get scored
matches with prices, the cheapest highlighted, and the saving versus the priciest.
Tick the ones that are really the same product and press **Track These**.

Matches are labelled **high / medium / low** confidence, with reasons when
something looks off — `looks like an accessory (case, cover)`,
`model-number-missing`, `used/refurbished`, `price far below the others`. High
confidence ones are pre-ticked; everything else is your call.

Each shop gets its own section, filled in the moment that shop's search finishes.
Measured for "Sony WH-1000XM5": eBay reports in ~1s, Amazon ~2.5s, Lazada ~3.3s,
and the whole search, including looking up missing prices (3 at a time), takes
**~8 seconds** (it was 30). The first search after starting the server can take ~7s
longer while Chromium starts cold. Lower `DISCOVER_PER_SHOP` /
`DISCOVER_PRICE_LIMIT` to speed it up further.

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
declared cheapest. Listings with no recognized currency are also shown but excluded
from ranking.

**Is now a good time to buy?** Computed on the *best price across shops over time*
(snapshots bucketed hourly, minimum per bucket), since that's what you'd pay:

- Target price met → `BUY NOW`
- Under 3 observations → `NOT ENOUGH DATA`
- Price never varied → `NEUTRAL` (percentile is meaningless when all values tie)
- Else by percentile of the current best price: bottom 25% → `BUY NOW`,
  top 25% → `WAIT`, middle → `NEUTRAL`

The target is in whatever currency you pick next to it. The picker defaults to the
currency you're viewing prices in. Leave it on **Shop's currency** and the target
uses the product's primary currency (the first successful source with a known
currency). Before the target is compared with the price history, it is converted
into the history's currency: your display currency if you picked one, otherwise the
primary currency. So a target of MYR 800 is read as about SGD 250, not SGD 800. The
product page shows both figures. If no rate is available, the target is shown but
does not affect the verdict. The target is stored as you typed it and is never
rewritten.

### Past prices from the Internet Archive

A newly tracked product has no history, so the verdict would say `NOT ENOUGH DATA`
for days. When you track a listing, the app searches the **Internet Archive**
(web.archive.org) in the background for dated copies of that same listing's page.
It reads the price from each copy with the normal extractor and adds those prices
to the history. They count in the chart and the verdict at once. For example, the
amazon.com WH-1000XM5 page gave 9 prices from May 2025 to Sep 2026.

What to expect:
- **Only the listing's own page is used,** meaning its URL plus the shop's standard
  form of it (Amazon `/dp/<id>`), on the same site. An amazon.com page never
  feeds an amazon.sg listing.
- **"Cheapest right now" stays live.** Archived prices are history only. In
  *Raw snapshots* they're marked **archived** and link to the copy they came from.
- **Some copies are left out:** a price in another currency, and a price under a
  third or over three times the listing's usual price, which is usually an
  accessory or a used offer. Each listing's note says what was found and what was
  excluded.
- **It works for Amazon and for sites that embed standard product price data.
  It doesn't work for Lazada or Shopee.** They draw the real price with scripts,
  so their archived copies hold only the crossed-out list price, which the app
  never reads.
- **It takes a few minutes and asks the archive slowly:** at most 24 copies, 15
  requests a minute. If the archive says "slow down" (HTTP 429) or refuses the
  connection, every lookup pauses for 15–60 minutes, because the archive
  blocks clients that keep going. "Look for archived prices" on the product page
  runs it again, and never adds a copy twice.

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

Converted price history and its chart use **today's** rate throughout, including for old snapshots.
Within one currency that leaves the history's shape untouched; across currencies it
means the series reflects today's rate, not the rate on the day each price was seen.

> Converted figures are mid-market and **indicative only** — they exclude shipping,
> card FX fees and import duty, so a foreign purchase really costs more than the
> number shown.

## 7. Settings

The first four are easiest to change on the **Admin** page, which overrides these
environment variables. The variables remain as defaults. A variable set to an
unusable value (e.g. `REFRESH_INTERVAL_HOURS=0.5`, below the 1-hour minimum) is
ignored in favour of the default. The Admin page lists any it is ignoring.

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
pip install -r requirements-dev.txt   # once: httpx, for the route tests
python -m tests.test_extraction   # extraction, comparison, decisions
python -m tests.test_search       # matching, URL filtering, throttle detection
python -m tests.test_currency     # what may be ranked, charted or compared with a target
python -m tests.test_shop_search  # concurrent shops, block detection, browser start-up
python -m tests.test_history      # archived prices: matching, filtering, back-off, live-only current price
python -m tests.test_auth         # accounts, sessions, private products, admin page, CSRF guard
python -m tests.test_hosting      # both databases, outage page, /healthz, daily cron run, proxy
```

GitHub Actions runs all seven on every push and pull request, on Ubuntu and
Windows, and again against Postgres 17 (see the badge at the top).

**Against Postgres, like CI.** Start a throwaway Postgres in Docker and point
the tests at it:

```powershell
docker run -d --name pt-pg -p 5433:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=test postgres:17
$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5433/test"
python -m tests.test_auth    # ...or any suite
```

Every suite starts by **dropping the whole schema** of that database, so the
helper refuses any host but `localhost`/`127.0.0.1`, and refuses the URL in
`DATABASE_URL`. Never point it at the hosted database.

`test_shop_search` is offline too. Its browser checks run local Chromium against
in-memory pages, never a shop. `test_history` fakes the archive, so it never
contacts web.archive.org.

Covers every extraction strategy against fixtures, multi-currency parsing
(`Rp1.234.567` vs `1,234.56`), bot-wall and throttle detection, product-vs-accessory
matching, price outliers, cross-retailer comparison, currency conversion (including
that originals stay untouched and unconvertible currencies never win) and every
verdict branch. `test_currency` also checks that unknown-currency prices are never
ranked or charted, that target prices are converted before they are compared, and
that the database upgrade keeps existing products. It uses a throwaway database,
never `data/app.db`.

## 9. Hosting on Vercel

A personal dev deployment, not a launch. Deploys go through GitHub Actions: a
push to `main` is deployed only after every test job passes. Vercel's own Git
auto-deploy is switched off in `vercel.json`, so a failing test always blocks a
deploy.

> **Right now (2026-09-25) we're trying Vercel's Git auto-deploy instead.**
> `vercel.json` isn't committed yet. Until it is:
> - every push deploys whether or not the tests pass;
> - there's no daily cron;
> - the region is Vercel's default.
>
> Leave `SCHEDULER_MODE` unset meanwhile, and skip `VERCEL_TOKEN`.

**One-time setup (the owner, in the Vercel and GitHub dashboards):**

1. In the Vercel project, turn on **Container Images** (it builds
   `Dockerfile.vercel`). `vercel.json` pins the region to `sin1` (Singapore).
2. Install **Neon** from the Vercel Marketplace (Singapore if offered, Postgres
   17, preview branching off). It adds `DATABASE_URL` to the project by itself.
3. Add the Vercel environment variables below, for **Production**.
4. Add the GitHub repository secrets below (Settings → Secrets and variables →
   Actions).
5. Push to `main`. When CI is green, the deploy job ships it. **Register on the
   hosted site straight away**: the first account there becomes its admin.

| Where | Name | Value |
|---|---|---|
| Vercel env | `DATABASE_URL` | added by Neon; don't type it |
| Vercel env | `SCHEDULER_MODE` | `cron` |
| Vercel env | `CRON_SECRET` | a long random string you generate (mark it Sensitive). Vercel's cron sends it as `Authorization: Bearer …` |
| GitHub secret | `VERCEL_TOKEN` | vercel.com → Account Settings → Tokens |
| GitHub secret | `VERCEL_ORG_ID` | your Vercel ID (personal) or Team ID |
| GitHub secret | `VERCEL_PROJECT_ID` | the project's Settings → General → Project ID |
| GitHub variable (optional) | `PRODUCTION_URL` | e.g. `https://<project>.vercel.app`, for the post-deploy health check |

Values are never written down in the repo. Until `VERCEL_TOKEN` exists, the
deploy job is **skipped with a notice**, and CI stays green.

**On Vercel Hobby, prices refresh once a day** (02:00 Singapore time), not every
6 hours: Hobby runs cron jobs at most daily. The Admin page shows "once a day,
set by the host" instead of the interval. Each daily run re-checks the listings
checked longest ago first, then finishes any archive lookups left undone, and
stops in time for Vercel's 300-second limit. Whatever it doesn't reach goes
first the next day. "Refresh my prices" and the admin's refresh button still
work any time.

To roll back, promote the previous deployment in the Vercel dashboard. The data
stays in Neon either way. Local use is unaffected: with no `DATABASE_URL`, the
app uses `data/app.db` and its own 6-hour timer.

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
  database.py     The storage port: SQLite file or Postgres (DATABASE_URL), schema + migration
  refresh.py      Fetch + store; stalest-first daily refresh
  scheduler.py    Background interval job, or the host's daily run (SCHEDULER_MODE=cron)
  search/
    providers.py  Product discovery + throttle handling + caching
    matching.py   Scoring a listing against what you asked for
    base.py       Candidate type
  templates/      Jinja2 HTML
  static/         CSS
tests/            Fixture-based tests (helpers.py picks SQLite or TEST_DATABASE_URL)
data/app.db       SQLite (created on first run)
Dockerfile.vercel The one image: CI smoke-tests it, Vercel runs it
vercel.json       Region, daily cron, Git auto-deploy off
.github/workflows/ci.yml   Tests on Ubuntu, Windows and Postgres; container smoke test; gated deploy
scripts/drift-check.sh     Docs ↔ code check (vendored from the supercharge skill)
```

## Known limits

- **FX rates are indicative** — mid-market, up to 12h old, and they exclude
  shipping, card FX fees and import duty. The real cost of a foreign purchase is
  higher than the converted figure.
- **Amazon and Shopee are usually blocked**; their official APIs are the real fix.
- **Discovery only searches shops with an adapter**, so it can tell a product page
  from a category page.
- **Matching ranks, it doesn't decide** — you confirm before anything is tracked.
