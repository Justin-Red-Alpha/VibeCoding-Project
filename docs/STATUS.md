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
| refresh | ✅ built | **no offline tests** | — | [refresh/STATUS.md](refresh/STATUS.md) |

## Cross-cutting
- **Coherence:** Law 2 is advisory (untyped `t_sse` variants). All other laws
  PASS. See [architecture-map.md](architecture-map.md) §5.
- **Tests:** 232 offline checks across 4 suites. The refresh component and FX
  fetching have none.
- **Drift:** every `path:symbol` in the component maps resolves. Run
  `bash ~/.claude/skills/supercharge/scripts/drift-check.sh`.
