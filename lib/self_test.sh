#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring self-test — writer/reviewer handshake verification
# Globals read: ROOT_DIR, RUNTIME_DIR, LOG_DIR, ENGINE, REVIEW_ENGINE, MODEL_OVERRIDE,
#   REVIEW_MODEL_OVERRIDE, PAIR_MODE
# Globals written: ENGINE, REVIEW_ENGINE, MODEL_OVERRIDE, REVIEW_MODEL_OVERRIDE,
#   PAIR_MODE (restored after run_all_self_tests)
# Depends on: engines.sh (run_ai_turn), wizard.sh (apply_pair_mode,
#   apply_default_models_for_current_pair)

run_self_test() {
  local selftest_dir
  selftest_dir="${RUNTIME_DIR:-$ROOT_DIR/.mainspring}/selftest/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$selftest_dir"
  local writer_file="$selftest_dir/writer-output.txt"
  local writer_log
  writer_log="$LOG_DIR/selftest-writer-$(date +%Y%m%d-%H%M%S).log"
  local writer_display
  writer_display="$(mktemp)"

  echo "=== Mainspring Pair Self-Test ==="
  echo "Writer:   $ENGINE (${MODEL_OVERRIDE:-default})"
  echo "Reviewer: $REVIEW_ENGINE (${REVIEW_MODEL_OVERRIDE:-default})"
  echo "Dir:      $selftest_dir"
  echo ""

  local writer_prompt
  writer_prompt="You are running a self-test for Mainspring loop orchestration.

Write exactly one file at this absolute path:
$writer_file

The file content must be exactly:
engine=$ENGINE
model=${MODEL_OVERRIDE:-default}
status=writer-ok

Rules:
- create or overwrite only that file
- do not modify any other file
- after writing it, print one short confirmation line"

  local writer_status=0
  if run_ai_turn writer "$writer_prompt" "$writer_log" "$writer_display"; then
    writer_status=0
  else
    writer_status=$?
  fi

  echo ""
  echo "--- Writer self-test output ---"
  cat "$writer_display" || true
  echo ""

  if [ "$writer_status" -ne 0 ] || [ ! -f "$writer_file" ]; then
    echo "SELF_TEST_RESULT: FAIL"
    echo "Reason: writer did not produce the expected file."
    rm -f "$writer_display"
    return 1
  fi

  local review_log
  review_log="$LOG_DIR/selftest-review-$(date +%Y%m%d-%H%M%S).log"
  local review_display
  review_display="$(mktemp)"
  local review_prompt
  review_prompt="You are the review gate for a Mainspring self-test.

Inspect this file:
$writer_file

Expected content:
engine=$ENGINE
model=${MODEL_OVERRIDE:-default}
status=writer-ok

Return exactly:
REVIEW_VERDICT: PASS or FAIL
RATIONALE: one sentence"

  local review_status=0
  if run_ai_turn reviewer "$review_prompt" "$review_log" "$review_display"; then
    review_status=0
  else
    review_status=$?
  fi

  echo ""
  echo "--- Reviewer self-test output ---"
  cat "$review_display" || true
  echo ""

  if [ "$review_status" -eq 0 ] && grep -Eq '^REVIEW_VERDICT:[[:space:]]*PASS' "$review_display"; then
    echo "SELF_TEST_RESULT: PASS"
    rm -f "$writer_display" "$review_display"
    return 0
  fi

  echo "SELF_TEST_RESULT: FAIL"
  rm -f "$writer_display" "$review_display"
  return 1
}

run_all_self_tests() {
  local pairs=("claude+codex" "codex+codex" "claude+claude" "codex+claude")
  local failed=0
  local result_log
  result_log="$LOG_DIR/selftest-matrix-$(date +%Y%m%d-%H%M%S).log"
  local original_engine="$ENGINE"
  local original_review_engine="$REVIEW_ENGINE"
  local original_model="$MODEL_OVERRIDE"
  local original_review_model="$REVIEW_MODEL_OVERRIDE"
  local original_pair="$PAIR_MODE"

  echo "=== Mainspring Pair Matrix Self-Test ===" | tee -a "$result_log"
  for pair in "${pairs[@]}"; do
    PAIR_MODE="$pair"
    ENGINE=""
    REVIEW_ENGINE=""
    MODEL_OVERRIDE=""
    REVIEW_MODEL_OVERRIDE=""
    apply_pair_mode "$PAIR_MODE"
    apply_default_models_for_current_pair

    echo "" | tee -a "$result_log"
    echo ">>> Testing $PAIR_MODE (writer=$ENGINE:$MODEL_OVERRIDE reviewer=$REVIEW_ENGINE:$REVIEW_MODEL_OVERRIDE)" | tee -a "$result_log"
    if run_self_test | tee -a "$result_log"; then
      echo "MATRIX_RESULT: $PAIR_MODE PASS" | tee -a "$result_log"
    else
      echo "MATRIX_RESULT: $PAIR_MODE FAIL" | tee -a "$result_log"
      failed=$((failed + 1))
    fi
  done

  ENGINE="$original_engine"
  REVIEW_ENGINE="$original_review_engine"
  MODEL_OVERRIDE="$original_model"
  REVIEW_MODEL_OVERRIDE="$original_review_model"
  PAIR_MODE="$original_pair"

  echo "" | tee -a "$result_log"
  if [ "$failed" -eq 0 ]; then
    echo "SELF_TEST_ALL_RESULT: PASS" | tee -a "$result_log"
    echo "Matrix log: $result_log"
    return 0
  fi
  echo "SELF_TEST_ALL_RESULT: FAIL ($failed pair(s) failed)" | tee -a "$result_log"
  echo "Matrix log: $result_log"
  return 1
}
