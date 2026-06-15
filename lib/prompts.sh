#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring mission prompts — writer/reviewer prompt templates
# Globals read: SPEED_PROFILE, MAX_AGENTS
# Globals written: TASKMASTER_BASE_MISSION, NIGHT_BASE_MISSION

agent_mode_is_valid() {
  case "${1:-code}" in
    architect|code|debug|ask) return 0 ;;
    *) return 1 ;;
  esac
}

agent_mode_allows_no_product_change() {
  case "${1:-code}" in
    architect|ask) return 0 ;;
    *) return 1 ;;
  esac
}

agent_mode_closes_taskmaster_item() {
  case "${1:-code}" in
    architect|ask) return 1 ;;
    *) return 0 ;;
  esac
}

agent_mode_writer_contract() {
  case "${1:-code}" in
    architect)
      cat <<'EOF'
Writer role mode: architect
- Do not edit product code or tests.
- Produce architecture, boundary, sequencing, or tradeoff guidance only.
- If the selected work requires implementation to be meaningful, stop and report the implementation handoff instead of pretending the design note shipped the product.
- Close out with the concrete files or decisions a future code-mode wave should own.
EOF
      ;;
    debug)
      cat <<'EOF'
Writer role mode: debug
- Start from the failure evidence and identify the root cause before editing.
- Make the smallest implementation change that fixes the verified cause.
- Preserve existing behavior outside the failing path.
- Close out with the failing evidence, diagnosis, fix, and targeted verification.
EOF
      ;;
    ask)
      cat <<'EOF'
Writer role mode: ask
- Do not edit files.
- Answer, analyze, or research the requested item only.
- If the selected work requires code or docs changes to be complete, stop and report that handoff explicitly.
- Close out with evidence, assumptions, and the next executable step.
EOF
      ;;
    code|*)
      cat <<'EOF'
Writer role mode: code
- Implement the selected product slice normally.
- Keep the diff scoped, reversible, and verified.
- Close out with chapter, competitor, launch, file, simplification, verification, and remaining-gap evidence.
EOF
      ;;
  esac
}

agent_mode_review_contract() {
  case "${1:-code}" in
    architect)
      cat <<'EOF'
Review lens for writer role mode: architect
- Evaluate architecture quality, constraints, boundaries, and handoff clarity.
- FAIL if production code or tests were edited.
- PASS only when the advisory output materially improves the next implementation decision.
- A PASS is advisory and must not close a Taskmaster implementation item as done.
EOF
      ;;
    debug)
      cat <<'EOF'
Review lens for writer role mode: debug
- Evaluate whether the diagnosis matches the evidence and the fix is minimal.
- FAIL if the wave patches symptoms without proving the root cause or skips targeted verification.
EOF
      ;;
    ask)
      cat <<'EOF'
Review lens for writer role mode: ask
- Evaluate answer correctness, source/evidence quality, and clear next steps.
- FAIL if files were edited or the answer claims shipped product progress.
- PASS only when the answer materially improves the next implementation decision.
- A PASS is advisory and must not close a Taskmaster implementation item as done.
EOF
      ;;
    code|*)
      cat <<'EOF'
Review lens for writer role mode: code
- Evaluate shipped product quality, changed-file evidence, tests, and chapter/competitor/launch deltas.
- PASS only if this wave materially improves product quality.
EOF
      ;;
  esac
}

apply_agent_mode_to_prompt() {
  local prompt="$1"
  local agent_mode="${2:-code}"
  printf '%s\n\n%s\n' "$prompt" "$(agent_mode_writer_contract "$agent_mode")"
}

# shellcheck disable=SC2034
TASKMASTER_BASE_MISSION='You are the autonomous execution worker.

Task Master is the ONLY task source.

FIRST read (skip any that are not present):
- AGENTS.md
- CLAUDE.md
- .taskmaster/CLAUDE.md
- docs/prd.md

Then work in a strict loop:
1. Run `task-master next`.
2. If there is no actionable task, stop cleanly.
3. Run `task-master show <id>` for the selected task.
4. If the selected task has subtasks, work the next ready subtask instead of closing the parent task directly.
5. Never mark a parent task done while any of its subtasks remain pending, in-progress, review, or blocked.
6. Implement only the selected task/subtask. Do not invent side quests outside Task Master.
7. Run relevant targeted tests, then required verification.
8. Do not mark the task done yourself. A separate review gate will decide PASS or FAIL.
9. If blocked or partially complete, update the task with concrete notes and leave it not-done.
10. Repeat until no actionable tasks remain.

Required close-out for each completed task:
1. Files changed
2. Simplifications made
3. Verification evidence (tests run, output)
4. Remaining gap, if any

Verification rules:
- Follow AGENTS.md / CLAUDE.md verification requirements when present.
- Do not mark done without proof.
- Stop on destructive, credential, billing, deployment, or ambiguous decisions and report the blocker.

Execution rules:
- Prefer one task at a time from Task Master.
- If a task is too shallow to change real quality, deepen it before calling it done.
- Speed profile: $SPEED_PROFILE
- Maximum subagents / parallel helper lanes allowed: $MAX_AGENTS
- Use as much safe parallelism as the speed profile allows. For speed=max, aggressively use up to $MAX_AGENTS subagents for bounded independent lanes; for speed=fast, use moderate parallelism; for speed=standard, use minimal parallelism.
- Parallelism protocol:
  - For speed=max: begin by identifying up to $MAX_AGENTS bounded, disjoint lanes for the current task/subtask before writing code.
  - Use subagents only when write scopes are disjoint (for example: app code, tests, docs, isolated component files).
  - Do not parallelize edits to the same file or tightly coupled refactors.
  - If no safe disjoint lanes exist, say so and continue serially.
  - In your close-out, state whether you used 0, 1, or N parallel lanes and which file scopes each lane owned.
- Use Context7 for library/API documentation when needed.
- Do not deploy.
- Do not rotate secrets.
- Do not change legal/licensing/authorship without explicit need.'

# shellcheck disable=SC2034
NIGHT_BASE_MISSION='You are the autonomous night worker.

The PRD is the main source of truth for what remains to build and improve.

FIRST read (skip any that are not present):
- AGENTS.md
- CLAUDE.md
- PRD file passed in this prompt

Then work in this order:
1. Read the PRD and identify the next highest-value unfinished slice.
2. Prefer work that is fully autonomous and reversible.
3. Implement one coherent slice at a time.
4. Run relevant targeted tests, then required verification.
5. Update docs/checklists if reality changed.
6. Repeat until you hit a true blocker or no safe autonomous work remains.

Required close-out for each completed slice:
1. Files changed
2. Simplifications made
3. Verification evidence (tests run, output)
4. Remaining gap, if any

Verification rules:
- Follow AGENTS.md / CLAUDE.md verification requirements when present.
- Do not claim done without proof.
- Stop on destructive, credential, billing, deployment, or ambiguous decisions and report the blocker.

Execution rules:
- Use the PRD as the planning source, not freeform wandering.
- Prefer clean vertical slices over scattered micro-edits.
- Speed profile: $SPEED_PROFILE
- Maximum subagents / parallel helper lanes allowed: $MAX_AGENTS
- Use as much safe parallelism as the speed profile allows. For speed=max, aggressively use up to $MAX_AGENTS subagents for bounded independent lanes; for speed=fast, use moderate parallelism; for speed=standard, use minimal parallelism.
- Parallelism protocol:
  - For speed=max: begin by identifying up to $MAX_AGENTS bounded, disjoint lanes for the current slice before writing code.
  - Use subagents only when write scopes are disjoint (for example: UI lane, tests lane, docs lane, server lane on different files).
  - Do not parallelize edits to the same file or tightly coupled refactors.
  - If no safe disjoint lanes exist, say so and continue serially.
  - In your close-out, state whether you used 0, 1, or N parallel lanes and which file scopes each lane owned.
- Use Context7 for library/API documentation when needed.
- Do not deploy.
- Do not rotate secrets.
- Do not change legal/licensing/authorship without explicit need.'
