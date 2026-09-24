# Browser — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| skipped resource kinds | `{image, font, media}` | `app/browser.py:SKIPPED_RESOURCES` | built |
| `BrowserUnavailable` | exception | `app/browser.py:BrowserUnavailable` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `run` | `Coroutine⟨A⟩ → A` | `app/browser.py:run` | built |
| `chromium?` | `() → Browser` | `app/browser.py:chromium` | built |
| `new_page` | `Browser → Page` | `app/browser.py:new_page` | built |
| `skip_heavy` | `Request → abort ⊕ continue` | `app/browser.py:_skip_heavy` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. only seam that starts Chromium | `app/browser.py:chromium` | `tests/test_shop_search.py:test_browser_survives_reload_loop_policy` |
| 2. independent of the loop policy | `app/browser.py:run` | `tests/test_shop_search.py:test_browser_survives_reload_loop_policy` |
| 3. heavy resources skipped | `app/browser.py:_skip_heavy` | `tests/test_shop_search.py:test_browser_survives_reload_loop_policy` |
| start failure is an error, not empty | `app/browser.py:BrowserUnavailable` | `tests/test_shop_search.py:test_browser_failure_surfaces` |

## Notes / divergences
- Rule 1 is a convention, not a check. `rg "playwright.sync_api" app/` should
  stay empty. The test scripts are exempt.
- A Chromium cold start costs ~7 s on the first launch after a server start
  (measured). A startup warm-up is **planned**, not built. See STATUS.
