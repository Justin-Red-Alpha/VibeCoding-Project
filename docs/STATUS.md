# System status

> Roll-up of every <component>/STATUS.md. Detail lives in the linked file. The
> **In flight** column comes from `openspec list --json` (empty as of 2026-09-24).

| Component | State | Headline gap | In flight | Detail |
| --- | --- | --- | --- | --- |
| discovery | 🟡 partial | only Amazon and Lazada return results. eBay is blocked; Shopee/Qoo10 have no site search | — | [discovery/STATUS.md](discovery/STATUS.md) |
| extraction | ✅ built | Shopee API gets 403 | — | [extraction/STATUS.md](extraction/STATUS.md) |
| browser | ✅ built | ~7 s cold start on the first search after a restart | — | [browser/STATUS.md](browser/STATUS.md) |
| storage | ✅ built | the success ⊕ failure rule is held by convention | — | [storage/STATUS.md](storage/STATUS.md) |
| analysis | ✅ built | no historical FX rate | — | [analysis/STATUS.md](analysis/STATUS.md) |
| fx | ✅ built | — | — | [fx/STATUS.md](fx/STATUS.md) |
| web | ✅ built | no target edit form. SSE events not declared once | — | [web/STATUS.md](web/STATUS.md) |
| refresh | ✅ built | rules 1 and 3 (every attempt recorded, quoted currency) untested | — | [refresh/STATUS.md](refresh/STATUS.md) |
| auth | ✅ built | no password change / reset; in-memory throttle | — | [auth/STATUS.md](auth/STATUS.md) |
| settings | ✅ built | — | — | [settings/STATUS.md](settings/STATUS.md) |
| history | 🟡 partial | Amazon only (9 prices live for the WH-1000XM5). Lazada/Shopee need BuyWhere. One suspicious USD 88 capture unchecked | — | [history/STATUS.md](history/STATUS.md) |

## Cross-cutting
- **Coherence:** Law 2 is advisory (untyped `t_sse` variants). All other laws
  PASS. See [architecture-map.md](architecture-map.md) §5.
- **Tests:** 486 offline checks across 6 suites. FX fetching has none (network
  only). `test_auth` blocks `requests` so no test can reach the network by mistake.
- **Code review, 2026-09-24:** all 15 findings on the accounts/admin change
  fixed, each with a test. The concurrency ones run real threads and were checked
  against the pre-fix code (it let 40 of 40 parallel guesses through, and it ran
  two refresh batches at once).
- **External limits:** the Internet Archive blocks clients that ignore HTTP 429,
  for an hour and doubling on repeat. `history` stops on the first sign and
  pauses. Don't hand-probe web.archive.org in loops.
- **Drift:** every `path:symbol` in the component maps resolves. Run
  `bash ~/.claude/skills/supercharge/scripts/drift-check.sh`.
