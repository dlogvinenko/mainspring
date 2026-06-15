#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_doctor.bats — exercise non-mutating doctor helpers.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  COMMON_LIB="$ROOT_DIR/lib/common.sh"
  DOCTOR_LIB="$ROOT_DIR/lib/doctor.sh"
  TMPDIR_BATS="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR_BATS"
  unset MAINSPRING_TEAM_EXCLUDE_PREFIXES
  unset OMX""_"LOOP"_TEAM_EXCLUDE_PREFIXES
  unset MAINSPRING_PY
  unset MAINSPRING_RUNTIME_PYTHON
  unset VIRTUAL_ENV
}

_load_doctor() {
  if [ ! -f "$DOCTOR_LIB" ]; then
    skip "required helper missing: $DOCTOR_LIB"
  fi
  # shellcheck source=../../lib/common.sh
  source "$COMMON_LIB"
  # shellcheck source=../../lib/doctor.sh
  source "$DOCTOR_LIB"
}

# Scenario: Workspace contains a nested git repo and no team exclude prefix.
# Expected: doctor reports a WARN so team fanout cannot miss the invisible scope.
@test "doctor_nested_repo_visibility_report warns for uncovered nested repo" {
  _load_doctor
  local project
  project="$TMPDIR_BATS/project"
  mkdir -p "$project/.git" "$project/plugins/example/.git"

  run doctor_nested_repo_visibility_report "$project"

  [ "$status" -eq 0 ]
  [[ "$output" == *"WARN"* ]]
  [[ "$output" == *"plugins/example"* ]]
  [[ "$output" == *"MAINSPRING_TEAM_EXCLUDE_PREFIXES"* ]]
}

# Scenario: MAINSPRING_TEAM_EXCLUDE_PREFIXES covers the nested repo path.
# Expected: doctor reports OK instead of WARN.
@test "doctor_nested_repo_visibility_report accepts covered nested repo" {
  _load_doctor
  local project
  project="$TMPDIR_BATS/project"
  mkdir -p "$project/.git" "$project/plugins/example/.git"
  export MAINSPRING_TEAM_EXCLUDE_PREFIXES="plugins/example"

  run doctor_nested_repo_visibility_report "$project"

  [ "$status" -eq 0 ]
  [[ "$output" == *"OK"* ]]
  [[ "$output" == *"covered by team exclude prefix: plugins/example"* ]]
  [[ "$output" != *"WARN"* ]]
}

# Scenario: Codex/Claude helper worktrees live under .claude by default.
# Expected: doctor treats them as covered without per-project env setup.
@test "doctor_nested_repo_visibility_report covers claude helper worktrees by default" {
  _load_doctor
  local project
  project="$TMPDIR_BATS/project"
  mkdir -p "$project/.git" "$project/.claude/worktrees/agent/.git"

  run doctor_nested_repo_visibility_report "$project"

  [ "$status" -eq 0 ]
  [[ "$output" == *"OK"* ]]
  [[ "$output" == *".claude/worktrees/agent"* ]]
  [[ "$output" != *"WARN"* ]]
}

# Scenario: Only a stale pre-v1 env var is configured.
# Expected: public Mainspring ignores it and reports the nested repo.
@test "doctor_nested_repo_visibility_report ignores legacy exclude alias" {
  _load_doctor
  local project
  local legacy_prefix="OMX""_LOOP"
  project="$TMPDIR_BATS/project"
  mkdir -p "$project/.git" "$project/docs/private/.git"
  export "${legacy_prefix}_TEAM_EXCLUDE_PREFIXES=docs/private"

  run doctor_nested_repo_visibility_report "$project"

  [ "$status" -eq 0 ]
  [[ "$output" == *"WARN"* ]]
  [[ "$output" == *"docs/private"* ]]
}

# Scenario: Workspace has no nested git repos.
# Expected: doctor reports a clean OK summary.
@test "doctor_nested_repo_visibility_report reports no nested repos" {
  _load_doctor
  local project
  project="$TMPDIR_BATS/project"
  mkdir -p "$project/.git" "$project/src"

  run doctor_nested_repo_visibility_report "$project"

  [ "$status" -eq 0 ]
  [[ "$output" == *"OK"* ]]
  [[ "$output" == *"no nested git repos detected"* ]]
}

# Scenario: doctor is invoked from a plain directory such as /tmp.
# Expected: it reports the project-context problem once and does not scan the
# whole temporary tree for unrelated nested repositories.
@test "run_doctor skips nested repo scan outside a git worktree" {
  _load_doctor
  local project fake_py calls_file
  project="$TMPDIR_BATS/plain-directory"
  MAINSPRING_PY_DIR="$TMPDIR_BATS/py"
  fake_py="$project/.venv/bin/python3"
  calls_file="$TMPDIR_BATS/python-calls.log"
  mkdir -p "$project/.venv/bin" "$project/unrelated/repo/.git" "$MAINSPRING_PY_DIR" "$TMPDIR_BATS/state" "$TMPDIR_BATS/logs"
  printf '#!/bin/sh\nexit 0\n' > "$project/mainspring.sh"
  chmod +x "$project/mainspring.sh"
  touch "$MAINSPRING_PY_DIR/engine_registry.py" "$MAINSPRING_PY_DIR/fd_lock.py"
  cat > "$fake_py" <<SH
#!/bin/sh
printf 'venv %s\n' "\$*" >> "$calls_file"
if [ "\${1:-}" = "-m" ]; then
  exit 0
fi
case "\${1:-}" in
  *engine_registry.py)
    printf 'Mainspring engine inventory\n'
    printf -- '- codex: available (/venv/python3) default=gpt-5.5 execution=shell\n'
    ;;
esac
exit 0
SH
  chmod +x "$fake_py"
  export ROOT_DIR="$project"
  export SCRIPT_DIR="$project"
  export STATE_DIR="$TMPDIR_BATS/state"
  export WAVE_LEDGER_FILE="$TMPDIR_BATS/waves.jsonl"
  export LAST_RUN_FILE="$TMPDIR_BATS/last-run.env"
  export LOCK_FILE="$TMPDIR_BATS/mainspring.lock"
  export LOG_DIR="$TMPDIR_BATS/logs"
  notify_enabled() { return 1; }
  taskmaster_json_status_summary() { printf 'OK taskmaster summary\n'; }
  taskmaster_scope_safety_summary() { printf 'OK scope summary\n'; }
  status_recommendations() { printf 'no action\n'; }
  unset VIRTUAL_ENV
  unset MAINSPRING_PY
  cd "$project"

  run run_doctor

  [ "$status" -eq 1 ]
  [[ "$output" == *"FAIL: not inside a git worktree"* ]]
  [[ "$output" == *"OK: nested git repo scan skipped outside a git worktree"* ]]
  [[ "$output" != *"unrelated/repo"* ]]
}

# Scenario: A runtime has active team state but omx is not installed.
# Expected: doctor reports a structured warning instead of leaking a shell
# command-not-found error from the active-team probe.
@test "doctor_active_team_report warns cleanly when omx is unavailable" {
  _load_doctor
  local state_dir
  state_dir="$TMPDIR_BATS/state"
  mkdir -p "$state_dir/team/demo"
  printf '{}\n' > "$state_dir/team/demo/config.json"

  PATH="/bin:/usr/bin" run doctor_active_team_report "$state_dir"

  [ "$status" -eq 0 ]
  [[ "$output" == *"WARN"* ]]
  [[ "$output" == *"active team state exists for demo but team backend command is not in PATH"* ]]
  [[ "$output" != *"command not found"* ]]
}

# Scenario: The full doctor command runs from a minimal caller PATH while stale
# team state exists. mainspring.sh may add Homebrew/FNM paths for non-login
# shells, so globally installed operator tools can still be visible.
# Expected: it exits successfully with warnings, preserving the fresh-box
# portability contract without leaking shell command errors.
@test "mainspring doctor survives minimal path with active team state" {
  local runtime_dir home_dir
  runtime_dir="$TMPDIR_BATS/runtime"
  home_dir="$TMPDIR_BATS/home"
  mkdir -p "$runtime_dir/state/team/demo" "$home_dir"
  printf '{}\n' > "$runtime_dir/state/team/demo/config.json"

  run env -i \
    HOME="$home_dir" \
    USER="${USER:-mainspring-test}" \
    TMPDIR="$TMPDIR_BATS" \
    PATH="/bin:/usr/bin" \
    MAINSPRING_RUNTIME_DIR="$runtime_dir" \
    "$ROOT_DIR/mainspring.sh" --doctor

  [ "$status" -eq 0 ]
  if [[ "$output" != *"WARN: task-master missing from PATH"* ]]; then
    [[ "$output" == *"OK: task-master ->"* ]]
  fi
  if [[ "$output" != *"WARN: team backend command missing from PATH"* ]]; then
    [[ "$output" == *"OK: team backend command ->"* ]]
  fi
  [[ "$output" != *"OK: node_modules not required"* ]]
  [[ "$output" != *"node_modules missing"* ]]
  [[ "$output" == *"DOCTOR_RESULT: WARN"* ]]
  [[ "$output" != *"command not found"* ]]
}

# Scenario: The standalone repo has no package.json.
# Expected: doctor omits JavaScript dependency status entirely.
@test "doctor_node_modules_report omits JavaScript deps without package.json" {
  _load_doctor
  local project
  project="$TMPDIR_BATS/project"
  mkdir -p "$project"

  run doctor_node_modules_report "$project"

  [ "$status" -eq 0 ]
  [ -z "$output" ]
}

# Scenario: A JavaScript package exists but dependencies are not installed.
# Expected: doctor keeps the node_modules warning for real JS projects.
@test "doctor_node_modules_report warns when package.json exists without node_modules" {
  _load_doctor
  local project
  project="$TMPDIR_BATS/project"
  mkdir -p "$project"
  printf '{}\n' > "$project/package.json"

  run doctor_node_modules_report "$project"

  [ "$status" -eq 0 ]
  [[ "$output" == *"WARN"$'\t'"node_modules missing; run npm install before local tests/builds"* ]]
}

# Scenario: The operator is running inside a Python virtual environment.
# Expected: engine inventory uses that interpreter before any repo fallback.
@test "doctor_python prefers active virtualenv python" {
  _load_doctor
  local project venv
  project="$TMPDIR_BATS/project"
  venv="$TMPDIR_BATS/venv"
  mkdir -p "$project/.venv/bin" "$venv/bin"
  printf '#!/bin/sh\nexit 0\n' > "$project/.venv/bin/python3"
  printf '#!/bin/sh\nexit 0\n' > "$venv/bin/python3"
  chmod +x "$project/.venv/bin/python3" "$venv/bin/python3"
  ROOT_DIR="$project"
  export VIRTUAL_ENV="$venv"

  run doctor_python

  [ "$status" -eq 0 ]
  [ "$output" = "$venv/bin/python3" ]
}

# Scenario: No virtualenv is active but the source checkout has a local .venv.
# Expected: doctor uses the source-local interpreter for Python module probes.
@test "doctor_python falls back to repo venv python" {
  _load_doctor
  local project
  project="$TMPDIR_BATS/project"
  mkdir -p "$project/.venv/bin"
  printf '#!/bin/sh\nexit 0\n' > "$project/.venv/bin/python3"
  chmod +x "$project/.venv/bin/python3"
  ROOT_DIR="$project"
  SCRIPT_DIR="$project"
  unset VIRTUAL_ENV

  run doctor_python

  [ "$status" -eq 0 ]
  [ "$output" = "$project/.venv/bin/python3" ]
}

# Scenario: Packaged Mainspring runs inside a project that has its own .venv.
# Expected: doctor uses the packaged runtime Python, not the caller project's venv.
@test "doctor_python prefers packaged runtime python over project venv" {
  _load_doctor
  local project runtime_python
  project="$TMPDIR_BATS/project"
  runtime_python="$TMPDIR_BATS/pipx-python"
  mkdir -p "$project/.venv/bin"
  printf '#!/bin/sh\nexit 0\n' > "$project/.venv/bin/python3"
  printf '#!/bin/sh\nexit 0\n' > "$runtime_python"
  chmod +x "$project/.venv/bin/python3" "$runtime_python"
  ROOT_DIR="$project"
  SCRIPT_DIR="$TMPDIR_BATS/packaged-mainspring"
  export MAINSPRING_RUNTIME_PYTHON="$runtime_python"
  unset VIRTUAL_ENV
  unset MAINSPRING_PY

  run doctor_python

  [ "$status" -eq 0 ]
  [ "$output" = "$runtime_python" ]
}

# Scenario: The operator provides an explicit Python interpreter.
# Expected: doctor uses MAINSPRING_PY before falling back to PATH python3.
@test "doctor_python accepts explicit MAINSPRING_PY override" {
  _load_doctor
  local project custom_python
  project="$TMPDIR_BATS/project"
  custom_python="$TMPDIR_BATS/custom-python"
  mkdir -p "$project"
  printf '#!/bin/sh\nexit 0\n' > "$custom_python"
  chmod +x "$custom_python"
  ROOT_DIR="$project"
  unset VIRTUAL_ENV
  export MAINSPRING_PY="$custom_python"

  run doctor_python

  [ "$status" -eq 0 ]
  [ "$output" = "$custom_python" ]
}

# Scenario: The full doctor path probes engines through the resolved project Python.
# Expected: a repo-local .venv can satisfy LiteLLM checks without a node_modules warning.
@test "run_doctor uses resolved python for engine inventory and skips absent node_modules" {
  _load_doctor
  local project fake_py calls_file
  project="$TMPDIR_BATS/project"
  MAINSPRING_PY_DIR="$TMPDIR_BATS/py"
  fake_py="$project/.venv/bin/python3"
  calls_file="$TMPDIR_BATS/python-calls.log"
  mkdir -p "$project/.venv/bin" "$MAINSPRING_PY_DIR" "$TMPDIR_BATS/state"
  printf '#!/bin/sh\nexit 0\n' > "$project/mainspring.sh"
  chmod +x "$project/mainspring.sh"
  touch "$MAINSPRING_PY_DIR/engine_registry.py" "$MAINSPRING_PY_DIR/fd_lock.py"
  cat > "$fake_py" <<SH
#!/bin/sh
printf 'venv %s\n' "\$*" >> "$calls_file"
cat <<'OUT'
Mainspring engine inventory
- anthropic: available (/venv/python3) default=anthropic/claude-sonnet-4.5 execution=shell-dispatch quota=not-implemented module=litellm:available env=ANTHROPIC_API_KEY:missing
- azure: available (/venv/python3) default=azure/gpt-5.5 execution=shell-dispatch quota=not-implemented module=litellm:available env=AZURE_API_KEY,AZURE_API_BASE:missing
- gemini: available (/venv/python3) default=gemini/gemini-2.5-pro execution=shell-dispatch quota=not-implemented module=litellm:available env=GOOGLE_API_KEY:missing
- grok: available (/venv/python3) default=xai/grok-4 execution=shell-dispatch quota=not-implemented module=litellm:available env=XAI_API_KEY:missing
- litellm: available (/venv/python3) default=gpt-5.5 execution=shell-dispatch quota=not-implemented module=litellm:available
- mistral: available (/venv/python3) default=mistral/mistral-large-latest execution=shell-dispatch quota=not-implemented module=litellm:available env=MISTRAL_API_KEY:missing
- ollama: available (/venv/python3) default=ollama/codellama execution=shell-dispatch quota=not-implemented module=litellm:available
- openai: available (/venv/python3) default=openai/gpt-5.5 execution=shell-dispatch quota=not-implemented module=litellm:available env=OPENAI_API_KEY:missing
- openrouter: available (/venv/python3) default=openrouter/anthropic/claude-sonnet-4.5 execution=shell-dispatch quota=not-implemented module=litellm:available env=OPENROUTER_API_KEY:missing
OUT
exit 0
SH
  chmod +x "$fake_py"
  export ROOT_DIR="$project"
  export SCRIPT_DIR="$project"
  export STATE_DIR="$TMPDIR_BATS/state"
  export WAVE_LEDGER_FILE="$TMPDIR_BATS/waves.jsonl"
  export LAST_RUN_FILE="$TMPDIR_BATS/last-run.env"
  export LOCK_FILE="$TMPDIR_BATS/mainspring.lock"
  export LOG_DIR="$TMPDIR_BATS/logs"
  mkdir -p "$LOG_DIR"
  notify_enabled() { return 1; }
  taskmaster_json_status_summary() { printf 'OK taskmaster summary\n'; }
  taskmaster_scope_safety_summary() { printf 'OK scope summary\n'; }
  status_recommendations() { printf 'no action\n'; }
  unset VIRTUAL_ENV
  unset MAINSPRING_PY

  run run_doctor

  [ "$status" -eq 0 ]
  [[ "$(cat "$calls_file")" == *"$MAINSPRING_PY_DIR/hud.py"* ]]
  [[ "$(cat "$calls_file")" == *"-m pytest --version"* ]]
  [[ "$(cat "$calls_file")" == *"$MAINSPRING_PY_DIR/engine_registry.py"* ]]
  [[ "$output" != *"node_modules"* ]]
  [[ "$output" == *"module=litellm:available"* ]]
  [[ "$output" != *"registered engine Python module missing"* ]]
}

# Scenario: Engine inventory has missing provider env vars but Python modules
# are installed.
# Expected: doctor does not turn credential setup rows into module warnings.
@test "doctor_engine_modules_missing ignores env missing rows" {
  _load_doctor

  run doctor_engine_modules_missing <<'EOF'
- gemini: available (/path/python3) default=gemini/gemini-2.5-pro execution=shell-dispatch quota=not-implemented module=litellm:available env=GOOGLE_API_KEY:missing
EOF

  [ "$status" -eq 1 ]
}

# Scenario: Engine inventory reports a missing Python module.
# Expected: doctor preserves the module warning for actual module gaps.
@test "doctor_engine_modules_missing detects module missing rows" {
  _load_doctor

  run doctor_engine_modules_missing <<'EOF'
- gemini: available (/path/python3) default=gemini/gemini-2.5-pro execution=shell-dispatch quota=not-implemented module=litellm:missing env=GOOGLE_API_KEY:missing
EOF

  [ "$status" -eq 0 ]
}

# Scenario: Provider-engine credentials are missing during a local readiness check.
# Expected: doctor surfaces exact remediation instead of only raw inventory status.
@test "mainspring doctor explains provider setup remediation" {
  unset GOOGLE_API_KEY

  run "$ROOT_DIR/mainspring.sh" --doctor

  [ "$status" -eq 0 ]
  [[ "$output" == *"setup: environment variable GOOGLE_API_KEY is not set for engine gemini"* ]]
  [[ "$output" == *"run: export GOOGLE_API_KEY=<provider API key>"* ]]
}
