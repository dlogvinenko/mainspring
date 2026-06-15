#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring wave-loop state and failure helpers.
# shellcheck disable=SC2034

classify_engine_failure_reason() {
  local engine="$1"
  local exit_code="$2"
  local display_file="$3"
  local reason
  reason="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py" failure \
    --engine "$engine" \
    --exit-code "$exit_code" \
    --raw-tail-file "$display_file" \
    --format reason 2>/dev/null || true)"
  if [ -n "${reason// }" ]; then
    echo "$reason"
  else
    echo "engine:exit_nonzero"
  fi
}

initialize_solo_wave_state() {
    WAVE_START_EPOCH="$(date +%s)"
    WAVE_MARKER="$(mktemp)"
    TASK_ID=""
    WORK_ID=""
    TASK_STATUS_BEFORE=""
    TASK_STATUS_AFTER=""
    WAVE_PROMPT_FILE=""
    WAVE_PROMPT_SHA256=""
    WAVE_GIT_HEAD=""
    WAVE_GIT_STATUS=""
    WAVE_PRD_PATH=""
    echo "========================================"
    echo "=== WAVE $WAVE starting at $(date) ==="
    echo "========================================"

}

record_no_actionable_task_stop() {
  local blocked_reason="$1"
  local operator_message="$2"
  local next_action="$3"
  local raw_output="${4:-}"
  local STOP_EPOCH
  STOP_EPOCH="$(date +%s)"

  append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "" "scheduler" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$STOP_EPOCH" "0" "" "STOP" "routing:no_actionable_task" "0" "$blocked_reason" "$next_action" "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT"
  {
    printf '%s\n' "$operator_message"
    [ -n "$raw_output" ] && printf '%s\n' "$raw_output"
  } | tee -a "$LOG_FILE"
  {
    printf '=== WAVE %s SUMMARY | %s ===\n' "$WAVE" "$(date)"
    printf 'Mode: %s\n' "$MODE"
    printf 'Engine: %s\n' "$ENGINE"
    printf 'Exit code: 0\n'
    printf '%s\n' "---"
    printf '%s\n' "$operator_message"
    [ -n "$raw_output" ] && printf '%s\n' "$raw_output"
    printf '\n'
  } >> "$SUMMARY_FILE"
}

handle_empty_taskmaster_parent() {
  local EMPTY_PARENT_STATUS
  EMPTY_PARENT_STATUS="$(taskmaster_parent_rollup_status "$TASK_ID")"
  if [ -n "${EMPTY_PARENT_STATUS// }" ]; then
    echo "No ready subtask found under task $TASK_ID. Rolling parent up to $EMPTY_PARENT_STATUS and continuing."
    echo "No ready subtask found under task $TASK_ID. Rolling parent up to $EMPTY_PARENT_STATUS and continuing." >> "$LOG_FILE"
    task-master set-status --id="$TASK_ID" --status="$EMPTY_PARENT_STATUS" >/dev/null 2>&1 || true
  else
    echo "No ready subtask found under task $TASK_ID. Marking parent as blocked to avoid a stale review loop."
    echo "No ready subtask found under task $TASK_ID. Marking parent as blocked to avoid a stale review loop." >> "$LOG_FILE"
    task-master set-status --id="$TASK_ID" --status=blocked >/dev/null 2>&1 || true
  fi
  append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "$TASK_ID" "scheduler-repair" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "0" "" "REPAIR" "routing:empty_parent" "0" "" "Inspect child statuses and dependencies before rerunning team fanout." "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT"
  if [ "$RUN_ONCE" = true ]; then
    echo "Run-once mode enabled. Stopping after empty Taskmaster parent $TASK_ID."
    echo "Run-once mode enabled. Stopping after empty Taskmaster parent $TASK_ID." >> "$LOG_FILE"
    return 0
  fi
  echo "Pausing 10s before next wave..."
  echo "Pausing 10s before next wave..." >> "$LOG_FILE"
  sleep 10
  WAVE=$((WAVE + 1))
  return 1
}
