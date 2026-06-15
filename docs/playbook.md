# Mainspring Maintainer Playbook

The daily/weekly operational flow for maintainers executing on this repository's
Mainspring Product Requirements Document (PRD). This is not the first-read user
guide; start with [`guide.md`](guide.md) when you want to install or run the
CLI.

> **The four-doc system**:
> | Doc | Question it answers |
> |---|---|
> | [`prd.md`](prd.md) | What are we building, in what phases, with what gates? (the plan) |
> | [`method.md`](method.md) | How do we plan? (the meta — used to write the PRD) |
> | [`playbook.md`](playbook.md) | How do maintainers execute on the plan day by day? (this file) |
> | [`guide.md`](guide.md) | Which command does what? (CLI reference) |
>
> The PRD is the contract. The Method produced it. The Playbook executes it. The Guide is the remote control.

This playbook is itself a Method-shaped output, just at a different level: the PRD's "Operational doctrine" section gives the strategic answers (when to use solo vs team); the Playbook gives the _step-by-step_.

---

## Contents

1. [Phase lifecycle](#phase-lifecycle)
2. [Daily work loop](#daily-work-loop)
3. [Phase activation ritual](#phase-activation-ritual)
4. [Phase completion ritual](#phase-completion-ritual)
5. [Weekly health ritual](#weekly-health-ritual)
6. [Monthly health ritual](#monthly-health-ritual)
7. [Pair selection decision tree](#pair-selection-decision-tree)
8. [Stuck-task escalation](#stuck-task-escalation)
9. [Recursive Method (sub-PRDs)](#recursive-method-sub-prds)
10. [Disaster recovery shortcuts](#disaster-recovery-shortcuts)
11. [Anti-patterns](#anti-patterns)

---

## Phase lifecycle

Five states. A phase is in exactly one at any time.

```
Inactive ──► Activating ──► Active ──► Verifying ──► Done
                                │           │
                                └───── back ◄ (gates fail)
```

| State          | Meaning                                                                           | Source of truth                                                           |
| -------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| **Inactive**   | Phase exists in PRD but no tasks in Taskmaster yet                                | PRD Phase Map; Taskmaster has zero tasks tagged with this phase           |
| **Activating** | Decomposition in progress (Method Step 6 underway)                                | Operator session; transient                                               |
| **Active**     | Tasks in Taskmaster, work happening, at least one task `in-progress` or `pending` | `.mainspring/state/active-phase.json` + Taskmaster                        |
| **Verifying**  | All tasks `done`, running phase-level gates                                       | `.mainspring/state/active-phase.json` flag `verifying: true`              |
| **Done**       | Gates green, PRD checkbox `[x]`, transition timestamp recorded                    | PRD heading `(DONE YYYY-MM-DD)` + `.mainspring/state/phase-history.jsonl` |

Only one phase is `Active` at a time per PRD. A second phase moving to `Active` while the first is incomplete is a Method violation (commandment 6: phases end green or they aren't done).

`.mainspring/state/active-phase.json` shape:

```json
{
  "prd": "docs/prd.md",
  "active_phase": "P1",
  "previous_phase": "P0",
  "activated_at": "2026-04-26T18:42:00Z",
  "completed_phases": ["P0"],
  "tasks_total": 4,
  "tasks_done": 0,
  "verifying": false
}
```

This file is gitignored runtime state. Treat Mainspring command output as canonical when it initializes or updates the state; edit by hand only at phase boundaries or during recovery.

---

## Daily work loop

A normal session, 60-120 min, repeatable. Walk these in order.

### Setup (1 min)

```bash
cd <repo-root>
cat .mainspring/state/active-phase.json    # remind yourself which phase is active
task-master use-tag mainspring             # switch to Mainspring backlog
task-master next                           # show next ready task
```

If `next` returns nothing → either current phase is done (run [Phase completion ritual](#phase-completion-ritual)) or all tasks are blocked (run [Stuck-task escalation](#stuck-task-escalation)).

### Pick the task (1 min)

```bash
task-master show <id>     # full task body
```

Re-read the relevant PRD phase. The task is a concrete instance of a phase commitment; if the task and the PRD disagree, the PRD wins — update the task with `task-master update-subtask --id=<id> --prompt="..."`.

### Run a wave (5-15 min wall, mostly waiting)

Pick the pair per the [decision tree](#pair-selection-decision-tree). Default: `claude+codex`.

```bash
mainspring taskmaster \
  --topology solo \
  --pair claude+codex \
  --once
```

While the wave runs, do not start other work in the same repo. The lock file blocks parallel waves anyway, but interleaved git changes confuse the writer.

### Verify (5 min)

The wave produces:

- One JSONL line in `.mainspring/logs/waves.jsonl`.
- A summary log: `cat .mainspring/logs/latest-summary.log`
- The reviewer's verdict: `tail -30 .mainspring/logs/latest-summary.log | grep -A1 VERDICT`

If verdict = `PASS`:

```bash
# Mainspring repository gate
make release-check
# docs: did we update docs/ if the change affects user-visible behavior?
```

Gate green → mark task done:

```bash
task-master set-status --id=<id> --status=done
```

If any of the four fails: revert wave changes, mark task `in-progress`, fix manually or run another wave with a clarification prompt.

If verdict = `FAIL`:

- Read the rationale: `tail -100 .mainspring/logs/latest-summary.log | grep -A20 RATIONALE`
- If fixable in <5 min: fix and re-run wave (same task)
- If task definition was wrong: update task, then re-run
- If 3rd consecutive FAIL on the same task: see [Stuck-task escalation](#stuck-task-escalation)

### Loop or stop

Loop back to "Pick the task". Stop when:

- All tasks in current phase are `done` → run [Phase completion ritual](#phase-completion-ritual)
- Daily energy is gone (don't push tired commits)
- Hard blocker (stuck-escalated, missing dep)

### End-of-day (3 min)

```bash
git status                                              # operational checkpoints OK to leave
task-master list --status in-progress                   # should be empty or <=1 (yours)
task-master use-tag main                                # switch back to default tag
ls -la .mainspring/logs/latest*.log                     # confirm logs exist for today
```

If anything in `in-progress` other than the task you're holding, set it back to `pending` so tomorrow's `next` is clean.

Stop for the day with the project state understandable to tomorrow's operator.

---

## Phase activation ritual

Trigger: previous phase marked `done` (or starting fresh from PRD Phase 1).

Time budget: 15-30 min.

### Steps

1. **Confirm previous phase is truly done.**

   ```bash
   task-master use-tag mainspring
   task-master list --status pending,in-progress | grep "P<n-1>" || echo "(previous phase clean)"
   ```

   PRD checkbox `[x]` for every task in previous phase. Acceptance criteria of the previous phase verified (re-read them).

2. **Update `.mainspring/state/active-phase.json`** to reflect the new active phase. Increment `completed_phases`, set `tasks_total: <count of new phase's PRD tasks>`, reset `tasks_done: 0`, `verifying: false`.

3. **Decompose the new phase into Taskmaster.** Apply the Method's Step 6 (phase-by-phase pattern):
   - Read the PRD's phase section (e.g. "### P2 — De-monolith").
   - Prefer `mainspring decompose docs/prd.md --phase P<n> --apply --tasks-file <tasks.json>` so generated tasks are validated and idempotent.
   - If decomposing manually, create one Taskmaster task per PRD task using `task-master add-task --prompt="..."`. The prompt should be the full task body following [`method/skill/templates/task.md`](../method/skill/templates/task.md): title, summary, scope, acceptance criteria, test plan, dependencies, manual blocker check, priority, effort.
   - Set inter-task dependencies: `task-master add-dependency --id=<later> --depends-on=<earlier>`.

4. **Sanity-check the new tasks** (Method Step 7):
   - No "improve X" / "clean up Y" titles? Reject and rewrite.
   - All manual blockers (if any in this phase) marked `blocked` and pushed to last-phase position?
   - `task-master validate-dependencies` returns clean?
   - Each task's effort estimate ≤ half-day? If not, expand: `task-master expand --id=<id> --research --force`.

5. **Print the first task** that has all dependencies resolved:

   ```bash
   task-master next
   ```

6. **Document the activation** in `.mainspring/logs/phase-history.jsonl`:
   ```json
   {
     "ts": "2026-04-26T19:00:00Z",
     "event": "phase_activated",
     "phase": "P2",
     "tasks_total": 5,
     "previous": "P1"
   }
   ```

### What NOT to do

- **Decompose more than one phase ahead.** Phase-by-phase pattern: each phase decomposes when it activates, not before. Future phases stay as outlines in the PRD.
- **Skip Step 7 because "the tasks are already in the PRD".** Sanity-check catches things the PRD didn't (e.g. a task that secretly requires a manual blocker).
- **Activate before previous gates pass.** If P1's verification gates failed, P1 is not done; do not activate P2.

---

## Phase completion ritual

Trigger: last task in the current phase marked `done`.

Time budget: 15-30 min.

### Steps

1. **Run the phase verification gate** at phase scope:

   ```bash
   make release-check
   # docs: did the phase produce user-visible changes? Update docs/ if so.
   ```

2. **Verify phase-level acceptance criteria** from the PRD (each phase has an "Acceptance:" block — read every bullet, confirm).

3. **Update PRD**:
   - Change phase header from `### P<n> — <name> (<estimate>)` to `### P<n> — <name> (DONE YYYY-MM-DD)`.
   - Mark every task `[x]`.

4. **Update `.mainspring/state/active-phase.json`**:

   ```json
   {
     "prd": "docs/prd.md",
     "active_phase": null,
     "previous_phase": "P<n>",
     "completed_phases": ["P0", "P1", ..., "P<n>"],
     "completed_at": "2026-04-26T20:00:00Z",
     "verifying": false
   }
   ```

5. **Log to `.mainspring/logs/phase-history.jsonl`**:

   ```json
   {
     "ts": "2026-04-26T20:00:00Z",
     "event": "phase_completed",
     "phase": "P<n>",
     "tasks_done": 4,
     "duration_days": 2
   }
   ```

6. **Decide**:
   - Activate next phase now? Run [Phase activation ritual](#phase-activation-ritual).
   - Pause? Update `.mainspring/state/active-phase.json` with `paused_at`. Resume by re-running activation when ready.

### Phase-completion gates that block transition

A phase is NOT done — do not advance — if any of these fail:

- Any test failing
- Any typecheck error
- Build broken
- shellcheck regression vs phase-start baseline
- Any task in this phase still `pending` or `in-progress`
- Any task whose acceptance criteria failed manual verification

---

## Weekly health ritual

Run every Monday morning. Cap: 10 min.

```bash
cd <repo-root>

# 1. Recent waves
mainspring --metrics --days 7 2>/dev/null \
  || tail -50 .mainspring/logs/waves.jsonl 2>/dev/null | jq -c '{ts, verdict, task_id, pair, duration_s}' \
  || echo "(no waves yet)"

# 2. Environment diagnostic, if anything looks wrong
mainspring doctor

# 3. Backlog state
task-master use-tag mainspring && task-master list

# 4. Stuck check
task-master list --status pending --tag mainspring | head -20
# Anything pending > 7 days → either start it or re-evaluate.

# 5. Active phase truth
cat .mainspring/state/active-phase.json
# Sanity: tasks_done count matches Taskmaster reality?

task-master use-tag main    # switch back
```

Things to act on after the ritual:

- Pass rate per pair drops below 70% → investigate before next wave on that pair
- A task `pending` for >7 days → split, re-prioritize, or block with reason
- Sudden 2x increase in mean duration → engine quality drift; check provider status
- Any phase open >2 weeks → split into smaller phase or re-scope

---

## Monthly health ritual

First Monday of each month. Cap: 30 min. Run weekly first.

```bash
# 1. Full local CI
npm run ci

# 2. Lint everything
npm run lint
shellcheck -S warning mainspring.sh lib/*.sh
ruff check py/

# 3. Coverage check
npx vitest run --coverage | tail -20

# 4. PRD reality audit
# Read PRD's "Current truth snapshot" section.
# For every row, re-run the Source command. Any row that doesn't match reality → update PRD.

# 5. Phase history review
cat .mainspring/logs/phase-history.jsonl | jq -c .
# Average phase duration, longest-running phase, any phase that flipped active→inactive→active (sign of bad scoping).

# 6. Notifier sanity (after P5 ships)
tail -20 .mainspring/logs/notifier.log
# Anything weird? Telegram daemon stuck? rate limits hitting too often?

# 7. Disabled-pairs cleanup (after P6 ships)
cat .mainspring/state/disabled-pairs.json
# Any pair disabled >30 days → re-enable manually or remove from registry.
```

---

## Pair selection decision tree

Until P6 metrics-driven routing ships, the decision tree is:

```
                  ┌─────────────────────────────────────┐
                  │ Is the task plugin/nested-repo?     │
                  └──────────┬──────────────────────────┘
                             │ yes
                             ▼
                       SOLO topology, claude+codex.
                       (Per ADR-03: nested repo invisible to team workers.)
                             │ no
                             ▼
              ┌──────────────────────────────────────────────────────┐
              │ Is one of the engines rate-limited right now?        │
              └──────────────────────────┬───────────────────────────┘
                                         │ yes
                       ┌─────────────────┴─────────────────┐
                       │                                   │
                  Codex limited                     Claude limited
                       ▼                                   ▼
                 claude+claude                       codex+codex
                       │                                   │
                       └─────────────┬─────────────────────┘
                                     │ no
                                     ▼
                             DEFAULT: claude+codex
                             (claude opus writer, codex gpt-5.5 xhigh reviewer)
                             (Per ADR-04: always premium, never fast lanes.)
```

**Topology**: solo unless 4+ ready non-conflicting tasks AND leader workspace clean AND no nested-repo work in queue head.

**`--once` vs continuous**: `--once` while playbook is being applied manually (you read the verdict between waves). Continuous loops are for overnight runs after the loop is well-trusted (post-P3, post-P4).

---

## Stuck-task escalation

A task is _stuck_ after 3 consecutive `FAIL` waves on the same task without intervening task body changes.

### Step 1 (after 3 FAIL): root-cause read

```bash
ls -t .mainspring/logs/*-summary-*.log | head -3 | xargs -I{} sh -c 'echo "=== {} ==="; tail -50 "{}"'
```

Look for: same error repeated → task body is wrong; different errors each time → environment/flake; reviewer rejecting on same field → task acceptance criteria mismatch.

### Step 2: choose one of four moves

| Cause                    | Move            | Command                                                                                          |
| ------------------------ | --------------- | ------------------------------------------------------------------------------------------------ |
| Task body too vague      | Rewrite + retry | `task-master update-subtask --id=<id> --prompt="precise body..."`, then re-run wave              |
| Task too big             | Split           | `task-master expand --id=<id> --research --force`, then start with subtask 1                     |
| Pair wrong for this task | Switch pair     | re-run wave with different `--pair` (e.g. `claude+claude` if `claude+codex` failed)              |
| Task needs human action  | Block           | `task-master set-status --id=<id> --status=blocked` + add note explaining what human needs to do |

### Step 3 (after 5 FAIL): hard-block

```bash
task-master set-status --id=<id> --status=blocked
task-master update-subtask --id=<id> --prompt="HARD BLOCKED after 5 fails. Root cause: <one sentence>. Operator review required before any retry."
```

Do not retry without operator review. Keeps the queue moving.

### Step 4: log the escalation

```json
# .mainspring/logs/escalations.jsonl
{"ts":"2026-04-26T20:00:00Z","task_id":"3.4","fails":5,"root_cause":"...","move":"hard-block"}
```

Monthly health ritual reviews this file.

---

## Recursive Method (sub-PRDs)

When inside an active phase you discover a sub-scope big enough to warrant its own PRD:

### Recognise the trigger

You're working on task `P2-1` (extract heredocs). Mid-work you realise that the heredoc-extraction discovers 4 incompatible Python module patterns and needs its own architectural plan.

### Don't pollute the parent PRD

Wrong: stuff sub-architecture into P2-1's task body (loses traceability) or expand the PRD's P2 with new sub-phases (parent PRD is the wrong place — it's about Mainspring, not heredoc-extraction-architecture).

### Right: spawn a sub-PRD

1. New scope: `docs/sub/heredoc-extraction/prd.md` (or wherever fits — sub-folder under the parent PRD's location).
2. Apply the Method (Steps 1-8) to the sub-scope. The audit/reality-reset/ADRs/PRD/decompose flow is identical, just nested.
3. Sub-PRD's phases become sub-tasks of the parent task `P2-1`. In Taskmaster, create them under tag `mainspring` with `parent_id=<parent_task_id>`.
4. Sub-PRD inherits parent's ADRs unless explicitly overridden in its own ADR section.
5. When sub-PRD's last phase completes, mark parent task done.

### Heuristic for "big enough"

- ≥ 3 sub-tasks of substance (not "one helper function")
- ≥ 1 ADR-worthy decision (e.g. "which Python library do we depend on")
- ≥ 1 day of effort

If only 1-2 of those, just expand the parent task; don't spawn a sub-PRD. Method overhead has a cost.

---

## Disaster recovery shortcuts

Quick-reference table; full procedures in PRD's [Disaster recovery](prd.md#disaster-recovery) section.

| Symptom                                                | Quick recovery                                                                                                                |
| ------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `waves.jsonl` corrupt (`mainspring --metrics` errors)  | `mv .mainspring/logs/waves.jsonl{,.bak}; jq -c . .mainspring/logs/waves.jsonl.bak > .mainspring/logs/waves.jsonl 2>/dev/null` |
| Stale lock (Mainspring claims running with no process) | `mainspring --repair-state --dry-run`, then `mainspring --repair-state --force` if the preview is correct                     |
| Dead host mid-wave (lock held by ghost pid)            | `mainspring --repair-state --dry-run`, then `mainspring --repair-state --force` if the preview is correct                     |
| Wave loop runaway (10+ FAILs same task)                | `mainspring stop --force`, then [Stuck-task escalation](#stuck-task-escalation) Step 3. Use `mainspring stop --help` before cross-project cleanup. |
| Stuck team backend                                     | `mainspring --repair-state --dry-run`; use `mainspring --last-run --restart-team` only after inspecting preserved worker heads |
| Stale worktrees (git worktree list shows ghosts)       | `git worktree prune`                                                                                                          |
| Telegram daemon stuck (no notifier.log activity >1h)   | `mainspring notify-health --format json`; if stale, `mainspring notify-restart`, then `mainspring notify-test`                |
| `.mainspring/state/active-phase.json` corrupt          | Stop active work, inspect the PRD reality, then rebuild the file from source-of-truth tasks                                   |

---

## Anti-patterns

DON'T:

- **Skip the activation ritual** ("I'll just start working on P2"). The ritual exists because future-you will not remember which task was meant to be first when the queue is fresh.
- **Decompose more than one phase ahead.** Premature decomposition is wasted work — the next phase's tasks change shape based on what the current phase actually produced.
- **Mark a task `done` without all 4 verification gates.** The whole Method point is structural; cutting corners undoes it.
- **Run multiple waves on the same task without a body change.** If the wave failed once, repeating without a change is just buying lottery tickets. Update task body first.
- **Edit `.mainspring/state/active-phase.json` while a wave is running.** State race; the wave loop owns that file during a wave.
- **Cross-tag tasks** (`mainspring` + `main`). Tags are scope boundaries; mixing them produces confusion when reading `task-master list`.
- **Push operational-checkpoint commits without a maintainer history pass.** Operational commits are scaffolding; semantic finalization is the contract with future readers.
- **Use `--restart-team` as a routine reset.** It's a recovery step, not a daily action. If you find yourself running it every other day, the team config is wrong.
- **Run two Method invocations in parallel sessions.** The reality-reset step deletes files; two sessions deleting could destroy each other's docs.

---

_Last edited: 2026-04-26. This file is the operational contract; if any other doc disagrees with it on day-to-day execution, update it._
