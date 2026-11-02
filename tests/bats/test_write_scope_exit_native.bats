#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
setup() {
  ARM="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  PROJECT="$BATS_TEST_TMPDIR/project"
  CASE="$BATS_TEST_TMPDIR/case"
}
@test "scope priority must preserve an initial failed writer exit status" {
  run /bin/bash --noprofile --norc "$ARM/tests/bats/native_loop_harness.sh" "$ARM" "$PROJECT" failed_no_retry_scope "$CASE"
  [ "$status" -eq 1 ]
  grep -q 'FAIL|scope:violation' "$CASE/ledger"
  [ ! -s "$CASE/checkpoints" ]
}


@test "clean failed writer retains existing exit and retry-disabled handling" {
  run /bin/bash --noprofile --norc "$ARM/tests/bats/native_loop_harness.sh" "$ARM" "$PROJECT" clean_failed_no_retry "$CASE"
  [ "$status" -eq 1 ]
  grep -q 'ERROR|engine:typecheck_fail' "$CASE/ledger"
  ! grep -q 'scope:violation' "$CASE/ledger"
  [ ! -s "$CASE/checkpoints" ]
}
