#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring wave-loop startup and team-preflight helpers.
# shellcheck disable=SC2034

initialize_wave_loop_logs() {
  WAVE=1
  LOG_FILE="$LOG_DIR/${MODE}-loop-$(date +%Y%m%d-%H%M%S).log"
  local LATEST_LOG="$LOG_DIR/latest.log"
  local LATEST_MODE_LOG="$LOG_DIR/latest-${MODE}.log"
  SUMMARY_FILE="$LOG_DIR/${MODE}-summary-$(date +%Y%m%d-%H%M%S).log"
  local LATEST_SUMMARY_LOG="$LOG_DIR/latest-summary.log"
  local LATEST_MODE_SUMMARY_LOG="$LOG_DIR/latest-${MODE}-summary.log"

  : > "$LOG_FILE"
  : > "$SUMMARY_FILE"

  ln -sf "$(basename "$LOG_FILE")" "$LATEST_LOG"
  ln -sf "$(basename "$LOG_FILE")" "$LATEST_MODE_LOG"
  ln -sf "$(basename "$SUMMARY_FILE")" "$LATEST_SUMMARY_LOG"
  ln -sf "$(basename "$SUMMARY_FILE")" "$LATEST_MODE_SUMMARY_LOG"

  {
    echo "=== Mainspring Autonomous Loop ==="
    echo "Root: $ROOT_DIR"
    echo "Mode: $MODE"
    echo "Topology: $TOPOLOGY"
    echo "Engine: $ENGINE"
    echo "Model: ${MODEL_OVERRIDE:-default}"
    echo "Auto-retry CI: ${AUTO_RETRY_CI:-0}"
    [ -n "${AUTO_RETRY_CI_LOG:-}" ] && echo "Auto-retry CI log: $AUTO_RETRY_CI_LOG"
    echo "Log: $LOG_FILE"
    echo "Latest log: $LATEST_LOG"
    echo "Latest mode log: $LATEST_MODE_LOG"
    echo "Summary log: $SUMMARY_FILE"
    echo "Latest summary log: $LATEST_SUMMARY_LOG"
    echo "Latest mode summary log: $LATEST_MODE_SUMMARY_LOG"
    echo "Started at: $(date)"
    echo ""
  } | tee -a "$LOG_FILE"

}

run_team_preflight_if_needed() {
  TEAM_PREFLIGHT_RESULT="continue"
  # --- Team topology pre-flight ---
  if [ "$TOPOLOGY" = "team" ]; then
    local TEAM_RUN_STATUS=0
    local TEAM_START_EPOCH
    TEAM_START_EPOCH="$(date +%s)"
    if run_team_topology; then
      TEAM_RUN_STATUS=0
    else
      TEAM_RUN_STATUS=$?
    fi
    local TEAM_END_EPOCH
    TEAM_END_EPOCH="$(date +%s)"
    if [ "$TEAM_RUN_STATUS" -eq 2 ]; then
      local TEAM_REASON
      TEAM_REASON="${TEAM_FALLBACK_REASON:-team:no_parallel_safe_work}"
      local TASKMASTER_FALLBACK_ID=""
      local TEAM_FALLBACK_ACTION=""
      append_wave_ledger "team-preflight-$(date +%Y%m%d-%H%M%S)" "$MODE" "team" "" "" "team-preflight" "$ENGINE" "$REVIEW_ENGINE" "$TEAM_START_EPOCH" "$TEAM_END_EPOCH" "$TEAM_RUN_STATUS" "" "FAIL" "$TEAM_REASON" "0" "team_fallback_to_solo" "Continue in solo topology for review/status recovery." "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT"
      TEAM_FALLBACK_ACTION="$(team_fallback_taskmaster_action "$TEAM_REASON")"
      if [ "$MODE" = "taskmaster" ] && [ "$TEAM_FALLBACK_ACTION" = "block_taskmaster" ]; then
        TASKMASTER_FALLBACK_ID="$(fallback_taskmaster_next 2>/dev/null || true)"
        if [ -n "${TASKMASTER_FALLBACK_ID// }" ]; then
          echo "Blocking Taskmaster item $TASKMASTER_FALLBACK_ID after non-recoverable team fallback: $TEAM_REASON"
          echo "Blocking Taskmaster item $TASKMASTER_FALLBACK_ID after non-recoverable team fallback: $TEAM_REASON" >> "$LOG_FILE"
          task-master set-status --id="$TASKMASTER_FALLBACK_ID" --status=blocked >/dev/null 2>&1 || true
        fi
      fi
      TOPOLOGY="solo"
      echo ""
      echo "=== Continuing in solo topology for review/status recovery ==="
      echo "Topology: $TOPOLOGY"
      echo ""
    else
      append_wave_ledger "team-$(date +%Y%m%d-%H%M%S)" "$MODE" "team" "" "" "team-dispatch" "$ENGINE" "$REVIEW_ENGINE" "$TEAM_START_EPOCH" "$TEAM_END_EPOCH" "$TEAM_RUN_STATUS" "" "$([ "$TEAM_RUN_STATUS" -eq 0 ] && echo PASS || echo FAIL)" "$([ "$TEAM_RUN_STATUS" -eq 0 ] && echo "" || echo team:run_failed)" "0" "" "Inspect team status and Taskmaster review items." "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT"
      TEAM_PREFLIGHT_RESULT="done"
      return "$TEAM_RUN_STATUS"
    fi
  fi

}
