# work — implement, test at volume, reconcile

The plan step is delegated: OpenSpec's propose flow writes `proposal.md`,
`design.md` and `tasks.md`, kept categorical by the `rules:` block in
`openspec/config.yaml` ([`openspec.md`](openspec.md)). **Do not hand-write a plan
document** — that artifact has one owner and it is not this skill.

What stays here is everything after: code, a suite worth trusting, and making the
docs true again. Steps 2–4 are non-optional. A change is not done because it works.

---

## 1. Code

Implement the change's task list. Keep the diff aligned with `ARCHITECTURE.md`
intent; where the code must diverge from the design, note it — you feed it back in
step 4.

Locate touch sites with **semble**, never a blind grep sweep. Ask **graphify** what
a change reaches before you widen it (`graphify affected "<node>"`). Apply the §5
principles: isolate effects behind ports, deduce don't store, one source of truth
for shared structure, YAGNI.

## 2. Write tests — at volume, via subagents, covering every edge case

The highest-leverage delegation. The suite must be **trustworthy**: a green run
means the behaviour is actually correct, not merely exercised.

Fan out test-writing agents — one per behaviour cluster or component, launched
concurrently. Each agent's brief is to enumerate the edge cases the *model*
dictates, then write tests for all of them:

- **Partiality boundaries** — for a `Partial` morphism, test where it is defined
  **and** where it is undefined (`?` / null / empty). Both branches.
- **Composition-rule invariants** (ARCHITECTURE §6) — one test per invariant
  (`total = subtotal + tax` holds under every mutation path).
- **Deduced morphisms** — assert the deduced value equals its definition **and is
  not independently stored**. This is the guard against the copy that drifts (§5).
- **Coherence-law failure modes** (§4.5) — a `Trm`'s datum absent at one end
  (Laws 1/2), an unmediated cross-`Loc` reach (Law 4).
- **Functor laws** where a functor is claimed — a state machine reaches only legal
  states; a strategy resolver dispatches every registered key.
- **Boundary inputs only** (§5 YAGNI) — validate at the `Trm`s into the component;
  trust internal guarantees, do not test impossible internal states.

When resolution **B** is in force (external-surface specs, see
[`openspec.md`](openspec.md) §4), every `#### Scenario:` in the change's delta spec
is already one enumerated test — start from that list instead of inventing it.

No frameworks beyond what the repo already uses; match the existing test style.

## 3. Run tests → fix until green

On failure, fix the **root cause**, not the symptom: grep every caller of the
function you touch — one guard in the shared morphism beats a guard in every
caller. Re-run. A failing suite is not "done".

## 4. Reconcile docs with the built code

Implementing changed the design in ways the plan did not foresee. **Make the docs
true** (§6.3). Bottom-up, so each level is deduced from settled detail below it
(§4.3) — do the steps in this order and skip only the ones whose condition is false:

| # | Doc | Update | Skip when |
| --- | --- | --- | --- |
| 1 | `docs/<c>/IMPLEMENTATION.md` | new/changed rows: object or morphism → `file:symbol`, `State` = built/partial/planned | never — this is the ground truth |
| 2 | `docs/<c>/ARCHITECTURE.md` | morphism table **and** diagram in the same step; composition rules; explicit `Note:` exceptions | the model did not change |
| 3 | `docs/<c>/STATUS.md` | recompute built/partial/unbuilt, refresh needs-work rows | nothing in that component changed |
| 4 | `docs/IMPLEMENTATION.md` | component code roots, shared objects, inter-component ports | no code root, shared object, or port changed |
| 5 | `docs/STATUS.md` | one row per component, deduced from step 3 | no component status changed |
| 6 | `docs/architecture-map.md` | four-atom tables, component table, §4.5 checklist | no atoms or components changed |
| 7 | `docs/<c>/suggestions.md` + roll-up | refresh | the model did not change materially |

**Diagram ⇔ table** is a hard invariant: every arrow in a diagram appears in a
morphism table and every table row appears in a diagram. Fixing one without the
other is the most common way these docs go quietly wrong.

Then write `docs/<c>/reviews/review-<slug>.md` — the §4.5 checklist run against
what was actually built:

```markdown
# Review — <slug>

> Ran after building. Checks the change against FRAMEWORK §4.5. Not a prose review.

## Coherence laws
- [x] 1. Placement honesty — <one line of evidence>
- [x] 2. Transmission well-typing — <one line>
- [x] 3. Placement totality — <one line>
- [ ] 4. Dependency mediation — FAIL: `<Loc A>` reaches `<Loc B>` with no `Trm`
      → open item, `<next action>`
- [x] 5. Composition soundness — <one line>
- [x] 6. runsAt is a relation — <one line>

## Model delta actually shipped
<what the built code differs from in design.md, and which doc absorbed it>

## Modeling smells swept (§3)
<no parallel objects · deduced not copied · one source of truth per shared Dat>
```

`[x]` PASS, `[ ]` FAIL with the localised defect named, `[~]` partial/advisory. A
FAIL is a real architecture bug — surface it as an open item, do not paper over it.

## 5. Drift check

Run it before archiving. Every `` `path:symbol` `` claimed in a
`docs/*/IMPLEMENTATION.md` must resolve against `git ls-files`. A dead row means
either the code moved and the doc lied, or the row was aspirational — fix the row,
fix the code, or demote its `State` to `planned`. Only then archive the change.

## 6. Session close

If this ends the session, follow [`sessions.md`](sessions.md) and write the
immutable handoff **after** reconciliation, so it can name exactly which docs moved.

**Definition of done:** code + green suite + reconciled docs + coherence checklist +
clean drift check + live/open state recorded.

---

## Orchestration — tier per §6

| Step | Delegate | Tier |
| --- | --- | --- |
| Locating touch sites | semble/graphify, then read-only agents in parallel | cheap |
| Model delta / design | main thread, or one design agent for hard designs | high |
| Coding | one agent per independent slice | mid |
| Test enumeration + writing | agents in parallel, one per behaviour cluster — **the volume win** | mid; cheap for routine suites |
| Fixing | one agent per independent failure cluster, root-cause discipline | mid |
| Reconciliation | one agent per component, then one for the roll-ups | mid → cheap |
| Coherence-law verification | independent verifiers, one per law | cheap — the power is independence |

Launch independent agents in one batch so they run concurrently.
