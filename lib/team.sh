#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring team topology — parallel worker dispatch and supervision
# Globals read: ROOT_DIR, LOG_FILE, LOCK_FILE, MODE, ENGINE, MODEL_OVERRIDE,
#   REVIEW_ENGINE, CODEX_REASONING_EFFORT, MAX_AGENTS, TOPOLOGY,
#   RETRY_TASK_IDS,
#   AUTO_TMUX, TEAM_FALLBACK_TO_SOLO, TEAM_SUPERVISE, TEAM_POLL_SECONDS,
#   TEAM_PENDING_NUDGE_SECONDS, TEAM_STALE_IN_PROGRESS_MINUTES,
#   MAINSPRING_PY_DIR, AUTO_CHECKPOINT, AUTO_CHECKPOINT_DENY_PATHS,
#   STATE_DIR, TEAM_DIR
# Globals written: TEAM_FALLBACK_REASON
# Depends on: common.sh (git_status_short, nested_repo_dirty_count,
#   auto_checkpoint_dirty_tree, count_nonempty_lines),
#   status.sh (preflight_team_artifacts — but that function is in this module),
#   taskmaster_helpers.sh (collect_parallel_taskmaster_items,
#   taskmaster_team_skip_reason)

team_state_root() {
  echo "${STATE_DIR:-$ROOT_DIR/.mainspring/state}"
}

team_artifact_root() {
  echo "${TEAM_DIR:-$ROOT_DIR/.mainspring/team}"
}

team_python() {
  declare -F mainspring_python >/dev/null 2>&1 && { mainspring_python; return; }
  [ -n "${MAINSPRING_PYTHON:-}" ] && { printf '%s\n' "$MAINSPRING_PYTHON"; return; }
  [ -n "${MAINSPRING_PY:-}" ] && { printf '%s\n' "$MAINSPRING_PY"; return; }
  command -v python3 2>/dev/null || command -v python
}

team_cleanup_requires_restart() {
  local team_name="$1"
  local reason="$2"
  echo "Refusing destructive team backend cleanup for $team_name without --restart-team."
  echo "Reason: $reason"
  echo "Run: mainspring --last-run --restart-team"
  return 1
}

team_name_is_safe_for_cleanup() {
  local team_name="$1"
  case "$team_name" in
    ""|"."|".."|*/*|*\\*|*".."*|*[!A-Za-z0-9._-]*)
      return 1
      ;;
  esac
  return 0
}

team_cleanup_path_is_under() {
  local root="$1"
  local target="$2"
  local root_abs parent_abs target_abs
  root_abs="$(cd "$root" 2>/dev/null && pwd -P)" || return 1
  [ "$root_abs" != "/" ] || return 1
  parent_abs="$(cd "$(dirname "$target")" 2>/dev/null && pwd -P)" || return 1
  target_abs="$parent_abs/$(basename "$target")"
  case "$target_abs" in
    "$root_abs"/*) return 0 ;;
    *) return 1 ;;
  esac
}

team_cleanup_refuse_unsafe_path() {
  local root="$1"
  local target="$2"
  echo "Refusing destructive team cleanup outside runtime root."
  echo "Root: $root"
  echo "Target: $target"
  return 1
}

validate_team_worker_launch_args() {
  case "${MODEL_OVERRIDE:-}" in *[!A-Za-z0-9._:/@+-]*) echo "Invalid team worker model id: $MODEL_OVERRIDE"; return 1 ;; esac
  [ "$ENGINE" != "codex" ] && return 0
  case "$CODEX_REASONING_EFFORT" in none|minimal|low|medium|high|xhigh) return 0 ;; esac
  echo "Invalid Codex reasoning effort for team workers: $CODEX_REASONING_EFFORT"
  return 1
}

cleanup_team_artifacts() {
  local team_name="$1"
  local cleanup_gate="${2:-}"
  [ -n "${team_name// }" ] || return 0
  if [ "$cleanup_gate" != "restart-team" ]; then
    team_cleanup_requires_restart "$team_name" "${cleanup_gate:-team cleanup}"
    return 1
  fi
  if ! team_name_is_safe_for_cleanup "$team_name"; then
    echo "Refusing unsafe team name for destructive cleanup: $team_name"
    return 1
  fi
  local wt team_root state_root team_path worktrees_path state_team_root state_team_path
  team_root="$(team_artifact_root)"; state_root="$(team_state_root)"
  team_path="$team_root/$team_name"; worktrees_path="$team_path/worktrees"
  state_team_root="$state_root/team"; state_team_path="$state_team_root/$team_name"
  mkdir -p "$team_root" "$state_team_root"
  team_cleanup_path_is_under "$team_root" "$team_path" || team_cleanup_refuse_unsafe_path "$team_root" "$team_path" || return 1
  team_cleanup_path_is_under "$state_team_root" "$state_team_path" || team_cleanup_refuse_unsafe_path "$state_team_root" "$state_team_path" || return 1
  [ ! -L "$worktrees_path" ] || { echo "Refusing symlinked team worktrees directory: $worktrees_path"; return 1; }
  for wt in "$worktrees_path"/worker-{1,2,3,4,5,6}; do
    [ -d "$wt" ] || continue
    local worker_name head_ref safe_team_name
    worker_name="$(basename "$wt")"
    safe_team_name="$(printf '%s' "$team_name" | tr -c 'A-Za-z0-9._-' '-')"
    head_ref="$(git -C "$wt" rev-parse HEAD 2>/dev/null || true)"
    [ -z "$head_ref" ] || git update-ref "refs/mainspring-preserve/$safe_team_name/$worker_name" "$head_ref" >/dev/null 2>&1 || true
    [ ! -L "$wt" ] || { echo "Refusing symlinked team worker worktree: $wt"; return 1; }
    team_cleanup_path_is_under "$worktrees_path" "$wt" || team_cleanup_refuse_unsafe_path "$worktrees_path" "$wt" || return 1
    if git -C "$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      git worktree remove --force "$wt" >/dev/null 2>&1 || rm -rf -- "$wt"
    else
      rm -rf -- "$wt"
    fi
  done
  git worktree prune >/dev/null 2>&1 || true
  rm -rf -- "$team_path" "$state_team_path"
}

restart_active_teams() {
  local config team_name found=false state_root
  state_root="$(team_state_root)"
  for config in "$state_root/team"/*/config.json; do
    [ -f "$config" ] || continue
    found=true
    team_name="$(basename "$(dirname "$config")")"
    echo "Restart requested: shutting down existing team backend $team_name"
    omx team "shutdown" "$team_name" --force >/dev/null 2>&1 || true
    cleanup_team_artifacts "$team_name" "restart-team"
  done
  if [ "$found" = false ]; then
    echo "Restart requested: no active team backend state found."
  fi
  if [ -f "$LOCK_FILE" ]; then
    local lock_pid
    lock_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    if [ -n "$lock_pid" ] && [ "$lock_pid" != "$$" ] && kill -0 "$lock_pid" 2>/dev/null; then
      echo "Restart requested: stopping old Mainspring process $lock_pid"
      kill "$lock_pid" >/dev/null 2>&1 || true
      sleep 1
    fi
    rm -f "$LOCK_FILE"
  fi
}

preflight_team_artifacts() {
  local config team_name status_json status phase state_root
  state_root="$(team_state_root)"
  for config in "$state_root/team"/*/config.json; do
    [ -f "$config" ] || continue
    team_name="$(basename "$(dirname "$config")")"
    status_json="$(omx team status "$team_name" --json 2>/dev/null || true)"
    status="$(printf '%s' "$status_json" | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field status)"
    phase="$(printf '%s' "$status_json" | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field phase)"

    if [ "$status" = "missing" ] || [ -z "$status" ]; then
      team_cleanup_requires_restart "$team_name" "stale or unreadable team state"
      return 1
    fi

    if [ "$phase" = "complete" ] || [ "$phase" = "cancelled" ] || [ "$phase" = "failed" ]; then
      team_cleanup_requires_restart "$team_name" "finished team state ($phase)"
      return 1
    fi

    echo "Active team backend already exists: $team_name (phase: ${phase:-unknown})."
    echo "Use: mainspring hud --all-runtimes"
    echo "To reset after inspection: mainspring --last-run --restart-team"
    echo "Not launching a duplicate team."
    return 1
  done
  git worktree prune >/dev/null 2>&1 || true
  return 0
}

build_parallel_team_prompt() {
  cat <<'EOF'
Bootstrap only for the Mainspring parallel Taskmaster coordinator.

This bootstrap prompt is not a product work item and is not Taskmaster backlog truth.
Do not review, document, implement, infer, or create Taskmaster tasks from this prompt text.
Wait for explicit team backend tasks whose description contains a `Task Master id: ...` line.
When assigned an explicit Task Master id, read project guidance files (AGENTS.md / CLAUDE.md when present) and Taskmaster docs, work only on that id, keep file ownership disjoint, leave Taskmaster work in review unless reviewer PASS exists, and report changed files plus verification evidence.
EOF
}

dispatch_parallel_team_tasks() {
  local team_name="$1"
  local items_jsonl="$2"
  local team_size="$3"
  local dispatch_status=0
  local retry_id
  local restore_nounset=0
  case "$-" in
    *u*)
      restore_nounset=1
      set +u
      ;;
  esac
  local retry_args=()
  if declare -p RETRY_TASK_IDS >/dev/null 2>&1; then
    for retry_id in "${RETRY_TASK_IDS[@]}"; do
      [ -n "${retry_id// }" ] && retry_args+=(--retry-task "$retry_id")
    done
  fi
  "$(team_python)" "$MAINSPRING_PY_DIR/team_dispatch.py" dispatch "$team_name" "$team_size" "$items_jsonl" "${retry_args[@]}" || dispatch_status=$?
  [ "$restore_nounset" -eq 1 ] && set -u
  return "$dispatch_status"
}

team_task_counts() {
  local team_name="$1"
  "$(team_python)" "$MAINSPRING_PY_DIR/team_dispatch.py" counts "$team_name"
}

nudge_pending_team_tasks() {
  local team_name="$1"
  local min_age_seconds="${TEAM_PENDING_NUDGE_SECONDS:-60}"
  "$(team_python)" "$MAINSPRING_PY_DIR/team_dispatch.py" nudge "$team_name" --min-age-seconds "$min_age_seconds"
}

requeue_stale_team_tasks() {
  local team_name="$1"
  local stale_minutes="${TEAM_STALE_IN_PROGRESS_MINUTES:-10}"
  "$(team_python)" "$MAINSPRING_PY_DIR/team_dispatch.py" requeue "$team_name" --stale-minutes "$stale_minutes"
}

close_bootstrap_tasks() {
  local team_name="$1"
  "$(team_python)" "$MAINSPRING_PY_DIR/team_dispatch.py" close-bootstrap "$team_name"
}

supervise_team_run() {
  local team_name="$1"
  local team_size="$2"
  local poll_seconds="${TEAM_POLL_SECONDS:-30}"

  if [ "${TEAM_SUPERVISE:-true}" != "true" ]; then
    return 0
  fi

  echo "Supervising team run: $team_name"
  echo "Supervising team run: $team_name" >> "$LOG_FILE"

  while true; do
    local status_json status phase dead_count counts pending in_progress completed failed
    status_json="$(omx team status "$team_name" --json 2>/dev/null || true)"
    status="$(printf '%s' "$status_json" | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field status)"
    phase="$(printf '%s' "$status_json" | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field phase)"
    dead_count="$(printf '%s' "$status_json" | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field dead-workers)"

    if [ "$status" = "missing" ] || [ -z "$status" ]; then
      echo "Team state disappeared while supervising: $team_name"
      echo "Team state disappeared while supervising: $team_name" >> "$LOG_FILE"
      team_cleanup_requires_restart "$team_name" "team state disappeared during supervision" | tee -a "$LOG_FILE" || true
      return 2
    fi

    if [ "${dead_count:-0}" -ge "$team_size" ]; then
      echo "All team backend workers are dead for $team_name. Leaving team state intact; explicit restart is required."
      echo "All team backend workers are dead for $team_name. Leaving team state intact; explicit restart is required." >> "$LOG_FILE"
      team_cleanup_requires_restart "$team_name" "all team workers are dead" | tee -a "$LOG_FILE" || true
      return 2
    fi

    requeue_stale_team_tasks "$team_name" | tee -a "$LOG_FILE"
    nudge_pending_team_tasks "$team_name" | tee -a "$LOG_FILE"
    if ! counts="$(team_task_counts "$team_name" 2>>"$LOG_FILE")"; then
      echo "Could not read team backend task counts. Retrying after ${poll_seconds}s instead of assuming idle."
      echo "Could not read team backend task counts. Retrying after ${poll_seconds}s instead of assuming idle." >> "$LOG_FILE"
      sleep "$poll_seconds"
      continue
    fi
    read -r pending in_progress completed failed <<<"$counts"
    echo "Team $team_name status: phase=${phase:-unknown} pending=$pending in_progress=$in_progress completed=$completed failed=$failed"
    echo "Team $team_name status: phase=${phase:-unknown} pending=$pending in_progress=$in_progress completed=$completed failed=$failed" >> "$LOG_FILE"
    if [ "${failed:-0}" -gt 0 ]; then
      echo "Team $team_name has failed Task Master assignments; inspect with: mainspring hud --all-runtimes"
      echo "Team $team_name has failed Task Master assignments; inspect with: mainspring hud --all-runtimes" >> "$LOG_FILE"
    fi

    if [ "${pending:-0}" -eq 0 ] && [ "${in_progress:-0}" -eq 0 ]; then
      local next_items
      next_items="$(collect_parallel_taskmaster_items "$team_size")"
      if [ -n "${next_items// }" ]; then
        echo "Dispatching next Taskmaster batch into existing team: $team_name"
        echo "Dispatching next Taskmaster batch into existing team: $team_name" >> "$LOG_FILE"
        printf '%s\n' "$next_items" >> "$LOG_FILE"
        if ! dispatch_parallel_team_tasks "$team_name" "$next_items" "$team_size" | tee -a "$LOG_FILE"; then
          echo "Taskmaster batch dispatch reported failures. Retrying supervision after ${poll_seconds}s."
          echo "Taskmaster batch dispatch reported failures. Retrying supervision after ${poll_seconds}s." >> "$LOG_FILE"
          sleep "$poll_seconds"
          continue
        fi
      else
        local skip_reason
        skip_reason="$(taskmaster_team_skip_reason)"
        if [ -n "${skip_reason// }" ]; then
          # shellcheck disable=SC2034  # consumed by wave_loop.sh after this function returns.
          TEAM_FALLBACK_REASON="$skip_reason"
          echo "No more parallel-safe Taskmaster work because ready work is outside team worktree visibility: $skip_reason"
          echo "No more parallel-safe Taskmaster work because ready work is outside team worktree visibility: $skip_reason" >> "$LOG_FILE"
        else
          # shellcheck disable=SC2034  # consumed by wave_loop.sh after this function returns.
          TEAM_FALLBACK_REASON="team:no_parallel_safe_work"
        fi
        echo "No more parallel-safe Taskmaster work. Leaving team state intact; explicit restart is required for cleanup: $team_name"
        echo "No more parallel-safe Taskmaster work. Leaving team state intact; explicit restart is required for cleanup: $team_name" >> "$LOG_FILE"
        team_cleanup_requires_restart "$team_name" "team finished available parallel work" | tee -a "$LOG_FILE" || true
        if [ "${TEAM_FALLBACK_TO_SOLO:-true}" = "true" ]; then
          return 2
        fi
        return 0
      fi
    fi

    sleep "$poll_seconds"
  done
}

find_latest_team_name() {
  "$(team_python)" "$MAINSPRING_PY_DIR/runtime_state.py" find-latest-team "$(team_state_root)/team"
}

find_active_team_name() {
  local config team_name status_json status phase state_root
  state_root="$(team_state_root)"
  for config in "$state_root/team"/*/config.json; do
    [ -f "$config" ] || continue
    team_name="$(basename "$(dirname "$config")")"
    status_json="$(omx team status "$team_name" --json 2>/dev/null || true)"
    status="$(printf '%s' "$status_json" | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field status)"
    phase="$(printf '%s' "$status_json" | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field phase)"
    if [ -n "$status" ] && [ "$status" != "missing" ] \
      && [ "$phase" != "complete" ] && [ "$phase" != "cancelled" ] && [ "$phase" != "failed" ]; then
      echo "$team_name"
      return 0
    fi
  done
  return 1
}

run_team_topology() {
  # shellcheck disable=SC2034  # consumed by wave_loop.sh after this function returns.
  TEAM_FALLBACK_REASON=""
  if [ "$MODE" != "taskmaster" ]; then
    echo "Team topology currently supports taskmaster mode only. Use --topology solo for night mode."
    return 1
  fi
  command -v omx >/dev/null 2>&1 || { echo "team backend command missing from PATH"; return 1; }
  local team_size="$MAX_AGENTS"
  if ! [[ "$team_size" =~ ^[0-9]+$ ]]; then
    team_size=4
  fi
  [ "$team_size" -lt 2 ] && team_size=2
  [ "$team_size" -gt 6 ] && team_size=6

  if ! preflight_team_artifacts; then
    local active_team
    active_team="$(find_active_team_name || true)"
    if [ -n "${active_team// }" ]; then
      echo "Resuming supervision of active team backend: $active_team"
      echo "Resuming supervision of active team backend: $active_team" >> "$LOG_FILE"
      supervise_team_run "$active_team" "$team_size"
      return $?
    fi
    return 2
  fi
  if [ -z "${TMUX:-}" ]; then
    if [ ! -t 1 ]; then
      echo "Team topology requires an interactive terminal/tmux. Falling back to solo topology in non-TTY execution."
      return 2
    fi
    if [ "${AUTO_TMUX:-true}" != "true" ]; then
      echo "Team topology requires tmux. Start inside tmux or set MAINSPRING_AUTO_TMUX=true."
      echo "Manual command:"
      echo "  tmux new-session -s mainspring 'cd \"$ROOT_DIR\" && mainspring --last-run'"
      return 1
    fi
    command -v tmux >/dev/null 2>&1 || {
      echo "Team topology requires tmux, but tmux is missing from PATH."
      echo "Install tmux or run with --topology solo."
      return 1
    }
    local session_name root_q
    session_name="mainspring-$(date +%Y%m%d-%H%M%S)"
    printf -v root_q '%q' "$ROOT_DIR"
    echo "Team topology requires tmux. Relaunching inside tmux session: $session_name"
    echo "If you detach, reattach with:"
    echo "  tmux attach -t $session_name"
    release_lock
    exec tmux new-session -s "$session_name" "cd $root_q && mainspring --last-run; printf '\\nTeam run ended. Press Enter to close this tmux pane. '; read _"
  fi

  local dirty_count dirty_preview blocking_dirty
  auto_checkpoint_dirty_tree "Pre-team fanout checkpoint from mainspring." "$AUTO_CHECKPOINT" "$LOG_FILE" "${AUTO_CHECKPOINT_DENY_PATHS[@]}" || true
  dirty_preview="$(git_status_short)"
  blocking_dirty="$(printf '%s\n' "$dirty_preview" | grep -vE '^.. package-lock\.json$' | sed '/^[[:space:]]*$/d' || true)"
  if [ -n "${blocking_dirty// }" ] && ! printf '%s\n' "$blocking_dirty" | grep -vqE '^.. \.taskmaster/'; then
    echo "Only .taskmaster state is dirty; checkpointing it before team fanout."
    echo "Only .taskmaster state is dirty; checkpointing it before team fanout." >> "$LOG_FILE"
    git add .taskmaster >/dev/null 2>&1 || true
    if git diff --cached --quiet -- .taskmaster; then
      echo "No staged .taskmaster changes after add; continuing."
      echo "No staged .taskmaster changes after add; continuing." >> "$LOG_FILE"
    elif git commit --no-verify -m "Checkpoint Taskmaster state before Mainspring team fanout" \
      -m "Taskmaster state changed during autonomous execution. Checkpoint it before creating worker worktrees so the leader checkout is clean and backlog truth is preserved." \
      -m "Constraint: Mainspring team fanout creates worktrees from the current leader commit" \
      -m "Rejected: leave dirty .taskmaster files unstaged | workers would fork from stale backlog truth" \
      -m "Confidence: medium" \
      -m "Scope-risk: narrow" \
      -m "Reversibility: clean" \
      -m "Directive: Keep this checkpoint separate from product code changes unless intentionally squashing local history" \
      -m "Tested: not run; operational checkpoint only" \
      -m "Not-tested: no product tests run by the checkpoint step itself" >/dev/null 2>&1; then
      echo ".taskmaster checkpoint committed."
      echo ".taskmaster checkpoint committed." >> "$LOG_FILE"
      dirty_preview="$(git_status_short)"
      blocking_dirty="$(printf '%s\n' "$dirty_preview" | grep -vE '^.. package-lock\.json$' | sed '/^[[:space:]]*$/d' || true)"
    else
      echo "Could not checkpoint .taskmaster state automatically. Falling back to solo topology."
      echo "Could not checkpoint .taskmaster state automatically. Falling back to solo topology." >> "$LOG_FILE"
      return 2
    fi
  fi
  dirty_count="$(printf '%s\n' "$blocking_dirty" | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')"
  if [ "${dirty_count:-0}" -gt 0 ]; then
    echo "Team topology cannot start while the leader workspace is dirty."
    echo "Reason: team topology creates worker worktrees from the current repo, and dirty leader changes would be unsafe to fan out."
    echo "Dirty files: $dirty_count"
    echo "First dirty entries:"
    printf '%s\n' "$blocking_dirty" | sed -n '1,12p'
    echo ""
    echo "Safe options:"
    echo "  0. Let the loop auto-checkpoint safe files: MAINSPRING_AUTO_CHECKPOINT=true mainspring --last-run --restart-team"
    echo "  1. Commit the current work, then rerun: mainspring --last-run"
    echo "  2. Stash the current work, then rerun: git stash push -u -m 'before team fanout'"
    echo "  3. Use solo mode without worktrees: mainspring taskmaster --topology solo --pair codex+codex"
    echo ""
    echo "Falling back to solo topology instead of blocking the loop."
    return 2
  fi
  if printf '%s\n' "$dirty_preview" | grep -qE '^.. package-lock\.json$'; then
    echo "Only package-lock.json is dirty; stashing it before team fanout because worker worktrees require a clean leader."
    echo "Only package-lock.json is dirty; stashing it before team fanout because worker worktrees require a clean leader." >> "$LOG_FILE"
    if git stash push -m "mainspring package-lock drift before team fanout" -- package-lock.json >/dev/null 2>&1; then
      echo "package-lock.json stashed. Restore later with: git stash list | head"
      echo "package-lock.json stashed. Restore later with: git stash list | head" >> "$LOG_FILE"
    else
      echo "Could not stash package-lock.json. Falling back to solo topology."
      echo "Could not stash package-lock.json. Falling back to solo topology." >> "$LOG_FILE"
      return 2
    fi
  fi

  local items_jsonl
  items_jsonl="$(collect_parallel_taskmaster_items "$team_size")"
  if [ -z "${items_jsonl// }" ]; then
    local skip_reason
    skip_reason="$(taskmaster_team_skip_reason)"
    if [ -n "${skip_reason// }" ]; then
      # shellcheck disable=SC2034  # consumed by wave_loop.sh after this function returns.
      TEAM_FALLBACK_REASON="$skip_reason"
      echo "No parallel-safe pending/in-progress Taskmaster items found because ready work is outside team worktree visibility: $skip_reason"
    else
      # shellcheck disable=SC2034  # consumed by wave_loop.sh after this function returns.
      TEAM_FALLBACK_REASON="team:no_parallel_safe_work"
    fi
    echo "No parallel-safe pending/in-progress Taskmaster items found."
    if [ "${TEAM_FALLBACK_TO_SOLO:-true}" = "true" ]; then
      echo "Falling back to solo topology to process review/status recovery lanes."
      return 2
    fi
    echo "Use --topology solo if you want to process review/status recovery lanes."
    return 0
  fi

  local team_prompt
  team_prompt="$(build_parallel_team_prompt)"

  local worker_cli="$ENGINE"
  local worker_args=""
  validate_team_worker_launch_args || return 1
  if [ "$worker_cli" = "codex" ]; then
    worker_args="-c model_reasoning_effort=\"$CODEX_REASONING_EFFORT\""
  fi
  if [ -n "${MODEL_OVERRIDE:-}" ]; then
    worker_args="--model $MODEL_OVERRIDE${worker_args:+ $worker_args}"
  fi

  local team_output team_name
  local team_status=0
  while true; do
    echo "=== Mainspring Team Parallel Topology ==="
    echo "Mode: taskmaster"
    echo "Workers: $team_size"
    echo "Worker CLI: $ENGINE"
    echo "Worker model: ${MODEL_OVERRIDE:-default}"
    [ "$ENGINE" = "codex" ] && echo "Worker reasoning: $CODEX_REASONING_EFFORT"
    echo "Candidate work items:"
    printf '%s\n' "$items_jsonl"
    echo ""
    {
      echo "=== TEAM TOPOLOGY START | $(date) ==="
      echo "Workers: $team_size"
      echo "Worker CLI: $ENGINE"
      echo "Worker model: ${MODEL_OVERRIDE:-default}"
      [ "$ENGINE" = "codex" ] && echo "Worker reasoning: $CODEX_REASONING_EFFORT"
      echo "Candidate work items:"
      printf '%s\n' "$items_jsonl"
      echo
    } >> "$LOG_FILE"

    team_output="$(mktemp)"
    team_name=""
    team_status=0
    local team_launch_pid=""
    set +e
    (
      env MAINSPRING_TEAM_WORKER_CLI="$worker_cli" MAINSPRING_TEAM_WORKER_LAUNCH_ARGS="$worker_args" \
        omx team "${team_size}:executor" "$team_prompt" 2>&1 | tee "$team_output" | tee -a "$LOG_FILE"
    ) &
    team_launch_pid=$!
    set -e
    for _ in $(seq 1 30); do
      team_name="$(sed -n 's/^Team started:[[:space:]]*//p' "$team_output" | tail -n 1)"
      if [ -z "${team_name// }" ]; then
        team_name="$(find_latest_team_name)"
      fi
      if [ -n "${team_name// }" ]; then
        break
      fi
      if ! kill -0 "$team_launch_pid" 2>/dev/null; then
        set +e
        wait "$team_launch_pid"
        team_status=$?
        set -e
        break
      fi
      sleep 1
    done
    if [ -z "${team_name// }" ] && kill -0 "$team_launch_pid" 2>/dev/null; then
      kill "$team_launch_pid" >/dev/null 2>&1 || true
      wait "$team_launch_pid" >/dev/null 2>&1 || true
      team_status=124
    fi
    if [ -z "${team_name// }" ] && [ "$team_size" -gt 2 ]; then
      local retry_reason="missing team name"
      if grep -Eq 'failed to create worker pane|no space for new pane' "$team_output"; then
        retry_reason="tmux pane allocation failed"
      fi
      rm -f "$team_output"
      team_size=$((team_size - 2))
      echo "Team backend startup did not produce a usable team ($retry_reason). Retrying with $team_size workers."
      echo "Team backend startup did not produce a usable team ($retry_reason). Retrying with $team_size workers." >> "$LOG_FILE"
      continue
    fi
    rm -f "$team_output"
    break
  done
  if [ -z "${team_name// }" ]; then
    echo "Could not find team backend name from startup output or state. Not dispatching tasks."
    return 2
  fi
  if [ "$team_status" -ne 0 ]; then
    local started_status
    started_status="$(omx team status "$team_name" --json 2>/dev/null | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field usable-check || true)"
    if [ "$started_status" = "usable" ]; then
      echo "team backend exited with code $team_status, but team state is usable. Continuing with dispatch."
      echo "team backend exited with code $team_status, but team state is usable. Continuing with dispatch." >> "$LOG_FILE"
    else
      echo "team backend exited with code $team_status before dispatch. Leaving team state intact; explicit restart is required."
      echo "team backend exited with code $team_status before dispatch. Leaving team state intact; explicit restart is required." >> "$LOG_FILE"
      team_cleanup_requires_restart "$team_name" "team startup failed before dispatch" | tee -a "$LOG_FILE" || true
      return 2
    fi
  fi
  items_jsonl="$(printf '%s\n' "$items_jsonl" | sed -n "1,${team_size}p")"
  echo "Dispatching Taskmaster work items through team backend API: $team_name"
  echo "Dispatching Taskmaster work items through team backend API: $team_name" >> "$LOG_FILE"
  if ! dispatch_parallel_team_tasks "$team_name" "$items_jsonl" "$team_size" | tee -a "$LOG_FILE"; then
    echo "Initial Taskmaster dispatch reported failures. Continuing supervision so pending/inbox recovery can retry."
    echo "Initial Taskmaster dispatch reported failures. Continuing supervision so pending/inbox recovery can retry." >> "$LOG_FILE"
  fi
  # Auto-close bootstrap tasks so they don't clutter the team ledger (P4-7).
  close_bootstrap_tasks "$team_name" 2>>"$LOG_FILE" | tee -a "$LOG_FILE" || true
  echo "Team API dispatch complete. Monitor with:"
  echo "  mainspring hud --all-runtimes"
  supervise_team_run "$team_name" "$team_size"
  return $?
}

team_fallback_taskmaster_action() {
  local reason="$1"
  "$(team_python)" "$MAINSPRING_PY_DIR/failure_taxonomy.py" action "$reason" 2>/dev/null || true
}
