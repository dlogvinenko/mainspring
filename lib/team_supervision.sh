#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring Team supervision, sourced after team.sh.
# Globals read: LOG_FILE, MAINSPRING_PY_DIR, TEAM_POLL_SECONDS,
#   TEAM_SUPERVISE, TEAM_FALLBACK_TO_SOLO
# Globals written: TEAM_FALLBACK_REASON
# Depends on: team.sh and taskmaster_helpers.sh

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
    local status_json status phase dead_count total_count usable counts pending in_progress completed failed
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

    case "$phase" in
      cancelled|failed)
        echo "Team backend reached terminal phase $phase while supervising: $team_name"
        echo "Team backend reached terminal phase $phase while supervising: $team_name" >> "$LOG_FILE"
        team_cleanup_requires_restart "$team_name" "team reached terminal phase $phase during supervision" | tee -a "$LOG_FILE" || true
        return 2
        ;;
    esac

    total_count="$(printf '%s' "$status_json" | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field total-workers)"
    if [ "$status" = "ok" ] && [ "${total_count:-0}" -gt 0 ] && [ "${dead_count:-0}" -eq "$total_count" ]; then
      echo "All team backend workers are dead for $team_name. Leaving team state intact; explicit restart is required."
      echo "All team backend workers are dead for $team_name. Leaving team state intact; explicit restart is required." >> "$LOG_FILE"
      team_cleanup_requires_restart "$team_name" "all team workers are dead" | tee -a "$LOG_FILE" || true
      return 2
    fi

    usable="$(printf '%s' "$status_json" | "$(team_python)" "$MAINSPRING_PY_DIR/team_status.py" --field usable-check || true)"
    if [ "$usable" != "usable" ]; then
      echo "Team status is not usable while supervising: $team_name"
      echo "Team status is not usable while supervising: $team_name" >> "$LOG_FILE"
      team_cleanup_requires_restart "$team_name" "team status is not usable during supervision" | tee -a "$LOG_FILE" || true
      return 2
    fi

    if [ "$phase" != "complete" ]; then
      requeue_stale_team_tasks "$team_name" | tee -a "$LOG_FILE"
      nudge_pending_team_tasks "$team_name" | tee -a "$LOG_FILE"
    fi
    if ! counts="$(team_task_counts "$team_name" 2>>"$LOG_FILE")"; then
      if [ "$phase" = "complete" ]; then
        team_cleanup_requires_restart "$team_name" "completed team has unreadable task counts" | tee -a "$LOG_FILE" || true
        return 2
      fi
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
      if ! next_items="$(collect_parallel_taskmaster_items "$team_size")"; then
        team_cleanup_requires_restart "$team_name" "could not read ready Taskmaster work" | tee -a "$LOG_FILE" || true
        return 2
      fi
      if [ -n "${next_items// }" ]; then
        if [ "$phase" = "complete" ]; then
          team_cleanup_requires_restart "$team_name" "completed team has undispatched parallel work" | tee -a "$LOG_FILE" || true
          return 2
        fi
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
        if ! skip_reason="$(taskmaster_team_skip_reason)"; then
          team_cleanup_requires_restart "$team_name" "could not read Taskmaster team skip reason" | tee -a "$LOG_FILE" || true
          return 2
        fi
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

    if [ "$phase" = "complete" ]; then
      team_cleanup_requires_restart "$team_name" "completed team has unfinished tasks" | tee -a "$LOG_FILE" || true
      return 2
    fi
    sleep "$poll_seconds"
  done
}
