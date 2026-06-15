#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_write_scope.bats — exercise lib/write_scope.sh.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  WRITE_SCOPE_LIB="$ROOT_DIR/lib/write_scope.sh"
  MAINSPRING_SH="${MAINSPRING_SH:-$ROOT_DIR/mainspring.sh}"
}

_load_write_scope() {
  if [ ! -f "$WRITE_SCOPE_LIB" ]; then
    skip "required helper missing: $WRITE_SCOPE_LIB"
  fi
  source "$WRITE_SCOPE_LIB"
}

@test "check_write_scope allows planning docs and top-level metadata paths" {
  _load_write_scope
  input="$(printf 'src/App.tsx\ndocs/prd.md\n.taskmaster/docs/ledger.md\nlib/write_scope.sh\nREADME.md\n.gitignore\n')"

  run check_write_scope <<< "$input"

  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

@test "check_write_scope rejects secrets dependency and report artifact paths" {
  _load_write_scope
  input="$(printf '.env\n.env.local\nnested/.env\n.secret\nnode_modules/pkg/index.js\n.git/index\n.git/config\ndist/assets/app.js\ncoverage/lcov.info\nplaywright-report/index.html\ntest-results/run.json\n')"

  run check_write_scope <<< "$input"

  [ "$status" -eq 1 ]
  [[ "$output" == *"write_scope violation: .env"* ]]
  [[ "$output" == *"write_scope violation: node_modules/pkg/index.js"* ]]
  [[ "$output" != *"write_scope violation: .git/index"* ]]
  [[ "$output" == *"write_scope violation: .git/config"* ]]
  [[ "$output" != *"write_scope violation: dist/assets/app.js"* ]]
}

@test "check_write_scope allows generated build caches dist assets and sqlite sidecars" {
  _load_write_scope
  input="$(printf 'build/test-results/test/TEST-Foo.xml\n.gradle/8.10.2/fileHashes/fileHashes.bin\ndist/assets/app.js\ndist/index.html\ntarget/classes/App.class\n.next/cache/trace\nserver/tracker.db-shm\nserver/tracker.db-wal\n')"

  run check_write_scope <<< "$input"

  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

@test "check_write_scope ignores blank lines" {
  _load_write_scope

  run check_write_scope <<< "$(printf '\n  \n\n')"

  [ "$status" -eq 0 ]
}

@test "mainspring sources write_scope before wave_loop" {
  run bash -n "$MAINSPRING_SH"

  [ "$status" -eq 0 ]
}

@test "bats tests do not reference pre-extraction mainspring script paths" {
  local stale_pattern
  stale_pattern="scripts""/mainspring/"

  run grep -R "$stale_pattern" "$BATS_TEST_DIRNAME"

  [ "$status" -eq 1 ]
  [ "$output" = "" ]
}
