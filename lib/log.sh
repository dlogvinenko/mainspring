#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring logging — wave ledger and wave summary
# Globals read: MAINSPRING_PY_DIR
# Globals written: none

append_wave_ledger() {
  # All context is passed explicitly — no hidden global reads.
  # Args 1-17: wave data fields.  Args 18-21: context that was formerly global.
  # Optional args 22-23: Taskmaster status before/after the wave.
  # Optional args 24-28: prompt/worktree replay provenance.
  # Optional arg 29: engine usage JSONL sidecar for ledger cost/token truth.
  local wave_id="$1"
  local mode="$2"
  local topology="$3"
  local team="$4"
  local task_id="$5"
  local selected_lane="$6"
  local engine="$7"
  local reviewer="$8"
  local start_epoch="$9"
  local end_epoch="${10}"
  local exit_code="${11}"
  local changed_files="${12}"
  local verdict="${13}"
  local failure_reason="${14}"
  local retry_count="${15}"
  local blocked_reason="${16}"
  local next_action="${17}"
  local ledger_file="${18}"
  local model_override="${19}"
  local review_model_override="${20}"
  local reasoning_effort="${21}"
  local task_status_before="${22:-}"
  local task_status_after="${23:-}"
  local prompt_path="${24:-}"
  local prompt_sha256="${25:-}"
  local git_head="${26:-}"
  local git_status_before="${27:-}"
  local prd_path="${28:-}"
  local usage_path="${29:-}"
  mkdir -p "$(dirname "$ledger_file")"
  WAVE_ID="${MAINSPRING_WAVE_ID_OVERRIDE:-$wave_id}" \
  MODE_VALUE="$mode" \
  TOPOLOGY_VALUE="$topology" \
  TEAM_VALUE="$team" \
  TEAM_NAME_VALUE="$team" \
  TASK_ID_VALUE="$task_id" \
  TASK_STATUS_BEFORE_VALUE="$task_status_before" \
  TASK_STATUS_AFTER_VALUE="$task_status_after" \
  SELECTED_LANE="$selected_lane" \
  ENGINE_VALUE="$engine" \
  REVIEWER_VALUE="$reviewer" \
  MODEL_VALUE="${model_override:-default}" \
  REVIEW_MODEL_VALUE="${review_model_override:-default}" \
  REASONING_VALUE="$reasoning_effort" \
  START_EPOCH="$start_epoch" \
  END_EPOCH="$end_epoch" \
  EXIT_CODE_VALUE="$exit_code" \
  CHANGED_FILES_VALUE="$changed_files" \
  VERDICT_VALUE="$verdict" \
  FAILURE_REASON_VALUE="$failure_reason" \
  PROMPT_PATH_VALUE="$prompt_path" \
  PROMPT_SHA256_VALUE="$prompt_sha256" \
  GIT_HEAD_VALUE="$git_head" \
  GIT_STATUS_BEFORE_VALUE="$git_status_before" \
  PRD_PATH_VALUE="$prd_path" \
  USAGE_PATH_VALUE="$usage_path" \
  REPLAYED_FROM_VALUE="${MAINSPRING_REPLAYED_FROM:-}" \
  REPLAY_OVERRIDES_VALUE="${MAINSPRING_REPLAY_OVERRIDES:-}" \
  RETRY_COUNT_VALUE="$retry_count" \
  BLOCKED_REASON_VALUE="$blocked_reason" \
  NEXT_ACTION_VALUE="$next_action" \
    "$(mainspring_python)" "$MAINSPRING_PY_DIR/wave_log.py" append --ledger "$ledger_file"
}

append_wave_summary() {
  local summary_file="$1"
  local wave="$2"
  local mode="$3"
  local engine="$4"
  local exit_code="$5"
  local display_file="$6"

  {
    echo "=== WAVE $wave SUMMARY | $(date) ==="
    echo "Mode: $mode"
    echo "Engine: $engine"
    echo "Exit code: $exit_code"
    echo "---"
    if [ -s "$display_file" ]; then
      tail -n 120 "$display_file"
    else
      echo "[no human-readable engine output captured]"
    fi
    echo
  } >> "$summary_file"
}
