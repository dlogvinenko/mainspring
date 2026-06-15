#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring lock management
# Globals read: LOCK_FILE, MAINSPRING_PY_DIR
# Globals written: fd 9

lock_fd9_nonblocking() {
  if command -v flock >/dev/null 2>&1; then
    flock -n 9
    return $?
  fi

  local runtime_python
  runtime_python="$(mainspring_python)"
  if [ ! -x "$runtime_python" ] && ! command -v "$runtime_python" >/dev/null 2>&1; then
    echo "Mainspring runtime lock requires either flock or Python fcntl support." >&2
    return 2
  fi

  "$runtime_python" "$MAINSPRING_PY_DIR/fd_lock.py" lock 9
}

unlock_fd9() {
  if command -v flock >/dev/null 2>&1; then
    flock -u 9 >/dev/null 2>&1 || true
    return 0
  fi

  local runtime_python
  runtime_python="$(mainspring_python)"
  [ -x "$runtime_python" ] || command -v "$runtime_python" >/dev/null 2>&1 || return 0
  "$runtime_python" "$MAINSPRING_PY_DIR/fd_lock.py" unlock 9 >/dev/null 2>&1 || true
}

acquire_lock() {
  mkdir -p "$(dirname "$LOCK_FILE")"
  touch "$LOCK_FILE"
  exec 9<>"$LOCK_FILE"

  local lock_status=0
  lock_fd9_nonblocking || lock_status=$?
  if [ "$lock_status" -ne 0 ]; then
    local existing_pid
    existing_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    if [ "$lock_status" -eq 1 ]; then
      echo "Mainspring already running (pid ${existing_pid:-unknown}); stop it or wait." >&2
    else
      echo "Mainspring could not acquire runtime lock ${LOCK_FILE}; run --doctor for dependency details." >&2
    fi
    exec 9>&- 2>/dev/null || true
    exit 1
  fi

  local existing_pid
  existing_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
  if [ -n "$existing_pid" ] && [ "$existing_pid" != "$$" ] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "Mainspring already running (pid ${existing_pid}); stop it or wait." >&2
    unlock_fd9
    exec 9>&- 2>/dev/null || true
    exit 1
  fi

  printf '%s\n' "$$" > "$LOCK_FILE"
}

release_lock() {
  unlock_fd9
  exec 9>&- 2>/dev/null || true
  if [ -f "$LOCK_FILE" ] && [ "$(cat "$LOCK_FILE" 2>/dev/null || true)" = "$$" ]; then
    rm -f "$LOCK_FILE"
  fi
}
