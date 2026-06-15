#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring common utilities
# Globals read: ROOT_DIR, MAINSPRING_PY_DIR
# Globals written: none
#
# ---------------------------------------------------------------------------
# Intentional globals — set once in mainspring.sh, read by sourced modules
# ---------------------------------------------------------------------------
# These globals are the DOCUMENTED contract between mainspring.sh and its
# modules.  They are set in mainspring.sh's "Global state" block and are
# intentionally shared via the bash source mechanism.  Any function that
# can receive its data as a parameter SHOULD; these survive only because
# bash has no module system and they are read in too many call sites to
# thread as arguments without making every function signature 10+ params.
#
# Category 1 — Identity & paths (set once, never mutated)
#   ROOT_DIR            repo root (two dirs above SCRIPT_DIR)
#   MAINSPRING_PY_DIR   path to the Python helper directory
#   RUNTIME_DIR         path to .mainspring/
#   STATE_DIR           path to runtime state dir
#   TEAM_DIR            path to runtime team worktree/state dir
#   LOG_DIR             path to runtime logs/
#   LOCK_FILE           path to the runtime lock file
#   LAST_RUN_FILE       path to last-run.env
#   CONFIG_FILE         path to project-local .mainspring.yaml
#   WAVE_LEDGER_FILE    path to runtime logs/waves.jsonl
#
# Category 2 — Run configuration (set by CLI parser / wizard, stable for the run)
#   MODE                "taskmaster" | "night"
#   ENGINE              writer engine name
#   REVIEW_ENGINE       reviewer engine name
#   MODEL_OVERRIDE      writer model id override (may be empty)
#   REVIEW_MODEL_OVERRIDE  reviewer model id override (may be empty)
#   CODEX_REASONING_EFFORT reasoning effort for codex engine
#   PAIR_MODE           compound pair string, e.g. "claude+codex"
#   SPEED_PROFILE       "standard" | "fast" | "max"
#   MAX_AGENTS          max parallel agents (1-6)
#   AUTO_RETRY_CI       retry budget for CI-detectable writer failures
#   AUTO_RETRY_CI_LOG   optional local CI log tail injected into CI retries
#   TOPOLOGY            "solo" | "team"
#   RUN_ONCE            "true" | "false"
#   PRD_PATH            path to PRD file (night mode)
#   AUTO_CHECKPOINT     "true" | "false"
#   DEFAULT_CODEX_MODEL, DEFAULT_FAST_CODEX_MODEL, DEFAULT_CLAUDE_MODEL
#
# Category 3 — Team configuration (set once, stable for the run)
#   AUTO_TMUX, TEAM_FALLBACK_TO_SOLO, TEAM_SUPERVISE
#   TEAM_POLL_SECONDS, SELF_HEAL, STALE_PROCESS_MINUTES
#   AUTO_CHECKPOINT_DENY_PATHS  (array of git pathspec excludes)
#
# Category 4 — Mutable runtime state (cross-module by necessity)
#   ACTIVE_CHILD_PID       PID of the current writer/reviewer subprocess.
#                          Set by engines.sh:run_with_heartbeat, read by
#                          mainspring.sh:cleanup_children trap.  Must be
#                          global because the EXIT trap has no parameters.
#   ACTIVE_HEARTBEAT_PID   PID of the heartbeat watcher for the child.
#                          Same lifecycle as ACTIVE_CHILD_PID.
#   IDLE_WAVES             consecutive idle-wave counter (wave_loop.sh).
#   WAVE                   1-indexed wave counter within the run (wave_loop.sh).
#   LOG_FILE               per-run log path (set in wave_loop.sh:run_wave_loop).
#   SUMMARY_FILE           per-run summary path (set in wave_loop.sh:run_wave_loop).
#
# Category 5 — Prompt templates (set once by prompts.sh, consumed by wave_loop.sh)
#   TASKMASTER_BASE_MISSION, NIGHT_BASE_MISSION
#
# Every other piece of context should be threaded as an explicit function
# parameter.  When adding a new global, document it here and in the
# module header that writes it.
# ---------------------------------------------------------------------------

git_status_short() {
  git status --short --untracked-files=no -- . \
    ':(exclude).mainspring' \
    ':(exclude)node_modules' \
    ':(exclude)dist' \
    ':(exclude)coverage' \
    ':(exclude)playwright-report' \
    ':(exclude)test-results' \
    ':(exclude)**/__pycache__/**' \
    ':(exclude)**/*.pyc' 2>/dev/null || true
}

git_status_all() {
  git status --short --untracked-files=all -- . \
    ':(exclude).mainspring' \
    ':(exclude)node_modules' \
    ':(exclude)dist' \
    ':(exclude)coverage' \
    ':(exclude)playwright-report' \
    ':(exclude)test-results' \
    ':(exclude)**/__pycache__/**' \
    ':(exclude)**/*.pyc' 2>/dev/null || true
}

mainspring_python() {
  local root="${ROOT_DIR:-}"
  local script_root="${SCRIPT_DIR:-$root}"
  if [ -n "${MAINSPRING_PY:-}" ] && [ -x "$MAINSPRING_PY" ]; then
    printf '%s\n' "$MAINSPRING_PY"
    return 0
  fi
  if [ -n "${MAINSPRING_RUNTIME_PYTHON:-}" ] && [ -x "$MAINSPRING_RUNTIME_PYTHON" ]; then
    printf '%s\n' "$MAINSPRING_RUNTIME_PYTHON"
    return 0
  fi
  if [ -n "${VIRTUAL_ENV:-}" ] && [ -x "$VIRTUAL_ENV/bin/python3" ]; then
    printf '%s\n' "$VIRTUAL_ENV/bin/python3"
    return 0
  fi
  if [ -n "$script_root" ] && [ -x "$script_root/.venv/bin/python3" ]; then
    printf '%s\n' "$script_root/.venv/bin/python3"
    return 0
  fi
  if [ -n "$root" ] && [ "$root" = "$script_root" ] && [ -x "$root/.venv/bin/python3" ]; then
    printf '%s\n' "$root/.venv/bin/python3"
    return 0
  fi
  printf '%s\n' "python3"
}

count_nonempty_lines() {
  sed '/^[[:space:]]*$/d' | wc -l | tr -d ' '
}

print_limited_lines() {
  local limit="${1:-20}"
  sed '/^[[:space:]]*$/d' | sed -n "1,${limit}p"
}

hash_file_sha256() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$path" | awk '{print $NF}'
    return 0
  fi
  return 1
}

format_epoch_local() {
  local epoch="$1"
  if [ -z "$epoch" ]; then
    echo "unknown"
    return
  fi
  date -r "$epoch" "+%-d %B %Y, %H:%M %Z" 2>/dev/null || echo "$epoch"
}

build_prd_brief() {
  local prd_path="$1"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/prd_brief.py" "$prd_path"
}

auto_checkpoint_dirty_tree() {
  # All context is passed explicitly — no hidden global reads.
  # Args: reason, auto_checkpoint_enabled, log_file, deny_paths...
  local reason="${1:-Mainspring checkpoint}"
  local auto_checkpoint_enabled="${2:-true}"
  local log_file="${3:-}"
  shift 3 || shift $#
  local -a deny_paths=("$@")

  if [ "$auto_checkpoint_enabled" != "true" ]; then
    return 1
  fi
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 1
  fi
  if git status --porcelain --untracked-files=all -- . "${deny_paths[@]}" | grep -q .; then
    :
  else
    return 0
  fi

  echo "Auto-checkpointing dirty leader workspace before team fanout."
  [ -n "$log_file" ] && echo "Auto-checkpointing dirty leader workspace before team fanout." >> "$log_file"
  if ! git add -A -- . "${deny_paths[@]}" >/dev/null 2>&1; then
    echo "Auto-checkpoint staging reported warnings; continuing if safe files were staged."
    [ -n "$log_file" ] && echo "Auto-checkpoint staging reported warnings; continuing if safe files were staged." >> "$log_file"
  fi

  if git diff --cached --quiet; then
    echo "Auto-checkpoint found no safe staged files; continuing."
    [ -n "$log_file" ] && echo "Auto-checkpoint found no safe staged files; continuing." >> "$log_file"
    return 0
  fi

  local changed_count
  changed_count="$(git diff --cached --name-only | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')"
  if git commit --no-verify -m "Checkpoint verified Mainspring workspace state" \
      -m "$reason" \
      -m "Committed automatically before creating parallel worker worktrees so team fanout starts from a reproducible clean leader checkout." \
      -m "Changed-files: ${changed_count:-unknown}" \
      -m "Constraint: team fanout requires a clean leader checkout before creating worker worktrees" \
      -m "Rejected: git add . without denylist | would capture runtime state, screenshots, local DBs, or secrets" \
      -m "Confidence: medium" \
      -m "Scope-risk: moderate" \
      -m "Reversibility: clean" \
      -m "Directive: Review this checkpoint as an operational boundary before squashing or publishing history" \
      -m "Tested: inherited from completed Mainspring wave evidence or pre-fanout verification" \
      -m "Not-tested: no additional tests run by the checkpoint step itself" >/dev/null 2>&1; then
    echo "Auto-checkpoint committed ${changed_count:-unknown} files."
    [ -n "$log_file" ] && echo "Auto-checkpoint committed ${changed_count:-unknown} files." >> "$log_file"
    return 0
  fi

  echo "Auto-checkpoint failed; leaving workspace untouched for solo fallback."
  [ -n "$log_file" ] && echo "Auto-checkpoint failed; leaving workspace untouched for solo fallback." >> "$log_file"
  return 1
}
