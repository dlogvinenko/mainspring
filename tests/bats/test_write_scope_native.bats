#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# Synthetic post-write blacklist admission only; no live side effects.
setup() {
  ARM="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  PROJECT="$BATS_TEST_TMPDIR/project"
  CASE="$BATS_TEST_TMPDIR/case"
}

_run_case() {
  run /bin/bash --noprofile --norc "$ARM/tests/bats/native_loop_harness.sh" "$ARM" "$PROJECT" "$1" "$CASE"
}

@test "forbidden-only zero-progress write is a scope failure, not idle" {
  _run_case forbidden_idle
  [ "$status" -eq 0 ]
  grep -q 'FAIL|scope:violation' "$CASE/ledger"
  ! grep -q 'engine:no_file_changes' "$CASE/ledger"
  [ ! -s "$CASE/reviews" ]
  [ ! -s "$CASE/checkpoints" ]
  [ -f "$PROJECT/node_modules/pkg/index.js" ]
}

@test "failed writer cannot waive scope through CI auto retry" {
  _run_case failed_ci_scope
  [ "$status" -ne 0 ]
  grep -q 'FAIL|scope:violation' "$CASE/ledger"
  [ "$(wc -l < "$CASE/writers" | tr -d ' ')" -eq 1 ]
  [ ! -s "$CASE/reviews" ]
  [ ! -s "$CASE/checkpoints" ]
}

@test "failed writer without CI retry still records scope violation" {
  _run_case failed_no_retry_scope
  grep -q 'FAIL|scope:violation' "$CASE/ledger"
  [ ! -s "$CASE/reviews" ]
  [ ! -s "$CASE/checkpoints" ]
}

@test "failed reviewer-feedback writer retry cannot waive scope" {
  _run_case review_retry_scope
  [ "$status" -eq 0 ]
  grep -q 'FAIL|scope:violation' "$CASE/ledger"
  [ "$(wc -l < "$CASE/writers" | tr -d ' ')" -eq 2 ]
  [ "$(wc -l < "$CASE/reviews" | tr -d ' ')" -eq 1 ]
  [ ! -s "$CASE/checkpoints" ]
}

@test "nested forbidden path after display cap reaches actual guard" {
  source "$ARM/lib/wave.sh"
  source "$ARM/lib/write_scope.sh"
  ROOT_DIR="$PROJECT"
  mkdir -p "$PROJECT/apps/000" "$PROJECT/apps/web/coverage"
  marker="$BATS_TEST_TMPDIR/marker"
  touch -t 202001010000 "$marker"
  for i in $(seq 1 120); do touch "$PROJECT/apps/000/file-$i.ts"; done
  touch "$PROJECT/apps/web/coverage/lcov.info"
  # find order is unspecified; impose one valid lexical order over actual files.
  find() { command find "$@" | sort; }
  displayed="$(print_wave_progress_files "$marker")"
  [ "$(printf '%s\n' "$displayed" | wc -l | tr -d ' ')" -eq 80 ]
  scope="$(print_wave_scope_files "$marker")"
  [[ "$scope" == *"apps/web/coverage/lcov.info"* ]]
  run check_write_scope <<< "$scope"
  [ "$status" -eq 1 ]
  [[ "$output" == *"apps/web/coverage/lcov.info"* ]]
}

@test "generated build artifacts retain scope allowance" {
  _run_case allowed_source
  [ "$status" -eq 0 ]
  grep -q 'PASS|' "$CASE/ledger"
  ! grep -q 'scope:violation' "$CASE/ledger"
  [ "$(wc -l < "$CASE/checkpoints" | tr -d ' ')" -eq 1 ]
}

@test "clean CI retry keeps existing recovery behavior" {
  _run_case clean_ci_retry
  [ "$status" -eq 0 ]
  grep -q 'ERROR|engine:typecheck_fail' "$CASE/ledger"
  grep -q 'PASS|' "$CASE/ledger"
  ! grep -q 'scope:violation' "$CASE/ledger"
  [ "$(wc -l < "$CASE/writers" | tr -d ' ')" -eq 2 ]
  [ "$(wc -l < "$CASE/checkpoints" | tr -d ' ')" -eq 1 ]
}

@test "clean no-progress remains idle without review or checkpoint" {
  _run_case clean_idle
  [ "$status" -eq 0 ]
  grep -q 'IDLE|engine:no_file_changes' "$CASE/ledger"
  [ ! -s "$CASE/reviews" ]
  [ ! -s "$CASE/checkpoints" ]
}

@test "pre-existing forbidden file is outside this mtime wave" {
  source "$ARM/lib/wave.sh"
  source "$ARM/lib/write_scope.sh"
  ROOT_DIR="$PROJECT"
  mkdir -p "$PROJECT"
  touch -t 201901010000 "$PROJECT/.env.local"
  marker="$BATS_TEST_TMPDIR/marker"
  touch -t 202001010000 "$marker"
  scope="$(print_wave_scope_files "$marker")"
  [ -z "$scope" ]
  run check_write_scope <<< "$scope"
  [ "$status" -eq 0 ]
}
