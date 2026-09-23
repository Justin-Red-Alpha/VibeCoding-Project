---
name: supercharge
description: >
  Runs the session loop and architecture discipline for a software project.
  Use when the user runs /supercharge start|work|end, opens or closes a work
  session, asks to hand off, resume, or recover where work was left, wants the
  architecture *intent* written down (objects, morphisms, locations,
  transmissions per FRAMEWORK.md), wants docs reconciled against code after a
  change, or wants drift between docs and code checked. Not a code-search tool
  and not a change-proposal tool — it routes to those.
---

# supercharge

Five tools, one loop, one install. `supercharge` owns the **session loop** and the
**intent layer**; it delegates everything else and never reimplements it.

| Slot | Owner | Answers |
| --- | --- | --- |
| Retrieval — pinpoint | **semble** | where is symbol X |
| Retrieval — structural | **graphify** | how does X connect to Y |
| Work state | **OpenSpec** | what is in flight, what is next, is it done |
| Memory — cross-project | **gbrain** | what did we decide, in any repo |
| Intent | **supercharge** | what the system is *supposed* to be |
| Continuity | **supercharge** | where we were, and the exact command that resumes it |

semble, graphify and OpenSpec all describe **what exists**. A description derived
from the code can never contradict the code. Drift is only detectable when
something independent asserts intent — that is this skill's job.

gbrain remembers across repos; `docs/sessions/` remembers *this* repo. They are not
two stores of the same thing: **supercharge stays the author**, gbrain indexes what it
wrote. Never write a session narrative straight into gbrain — that forks the record.

## Ownership law — one writer per artifact

Hard rule. Breaking it is how four stores rot into four stale stores.

```
intent       → docs/<component>/ARCHITECTURE.md    supercharge — hand-authored, normative, small
mapping      → docs/<component>/IMPLEMENTATION.md  supercharge rows, machine-verified by drift-check
in-flight    → openspec/changes/<slug>/            OpenSpec — machine-checkable
behaviour    → openspec/specs/<domain>/spec.md     OpenSpec — observable contract only
continuity   → docs/sessions/<date>-<slug>.md      supercharge — live state + resume commands
structure    → graphify-out/                       graphify — derived, never hand-edited
memory       → the gbrain brain repo                 gbrain — an INDEX over docs/sessions/, never the original
```

Corollaries: nothing in `openspec/changes/` survives past archive; `graphify-out/`
is derived and git-ignored; `docs/` is never generated wholesale.

## Grounding rule

The formal root method is [`FRAMEWORK.md`](FRAMEWORK.md) — read it once per session
before authoring any doc. A running system holds and transforms data (`Dat`, `Trn`)
and transmits it between sites (`Loc`, `Trm`); "good architecture" becomes something
you *check* against the §4.5 coherence laws, not argue about.

Never write free-floating architecture prose. For each claim: name the `Dat`, `Trn`,
`Loc`, or `Trm`; cite the FRAMEWORK rule; map it to `file:symbol` in
IMPLEMENTATION.md when built. A claim with no model location and no code or planned
realization is an open question or is discarded — it is not architecture.

1. Data / states / files / API payloads / records → `Dat`.
2. Functions / jobs / transitions / validators / renders / imports / exports → `Trn`.
3. Processes / browsers / servers / workers / databases / queues → `Loc`;
   cross-boundary carriers → `Trm`.
4. Every accepted model row maps to `file:symbol`, `planned`, or `open question`.

## The three modes

### `start` — restore context

1. Run `preflight` (`supercharge-preflight`, or `scripts/preflight.sh` from this
   skill's directory). Report anything missing and continue degraded.
2. **Orient.** If `graphify-out/graph.json` exists, query the graph with the user's
   opening question rather than reading files at random. If it does not exist and
   there is no `docs/` tree, offer to build both.
3. **Continuity.** Read the newest 1–3 `docs/sessions/*.md`, newest first, for live
   state and resume commands. This is the half no other tool has.
4. **Work state.** List in-flight OpenSpec changes with their task progress; for the
   change the user picks, ask OpenSpec what artifact is ready next.
   Commands and JSON fields: [`references/openspec.md`](references/openspec.md).
5. Read `docs/STATUS.md`, then only the component docs for whatever the user picks.
6. **Output:** where we were, what is in flight, what resumes it — quoting the exact
   commands from the session log.

No docs tree yet? Scaffold it — [`references/docs-tree.md`](references/docs-tree.md).

### `work` — plan → implement → reconcile

**There is deliberately no `/supercharge-work` command.** This runs automatically
whenever the skill is active and the user asks to add, change, or fix code — the
request *is* the trigger. `start` already loaded this section, so the flow below is
in context for the rest of the session; the references are read on demand.

1. **Plan** → delegate to OpenSpec's propose flow. Do **not** hand-write a plan
   document. The categorical discipline is enforced through `openspec/config.yaml`
   `rules:`, injected into every artifact prompt — see
   [`references/openspec.md`](references/openspec.md).
2. **Implement** → delegate to OpenSpec's apply flow. Locate touch sites with
   semble, never a blind grep sweep. Use graphify to find what a change reaches.
3. **Test at volume** — partiality boundaries (defined *and* undefined branches),
   composition-rule invariants, deduced-morphism checks, §4.5 failure modes, functor
   laws, boundary inputs only. [`references/reconcile.md`](references/reconcile.md).
4. **Reconcile** — non-optional, in order: `IMPLEMENTATION.md` rows →
   `ARCHITECTURE.md` morphism table and diagram → component `STATUS.md` → root
   `IMPLEMENTATION.md` (only if a code root, shared object, or inter-component port
   changed) → root `STATUS.md` → `architecture-map.md` (only if atoms or components
   changed). Write `reviews/review-<slug>.md` as the §4.5 checklist run.
   [`references/reconcile.md`](references/reconcile.md).
5. **Drift check** must pass before archiving: `supercharge-drift` (or
   `scripts/drift-check.sh`). A dead row is drift — fix it or record it.
6. **Archive** the change so its spec deltas merge into `openspec/specs/`.

### `end` — make the next `start` reliable

1. Run the drift check; fix or record every dead row.
2. Reconcile any docs the session touched (step 4 above).
3. Snapshot the in-flight OpenSpec state and paste it into the session log.
4. Write `docs/sessions/YYYY-MM-DD-<slug>.md` — **immutable**: decisions made, kept
   and discarded; benchmarks and comparisons; tests run; open ends; **live execution
   state** (running commands, jobs, machines, ports, generated artifacts) and
   **exact resume/inspect commands**. Template and bar:
   [`references/sessions.md`](references/sessions.md).
5. Update the graph so it tracks the new code.
6. If gbrain is installed **and preflight did not report an unconfigured brain**,
   index the log you just wrote —
   `gbrain capture --file docs/sessions/<newest>.md`. Index, never author: the file in
   git stays the source of record. Its `think` gap analysis (what the brain does *not*
   know) is the one capability this loop cannot produce on its own.

## Non-negotiable disciplines

1. **Start and end every session.** Never leave open work, live machines, running
   jobs, generated data, or blocked commands only in chat.
2. **No imagined architecture.** Grounded in `Dat`/`Trn`/`Loc`/`Trm` and mapped to
   real code or an explicit plan — or it is an open question, not a component.
3. **Model before code (§6.1).** No component gets code before it has an
   ARCHITECTURE.md section.
4. **Reconcile in the same change (§6.3).** A new field is a new morphism: update
   the morphism table and IMPLEMENTATION.md *with* the code, not after.
5. **Deduce, don't redescribe (§4.3, §5).** Roll-ups summarise and point at the
   per-component files; they never fork their content.
6. **The doc is the spec (§6.6).** Code violating a composition rule ⟹ fix the code
   or add an explicit `Note:` exception. Undocumented exceptions rot.
7. **Immutable sessions.** Never edit a past `sessions/*.md`. New findings ⟹ a new
   log plus updates to the *living* docs.
8. **Run the §4.5 checklist** before merging any non-trivial change.

## Degrading

Every tool is optional. Missing graphify → orient from `docs/` and sessions, skip
the graph update. Missing OpenSpec → no in-flight list; write the plan into the
change folder by hand. Missing semble → grep fallback. Missing gbrain → the session
log is still written, just not indexed across repos. The drift check needs only
git and grep, so it always works. `preflight` says what is absent; the session
continues either way.

## Orchestration

Fan out read-only agents for reading a system, writing tests, and reconciling one
component each; launch independent agents in one batch so they run concurrently.
Verify each coherence-law claim with independent cheap-tier verifiers — a panel's
power is independence, not depth. Reserve the top tier for framing the model and
judging conflicts, never inside the loop.
