# 2026-09-23 — deal-hunter build and toolchain setup

## 0. Continuation brief

Current state: the price-drop deal-hunting app is **built and working end to end**
— per-shop search rendered in a browser, results streamed to the page shop by shop,
multi-currency conversion, and an automatic BUY/WAIT verdict from price history.
111 checks pass across two suites. The project was **not under version control at
all** until this session; it now has git (2 commits on `main`, clean tree), OpenSpec
initialised, and a graphify code graph. The supercharge skill and 3 of its 4 helper
tools are installed and pass preflight. The local test server was **deliberately
stopped** at end of session.

Next step: decide between (a) finishing gbrain (2 PATH entries + `gbrain init`), or
(b) scaffolding the `docs/` tree so drift checking has something to check — it
currently has zero rows to verify. Neither blocks feature work.

Resume command/check: `/supercharge-start`, then `git log --oneline -3` and
`bash ~/.claude/skills/supercharge/scripts/preflight.sh`

---

## 1. Work completed

Built across the session, in order:

1. **Price tracker core** — FastAPI + SQLite (plain `sqlite3`, no ORM) + Jinja.
   Products, per-shop sources, price snapshots, hourly-bucketed best-price series,
   percentile-based BUY/WAIT/NEUTRAL verdicts.
2. **Multi-source comparison** — one product → many shop listings, ranked, cheapest
   tagged, savings computed. Required a v1→v2 schema migration.
3. **Deal discovery** — search by product name, score candidates against the query,
   user confirms which are the same item before anything is tracked.
4. **Currency conversion** — user-selectable display currency, rates cached in
   SQLite, conversion only at display time.
5. **Per-shop search + SSE streaming** — each shop searched on its own search page
   in a headless browser; results stream to the page shop by shop.
6. **Toolchain** — supercharge skill + OpenSpec/semble/graphify (gbrain partial),
   `git init` + 2 commits, `openspec init`, graphify code graph.

Docs written: `CLAUDE.md` (architecture invariants + traps, auto-loaded by Claude
Code), `README.md` (user guide), two memory files under
`~/.claude/projects/.../memory/`.

---

## 2. Decisions

| Decision | Verdict | Why |
| --- | --- | --- |
| Scrape Lazada's `pdt_price` from server HTML | **discarded** | It is the crossed-out LIST price. Read $589.00 on an item selling for $345.50 — would inflate every price ~70% and invent savings |
| Render Lazada in Playwright for the real price | **kept** | `.pdp-v2-product-price-content-salePrice` → SGD 345.50, verified against the live page |
| DuckDuckGo as the primary discovery route | **discarded** | Rate-limits after ~15–20 queries and stays blocked for hours; took the whole feature down |
| Per-shop site search in a browser as primary | **kept** | No shared query budget; result cards already carry prices, so one render prices a whole shop |
| Store prices already converted | **discarded** | Bakes today's FX rate into permanent history; a later rate move would silently rewrite what past prices "were" |
| Convert only at compare/display time | **kept** | Display currency can change freely; stored history never moves |
| Headline "best price" from all priced candidates | **discarded** | Produced "SGD 17.69, save 96%" (a WH-CH520, wrong model) and "SGD 38.60, save 91%" (flagged as implausible) |
| Headline requires `score >= 0.45` AND `not price_suspect` | **kept** | A listing the page itself warns about must not set the headline |
| Auto-track high-confidence matches | **discarded** | Matching can't reliably tell a product from its carrying case; user ticks before anything is tracked |
| Duplicate ranking/outlier logic in JavaScript | **discarded** | Would fork tested Python logic; JS is a dumb renderer instead |
| SSE with all logic server-side | **kept** | One tested implementation; progressive delivery verified over real HTTP |
| Run upstream `install.sh` | **discarded** | `curl\|bash`, 5 unpinned globals, writes to 10 agent dirs, edits `AGENTS.md`; also a bash script on Windows |
| Install each tool explicitly | **kept** | Every command visible; reading the script first revealed "NEVER `npm install -g gbrain` — unrelated package" |
| `curl -fsSL bun.sh/install \| bash` | **discarded** | Piping a remote script to a shell; used bun's official npm package instead |
| graphify full index (needs LLM API key) | **discarded** | Would send this codebase to an external API on the user's credits |
| `graphify . --code-only` | **kept** | Local AST only, no key, nothing leaves the machine |

---

## 3. Tests, checks, benchmarks

| Check | Result | What it proved |
| --- | --- | --- |
| `python -m tests.test_extraction` | **63 checks pass** | Extraction strategies, multi-currency parsing, comparison, FX conversion, every verdict branch |
| `python -m tests.test_search` | **48 checks pass** | Match scoring, product-vs-accessory, URL filtering, throttle detection, both headline regressions |
| Live per-shop search, `Sony WH-1000XM5` | Amazon 6 results ~5s; Lazada 6 results (+4s); eBay blocked (+9s) | Per-shop search works without any web search engine |
| SSE arrival times over `curl -N --no-buffer` | 01:57 → 02:01 → 02:10 → 02:19 | Streaming is genuinely progressive, not batched |
| Same stream under `fastapi.testclient` | all events at once | **TestClient buffers SSE** — do not use it to judge streaming |
| Lazada price, live | `SGD 345.50` via `lazada-css+browser` in 4.9s | Browser render returns the real price, not the $589.00 list price |
| FX conversion of SGD 345.50 | `MYR 1103.80`, `USD 270.92`, original preserved | Conversion correct; stored value untouched |
| Headline after fix | `SGD 210.39 at Amazon, save 53%` | Real product, believable saving (was SGD 17.69 / 96%) |
| `preflight.sh` | `preflight OK` | graphify 0.9.66, openspec 1.13.1, semble 0.5.5; gbrain blank |
| `drift-check.sh` | `no docs/ tree here — nothing to check` (exit 0) | Runs now that git exists; nothing to verify yet |
| `graphify . --code-only` | 254 nodes, 627 edges, 8 communities | Graph built locally, no API key |

---

## 4. Live handoff state

| Type | Handle / location | State | Inspect / resume | Stop / cleanup |
| --- | --- | --- | --- | --- |
| branch | `main` | clean, 2 commits | `git log --oneline -3` | none |
| process | uvicorn dev server (was pid 19268) | **stopped this session** | `Get-NetTCPConnection -LocalPort 8000 -State Listen` | already stopped |
| port | `127.0.0.1:8000` | **free** | as above | n/a |
| process | Playwright/chromium | none running (verified) | `Get-Process \| ? Path -like '*ms-playwright*'` | n/a |
| artifact | `graphify-out/` | built, **git-ignored** | `ls graphify-out/graph.json` | rebuild, never hand-edit |
| artifact | `data/app.db` | exists, **git-ignored**; holds cached FX rates, **0 tracked products** | `sqlite3 data/app.db ".tables"` | safe to delete; recreated on boot |
| artifact | `.venv/` | Python 3.14.7 + Playwright chromium | `.\.venv\Scripts\python.exe --version` | keep |
| artifact | session scratchpad | probe scripts, stream captures | `%TEMP%\claude\...\scratchpad` | disposable |
| secret | no LLM API keys set | `GEMINI_API_KEY`/`ANTHROPIC_API_KEY`/etc **absent** | — | graphify stays `--code-only` without one |

**To restart the app:**
```powershell
cd "C:\Users\Justin\GitHub Repos\VibeCoding Project"
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload      # http://127.0.0.1:8000
```

---

## 5. In-flight changes (from OpenSpec)

| Change | Tasks | Status | Next ready artifact |
| --- | --- | --- | --- |
| none | — | — | — |

`openspec list --json` → `{"changes": []}`. OpenSpec is initialised but no change has
been proposed yet; all work this session predates it.

---

## 6. Open items

| Priority | Item | Doc/code reference | Next action | Done when |
| --- | --- | --- | --- | --- |
| P1 | gbrain unusable — needs PATH + init | `~/.bun/bin`, `%APPDATA%\npm\node_modules\bun\bin` | Add both to user PATH (blocked for the agent last session — needs user approval), then `gbrain init` | `gbrain doctor` reports a configured brain |
| P2 | No `docs/` tree — drift check has 0 rows to verify | `references/docs-tree.md` | Scaffold `docs/<component>/ARCHITECTURE.md` + `IMPLEMENTATION.md` | `drift-check.sh` reports N refs, not "nothing to check" |
| P2 | Architecture not grounded in FRAMEWORK.md model | `CLAUDE.md` | Re-express invariants as `Dat`/`Trn`/`Loc`/`Trm` rows mapped to `file:symbol` | Every row maps to code, `planned`, or open question |
| P2 | Keyed search providers never tested | `app/search/providers.py` | Add SerpAPI/Brave/eBay Browse provider with a key | A keyed search returns candidates |
| P3 | eBay site search blocked (error page) | `app/adapters.py` EBAY | Try eBay Browse API instead of scraping search | eBay returns results |
| P3 | Lazada site search intermittent (6 results, then 0) | `app/search/site_search.py` | Add retry/backoff, or accept and document | Consistent results, or documented limit |
| P3 | `graphify.exe` shim broken on Windows | uv tool install | Use `python -m graphify` workaround; report upstream | `graphify .` works directly |
| P3 | Converted history uses today's rate for old snapshots | `app/analysis.py` `best_price_series` | Store the rate at snapshot time if cross-currency history matters | Series reflects each day's rate |

---

## 7. Architecture / model changes

No formal `Dat`/`Trn`/`Loc`/`Trm` model was authored this session — that is open item
P2, and this log should not be read as claiming one exists. Architecture is currently
captured informally in `CLAUDE.md` as seven invariants plus the traps behind them.

Structural shape, for orientation:

- **Loc**: the FastAPI process, the SQLite file, a headless Chromium per shop search,
  and the shops themselves (external, hostile, rate-limiting).
- **Trm**: HTTP to shops, SSE to the browser, the FX rate API.
- **Dat**: `products` → `sources` → `price_snapshots` (snapshots always in the shop's
  own currency), plus `settings` and `fx_rates`.
- **Trn**: extraction strategies (`scraper.py`), match scoring (`matching.py`),
  comparison + verdict (`analysis.py`), conversion (`fx.py`).

The one non-obvious coherence rule: **conversion is a display-time morphism, never a
write-time one.** Applying it on write makes stored history a function of today's FX
rate, which is incoherent — the same past price would mean different things on
different days.

---

## 8. Docs reconciled

| Doc | Change |
| --- | --- |
| `CLAUDE.md` | Authored this session. 7 invariants, traps already hit, per-shop reality table (search vs product page behave differently), discovery design, conventions |
| `README.md` | Rewritten for per-shop search, currency conversion, streaming; reality-check table; Lazada list-price warning |
| `.gitignore` | Added `graphify-out/` |
| `~/.claude/projects/.../memory/price-tracker-project.md` | Project goals and constraints |
| `~/.claude/projects/.../memory/vibecoding-env-quirks.md` | Windows/Python gotchas |
| `docs/sessions/2026-09-23-...` | This log |

No `ARCHITECTURE.md` / `IMPLEMENTATION.md` / `STATUS.md` exist yet — see open item P2.

---

## 9. Drift check

`bash ~/.claude/skills/supercharge/scripts/drift-check.sh` → **`no docs/ tree here —
nothing to check`** (exit 0). Not a pass: there is nothing to verify. Recorded as
open item **P2**. The check itself is functional now that the repo is under git.

---

## 10. Files changed

**Committed** (`6d59985`, `64fb4fa`):
- `app/` — `main.py`, `adapters.py`, `analysis.py`, `database.py`, `fx.py`,
  `refresh.py`, `scheduler.py`, `scraper.py`, `search/{base,matching,providers,site_search}.py`
- `app/templates/` — `base.html`, `index.html`, `product.html`, `discover.html`
- `app/static/style.css`
- `tests/test_extraction.py`, `tests/test_search.py`
- `CLAUDE.md`, `README.md`, `requirements.txt`, `.gitignore`
- `.claude/` (6 opsx commands + 6 skills), `openspec/config.yaml`

**Generated, ignored:** `graphify-out/`, `data/app.db`, `.venv/`

**Outside the repo:** `~/.claude/skills/supercharge/`, `~/.claude/commands/supercharge-*.md`,
and the memory files.
