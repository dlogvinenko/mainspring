#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_team.bats — exercise team-topology policy helpers.

setup() {
  PROJECT_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  TEAM_LIB="$PROJECT_ROOT/lib/team.sh"
  export MAINSPRING_PY_DIR="$PROJECT_ROOT/py"
  TMPDIR_BATS="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR_BATS"
}

_load_team() {
  if [ ! -f "$TEAM_LIB" ]; then
    skip "required helper missing: $TEAM_LIB"
  fi
  # shellcheck source=../../lib/team.sh
  source "$TEAM_LIB"
}

# Scenario: Team helpers are sourced without the top-level launcher globals.
# Expected: fallback runtime roots use the post-P7 .mainspring layout.
@test "team runtime roots default to .mainspring" {
  _load_team
  ROOT_DIR="$TMPDIR_BATS/root"
  unset STATE_DIR
  unset TEAM_DIR

  [ "$(team_state_root)" = "$ROOT_DIR/.mainspring/state" ]
  [ "$(team_artifact_root)" = "$ROOT_DIR/.mainspring/team" ]
}

_write_mock_omx() {
  mkdir -p "$TMPDIR_BATS/bin"
  cat > "$TMPDIR_BATS/bin/omx" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${MAINSPRING_MOCK_TEAM_LOG:?}"
if [ "${1:-}" = "team" ] && [ "${2:-}" = "status" ]; then
  printf '{"status":"missing","phase":"missing"}\n'
  exit 0
fi
exit 0
SH
  chmod +x "$TMPDIR_BATS/bin/omx"
  export MAINSPRING_MOCK_TEAM_LOG="$TMPDIR_BATS/team-backend-calls.log"
  export PATH="$TMPDIR_BATS/bin:$PATH"
}

_write_mock_team_dispatch() {
  mkdir -p "$MAINSPRING_PY_DIR"
  cat > "$MAINSPRING_PY_DIR/team_dispatch.py" <<'PY'
#!/usr/bin/env python3
import json
import sys

print(json.dumps(sys.argv[1:]))
PY
}

# Scenario: Team dispatch is called from a nounset shell with no retry override.
# Expected: an empty retry list does not expand RETRY_TASK_IDS as an unbound array.
@test "dispatch_parallel_team_tasks tolerates empty retry ids under nounset" {
  _load_team
  MAINSPRING_PY_DIR="$TMPDIR_BATS/py"
  _write_mock_team_dispatch
  local items_jsonl="$TMPDIR_BATS/items.jsonl"
  touch "$items_jsonl"
  # shellcheck disable=SC2034
  RETRY_TASK_IDS=()

  set -u
  run dispatch_parallel_team_tasks "demo" "$items_jsonl" "4"
  set +u

  [ "$status" -eq 0 ]
  [[ "$output" == *'"dispatch", "demo", "4"'* ]]
  [[ "$output" != *"--retry-task"* ]]
}

# Scenario: Ready work is invisible to team worktrees but visible to solo.
# Expected: policy returns solo_fallback so Taskmaster is not blocked.
@test "team_fallback_taskmaster_action keeps plugin-invisible work recoverable" {
  _load_team

  run team_fallback_taskmaster_action "routing:plugin_invisible"

  [ "$status" -eq 0 ]
  [ "$output" = "solo_fallback" ]
}

# Scenario: Team topology has no independent work, but no task-specific failure.
# Expected: no Taskmaster blocking action is returned.
@test "team_fallback_taskmaster_action does not block generic no-work fallback" {
  _load_team

  run team_fallback_taskmaster_action "team:no_parallel_safe_work"

  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}

# Scenario: A non-recoverable task-scoped routing failure reaches team preflight.
# Expected: policy returns block_taskmaster for the caller to apply.
@test "team_fallback_taskmaster_action blocks explicit scope routing failures" {
  _load_team

  run team_fallback_taskmaster_action "routing:scope_blocked"

  [ "$status" -eq 0 ]
  [ "$output" = "block_taskmaster" ]
}

# Scenario: A stale team state exists during automatic preflight.
# Expected: preflight refuses destructive cleanup and leaves worktrees/state intact.
@test "preflight_team_artifacts refuses stale cleanup without restart-team" {
  _load_team
  _write_mock_omx
  ROOT_DIR="$TMPDIR_BATS/root"
  STATE_DIR="$ROOT_DIR/.mainspring/state"
  TEAM_DIR="$ROOT_DIR/.mainspring/team"
  mkdir -p "$STATE_DIR/team/demo" "$TEAM_DIR/demo/worktrees/worker-1"
  printf '{"name":"demo"}\n' > "$STATE_DIR/team/demo/config.json"
  touch "$TEAM_DIR/demo/worktrees/worker-1/uncommitted.txt"

  run preflight_team_artifacts

  [ "$status" -ne 0 ]
  [[ "$output" == *"Refusing destructive team backend cleanup for demo without --restart-team."* ]]
  [ -d "$STATE_DIR/team/demo" ]
  [ -f "$TEAM_DIR/demo/worktrees/worker-1/uncommitted.txt" ]
}

# Scenario: The operator explicitly asks for team restart.
# Expected: restart_active_teams is the destructive cleanup gate and removes old artifacts.
@test "restart_active_teams cleans artifacts only through explicit restart path" {
  _load_team
  _write_mock_omx
  ROOT_DIR="$TMPDIR_BATS/root"
  STATE_DIR="$ROOT_DIR/.mainspring/state"
  TEAM_DIR="$ROOT_DIR/.mainspring/team"
  export LOCK_FILE="$TMPDIR_BATS/mainspring.pid"
  mkdir -p "$STATE_DIR/team/demo" "$TEAM_DIR/demo/worktrees/worker-1"
  printf '{"name":"demo"}\n' > "$STATE_DIR/team/demo/config.json"
  touch "$TEAM_DIR/demo/worktrees/worker-1/uncommitted.txt"

  run restart_active_teams

  [ "$status" -eq 0 ]
  [[ "$output" == *"Restart requested: shutting down existing team backend demo"* ]]
  [ ! -e "$STATE_DIR/team/demo" ]
  [ ! -e "$TEAM_DIR/demo/worktrees/worker-1" ]
  grep -q "team shutdown demo --force" "$MAINSPRING_MOCK_TEAM_LOG"
}

# Scenario: A corrupted team name reaches the destructive cleanup helper.
# Expected: cleanup refuses traversal-shaped names even when restart-team is explicit.
@test "cleanup_team_artifacts rejects unsafe team names" {
  _load_team
  ROOT_DIR="$TMPDIR_BATS/root"
  STATE_DIR="$ROOT_DIR/.mainspring/state"
  TEAM_DIR="$ROOT_DIR/.mainspring/team"
  mkdir -p "$TMPDIR_BATS/outside"
  touch "$TMPDIR_BATS/outside/keep.txt"

  run cleanup_team_artifacts "../outside" "restart-team"

  [ "$status" -ne 0 ]
  [[ "$output" == *"Refusing unsafe team name for destructive cleanup"* ]]
  [ -f "$TMPDIR_BATS/outside/keep.txt" ]
}

# Scenario: Runtime roots are unexpectedly misconfigured to filesystem root.
# Expected: cleanup refuses to compute destructive paths from /.
@test "cleanup_team_artifacts refuses root cleanup roots" {
  _load_team
  ROOT_DIR="$TMPDIR_BATS/root"
  STATE_DIR="$ROOT_DIR/.mainspring/state"
  TEAM_DIR="/"

  run cleanup_team_artifacts "demo" "restart-team"

  [ "$status" -ne 0 ]
  [[ "$output" == *"Refusing destructive team cleanup outside runtime root."* ]]
}

# Scenario: A local process or attacker turns the worktrees dir into a symlink.
# Expected: destructive restart cleanup refuses the symlink and does not delete
# worker-looking directories outside the Mainspring runtime root.
@test "cleanup_team_artifacts refuses symlinked worktrees root" {
  _load_team
  ROOT_DIR="$TMPDIR_BATS/root"
  STATE_DIR="$ROOT_DIR/.mainspring/state"
  TEAM_DIR="$ROOT_DIR/.mainspring/team"
  local team_path="$TEAM_DIR/demo"
  local outside="$TMPDIR_BATS/outside-worktrees"
  mkdir -p "$team_path" "$outside/worker-1" "$STATE_DIR/team/demo"
  touch "$outside/worker-1/keep.txt"
  ln -s "$outside" "$team_path/worktrees"

  run cleanup_team_artifacts "demo" "restart-team"

  [ "$status" -ne 0 ]
  [[ "$output" == *"Refusing symlinked team worktrees directory"* ]]
  [ -f "$outside/worker-1/keep.txt" ]
  [ -L "$team_path/worktrees" ]
}

# Scenario: Team worker launch args are built from operator-controlled model
# strings.
# Expected: whitespace-shaped values fail before they can become extra flags.
@test "validate_team_worker_launch_args rejects unsafe model override" {
  _load_team
  ENGINE="codex"
  MODEL_OVERRIDE="gpt-5.5 --unsafe"
  CODEX_REASONING_EFFORT="xhigh"

  run validate_team_worker_launch_args

  [ "$status" -ne 0 ]
  [[ "$output" == *"Invalid team worker model id"* ]]
}

# Scenario: Codex reasoning effort reaches the worker launch config.
# Expected: only the documented enum values are accepted.
@test "validate_team_worker_launch_args rejects invalid codex reasoning effort" {
  _load_team
  ENGINE="codex"
  MODEL_OVERRIDE="gpt-5.5"
  CODEX_REASONING_EFFORT="xhigh --unsafe"

  run validate_team_worker_launch_args

  [ "$status" -ne 0 ]
  [[ "$output" == *"Invalid Codex reasoning effort"* ]]
}

# Scenario: Valid provider-style model ids include slashes, dots, colons, and
# dashes.
# Expected: normal local/provider model routing remains usable.
@test "validate_team_worker_launch_args accepts provider model ids" {
  _load_team
  ENGINE="codex"
  MODEL_OVERRIDE="ollama/qwen3:8b"
  CODEX_REASONING_EFFORT="xhigh"

  run validate_team_worker_launch_args

  [ "$status" -eq 0 ]
  [ "$output" = "" ]
}
