# 2026-09-24 — docs tree and gbrain sync

## 0. Continuation brief

Current state: the supercharge **docs tree now exists**. It has 8 components, each
with ARCHITECTURE, IMPLEMENTATION, STATUS and suggestions, plus the architecture
map and three roll-ups. The drift check went from `0 dead / 0 refs` (nothing to
verify) to **`0 dead / 253 refs`**, and it was shown to catch a broken row.

gbrain now **references** the session logs instead of holding copies: it syncs
`docs/sessions/` as the federated source `vibecoding-sessions`. It's upgraded to
0.54.1, and ambient writeback is explicitly off.

The user fast-forwarded the previous session branch into `main` and pushed it
(`7fd8901`, `main` = `origin/main`). **This session's docs work is uncommitted on
`main`.**

Next step: commit the docs tree and this log (on a branch, per the harness rule),
then run `gbrain sync --source vibecoding-sessions --no-embed` so gbrain indexes
this log. After that, pick from `docs/suggestions.md`. #1 (declare the SSE event
types once) and #2 (refresh tests) have the best payoff.

Resume command/check: `git status --short`, then
`bash ~/.claude/skills/supercharge/scripts/drift-check.sh` (expect `0 dead / 253 refs`).

---

## 1. Work completed

1. **gbrain: memory capture handed to supercharge** (the user's call).
   - `gbrain config set memory.auto_writeback off`
   - `gbrain sources add vibecoding-sessions --path "<repo>/docs/sessions" --federated`
   - `gbrain sync --source vibecoding-sessions --no-embed`: 2 logs, 12 chunks,
     checkpoint `7fd89011`
   - The two earlier `gbrain capture` copies (`inbox/2026-09-24-8fe7a5b8` and
     `inbox/2026-09-24-2c7d14da`) were soft-deleted from the `default` source,
     which now has 0 pages.
   - The supercharge skill's `end` step 6 (`~/.claude/skills/supercharge/SKILL.md`)
     now says to sync the committed log, not capture it.
2. **gbrain upgraded** 0.52.2 → **0.54.1** (`gbrain self-upgrade`). Both pages
   survived.
3. **Docs tree scaffolded** following `references/docs-tree.md`, with FRAMEWORK.md
   read first.
   - The components were chosen from the graphify communities, cross-checked
     against the code's seams (§2 below).
   - Each component has `ARCHITECTURE.md` (model-first, diagram ⇔ table checked),
     `IMPLEMENTATION.md` (drift-checkable `file:symbol` rows), `STATUS.md`,
     `suggestions.md`, and empty `reviews/` and `general/` folders.
   - Roll-ups: `docs/architecture-map.md` (the four atoms, components, placement
     table, §4.5 checklist), `docs/IMPLEMENTATION.md`, `docs/STATUS.md` and
     `docs/suggestions.md`.
4. **`openspec/config.yaml`** now has the `context:` and `rules:` block from
   supercharge `references/openspec.md` §3, plus the §4 choice (option B). A
   probe change confirmed the rules reach artifact instructions; it was removed
   afterwards.
5. **`CLAUDE.md`** now opens with a pointer to the docs tree and the drift-check
   habit. A false claim was also corrected: keyed providers were described as
   "scaffolded" but are unbuilt.

---

## 2. Decisions

| Decision | Verdict | Why |
| --- | --- | --- |
| `gbrain capture` each log | **discarded** | It makes a second copy that drifts. The user asked gbrain to reference supercharge's logs |
| Sync `docs/sessions/` as a gbrain source | **kept** | gbrain indexes the committed file itself, and the page slug is the filename |
| Source not federated (the default) | discarded | It would only be searched when named, which defeats cross-project recall |
| gbrain ambient writeback | **off, explicitly** | The supercharge logs are the memory |
| Update the global supercharge SKILL.md `end` step | **kept** | Otherwise every future `end` would recapture and recreate the duplicates |
| Update Codex's copy (`.codex/skills/supercharge/`) | **not done** | The user said that copy is for OpenAI only. It still says `capture` |
| Install the gbrain skill pack offered by the upgrade | **not done** | The upgrade said to ask the user first. Pending |
| Decomposition into 8 components | **kept** | From the graph communities and code seams: discovery, extraction, browser, storage, analysis, fx, web, refresh |
| Put `Adapter` in its own component | discarded | It's shop knowledge read by discovery and web, authoritative in extraction. Recorded as a shared object |
| Put `scheduler` in its own component | discarded (merged into refresh) | The graph put it in refresh's community, and it has one job: trigger `refresh_all` |
| `fx` as part of `analysis` | discarded | fx has effects (network, cache). analysis is pure and takes conversion as a port that fx realises (§7.4) |
| `browser` as a component rather than a helper | **kept** | It owns a real `Loc` (Chromium), and its reason to exist is a Law 6 fact |
| Merge `Candidate` and `Source` (§3) | **rejected** | The reduction shows it isn't bijective on objects, and their lifetimes and `Loc`s differ (discovery suggestions #3) |
| `planned` rows point at existing functions | discarded | A planned row with a real ref would look built. Planned rows say "none yet" |
| OpenSpec §4 choice | **B** | Specs cover observable behaviour; docs/ARCHITECTURE covers internals |

---

## 3. Tests, checks, benchmarks

| Check | Result | What it proved |
| --- | --- | --- |
| `drift-check.sh` | **0 dead / 253 refs** | Every model row resolves to real code. It was 0/0 before |
| Per-component refs | web 45, discovery 39, extraction 37, analysis 35, storage 34, fx 15, browser 14, refresh 12, root 22 | Coverage is spread across all components |
| Mutation: rename a ref to `_chart_points_renamed` | 2 DEAD-SYMBOL reported, then restored to 0 | The check catches real drift in this repo |
| `drift-check.sh --selftest` | `selftest OK` | Dead refs exit non-zero and clean trees exit zero |
| `openspec validate --specs --strict` | 3/3 pass | The config change didn't break specs |
| Probe change `zz-config-probe` | context carries the docs pointer; 4 design rules, 3 task rules | Future proposals get the model rules. Probe deleted |
| `gbrain search "reload NotImplementedError Proactor"` | hit on `2026-09-24-currency-target-and-faster-search` (synced source) | Search reads the referenced file |
| `gbrain sources list` | `default` 0 pages · `vibecoding-sessions` 2 pages | No duplicates remain |
| Test suites | not rerun (docs and config only, no code changed) | — |

---

## 4. Live handoff state

| Type | Handle / location | State | Inspect / resume | Stop / cleanup |
| --- | --- | --- | --- | --- |
| branch | `main` @ `7fd8901` = `origin/main` | **dirty**: `docs/` tree, `openspec/config.yaml`, `CLAUDE.md`, this log (uncommitted) | `git status --short` | commit on a branch when the user says |
| branch | `session/2026-09-24-currency-and-search-speed` | merged and deleted by the user at 11:20 | `git reflog -3` | none |
| process | uvicorn `--reload` on 8000 | running (HTTP 200) | `Get-NetTCPConnection -LocalPort 8000 -State Listen` | see the previous log's §4 stop command |
| data | gbrain source `vibecoding-sessions` → `<repo>/docs/sessions` | federated, 2 pages, last sync at checkpoint `7fd89011` | `gbrain sources list` | `gbrain sources remove vibecoding-sessions` |
| data | gbrain `default` source | 0 pages (2 soft-deleted, recoverable for 72 h) | `gbrain list` | purged automatically after 72 h |
| config | gbrain | 0.54.1, `memory.auto_writeback off`, `embedding_disabled: true` | `gbrain config show` | — |
| config | `~/.claude/skills/supercharge/SKILL.md` | `end` step 6 edited (sync, not capture) | read lines ~127–140 | revert by hand if unwanted |
| config | `~/.claude/projects/.../memory/vibecoding-env-quirks.md` | gbrain sync workflow and delete caveat added | — | — |

**Caution for the next agent:** `gbrain delete <slug>` on a page in
`vibecoding-sessions` deletes the markdown file in `docs/sessions/`. Always pass
`--source-id`.

---

## 5. In-flight changes (from OpenSpec)

| Change | Tasks | Status | Next ready artifact |
| --- | --- | --- | --- |
| none | — | — | — |

`openspec list --json` → `{"changes": []}`.

---

## 6. Open items

| Priority | Item | Doc/code reference | Next action | Done when |
| --- | --- | --- | --- | --- |
| P1 | Docs tree and this log uncommitted | `docs/`, `openspec/config.yaml`, `CLAUDE.md` | Branch, commit, then `gbrain sync --source vibecoding-sessions --no-embed` | `git status` clean; `gbrain sources list` shows 3 pages |
| P2 | SSE event types not declared once (Law 2 advisory) | `docs/web/suggestions.md` #1 | OpenSpec change | Law 2 marked `[x]` in architecture-map §5 |
| P2 | `refresh` has no offline tests | `docs/refresh/STATUS.md` | Add `tests/test_refresh.py` | 4 rules in refresh IMPLEMENTATION have "Tested at" refs |
| P2 | Keyed search providers not built | `docs/discovery/STATUS.md` | Build one, or remove `available_providers` | Row moves from planned to built, or is deleted |
| P3 | gbrain skill pack offered by the 0.54.1 upgrade | `gbrain skillpack scaffold --all` | Ask the user | Answered |
| P3 | Codex's supercharge copy still says `gbrain capture` | `.codex/skills/supercharge/SKILL.md` | Only if the user wants Codex aligned | — |
| P3 | Rest of the backlog in `docs/suggestions.md` (#3–#11) | `docs/suggestions.md` | One OpenSpec change each | Rows move to a session log |
| P3 | Carried from the previous log: Chromium cold start, eBay Browse API, Shopee/Qoo10 search, Lazada intermittency, graphify shim, historical FX, target edit form, placeholder truncation | `docs/STATUS.md` | See each component's STATUS | — |

---

## 7. Architecture / model changes

The model now exists. It's `docs/architecture-map.md` plus the 8 component
ARCHITECTURE files.

- **Coherence (§4.5):** Laws 1, 3, 4, 5 and 6 PASS. **Law 2 is advisory**,
  because the `t_sse` variants have no single declaration.
- **Law 6 is the notable one.** Rendering and `fetch_price` are placed on up to
  four threads, and `browser.run` exists so that no placement assumes another's
  event-loop setup.
- **Smells swept:** no parallel objects (`Adapter` already consolidates search).
  One justified stored copy (`Product.currency`, write-once). `Candidate` vs
  `Source` was reduced and kept apart.
- **Divergence found and fixed:** CLAUDE.md claimed keyed providers were
  scaffolded, but none exist.

---

## 8. Docs reconciled

| Doc | Change |
| --- | --- |
| `docs/architecture-map.md`, `docs/IMPLEMENTATION.md`, `docs/STATUS.md`, `docs/suggestions.md` | Created (roll-ups deduced from the components) |
| `docs/{discovery,extraction,browser,storage,analysis,fx,web,refresh}/` | Created: ARCHITECTURE, IMPLEMENTATION, STATUS, suggestions, `reviews/`, `general/` |
| `openspec/config.yaml` | `context:` + `rules:` + the §4 option-B note |
| `CLAUDE.md` | Docs-tree pointer and drift habit; keyed-provider claim corrected; refresh test gap noted |
| `~/.claude/skills/supercharge/SKILL.md` | `end` step 6: sync the committed log, never capture |
| `~/.claude/projects/.../memory/vibecoding-env-quirks.md` | gbrain version, sync workflow, delete caveat |

---

## 9. Drift check

`bash ~/.claude/skills/supercharge/scripts/drift-check.sh` → **`0 dead / 253 refs`**.
This is the first run with something to verify. A deliberate break was caught (2
dead) and reverted.

---

## 10. Files changed

**Uncommitted in the repo:** `docs/` (new: 4 root docs + 8 × 4 component docs + 16
`.gitkeep`), `docs/sessions/2026-09-24-docs-tree-and-gbrain-sync.md` (this log),
`openspec/config.yaml`, `CLAUDE.md`.

**Outside the repo:** `~/.claude/skills/supercharge/SKILL.md`, the memory file
above, `~/.gbrain/` (source added, 2 pages soft-deleted, upgraded).
