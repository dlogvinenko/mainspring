---
name: mainspring-method
description: Apply the Mainspring Method when the operator starts any non-trivial scope of work — a new feature, refactor, new project, major change, audit, or planning session. The Method is a doctrine-first development flow: audit reality first, write a Product Requirements Document (PRD), make ADRs explicit, decompose into atomic Taskmaster tasks, separate manual blockers to the end, then execute via Mainspring waves. TRIGGER on phrases like "new feature", "let's build", "let's plan", "let's refactor", "plan for X", "PRD", "method", "doctrine", "refactor X", or "audit X". SKIP for trivial bug fixes, single-file edits, simple factual questions, renames, doc-only typo fixes, or work that is already mid-flight under an existing PRD/plan.
---

# Mainspring Method

You are operating under the Mainspring Method. The Method is a doctrine-first
development flow that turns vague intent into a written PRD, then into atomic Taskmaster
tasks, then into Mainspring waves.

The Method exists because autonomous AI work fails when agents produce fictional plans,
parallel planning artifacts, mixed manual blockers, and unverifiable progress. Each
commandment below is a defense against one of those failure modes. Honor them strictly.

The canonical example of the Method applied is `docs/prd.md` — Mainspring's own PRD.
When in doubt about shape or tone, reference it.

---

## The 11 Commandments

These are non-negotiable. If a step or template conflicts with a commandment, the
commandment wins.

1. **PRD before code.** Every non-trivial scope starts with a written PRD of fixed shape
   (see `templates/prd.md`). No exceptions, no "I'll plan as I go".
2. **Truth before plans.** Before writing the PRD, audit reality. Run parallel audit
   lanes (use `templates/audit-prompt.md`) to gather verified facts: file LOC, command
   output, and real results from real commands. Never trust hope, vibes, or prior
   AI-written plans without re-verifying.
3. **Reality reset before adding new docs.** Find and delete
   obsolete planning artifacts (use `templates/reality-reset-prompt.md`). Old AI-
   generated plans, superseded refactor docs, parallel planning files. One canonical
   document per scope. No layered drift.
4. **Atomic tasks, not vibes.** When decomposing into Taskmaster, each task names: file
   paths, line numbers (when refactoring), exact acceptance criteria, test plan. Never
   accept "improve X" or "clean up Y" as a task. Use `templates/task.md`.
5. **Manual blockers separated and
   deferred.** Anything requiring human action (production secrets, API keys, sign-offs,
   public submissions, account creation) becomes its own narrow Taskmaster task, marked
   `blocked` from the start, pushed to the LAST phase. Coding work NEVER waits on
   humans.
6. **Phases are commit-able milestones.** Each phase ends with all gates
   green: tests + typecheck + build + docs. No half-finished phases ship. No "we'll come
   back to that". If a phase isn't complete, it isn't a phase — it's still in progress.
7. **4-step verification.** Tests + typecheck + build + docs. Always. A task is not
   done until all four pass.
8. **The wave is the unit.** Once Mainspring is running, one writer+reviewer pass = one
   wave. One wave logs one JSONL line. The PRD's phases become Taskmaster tasks become
   waves.
9. **Metrics drive routing decisions.** When a phase finishes, look at
   `mainspring --metrics`. Which pair worked best? Which tasks stuck? Use data, not
   feelings.
10. **Health rituals.** Weekly (10 min) + monthly (30 min) checkpoints prevent drift.
    Add them to the PRD; do them.
11. **Practice the Method on itself.** Use the Method on the Method itself, on
   Mainspring itself, and on every new project. The Method's PRD
   ([docs/method.md](../../docs/method.md)) is itself PRD-shaped.

---

## The 8-Step Flow

When the skill activates, walk the user through these 8 steps in order. Don't skip;
don't reorder. Each step has a clear input and output, so the user can pause and resume.

### Step 1 — Frame the scope (≤ 5 min)

Ask the operator 3 questions if they're not already answered:

- What is the scope? (one sentence)
- What's the smallest visible end state that means "done"?
- What's explicitly NOT in this scope?

Output: a 3-line scope statement. Save mentally; you'll quote it in the PRD's Mission
section.

### Step 2 — Audit reality (parallel, ≤ 10 min)

Run parallel audit lanes per `templates/audit-prompt.md`. Use the agent runner already
available in the project; the Method requires independent parallel evidence, not a
specific vendor tool. The audit must produce VERIFIED numbers, not estimates:

- LOC counts
- shellcheck/lint/typecheck status
- list of relevant files with byte sizes
- existing related code paths
- existing related docs (and which are stale)
- any current bugs or known broken behavior

Run audits in parallel — never sequentially. Results feed the PRD's "Current truth
snapshot" section.

### Step 3 — Reality reset (≤ 5 min)

Run one reality-reset lane per `templates/reality-reset-prompt.md`. Output: a list of
files that are obsolete / superseded / parallel-planning / AI-fabricated and should be
deleted. Show the operator the list; on confirmation, delete them BEFORE writing the new
PRD. One canonical document per scope.

### Step 4 — Resolve open decisions (≤ 15 min)

Identify decisions that the PRD will need to lock in. For each, draft a one-paragraph
ADR per `templates/adr.md`: Context, Options Considered, Decision, Rationale,
Consequences, Reversal Cost. Then ask the operator for their answer on each ADR. Don't
guess; don't unilaterally decide load-bearing things. The operator owns the
architecture.

Common ADRs that always apply:

- **License** (if eventually OSS): MIT vs Apache-2.0 vs BSD-2.
- **Naming** (if introducing a new component): chosen name, alternatives considered,
  conflict notes.
- **Versioning policy.**
- **Backwards compatibility window** for any breaking change.

Project-specific ADRs are listed in the PRD itself.

### Step 5 — Write the PRD (≤ 30 min for a fresh PRD)

Read `templates/prd.md` and follow its 17-section structure exactly. The PRD must be
self-contained: a future agent reading only the PRD must be able to act without reading
any other doc. Cross-reference the audit (Step 2) for the "Current truth snapshot"
section. Cross-reference the ADRs (Step 4) for the ADR section.

Save the PRD at `docs/<scope>/prd.md` (or the project's convention).

### Step 6 — Decompose the ACTIVE phase into Taskmaster (≤ 15 min per phase)

**Phase-by-phase pattern, not all-at-once.** Decompose ONLY the currently-active phase
(the next one to start work on). Future phases stay as outlines in the PRD's Phase Map
until they activate. Premature decomposition is wasted work — task shapes change based
on what earlier phases actually produced.

Pick the active phase (the next `Inactive` phase after the last `Done` one). For each
PRD task in that phase, generate one Taskmaster task using `templates/task.md`. Apply
the **Manual Blocker Separation Rule**:

- If a task needs ANY human action → mark it `blocked` immediately, push it to the
  last-phase epic.
- If a task can be completed by an LLM agent end-to-end → mark `pending`, place in the
  right phase.
- Mixed tasks get split into a `pending` coding part + a `blocked` manual part with
  explicit dependency.

Each phase typically yields 4-10 atomic Taskmaster tasks. If the active phase yields
>10, the phase is too big — re-scope it in the PRD before decomposing.

Use Mainspring's local decomposition command when available: `mainspring decompose
docs/<scope>/prd.md --phase <name>`. Add `--apply --tasks-file <tasks.json>` when you
want it to write generated Taskmaster tasks idempotently. Manual decomposition with
`task-master add-task --prompt="..."` is the fallback for projects adopting the Method
without Mainspring (or with `--research` only when the task body is genuinely under-
specified — for tasks already detailed in the PRD, no `--research` needed).

When current phase completes, the [Phase activation
ritual](../../docs/playbook.md#phase-activation-ritual) re-invokes Step 6 for the next
phase. The Playbook is the operating contract for that loop.

### Step 7 — Sanity-check the backlog (≤ 5 min)

Run a self-check before handing off to Mainspring:

- Are any "improve X" or "clean up Y" tasks left? Reject them.
- Are manual blockers all in the LAST phase? If not, move them.
- Are phase dependencies right? `task-master validate-dependencies`.
- Are phase 1 tasks atomic enough that an LLM could finish each in <2 hours? If not,
  expand: `task-master expand --id=<id> --research --force`.

When a Taskmaster JSON file is available, run `mainspring scope-check <tasks.json>`
after the checklist. If Mainspring is not installed for the project, apply the same
checks manually before handoff.

### Step 8 — Hand off (≤ 1 min)

Print:

1. Path to the PRD.
2. Top 3 next-up Taskmaster ids with one-line descriptions.
3. Recommended Mainspring invocation:
   `mainspring taskmaster --topology solo --pair claude+codex --once`;
   source-checkout users can run `./mainspring.sh --project /path/to/project taskmaster
   --topology solo --pair claude+codex --once`.
4. Reminder of weekly + monthly health rituals from the PRD.

The user takes it from here. Mainspring runs the loop; the Method's job is done until
the next non-trivial scope.

---

## Templates index

| Template                            | Purpose                                                                                                | When to read |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------ |
| `templates/prd.md`                  | Product Requirements Document — the canonical document shape (17 sections)                             | Step 5       |
| `templates/adr.md`                  | Architecture Decision Record — Context / Options / Decision / Rationale / Consequences / Reversal Cost | Step 4       |
| `templates/task.md`                 | Atomic Taskmaster task with file:line specificity and manual-blocker flag                              | Step 6       |
| `templates/audit-prompt.md`         | Prompt for spawning a parallel audit agent (verified facts, not opinions)                              | Step 2       |
| `templates/reality-reset-prompt.md` | Prompt for the obsolete-doc cleanup pass                                                               | Step 3       |

Always read the template at the start of its step. Don't paraphrase the structure from
memory; templates are precise.

---

## Failure modes to refuse

If you find yourself doing any of these, STOP and re-read the relevant commandment:

- **Writing code before the PRD exists.** Stop. Step 5 first.
- **Writing the PRD without the audit (Step 2).** Stop. The PRD's "Current truth
  snapshot" needs verified numbers, not guesses.
- **Adding a "this looks done" task without acceptance criteria.** Stop. See
  `templates/task.md`. Atomic only.
- **Mixing a manual step into a coding task.** Stop. Split per Commandment 5.
- **Adding a phase without a clear "all 4 verification steps green" exit gate.** Stop.
  Commandment 6.
- **Skipping ADRs because "the answer is obvious".** Stop. The operator decides
  architecture; you draft and they ratify.
- **Accepting a vague request without Step 1.** Stop. Frame the scope in 3 lines first.
- **Using a previously-written plan without re-verifying its claims.** Stop. Old plans
  rot. Commandment 2.

---

## What good output looks like

A successful Method run produces, in order:

1. A 3-line scope statement (Step 1).
2. An audit report with verified numbers (Step 2 output).
3. A list of deleted obsolete files (Step 3 output).
4. A set of ADRs the operator has explicitly ratified (Step 4 output).
5. A PRD at `docs/<scope>/prd.md` of fixed 17-section shape (Step 5 output).
6. Taskmaster backlog with atomic tasks per phase, manual blockers in the last phase
   (Step 6 output).
7. A green `task-master validate-dependencies` (Step 7 output).
8. A clear hand-off to Mainspring (Step 8 output).

Time budget: 60-90 minutes for a medium scope, 2-3 hours for a major refactor. If it's
taking less than 30 minutes, you're cutting corners; check which commandment was
violated.

---

## Versioning

Mainspring Method v0.1 — formalized 2026-04-26 from lived practice on Mainspring's own
PRD.

When commandments change, bump version. When templates change, document migration in
`method/README.md`.
