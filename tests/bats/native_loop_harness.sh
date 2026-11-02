#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
ARM="$1"
ROOT_DIR="$2"
SCENARIO="$3"
CASE_DIR="$4"
mkdir -p "$ROOT_DIR" "$CASE_DIR/tmp" "$CASE_DIR/logs"
export TMPDIR="$CASE_DIR/tmp"
source "$ARM/lib/wave.sh"
source "$ARM/lib/write_scope.sh"
source "$ARM/lib/wave_loop.sh"
CAPTURE="$CASE_DIR/ledger"
REVIEWS="$CASE_DIR/reviews"
CHECKPOINTS="$CASE_DIR/checkpoints"
WRITERS="$CASE_DIR/writers"
TASK_EVENTS="$CASE_DIR/task-events"
SCOPE_CALLS="$CASE_DIR/scope-calls"
: > "$CAPTURE"; : > "$REVIEWS"; : > "$CHECKPOINTS"; : > "$WRITERS"
: > "$TASK_EVENTS"; : > "$SCOPE_CALLS"
MODE=taskmaster
TOPOLOGY=solo
ENGINE=synthetic
REVIEW_ENGINE=synthetic
MODEL_OVERRIDE=synthetic
REVIEW_MODEL_OVERRIDE=synthetic
CODEX_REASONING_EFFORT=synthetic
TASKMASTER_BASE_MISSION=synthetic
NIGHT_BASE_MISSION=synthetic
PRD_PATH=
AUTO_CHECKPOINT=true
AUTO_CHECKPOINT_DENY_PATHS=(synthetic)
AUTO_RETRY_CI=0
AUTO_RETRY_CI_LOG=
RUN_ONCE=true
MAX_IDLE_WAVES=3
IDLE_WAVES=0
LOG_DIR="$CASE_DIR/logs"
WAVE_LEDGER_FILE="$CASE_DIR/synthetic-waves.jsonl"
FAKE_TASK_STATUS=in-progress
WRITER_COUNT=0
REVIEW_COUNT=0
if [ "$SCENARIO" = failed_ci_scope ] || [ "$SCENARIO" = clean_ci_retry ]; then
  AUTO_RETRY_CI=1
fi

initialize_wave_loop_logs() {
  WAVE=1
  LOG_FILE="$CASE_DIR/loop.log"
  SUMMARY_FILE="$CASE_DIR/summary.txt"
  : > "$LOG_FILE"; : > "$SUMMARY_FILE"
}
run_team_preflight_if_needed() { TEAM_PREFLIGHT_RESULT="continue"; return 0; }
ensure_notify_daemon() { :; }
initialize_solo_wave_state() {
  WAVE_START_EPOCH=1000
  WAVE_MARKER="$(mktemp)"
  TASK_ID=; WORK_ID=; TASK_STATUS_BEFORE=; TASK_STATUS_AFTER=
  WAVE_PROMPT_FILE=; WAVE_PROMPT_SHA256=; WAVE_GIT_HEAD=; WAVE_GIT_STATUS=; WAVE_PRD_PATH=
}
task-master() {
  case "$1" in
    next) printf '%s\n' '#42 Synthetic work' ;;
    show) printf '%s\n' 'Synthetic work details' ;;
    set-status)
      printf '%s\n' "$*" >> "$TASK_EVENTS"
      case "$*" in *--status=review*) FAKE_TASK_STATUS=review ;; esac
      ;;
    *) return 97 ;;
  esac
}
pick_taskmaster_work_item() { printf '%s\n' 42; }
taskmaster_status_for_id() { printf '%s\n' "$FAKE_TASK_STATUS"; }
apply_agent_mode_to_prompt() { printf '%s\n' "$1"; }
agent_mode_allows_no_product_change() { return 1; }
hash_file_sha256() { printf '%s\n' synthetic-hash; }
git() { printf '%s\n' synthetic-head; }
git_status_short() { :; }
append_wave_summary() { :; }
append_wave_ledger() {
  local wave="$1"; shift 5
  local phase="$1"; shift 5
  local code="$1"; shift 2
  local verdict="$1"; shift
  local reason="$1"
  printf '%s|%s|%s|%s|%s\n' "$wave" "$phase" "$code" "$verdict" "$reason" >> "$CAPTURE"
}
classify_engine_failure_reason() { printf '%s\n' engine:exit_nonzero; }
auto_checkpoint_dirty_tree() { printf '%s\n' checkpoint >> "$CHECKPOINTS"; }
sleep() { if [ "$1" != 10 ]; then command sleep "$@"; fi; }
apply_review_gate() {
  REVIEW_COUNT=$((REVIEW_COUNT + 1))
  printf '%s\n' review >> "$REVIEWS"
  if [ "$SCENARIO" = review_retry_scope ] && [ "$REVIEW_COUNT" -eq 1 ]; then
    printf '%s\n' synthetic-feedback > "$LOG_DIR/taskmaster-review-fixed-wave1.log"
    REVIEW_GATE_FAILURE_REASON=review:gate_failed
    return 1
  fi
  FAKE_TASK_STATUS="done"
  return 0
}
extract_review_field() { printf '%s\n' 'Synthetic repair feedback'; }
run_ai_turn() {
  WRITER_COUNT=$((WRITER_COUNT + 1))
  printf '%s\n' "$WRITER_COUNT" >> "$WRITERS"
  command sleep 0.03
  printf '%s\n' 'Synthetic writer output' > "$4"
  case "$SCENARIO" in
    forbidden_idle)
      mkdir -p "$ROOT_DIR/node_modules/pkg"
      printf '%s\n' synthetic > "$ROOT_DIR/node_modules/pkg/index.js"
      ;;
    clean_idle) : ;;
    allowed_source)
      mkdir -p "$ROOT_DIR/src" "$ROOT_DIR/build/test-results" "$ROOT_DIR/dist/assets" "$ROOT_DIR/apps/web/build/test-results"
      printf '%s\n' synthetic > "$ROOT_DIR/src/a.ts"
      printf '%s\n' synthetic > "$ROOT_DIR/build/test-results/TEST.xml"
      printf '%s\n' synthetic > "$ROOT_DIR/dist/assets/app.js"
      printf '%s\n' synthetic > "$ROOT_DIR/apps/web/build/test-results/TEST.xml"
      ;;
    failed_ci_scope|clean_ci_retry|failed_no_retry_scope|clean_failed_no_retry)
      mkdir -p "$ROOT_DIR/src"
      printf '%s\n' "$WRITER_COUNT" > "$ROOT_DIR/src/a.ts"
      if [ "$WRITER_COUNT" -eq 1 ]; then
        if [ "$SCENARIO" != clean_ci_retry ] && [ "$SCENARIO" != clean_failed_no_retry ]; then printf '%s\n' synthetic > "$ROOT_DIR/.env.local"; fi
        printf '%s\n' 'Typecheck failed' > "$4"
        return 1
      fi
      ;;
    review_retry_scope)
      if [ "$WRITER_COUNT" -eq 1 ]; then
        mkdir -p "$ROOT_DIR/src"
        printf '%s\n' synthetic > "$ROOT_DIR/src/a.ts"
      else
        printf '%s\n' synthetic > "$ROOT_DIR/.env.local"
        return 1
      fi
      ;;
    *) return 96 ;;
  esac
  return 0
}
eval "$(declare -f check_write_scope | sed '1s/check_write_scope/actual_check_write_scope/')"
check_write_scope() {
  local input
  input="$(cat)"
  printf '%s\n' CHECK "$input" >> "$SCOPE_CALLS"
  printf '%s\n' "$input" | actual_check_write_scope
}
run_wave_loop
