#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_status.bats — exercise status/reporting helpers.

setup() {
  PROJECT_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  STATUS_LIB="$PROJECT_ROOT/lib/status.sh"
  TMPDIR_BATS="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR_BATS"
}

_load_status() {
  if [ ! -f "$STATUS_LIB" ]; then
    skip "required helper missing: $STATUS_LIB"
  fi
  # shellcheck source=../../lib/status.sh
  source "$STATUS_LIB"
}

# Scenario: Status helpers are sourced without the top-level launcher globals.
# Expected: fallback runtime state uses the post-P7 .mainspring layout.
@test "status runtime state defaults to .mainspring" {
  _load_status
  ROOT_DIR="$TMPDIR_BATS/root"
  unset STATE_DIR

  [ "$(runtime_state_dir)" = "$ROOT_DIR/.mainspring/state" ]
}

# Scenario: old team routing history exists but Taskmaster currently has no
# ready top-level item.
# Expected: recommendations explain the no-work state instead of suggesting a
# pointless solo rerun.
@test "status recommendations prefer no-ready Taskmaster over stale team routing" {
  _load_status
  LOCK_FILE="$TMPDIR_BATS/missing.lock"

  taskmaster_json_status_summary() {
    printf '%s\n' \
      "Taskmaster: done=7 review=0 in-progress=0 pending=0 blocked=7 deferred=0" \
      "scheduler: STOP_BLOCKED no ready top-level task"
  }
  taskmaster_scope_safety_summary() {
    printf '%s\n' "scope: no ready top-level Taskmaster item"
  }
  wave_routing_hints() {
    printf '%s\n' "routing: use solo mode; recent team run found no parallel-safe work."
  }

  run status_recommendations
  [ "$status" -eq 0 ]
  [[ "$output" == *"No ready Taskmaster work"* ]]
  [[ "$output" == *"task-master list"* ]]
  [[ "$output" != *"rerun with solo recovery"* ]]
  [[ "$output" != *"Recent team routing found no parallel-safe work"* ]]
}

# Scenario: old routing history exists, but the current project has no
# Taskmaster backlog at all.
# Expected: recommendations tell the operator to initialize/add backlog state
# instead of suggesting a stale solo rerun.
@test "status recommendations prefer missing Taskmaster setup over stale routing" {
  _load_status
  LOCK_FILE="$TMPDIR_BATS/missing.lock"

  taskmaster_json_status_summary() {
    printf '%s\n' "Taskmaster: missing .taskmaster/tasks/tasks.json"
  }
  taskmaster_scope_safety_summary() {
    printf '%s\n' "scope: Taskmaster file missing"
  }
  wave_routing_hints() {
    printf '%s\n' "routing: use solo mode; recent team run found no parallel-safe work."
  }

  run status_recommendations
  [ "$status" -eq 0 ]
  [[ "$output" == *"Taskmaster backlog missing"* ]]
  [[ "$output" == *"mainspring init checkout-redesign"* ]]
  [[ "$output" == *"replace checkout-redesign with your feature name"* ]]
  [[ "$output" != *"mainspring init <name>"* ]]
  [[ "$output" == *"Open live dashboard: mainspring hud"* ]]
  [[ "$output" != *"Run this command freely for diagnosis: mainspring status"* ]]
  [[ "$output" != *"Recent team routing found no parallel-safe work"* ]]
}

# Scenario: current Taskmaster state has actionable scope, but recent team
# routing found no disjoint work.
# Expected: recommendations keep the solo recovery command.
@test "status recommendations keep solo recovery when ready scope exists" {
  _load_status
  # shellcheck disable=SC2034  # consumed by status_recommendations from sourced lib.
  LOCK_FILE="$TMPDIR_BATS/missing.lock"

  taskmaster_json_status_summary() {
    printf '%s\n' \
      "Taskmaster: done=7 review=0 in-progress=0 pending=1 blocked=0 deferred=0" \
      "scheduler: SELECT #8 ready"
  }
  taskmaster_scope_safety_summary() {
    printf '%s\n' "scope: selected #8"
  }
  wave_routing_hints() {
    printf '%s\n' "routing: use solo mode; recent team run found no parallel-safe work."
  }

  run status_recommendations
  [ "$status" -eq 0 ]
  [[ "$output" == *"Recent team routing found no parallel-safe work"* ]]
  [[ "$output" == *"mainspring taskmaster --topology solo --pair codex+codex --once"* ]]
  [[ "$output" != *"No ready Taskmaster work"* ]]
}

# Scenario: dependency/quota probes and unrelated agent CLI processes are not
# Mainspring runtime launchers.
# Expected: process filtering omits those rows instead of leaking unrelated
# prompts into status output, while preserving a real Mainspring launcher row.
@test "runtime process filter hides unrelated agent prompts" {
  _load_status

  run bash -c "source '$STATUS_LIB'; printf '%s\n' \
    '111 1 S claude -p --dangerously-skip-permissions --verbose --output-format stream-json --include-partial-messages Reply exactly: ok' \
    '222 1 S codex exec --yolo Implement private task 8' \
    '333 1 S /bin/bash /private/path/mainspring.sh --project /tmp/app taskmaster --once' \
    '334 1 S /bin/bash -lc ./mainspring.sh --project /tmp/app taskmaster --once' \
    '444 1 S /bin/bash /private/path/mainspring.sh status' \
    | filter_runtime_process_lines"

  [ "$status" -eq 0 ]
  [[ "$output" != *"Reply exactly: ok"* ]]
  [[ "$output" != *"Implement private task 8"* ]]
  [[ "$output" != *"/private/path"* ]]
  [[ "$output" != *"status"* ]]
  [[ "$output" == *"pid=333 stat=S kind=mainspring-taskmaster"* ]]
  [[ "$output" == *"pid=334 stat=S kind=mainspring-taskmaster"* ]]
}

# Scenario: A developer may have arbitrary personal tmux sessions open.
# Expected: status reports only Mainspring launcher sessions and does not leak
# unrelated session names into public/status output.
@test "tmux status hides unrelated personal sessions" {
  _load_status

  run bash -c "source '$STATUS_LIB'; \
    tmux() { printf '%s\n' \
      'personal-vite: 1 windows (created Mon Jun  8 12:57:16 2026)' \
      'mainspring-20260613-082300: 1 windows (created Sat Jun 13 08:23:00 2026)'; }; \
    tmux_mainspring_summary"

  [ "$status" -eq 0 ]
  [[ "$output" == *"mainspring-20260613-082300"* ]]
  [[ "$output" != *"personal-vite"* ]]
}

# Scenario: tmux exists but only unrelated sessions are running.
# Expected: status says none instead of dumping personal session names.
@test "tmux status reports none when no Mainspring session exists" {
  _load_status

  run bash -c "source '$STATUS_LIB'; \
    tmux() { printf '%s\n' 'personal-work: 3 windows (created Sat Jun 13 08:23:00 2026)'; }; \
    tmux_mainspring_summary"

  [ "$status" -eq 0 ]
  [ "$output" = "none" ]
}
