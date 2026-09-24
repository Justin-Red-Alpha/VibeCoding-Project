# Settings — categorical model

> Model-first (FRAMEWORK §2/§4). Intended specification for this component. The
> code realises it (see IMPLEMENTATION.md). Source of record: `app/site_settings.py`,
> `app/admin.py` (the settings and maintenance routes).

## 1. Overview
The site-wide values an admin can change without a restart:
- the default display currency;
- the shops searched;
- the refresh interval;
- the discovery limits;
- whether archive lookups are paused.

It also covers the admin's maintenance actions: refresh everything, refresh FX,
and pause or resume lookups.

## 2. Why
Each value is a **deduced** morphism: `effective(key) = db(key) ∨ env(key) ∨
default(key)`, with validation at each step. Reading it at use time, rather than
at import, is what makes "no restart" true. Before this change, the values were
module constants frozen at import. Validation happens in the setter, so an
invalid value never becomes the stored one.

## 3. Core category
```mermaid
graph LR
    K["SettingKey"]
    DB["settings row"]
    E["env var"]
    D["code default"]
    V["value"]
    K -.->|"db?"| DB
    K -.->|"env?"| E
    K -->|"default"| D
    K -->|"effective (deduced)"| V
    style K fill:#cf7fcf,color:#fff
    style DB fill:#4f8cf7,color:#fff
    style E fill:#9a9a9a,color:#fff
    style D fill:#f7c04f,color:#000
    style V fill:#9a9a9a,color:#fff
```

## 4. Morphism table
| Morphism | Signature | Partiality | Semantics |
| --- | --- | --- | --- |
| `db?` | `SettingKey → value` | Partial | the admin's saved value |
| `env?` | `SettingKey → value` | Partial | the old environment variable (`REFRESH_INTERVAL_HOURS`, `DISCOVER_*`, `SEARCH_DOMAINS`) |
| `default` | `SettingKey → value` | Total | built in |
| `effective` | `SettingKey → value` | Deduced | the first *valid* of db, env, default. Read at use time |

## 6. Composition rules
1. **Range-checked:** refresh 1–168 h; per-shop 1–20; price lookups 0–20. The
   currency must be one of `DISPLAY_CURRENCIES`. Shops must be ones an adapter
   knows, never an arbitrary site.
2. **All or nothing** on the admin form: any invalid value restores every value
   saved earlier in that submission.
3. **Applied live:** search reads `search_domains()` per search; the stream reads
   the limits per request; the refresh interval reschedules the running job.
4. **Pause is honoured at the source:** `history.schedule_backfill` returns
   without scheduling while paused.

## 7. Atoms owned (FRAMEWORK §4)
**Trn**: the typed getters and validated setters in `site_settings`, and
`scheduler.set_refresh_interval`.
**Loc**: `ServerProc`, `SQLite` (`settings` table).
**Trm**: `t_sql` only.

## 8. Bridges to other components (ports)
| Boundary morphism | Signature | Stored? | Semantics |
| --- | --- | --- | --- |
| `search_domains` | `settings → discovery` | Stored | `providers.search_domains` delegates here |
| limits | `settings → web` | Stored | `discover_stream`, `discover_page` |
| refresh interval | `settings → refresh` | Stored | `start_scheduler`, `set_refresh_interval` |
| history pause | `settings → history` | Stored | `schedule_backfill` |
| default currency | `settings → web / templating` | Stored | anonymous visitors, and users without a preference |
