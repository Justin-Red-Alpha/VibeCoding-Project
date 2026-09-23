# sessions — start protocol, handoff logs, end reconciliation

Two modes bracket every piece of work:

- `start` — recover the shared session state before touching code.
- `end` — reconcile docs and write a handoff that makes the next `start` reliable.

A new agent or teammate should be able to run `start`, choose an open continuation,
and proceed **without chat history**. This half of the loop has no equivalent in
semble, graphify or OpenSpec — it is why the skill exists.

---

## start — recover a fresh session

Do this before touching code whenever a session begins, the user says `start`, or
the user says `continue`.

1. **Preflight.** Run the dependency report. Note anything missing and continue
   degraded — a missing tool weakens a step, it does not end the session.
2. **Read `FRAMEWORK.md` once.** It is the method for every architecture and
   reconciliation decision below.
3. **Orient structurally.** If `graphify-out/graph.json` exists, put the user's
   opening question to the graph before opening files at random. If it does not
   exist and there is no `docs/` tree, offer to build both
   ([`docs-tree.md`](docs-tree.md)).
4. **Read `docs/sessions/`, latest first.** Read the latest log fully. Skim older
   logs only until the open thread is clear.
5. **Extract continuations.** From the latest logs, list open items and any live
   handoff state: running commands, remote/local machines, jobs, ports, generated
   data, branches, files, blockers, and exact inspect/resume commands.
6. **Read the in-flight work state.** `openspec list --json` gives every change with
   `completedTasks`/`totalTasks`; for the change the user picks,
   `openspec status --json` names the first `ready` artifact — that is the next
   thing to write. Commands and fields: [`openspec.md`](openspec.md).
7. **Read `docs/STATUS.md`.** Which components are built, partial, or unbuilt, and
   where the component docs are.
8. **Choose the session to continue.**
   - If the user named a task, pick the matching open item / change.
   - If the user only said `start` or `continue`, show the 1–3 most relevant
     continuations and ask which to resume. If there is exactly one obvious
     continuation, resume it and say why.
9. **Drill in only where needed.** For the selected components read `STATUS.md` →
   `ARCHITECTURE.md` → `IMPLEMENTATION.md`, plus the relevant change folder and
   `reviews/`.
10. **Rehydrate live state.** Run the read-only inspect commands recorded in the
    handoff: `git status`, process/job checks, cloud/job status, port checks,
    artifact existence. **Do not restart, stop, or mutate live systems** unless the
    user asked or the next step requires it.
11. **Act.** Continue the recorded next step, answer the question, or route into
    `work` ([`reconcile.md`](reconcile.md)).

---

## The session log — `sessions/YYYY-MM-DD-<slug>.md`

**Immutable.** Never edit a past log. New facts get a new log plus updates to the
living docs (`STATUS`, `ARCHITECTURE`, `IMPLEMENTATION`, the map, suggestions).

The bar: another agent reads the latest relevant log and continues as though it ran
the session. Record exact handles and commands, not vibes. Never record secret
values; record secret *names* only, e.g. `OPENAI_API_KEY present in shell`.

Write the final log during `end`, after reconciliation, so it can name exactly which
docs were updated. If a session is interrupted before `end` completes, the next
`start` should say the previous session has no final handoff and recover from
git/OpenSpec/status facts.

Template:

```markdown
# YYYY-MM-DD — <slug>

## 0. Continuation brief
Current state: <one paragraph, honest and specific>
Next step: <the single best next action>
Resume command/check: `<exact command or file to open first>`

## 1. Work completed
<features/components touched, files changed, docs written, decisions executed.>

## 2. Decisions
| Decision | Verdict | Why |
| --- | --- | --- |
| <option A vs B> | kept A | <reason> |
| <option C> | discarded | <reason> |

Record kept AND discarded options so the next session does not re-litigate them.

## 3. Tests, checks, benchmarks
| Check | Result | What it proved |
| --- | --- | --- |
| `<command>` | <exact result> | <meaning> |

Record exact configs, numbers, and commit IDs when relevant.

## 4. Live handoff state
| Type | Handle / location | State | Inspect / resume | Stop / cleanup |
| --- | --- | --- | --- | --- |
| branch | `<branch>` | <dirty/clean/ahead> | `git status` | <none/command> |
| process | <pid/session/name> | <running/stopped/unknown> | `<command>` | `<command or none>` |
| machine/job | <provider/id/url> | <running/done/unknown> | `<command or URL>` | `<command or owner>` |
| port | `<host:port>` | <serving/free/unknown> | `<command>` | `<command or none>` |
| artifact | `<path or bucket/key>` | <created/partial/needed> | `<command>` | <keep/delete rule> |
| data | `<dataset/table/file>` | <read/written/queued> | `<command>` | <rollback/none> |

Include only rows that exist. If state cannot be verified, write `unknown` plus the
next inspect command. Never leave live infrastructure or generated data only in chat.

## 5. In-flight changes (from OpenSpec)
| Change | Tasks | Status | Next ready artifact |
| --- | --- | --- | --- |
| `<slug>` | 4/9 | in-progress | `tasks` |

Paste from `openspec list --json` + `openspec status --json`. `none` is a valid row.

## 6. Open items
| Priority | Item | Doc/code reference | Next action | Done when |
| --- | --- | --- | --- | --- |
| P0 | <thing> | `<path>` | <exact next step> | <observable check> |

Every open item needs a next action and a done check.

## 7. Architecture / model changes
<new or changed objects, morphisms, placements; coherence-law impact; any known
model/code divergence.>

## 8. Docs reconciled
| Doc | Change |
| --- | --- |
| `<path>` | <what was reconciled> |

## 9. Drift check
`supercharge-drift` → <N dead / M refs>. <fixed | recorded as open item #X>

## 10. Files changed
<code/config/doc files touched, or `none`.>
```

Adapt only by omission when a section is truly irrelevant. Sections 0, 2, 4, 6 and 8
are the handoff — keep them every time.

---

## end — make the next start reliable

Run whenever the user says `end`, `reconcile`, or the session is about to stop.

1. **Drift check.** Run it. A dead row is drift: fix it, or record it as an open item
   with a next action. Never archive a change over a failing drift check.
2. **Snapshot live state.** Inspect and record:
   - git branch/status and uncommitted work;
   - running local commands, dev servers, ports, terminals, logs;
   - remote machines, cloud jobs, queues, schedulers, deployments;
   - generated artifacts, datasets, exports, uploads, temporary files;
   - blockers, approvals needed, and the owner of the next decision.
3. **Snapshot work state.** `openspec list --json` and `openspec status --json` for
   the in-flight table. If a change is complete, archive it — after step 4.
4. **Reconcile affected docs bottom-up** so each level is deduced from settled
   detail below it (§4.3). Full order and rules: [`reconcile.md`](reconcile.md).
5. **Identify open items.** Each needs priority, reference, next action, and a done
   check. If there are none, write `none` — do not omit the section.
6. **Run or record checks.** Run the relevant tests. If a check cannot run, record
   why and the next command.
7. **Write the immutable session log** from the template above.
8. **Refresh the graph** so it tracks the new code (`graphify <path> --update`).
9. **Final sanity statement.** State the next `start` path: latest log to read, open
   item to continue, first command or file to inspect.

Delegate reconciliation one component per agent when useful, then roll up once. Use
independent verifiers for coherence-law claims when the change is non-trivial.

**Definition of done for a session:** drift check clean or recorded, docs reconciled,
session log written, live state recorded or explicitly `none`, open items recorded or
explicitly `none`, and the next `start` has a clear first step.
