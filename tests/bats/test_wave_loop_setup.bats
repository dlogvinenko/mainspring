#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_wave_loop_setup.bats — exercise wave loop startup logging.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WAVE_LOOP_SETUP_LIB="$ROOT_DIR/lib/wave_loop_setup.sh"
  TMPDIR_BATS="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR_BATS"
}

_load_wave_loop_setup() {
  if [ ! -f "$WAVE_LOOP_SETUP_LIB" ]; then
    skip "module not available: $WAVE_LOOP_SETUP_LIB"
  fi
  # shellcheck source=../../lib/wave_loop_setup.sh
  source "$WAVE_LOOP_SETUP_LIB"
}

@test "initialize_wave_loop_logs creates latest log targets immediately" {
  _load_wave_loop_setup
  LOG_DIR="$TMPDIR_BATS/logs"
  mkdir -p "$LOG_DIR"
  MODE="taskmaster"
  TOPOLOGY="solo"
  ENGINE="codex"
  MODEL_OVERRIDE="gpt-5.5"
  AUTO_RETRY_CI="0"

  stdout="$TMPDIR_BATS/stdout.log"
  initialize_wave_loop_logs > "$stdout"
  status=$?

  [ "$status" -eq 0 ]
  [ -f "$LOG_FILE" ]
  [ -f "$SUMMARY_FILE" ]
  [ -L "$LOG_DIR/latest.log" ]
  [ -f "$LOG_DIR/latest.log" ]
  [ -L "$LOG_DIR/latest-taskmaster.log" ]
  [ -f "$LOG_DIR/latest-taskmaster.log" ]
  [ -L "$LOG_DIR/latest-summary.log" ]
  [ -f "$LOG_DIR/latest-summary.log" ]
  [ -L "$LOG_DIR/latest-taskmaster-summary.log" ]
  [ -f "$LOG_DIR/latest-taskmaster-summary.log" ]
  grep -Fq "Log: $LOG_FILE" "$stdout"
  grep -Fq "Summary log: $SUMMARY_FILE" "$stdout"
  grep -Fq "Log: $LOG_FILE" "$LOG_FILE"
  grep -Fq "Summary log: $SUMMARY_FILE" "$LOG_FILE"
}
