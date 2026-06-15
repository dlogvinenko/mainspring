#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_lock.bats — exercise acquire_lock() from lib/lock.sh.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  COMMON_LIB="$ROOT_DIR/lib/common.sh"
  LOCK_LIB="$ROOT_DIR/lib/lock.sh"
  MAINSPRING_PY_DIR="$ROOT_DIR/py"
  TMPDIR_BATS="$(mktemp -d)"
}

teardown() {
  if declare -f release_lock >/dev/null 2>&1 && [ -n "${LOCK_FILE:-}" ]; then
    release_lock || true
  fi
  rm -rf "$TMPDIR_BATS"
}

_load_lock() {
  if [ ! -f "$LOCK_LIB" ]; then
    skip "required helper missing: $LOCK_LIB"
  fi
  source "$COMMON_LIB"
  source "$LOCK_LIB"
}

# Scenario: acquire_lock with no existing lock file.
# Expected: creates advisory PID file with current PID while holding fd lock.
@test "acquire_lock creates lock file with PID" {
  _load_lock
  LOCK_FILE="$TMPDIR_BATS/test.pid"
  acquire_lock
  [ -f "$LOCK_FILE" ]
  [ "$(cat "$LOCK_FILE")" = "$$" ]
  release_lock
}

# Scenario: acquire_lock with stale lock (PID doesn't exist).
# Expected: replaces stale advisory PID when no fd lock is held.
@test "acquire_lock replaces stale lock" {
  _load_lock
  LOCK_FILE="$TMPDIR_BATS/test.pid"
  echo "99999" > "$LOCK_FILE"
  # PID 99999 should not exist
  if kill -0 99999 2>/dev/null; then
    skip "PID 99999 is actually running"
  fi
  acquire_lock
  [ "$(cat "$LOCK_FILE")" = "$$" ]
  release_lock
}

# Scenario: acquire_lock when another process holds the fd lock.
# Expected: exits with error instead of trusting PID-file heuristics.
@test "acquire_lock exits when fd lock is held" {
  _load_lock
  LOCK_FILE="$TMPDIR_BATS/test.pid"
  acquire_lock
  run bash -c "
    { exec 9>&-; } 2>/dev/null || true
    source '$COMMON_LIB'
    source '$LOCK_LIB'
    MAINSPRING_PY_DIR='$MAINSPRING_PY_DIR'
    LOCK_FILE='$LOCK_FILE'
    acquire_lock
  "
  [ "$status" -ne 0 ]
  [[ "$output" == *"already running"* ]]
  release_lock
}

# Scenario: a legacy pre-flock loop left a live PID file but holds no fd lock.
# Expected: new code still refuses to overlap the live process.
@test "acquire_lock exits when legacy live PID owns lock file" {
  _load_lock
  LOCK_FILE="$TMPDIR_BATS/test.pid"
  echo "$$" > "$LOCK_FILE"
  run bash -c "
    source '$COMMON_LIB'
    source '$LOCK_LIB'
    MAINSPRING_PY_DIR='$MAINSPRING_PY_DIR'
    LOCK_FILE='$LOCK_FILE'
    acquire_lock
  "
  [ "$status" -ne 0 ]
  [[ "$output" == *"already running"* ]]
  [ "$(cat "$LOCK_FILE")" = "$$" ]
}

# Scenario: release_lock is called after a successful acquire.
# Expected: removes the owned advisory file and lets a new process acquire.
@test "release_lock removes owned file and unlocks" {
  _load_lock
  LOCK_FILE="$TMPDIR_BATS/test.pid"
  acquire_lock
  release_lock
  [ ! -e "$LOCK_FILE" ]
  run bash -c "
    source '$COMMON_LIB'
    source '$LOCK_LIB'
    MAINSPRING_PY_DIR='$MAINSPRING_PY_DIR'
    LOCK_FILE='$LOCK_FILE'
    acquire_lock
    release_lock
  "
  [ "$status" -eq 0 ]
  [ ! -e "$LOCK_FILE" ]
}
