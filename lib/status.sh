#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring status reporting, repair, and runtime state management
# Globals read: ROOT_DIR, MAINSPRING_PY_DIR, MODE, TOPOLOGY, ENGINE,
#   MODEL_OVERRIDE, REVIEW_ENGINE, REVIEW_MODEL_OVERRIDE, DEFAULT_CODEX_MODEL,
#   DEFAULT_FAST_CODEX_MODEL, CODEX_REASONING_EFFORT, LOCK_FILE,
#   WAVE_LEDGER_FILE, LOG_DIR, STATE_DIR, AUTO_CHECKPOINT
# Globals written: none

runtime_state_dir() {
  echo "${STATE_DIR:-$ROOT_DIR/.mainspring/state}"
}

nested_repo_status_summary() {
  local repo="$1"
  local label="$2"
  if [ ! -d "$repo" ]; then
    echo "$label: missing"
    return 0
  fi
  if ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "$label: present, not a git repo"
    return 0
  fi

  local branch head_desc status staged unstaged untracked first_entries
  branch="$(git -C "$repo" branch --show-current 2>/dev/null || true)"
  if git -C "$repo" rev-parse --verify HEAD >/dev/null 2>&1; then
    head_desc="$(git -C "$repo" rev-parse --short HEAD 2>/dev/null || true)"
  else
    head_desc="no commits yet"
  fi
  status="$(git -C "$repo" status --porcelain --untracked-files=all 2>/dev/null || true)"
  staged="$(printf '%s\n' "$status" | awk '/^[MADRCU]/ { count++ } END { print count + 0 }')"
  unstaged="$(printf '%s\n' "$status" | awk '/^.[MADRCU]/ { count++ } END { print count + 0 }')"
  untracked="$(printf '%s\n' "$status" | awk '/^\?\?/ { count++ } END { print count + 0 }')"
  echo "$label: git repo branch=${branch:-unknown} head=$head_desc staged=$staged unstaged=$unstaged untracked=$untracked"
  if [ -n "${status// }" ]; then
    first_entries="$(printf '%s\n' "$status" | print_limited_lines 12)"
    printf '%s\n' "$first_entries" | sed 's/^/  /'
  fi
}

nested_repo_dirty_count() {
  local repo="$1"
  if [ ! -d "$repo" ] || ! git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo 0
    return 0
  fi
  git -C "$repo" status --porcelain --untracked-files=all 2>/dev/null | count_nonempty_lines
}

active_team_status_summary() {
  local found=false config team_name status_json state_dir
  state_dir="$(runtime_state_dir)"
  for config in "$state_dir/team"/*/config.json; do
    [ -f "$config" ] || continue
    found=true
    team_name="$(basename "$(dirname "$config")")"
    if command -v omx >/dev/null 2>&1; then
      status_json="$(omx team status "$team_name" --json 2>/dev/null || true)"
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/runtime_state.py" team-status "$team_name" "$status_json"
    else
      echo "$team_name: team backend command missing from PATH; state file exists"
    fi
  done
  if [ "$found" = false ]; then
    echo "none"
  fi
}

runtime_state_summary() {
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/runtime_state.py" runtime-summary "$(runtime_state_dir)"
}

taskmaster_json_status_summary() {
  local tasks_file="$ROOT_DIR/.taskmaster/tasks/tasks.json"
  if [ ! -f "$tasks_file" ]; then
    echo "Taskmaster: missing .taskmaster/tasks/tasks.json"
    return 0
  fi
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" status-summary "$tasks_file"
}

taskmaster_scope_safety_summary() {
  local tasks_file="$ROOT_DIR/.taskmaster/tasks/tasks.json"
  if [ ! -f "$tasks_file" ]; then
    echo "scope: Taskmaster file missing"
    return 0
  fi
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" scope-summary "$tasks_file"
}

# shellcheck disable=SC2120
last_wave_summary() {
  local ledger="${1:-$WAVE_LEDGER_FILE}"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/wave_log.py" last-summary "$ledger"
}

# shellcheck disable=SC2120
wave_routing_hints() {
  local ledger="${1:-$WAVE_LEDGER_FILE}"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/wave_log.py" routing-hints "$ledger"
}

filter_runtime_process_lines() {
  awk '
    {
      if ($0 ~ /Reply exactly: ok/) {
        next
      }
      kind = ""
      if ($0 ~ /mainspring(\.sh)?([[:space:]]+[^[:space:]]+)*[[:space:]]+taskmaster([[:space:]]|$)/) {
        kind = "mainspring-taskmaster"
      } else if ($0 ~ /mainspring(\.sh)?([[:space:]]+[^[:space:]]+)*[[:space:]]+night([[:space:]]|$)/) {
        kind = "mainspring-night"
      } else if ($0 ~ /mainspring(\.sh)?([[:space:]]+[^[:space:]]+)*[[:space:]]+--last-run([[:space:]]|$)/) {
        kind = "mainspring-last-run"
      }
      if (!kind) {
        next
      }
      printf "pid=%s stat=%s kind=%s\n", $1, $3, kind
      found = 1
    }
    END {
      if (!found) {
        print "none"
      }
    }
  '
}

runtime_process_summary() {
  ps -axo pid,ppid,stat,command | filter_runtime_process_lines
}

tmux_mainspring_summary() {
  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux not found"
    return 0
  fi

  local lines
  lines="$(tmux ls 2>/dev/null | awk -F: '
    $1 ~ /^mainspring(-|$)/ {
      print substr($0, 1, 220)
      found = 1
    }
    END {
      if (!found) {
        print "none"
      }
    }
  ')" || lines="none"
  printf '%s\n' "$lines"
}

status_recommendations() {
  echo "Open live dashboard: mainspring hud"
  echo "Preview stale-state cleanup: mainspring --repair-state --dry-run"
  if [ -f "$LOCK_FILE" ]; then
    local lock_pid
    lock_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
      echo "Active loop lock: inspect with ps -p $lock_pid -o pid,ppid,stat,command"
    else
      echo "Stale lock candidate: rm only after mainspring status confirms no live loop owns $LOCK_FILE"
    fi
  fi

  local taskmaster_summary scope_summary routing_hint
  taskmaster_summary="$(taskmaster_json_status_summary 2>/dev/null || true)"
  scope_summary="$(taskmaster_scope_safety_summary 2>/dev/null || true)"
  routing_hint="$(wave_routing_hints 2>/dev/null || true)"

  if printf '%s\n%s\n' "$taskmaster_summary" "$scope_summary" \
    | grep -Eq 'Taskmaster: missing \.taskmaster/tasks/tasks\.json|scope: Taskmaster file missing'; then
    echo "Taskmaster backlog missing: run mainspring init checkout-redesign for a new PRD-backed project; replace checkout-redesign with your feature name. Or add .taskmaster/tasks/tasks.json before using taskmaster mode."
  elif printf '%s\n%s\n' "$taskmaster_summary" "$scope_summary" \
    | grep -Eq 'scheduler: STOP_BLOCKED no ready top-level task|scope: no ready top-level Taskmaster item'; then
    echo "No ready Taskmaster work: inspect blocked items with task-master list and task-master show <id> before rerunning."
  elif printf '%s\n' "$taskmaster_summary" | grep -q 'scheduler: STOP_BLOCKED #'; then
    echo "Blocked Taskmaster item: inspect exact graph with task-master show <id> before changing statuses."
  elif printf '%s\n' "$routing_hint" | grep -q 'recent team run found no parallel-safe work'; then
    echo "Recent team routing found no parallel-safe work: rerun a ready item in solo mode only after scope exists: mainspring taskmaster --topology solo --pair codex+codex --once"
  fi
}

run_status_report() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --help|-h)
        cat <<'EOF'
Usage: mainspring status

Print the current project, git, runtime, Taskmaster, wave, and recommended
next-action status without starting or stopping any work.
EOF
        return 0
        ;;
      *)
        echo "status: unknown flag: $1" >&2
        return 2
        ;;
    esac
  done

  local report_file report_status
  report_file="$(mktemp "${TMPDIR:-/tmp}/mainspring-status.XXXXXX")" || return 1
  report_status=0
  run_status_report_body >"$report_file" || report_status=$?
  if [ "$report_status" -ne 0 ]; then
    rm -f "$report_file"
    return "$report_status"
  fi
  cat "$report_file" || true
  rm -f "$report_file"
}

run_status_report_body() {
  echo "=== Mainspring Status ==="
  echo "Root: $ROOT_DIR"
  echo "Time: $(date)"
  echo ""

  echo "--- Run Defaults ---"
  echo "Mode: $MODE"
  echo "Topology: $TOPOLOGY"
  echo "Writer: $ENGINE (${MODEL_OVERRIDE:-default})"
  echo "Reviewer: $REVIEW_ENGINE (${REVIEW_MODEL_OVERRIDE:-default})"
  echo "Codex default: $DEFAULT_CODEX_MODEL"
  echo "Codex fast default: $DEFAULT_FAST_CODEX_MODEL"
  echo "Codex reasoning: $CODEX_REASONING_EFFORT"
  echo ""

  echo "--- Root Git ---"
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local root_status root_count
    root_status="$(git_status_all)"
    root_count="$(printf '%s\n' "$root_status" | count_nonempty_lines)"
    echo "root dirty entries: $root_count"
    if [ "$root_count" -gt 0 ]; then
      printf '%s\n' "$root_status" | print_limited_lines 24 | sed 's/^/  /'
    fi
  else
    echo "not inside root git worktree"
  fi
  echo ""

  echo "--- Runtime Processes ---"
  runtime_process_summary | sed -n '1,20p'
  echo ""

  echo "--- Tmux ---"
  tmux_mainspring_summary | sed -n '1,20p'
  echo ""

  echo "--- Runtime State ---"
  runtime_state_summary
  echo ""

  echo "--- Active Teams ---"
  active_team_status_summary
  echo ""

  echo "--- Taskmaster ---"
  taskmaster_json_status_summary
  taskmaster_scope_safety_summary
  echo ""

  echo "--- Wave Metrics ---"
  last_wave_summary
  wave_routing_hints
  echo ""

  echo "--- Recommended Next Action ---"
  status_recommendations
  echo ""
  echo "Instrument status: inspect/repair/status gates are available; execute only after git/runtime gates are clean."
  echo "Product backlog status: use the Taskmaster scheduler decision above as backlog truth; runner docs live in docs/guide.md."
}

repair_state() {
  local dry_run="$1"
  local force="$2"
  local repair_args=("$MAINSPRING_PY_DIR/runtime_state.py" repair "$(runtime_state_dir)")
  [ "$dry_run" = "true" ] && repair_args+=(--dry-run)
  [ "$force" = "true" ] && repair_args+=(--force)
  "$(mainspring_python)" "${repair_args[@]}"
}

stop_processes() {
  local arg has_force=false
  for arg in "$@"; do
    case "$arg" in
      --help|-h)
      cat <<'EOF'
Usage: mainspring stop --force [--all]

Stop recorded Mainspring work processes for this project.

Options:
  --force   Required safety flag for process termination.
  --all     Emergency only: stop every discovered Mainspring work process owned
            by this user, across projects.

Examples:
  mainspring stop --force
EOF
      return 0
      ;;
      --force) has_force=true ;;
      --all) ;;
      *)
        echo "stop: unknown flag: $arg" >&2
        echo "Usage: mainspring stop --force [--all]" >&2
        return 2
        ;;
    esac
  done
  if [ "$has_force" != true ]; then
    echo "stop: --force is required to terminate Mainspring processes." >&2
    echo "Usage: mainspring stop --force [--all]" >&2
    return 2
  fi
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/runtime_state.py" stop-processes "$(runtime_state_dir)" "$$" "$@"
}

cleanup_stale_loop_processes() {
  local ttl_minutes="$1"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/runtime_state.py" cleanup-stale "$$" "$ttl_minutes"
}

self_heal_runtime_state() {
  if [ "${SELF_HEAL:-true}" != "true" ]; then
    return 0
  fi

  # Stale process termination is destructive; keep startup self-heal
  # advisory-only and require the explicit repair/restart commands instead.

  if [ -f "$LOCK_FILE" ]; then
    local existing_pid
    existing_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    if [ -z "$existing_pid" ] || ! kill -0 "$existing_pid" 2>/dev/null; then
      echo "Removing stale lock file: $LOCK_FILE"
      rm -f "$LOCK_FILE"
    fi
  fi

  if command -v omx >/dev/null 2>&1; then
    preflight_team_artifacts || true
  fi

  local active_modes
  command -v omx >/dev/null 2>&1 || return 0
  active_modes="$(omx state list-active --json 2>/dev/null || true)"
  if printf '%s' "$active_modes" | grep -q '"ultrawork"'; then
    local has_live_runtime
    has_live_runtime="$(ps -axo command | grep -E 'codex exec|claude -p|omx team' | grep -v grep || true)"
    if [ -z "${has_live_runtime// }" ]; then
      echo "Stale ultrawork state detected with no live runtime process."
      echo "Run: mainspring --repair-state --dry-run, then mainspring --repair-state --force if the preview is correct."
    fi
  fi
  if printf '%s' "$active_modes" | grep -q '"skill-active"'; then
    local has_live_runtime
    has_live_runtime="$(ps -axo command | grep -E 'codex exec|claude -p|omx team' | grep -v grep || true)"
    if [ -z "${has_live_runtime// }" ]; then
      echo "Stale skill-active state detected with no live runtime process."
      echo "Run: mainspring --repair-state --dry-run, then mainspring --repair-state --force if the preview is correct."
    fi
  fi
}
