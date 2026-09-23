# openspec — the delegation map

**Every command name `supercharge` routes to lives in this file and nowhere else.**
When an upstream tool renames something, this is the only file to edit. `SKILL.md`
describes *what* to delegate; this file says *how*.

Verified against a live install of `@fission-ai/openspec@1.10.0` (bin `openspec`,
Node ≥ 20.19.0): every command and every `--json` flag in §1 and §2 was checked with
`--help`. The `/opsx:*` slash commands in §1 are **not** CLI subcommands — `openspec
init` writes them into the project and `openspec update` regenerates them from the
installed version, so **never vendor them** and treat the installed CLI as the
authority. `preflight` prints the version it found.

---

## 1. Lifecycle — which command, when

| supercharge step | OpenSpec slash command | What it produces |
| --- | --- | --- |
| understand the ask | `/opsx:explore` | scoping, no artifacts |
| **plan** (`work` step 1) | `/opsx:propose "<description>"` | `changes/<slug>/proposal.md` |
| design | (part of propose) | `changes/<slug>/design.md` |
| task list | (part of propose) | `changes/<slug>/tasks.md` |
| **implement** (`work` step 2) | `/opsx:apply` | code + ticked tasks |
| check | `/opsx:verify` | validation report |
| **archive** (`work` step 6) | `/opsx:archive` | deltas merged into `specs/`, folder moved |

Expanded profile adds `/opsx:new`, `/opsx:continue`, `/opsx:ff`, `/opsx:bulk-archive`,
`/opsx:onboard`.

Invocation syntax differs per host tool: `/opsx:propose` (standard),
`/opsx-propose` (Cursor, Copilot), `@opsx-propose` (Amazon Q),
`$openspec-propose` (Codex). Use the host's form.

Artifact dependency order is `proposal → {specs, design} → tasks`. Dependencies are
**enablers, not gates** — an artifact can be skipped.

## 2. The machine surface — which JSON field to read

This is the reason OpenSpec is worth delegating to at all. Exactly one JSON document
lands on stdout in `--json` mode; prose goes to stderr.

| Command | Read this |
| --- | --- |
| `openspec status --json` | `artifacts[]` with `status: done\|skipped\|ready\|blocked`, in dependency order — **the first `ready` entry is what to write next**; also `isPlanningComplete`, `applyRequires`, `nextSteps[]` |
| `openspec list --json` | `changes[]` with `completedTasks`, `totalTasks`, `status: no-tasks\|complete\|in-progress` |
| `openspec validate --json` | `items[].valid` plus `issues[]` (`level`/`path`/`message`/`line`). **Exits 1 when any item fails** |
| `openspec instructions <artifact> --json` | `template`, `instruction`, `context`, `rules`, `dependencies[]`, `unlocks[]` |
| `openspec instructions apply --json` | `tasks[]`, `progress{total,complete,remaining}`, `state: blocked\|all_done\|ready` |
| `openspec archive <name> --json` | `archivedAs: YYYY-MM-DD-name`, `specsUpdated`, `warnings[]` |
| `openspec doctor --json`, `openspec context --json` | health, referenced-store status |

Diagnostics share one envelope: `{severity, code, message, target?, fix?}`. Optional
keys are omitted rather than set to null.

`start` uses `list --json` then `status --json`. `end` pastes both into the session
log. Never re-derive this state by reading the markdown.

## 3. Keeping OpenSpec artifacts categorical

**The load-bearing integration detail.** `openspec/config.yaml` carries a free-text
`context:` block and per-artifact `rules:` that are injected into *every*
artifact-generation prompt — stronger enforcement than the same sentences sitting in
a `SKILL.md` the model may or may not re-read.

Write this at `openspec init` time:

```yaml
context: |
  Architecture method: FRAMEWORK.md (Dat / Trn / Loc / Trm + §4.5 coherence laws).
  Every claim must name its object, morphism, location or transmission and map to a
  real file:symbol, a planned item, or an explicit open question. Never invent
  architecture that cannot be grounded.

rules:
  design:
    - State the model delta as objects and morphisms with signature, partiality, semantics
    - Run the §3 Consolidation check — is this a new object, or an existing object plus morphisms?
    - Name the §4.5 coherence laws the change must keep satisfied
    - Isolate effects behind ports; deduce rather than store; one source of truth for shared structure
  specs:
    - Observable, consumer-facing behaviour only — no internal class or function names
    - Every requirement carries at least one happy-path and one failure Scenario
  tasks:
    - Every new or changed morphism gets a row in docs/<component>/IMPLEMENTATION.md with its file:symbol
    - Reconcile ARCHITECTURE.md, IMPLEMENTATION.md and STATUS.md before archiving
    - Run the supercharge drift check and fix dead rows before archiving
```

## 4. `specs/` vs `ARCHITECTURE.md` — pick one per repo

Both plausibly answer "what does this component do". Real duplication risk. Decide
once, at init, and record the choice in `openspec/config.yaml`.

- **A — skip specs.** Set `skip_specs: true` in each change's `.openspec.yaml`.
  `ARCHITECTURE.md` is the only contract; OpenSpec runs proposal → design → tasks.
  Simplest, no duplication, loses the scenario→test win.
- **B — scope specs to the external surface** *(default)*. `openspec/specs/` holds
  observable, consumer-facing behaviour: endpoints, status transitions, webhook
  contracts, CLI flags. `ARCHITECTURE.md` holds internal objects, morphisms and
  laws. Choose this when the project has real external consumers, because each
  `#### Scenario:` block then doubles as one enumerated test — exactly the list
  `work` step 3 would otherwise ask an agent to invent.

OpenSpec's own guidance supports the split: specs must avoid internal class and
function names, library choices, and step-by-step implementation — which is
precisely what `IMPLEMENTATION.md` is for.

Spec files use `## ADDED|MODIFIED|REMOVED Requirements` delta sections inside
`changes/<slug>/specs/<domain>/spec.md`; `archive` merges them into
`openspec/specs/<domain>/spec.md`.

## 5. Setup per repo

```bash
openspec init                                  # creates openspec/
openspec config set telemetry.enabled false    # telemetry is ON by default
```

Then paste §3's `context:` and `rules:` into `openspec/config.yaml`, and record the
§4 choice. Schemas are forkable — `openspec schema fork spec-driven research-first`
— if a repo needs a different artifact DAG.

## 6. Other delegated commands

| Purpose | Command |
| --- | --- |
| build the graph | `graphify <path>` |
| refresh the graph (`end`) | `graphify <path> --update` |
| orient (`start`) | `graphify query "<question>" [--dfs] [--budget N]` |
| blast radius of a change | `graphify affected "<node>" [--depth N]` |
| how two things connect | `graphify path "A" "B"` |
| explain one node | `graphify explain "<node>"` |
| pinpoint a symbol (MCP) | `mcp__semble__search` |
| find similar code (MCP) | `mcp__semble__find_related` |
| pinpoint a symbol (CLI) | `semble search "<query>" <path> [--content docs\|config\|all] [-k N]` |
| drift check | `supercharge-drift [repo] [--json]` |
| dependency report | `supercharge-preflight` |

If a `supercharge-*` shim is not on `$PATH`, run `scripts/drift-check.sh` /
`scripts/preflight.sh` from this skill's own directory.
