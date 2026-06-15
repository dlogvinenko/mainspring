#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring doctor — non-mutating readiness check
# Globals read: ROOT_DIR, LAST_RUN_FILE, LOCK_FILE, LOG_DIR, STATE_DIR,
#   AUTO_CHECKPOINT, MAINSPRING_PY_DIR
# Globals written: none
# Depends on: common.sh, status.sh, notify.sh (loaded before run_doctor)

doctor_builtin_team_exclude_prefixes() {
  printf '.claude\n'
}

doctor_team_exclude_prefixes() {
  local raw
  raw="${MAINSPRING_TEAM_EXCLUDE_PREFIXES:-}"
  {
    doctor_builtin_team_exclude_prefixes
    printf '%s\n' "$raw" | tr ',:' '\n'
  } | while IFS= read -r prefix; do
    prefix="${prefix#./}"
    prefix="${prefix%/}"
    [ -n "${prefix// }" ] && printf '%s\n' "$prefix"
  done
}

doctor_path_is_team_excluded() {
  local rel_path="$1"
  local prefixes prefix
  rel_path="${rel_path#./}"
  rel_path="${rel_path%/}"
  prefixes="$(doctor_team_exclude_prefixes)"
  [ -n "${prefixes// }" ] || return 1
  while IFS= read -r prefix; do
    [ -n "${prefix// }" ] || continue
    case "$rel_path" in
      "$prefix" | "$prefix"/*) return 0 ;;
    esac
  done <<< "$prefixes"
  return 1
}

doctor_nested_repo_visibility_report() {
  local root="${1:-$ROOT_DIR}"
  local marker repo_dir rel_path found=false
  if [ ! -d "$root" ]; then
    printf 'OK\tno workspace root available for nested repo scan\n'
    return 0
  fi

  while IFS= read -r marker; do
    repo_dir="$(dirname "$marker")"
    [ "$repo_dir" = "$root" ] && continue
    found=true
    rel_path="${repo_dir#"$root"/}"
    if doctor_path_is_team_excluded "$rel_path"; then
      printf 'OK\tNested git repo covered by team exclude prefix: %s\n' "$rel_path"
    else
      printf 'WARN\tNested git repo not covered by MAINSPRING_TEAM_EXCLUDE_PREFIXES: %s\n' "$rel_path"
    fi
  done < <(
    find "$root" \
      \( -path "$root/.git" -o \
         -path "$root/.mainspring" -o \
         -path "$root/.venv" -o \
         -path "$root/build" -o \
         -path "$root/node_modules" -o \
         -path "$root/dist" -o \
         -path "$root/coverage" \) -prune -o \
      -name .git -print 2>/dev/null
  )

  if [ "$found" = false ]; then
    printf 'OK\tno nested git repos detected\n'
  fi
}

doctor_active_team_report() {
  local state_dir="${1:-${STATE_DIR:-$ROOT_DIR/.mainspring/state}}"
  local team_config found_team=false team_name status_line
  for team_config in "$state_dir/team"/*/config.json; do
    [ -f "$team_config" ] || continue
    found_team=true
    team_name="$(basename "$(dirname "$team_config")")"
    if ! command -v omx >/dev/null 2>&1; then
      printf 'WARN\tactive team state exists for %s but team backend command is not in PATH; install the team backend or rerun with --topology solo\n' "$team_name"
      continue
    fi

    status_line="$(omx team status "$team_name" 2>&1 | sed -n '1,6p' || true)"
    if [ -n "${status_line// }" ]; then
      printf '%s\n' "$status_line" | sed "s/^/INFO\t[$team_name] /"
    else
      printf 'INFO\t[%s] no team status output\n' "$team_name"
    fi
    if printf '%s\n' "$status_line" | grep -q 'dead=[1-9]'; then
      printf 'WARN\tteam %s has dead workers\n' "$team_name"
    fi
  done
  if [ "$found_team" = false ]; then
    printf 'OK\tno active team backend state\n'
  fi
}

doctor_python() {
  mainspring_python
}

doctor_node_modules_report() {
  local root="${1:-${ROOT_DIR:-.}}"
  if [ ! -f "$root/package.json" ]; then
    return 0
  fi
  if [ -d "$root/node_modules" ]; then
    printf 'OK\tnode_modules present\n'
    if [ -x "$root/node_modules/.bin/vitest" ]; then
      printf 'OK\tlocal vitest present\n'
    else
      printf 'WARN\tlocal vitest missing\n'
    fi
    return 0
  fi
  printf 'WARN\tnode_modules missing; run npm install before local tests/builds\n'
}

doctor_engine_modules_missing() {
  grep -Eq '(^|[[:space:]])module=[^[:space:]]+:missing([[:space:]]|$)'
}

run_doctor() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --help|-h)
        cat <<'EOF'
Usage: mainspring doctor

Check local dependencies, git state, runtime locks, notifier health, engines,
Taskmaster integrity, package tooling, and optional GitHub tooling without
starting work.
EOF
        return 0
        ;;
      *)
        echo "doctor: unknown flag: $1" >&2
        return 2
        ;;
    esac
  done

  echo "=== Mainspring Doctor ==="
  echo "Root: $ROOT_DIR"
  echo "Time: $(date)"
  echo ""

  local problems=0
  local warnings=0
  local inside_git_worktree=false

  doctor_ok() {
    echo "OK: $*"
  }

  doctor_warn() {
    warnings=$((warnings + 1))
    echo "WARN: $*"
  }

  doctor_fail() {
    problems=$((problems + 1))
    echo "FAIL: $*"
  }

  doctor_command() {
    local cmd="$1"
    local severity="$2"
    local purpose="$3"
    local label="${4:-$cmd}"

    if command -v "$cmd" >/dev/null 2>&1; then
      doctor_ok "$label -> $(command -v "$cmd")"
      return 0
    fi

    case "$severity" in
      fail) doctor_fail "$label missing from PATH ($purpose)" ;;
      *) doctor_warn "$label missing from PATH ($purpose)" ;;
    esac
  }

  echo "--- Commands ---"
  doctor_command git fail "required for repository and replay checks"
  local runtime_python
  runtime_python="$(doctor_python)"
  if [ -x "$runtime_python" ] || command -v "$runtime_python" >/dev/null 2>&1; then
    doctor_ok "python runtime -> $runtime_python"
  else
    doctor_fail "Python runtime not found ($runtime_python)"
  fi
  doctor_command npm warn "JavaScript workspace verification (optional)"
  doctor_command node warn "JavaScript workspace verification (optional)"
  doctor_command task-master warn "Taskmaster backlog mode"
  doctor_command omx warn "team topology orchestration" "team backend command"
  doctor_command tmux warn "team topology panes"
  doctor_command codex warn "Codex writer/reviewer pair modes"
  doctor_command claude warn "Claude writer/reviewer pair modes"
  doctor_command fnm warn "node version manager; glob fallback used"
  doctor_command make warn "local CI Makefile"
  doctor_command shellcheck warn "make shell-lint"
  doctor_command ruff warn "make ruff"
  doctor_command bats warn "make bats"
  doctor_command jq warn "operator JSON inspection for --json outputs"
  doctor_command pipx warn "global install and package smoke checks"
  doctor_command gh warn "optional GitHub publication checks"
  if command -v flock >/dev/null 2>&1; then
    doctor_ok "flock -> $(command -v flock)"
  elif { [ -x "$runtime_python" ] || command -v "$runtime_python" >/dev/null 2>&1; } && "$runtime_python" "$MAINSPRING_PY_DIR/fd_lock.py" check >/dev/null 2>&1
  then
    doctor_ok "fd locks available via Python fcntl (flock command absent)"
  else
    doctor_fail "fd lock support missing; install flock or provide Python fcntl"
  fi
  echo ""

  echo "--- Git ---"
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    inside_git_worktree=true
    doctor_ok "git worktree detected"
    local status blocking_dirty package_lock_dirty taskmaster_dirty source_dirty
    status="$(git_status_short)"
    blocking_dirty="$(printf '%s\n' "$status" | grep -vE '^.. package-lock\.json$' | sed '/^[[:space:]]*$/d' || true)"
    package_lock_dirty="$(printf '%s\n' "$status" | grep -E '^.. package-lock\.json$' || true)"
    taskmaster_dirty="$(printf '%s\n' "$blocking_dirty" | grep -E '^.. \.taskmaster/' || true)"
    source_dirty="$(printf '%s\n' "$blocking_dirty" | grep -vE '^.. \.taskmaster/' | sed '/^[[:space:]]*$/d' || true)"
    if [ -n "${taskmaster_dirty// }" ]; then
      doctor_warn ".taskmaster state dirty; team mode will checkpoint it before fanout"
      printf '%s\n' "$taskmaster_dirty" | sed 's/^/  /' | sed -n '1,20p'
    fi
    if [ -n "${source_dirty// }" ]; then
      if [ "${AUTO_CHECKPOINT:-true}" = "true" ]; then
        doctor_warn "source/workflow dirty files will be auto-checkpointed before team fanout:"
      else
        doctor_warn "source/workflow dirty files can force solo fallback:"
      fi
      printf '%s\n' "$source_dirty" | sed 's/^/  /' | sed -n '1,20p'
    elif [ -z "${taskmaster_dirty// }" ]; then
      doctor_ok "no source/workflow dirty files"
    else
      doctor_ok "no source/workflow dirty files outside .taskmaster"
    fi
    if [ -n "${package_lock_dirty// }" ]; then
      doctor_warn "package-lock.json dirty; team mode will stash it before fanout"
    fi
    if git show-ref --heads --tags >/dev/null 2>&1; then
      doctor_ok "git refs are readable"
    else
      doctor_warn "git show-ref reports bad refs"
    fi
    if git stash list | grep -Eq 'mainspring package-lock drift before team fanout'; then
      doctor_warn "existing Mainspring package-lock stash found"
      git stash list | grep -E 'mainspring package-lock drift before team fanout' | sed -n '1,3p' | sed 's/^/  /'
    fi
  else
    doctor_fail "not inside a git worktree"
  fi
  echo ""

  echo "--- Team Worktree Visibility ---"
  if [ "$inside_git_worktree" = true ]; then
    local visibility_level visibility_message
    while IFS=$'\t' read -r visibility_level visibility_message; do
      [ -n "${visibility_level// }" ] || continue
      case "$visibility_level" in
        WARN) doctor_warn "$visibility_message" ;;
        OK) doctor_ok "$visibility_message" ;;
        *) doctor_warn "$visibility_level ${visibility_message:-}" ;;
      esac
    done < <(doctor_nested_repo_visibility_report "$ROOT_DIR")
  else
    doctor_ok "nested git repo scan skipped outside a git worktree"
  fi
  echo ""

  echo "--- Dependencies ---"
  local dependency_level dependency_message
  while IFS=$'\t' read -r dependency_level dependency_message; do
    [ -n "${dependency_level// }" ] || continue
    case "$dependency_level" in
      WARN) doctor_warn "$dependency_message" ;;
      OK) doctor_ok "$dependency_message" ;;
      *) doctor_warn "$dependency_level ${dependency_message:-}" ;;
    esac
  done < <(doctor_node_modules_report "$ROOT_DIR")
  local doctor_py
  doctor_py="$(doctor_python)"
  if "$doctor_py" "$MAINSPRING_PY_DIR/hud.py" --rich --once --ledger "$WAVE_LEDGER_FILE" --state-dir "${STATE_DIR:-$ROOT_DIR/.mainspring/state}" --width 80 >/dev/null 2>&1; then
    doctor_ok "Python rich present for hud --rich"
  else
    doctor_warn "Python rich missing or unusable (optional; required only for hud --rich)"
  fi
  if "$doctor_py" -m pytest --version >/dev/null 2>&1; then
    doctor_ok "Python pytest present for Mainspring pytest suite"
  else
    doctor_warn "Python pytest missing or unusable (required for make pytest)"
  fi
  echo ""

  echo "--- Engines ---"
  local engine_inventory_output
  if engine_inventory_output="$("$doctor_py" "$MAINSPRING_PY_DIR/engine_registry.py" 2>&1)"; then
    printf '%s\n' "$engine_inventory_output" | sed 's/^/  /'
    doctor_ok "engine registry readable"
    if printf '%s\n' "$engine_inventory_output" | doctor_engine_modules_missing; then
      doctor_warn "provider-engine Python module missing; install provider extras with Python 3.11-3.13 before provider waves"
    fi
  else
    printf '%s\n' "$engine_inventory_output" | sed 's/^/  /'
    doctor_warn "engine registry could not be read"
  fi
  echo ""

  echo "--- Script ---"
  local script_path="${SCRIPT_DIR:-$ROOT_DIR}/mainspring.sh"
  if bash -n "$script_path"; then
    doctor_ok "bash syntax passes"
  else
    doctor_fail "bash syntax failed"
  fi
  if [ -f "$LAST_RUN_FILE" ]; then
    doctor_ok "last-run settings exist: $LAST_RUN_FILE"
  else
    doctor_warn "last-run settings missing; run wizard once"
  fi
  echo ""

  echo "--- Runtime Lock ---"
  if [ -f "$LOCK_FILE" ]; then
    local lock_pid
    lock_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
      doctor_warn "Mainspring lock is active (pid $lock_pid)"
    else
      doctor_warn "stale lock file exists: $LOCK_FILE"
    fi
  else
    doctor_ok "no Mainspring lock"
  fi
  echo ""

  echo "--- Notification Daemon ---"
  if ! notify_enabled; then
    doctor_ok "Telegram notifications disabled"
  elif ! notify_configured; then
    doctor_warn "Telegram notifications enabled but token/chat id missing"
  else
    local notify_state_dir notify_pid_file notify_log_file notify_stale_seconds
    notify_state_dir="$(_notify_state_dir)"
    notify_pid_file="$(_notify_pid_file)"
    notify_log_file="$(_notify_log_file)"
    notify_stale_seconds="$(_notify_stale_seconds)"

    if [ -f "$notify_pid_file" ]; then
      local notify_pid
      notify_pid="$(cat "$notify_pid_file" 2>/dev/null || true)"
      if [ -n "$notify_pid" ] && kill -0 "$notify_pid" 2>/dev/null; then
        doctor_ok "Telegram notifier pid running ($notify_pid)"
      else
        doctor_warn "Telegram notifier pid is stale or dead (${notify_pid:-empty})"
      fi
    else
      doctor_warn "Telegram notifier pid missing; run mainspring notify-restart, then mainspring notify-test"
    fi

    local notify_health_output notify_health_status
    if notify_health_output="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/notify_telegram.py" health "$WAVE_LEDGER_FILE" \
      --state-dir "$notify_state_dir" \
      --log-file "$notify_log_file" \
      --pid-file "$notify_pid_file" \
      --stale-seconds "$notify_stale_seconds" 2>&1)"; then
      notify_health_status=0
    else
      notify_health_status=$?
    fi
    if [ "$notify_health_status" -eq 0 ]; then
      doctor_ok "$notify_health_output"
    elif [ "$notify_health_status" -eq 2 ]; then
      doctor_warn "$notify_health_output"
    else
      doctor_warn "Telegram notifier health probe failed: $notify_health_output"
    fi
  fi
  echo ""

  echo "--- Active Team ---"
  local active_team_level active_team_message
  while IFS=$'\t' read -r active_team_level active_team_message; do
    [ -n "${active_team_level// }" ] || continue
    case "$active_team_level" in
      WARN) doctor_warn "$active_team_message" ;;
      OK) doctor_ok "$active_team_message" ;;
      INFO) echo "  $active_team_message" ;;
      *) doctor_warn "$active_team_level ${active_team_message:-}" ;;
    esac
  done < <(doctor_active_team_report "${STATE_DIR:-$ROOT_DIR/.mainspring/state}")
  echo ""

  echo "--- Taskmaster Integrity ---"
  taskmaster_json_status_summary | sed 's/^/  /'
  taskmaster_scope_safety_summary | sed 's/^/  /'
  echo ""

  echo "--- Logs ---"
  [ -L "$LOG_DIR/latest-taskmaster.log" ] && doctor_ok "latest taskmaster log link exists" || doctor_warn "latest taskmaster log link missing"
  [ -L "$LOG_DIR/latest-taskmaster-summary.log" ] && doctor_ok "latest taskmaster summary link exists" || doctor_warn "latest taskmaster summary link missing"
  echo ""

  echo "--- Verdict ---"
  echo "Recommendations:"
  status_recommendations | sed 's/^/  /'
  if [ "$problems" -gt 0 ]; then
    echo "DOCTOR_RESULT: FAIL ($problems problems, $warnings warnings)"
    return 1
  fi
  if [ "$warnings" -gt 0 ]; then
    echo "DOCTOR_RESULT: WARN ($warnings warnings)"
    return 0
  fi
  echo "DOCTOR_RESULT: PASS"
  return 0
}
