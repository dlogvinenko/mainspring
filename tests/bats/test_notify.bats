#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_notify.bats — exercise notification functions from lib/notify.sh.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  COMMON_LIB="$ROOT_DIR/lib/common.sh"
  NOTIFY_LIB="$ROOT_DIR/lib/notify.sh"
  TMPDIR_BATS="$(mktemp -d)"
  MAINSPRING_PY_DIR="$ROOT_DIR/py"
  LOG_DIR="$TMPDIR_BATS/logs"
  WAVE_LEDGER_FILE="$LOG_DIR/waves.jsonl"
  mkdir -p "$LOG_DIR"
}

teardown() {
  rm -rf "$TMPDIR_BATS"
  unset MAINSPRING_NOTIFY_ENABLED
  unset MAINSPRING_TELEGRAM_BOT_TOKEN
  unset MAINSPRING_TELEGRAM_CHAT_ID
  unset MAINSPRING_NOTIFY_STALE_SECONDS
  unset MAINSPRING_NOTIFY_DRAIN_SECONDS
}

_load_notify() {
  if [ ! -f "$NOTIFY_LIB" ]; then
    skip "required helper missing: $NOTIFY_LIB"
  fi
  source "$COMMON_LIB"
  source "$NOTIFY_LIB"
}

_start_fake_notifier() {
  local fake_notifier ledger_arg state_arg
  fake_notifier="$TMPDIR_BATS/notify_telegram.py"
  ledger_arg="${1:-$WAVE_LEDGER_FILE}"
  state_arg="${2:-$(_notify_state_dir)}"
  cat > "$fake_notifier" <<'SH'
#!/bin/sh
child_pid=""
cleanup() {
  if [ -n "$child_pid" ]; then
    kill "$child_pid" 2>/dev/null || true
  fi
  exit 0
}
trap cleanup INT TERM
sleep 60 &
child_pid=$!
wait "$child_pid"
SH
  chmod +x "$fake_notifier"
  "$fake_notifier" watch "$ledger_arg" --state-dir "$state_arg" >/dev/null 2>&1 &
  echo "$!"
}

# Scenario: notify_enabled returns false when env not set.
# Expected: function returns 1.
@test "notify_enabled returns false when MAINSPRING_NOTIFY_ENABLED unset" {
  _load_notify
  unset MAINSPRING_NOTIFY_ENABLED
  run notify_enabled
  [ "$status" -ne 0 ]
}

# Scenario: notify_enabled returns true when MAINSPRING_NOTIFY_ENABLED=1.
# Expected: function returns 0.
@test "notify_enabled returns true when MAINSPRING_NOTIFY_ENABLED=1" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  notify_enabled
}

# Scenario: notify_enabled accepts the same case-insensitive truthy values as
# notify_telegram.py and HUD.
# Expected: shell auto-launch truth does not drift from operator-health truth.
@test "notify_enabled accepts yes on and uppercase true" {
  _load_notify

  MAINSPRING_NOTIFY_ENABLED=yes
  notify_enabled

  MAINSPRING_NOTIFY_ENABLED=on
  notify_enabled

  MAINSPRING_NOTIFY_ENABLED=TRUE
  notify_enabled
}

# Scenario: a stale pre-v1 notify env var is present.
# Expected: public Mainspring ignores it.
@test "notify_enabled ignores legacy env var" {
  _load_notify
  local legacy_prefix="OMX""_LOOP"
  unset MAINSPRING_NOTIFY_ENABLED
  export "${legacy_prefix}_NOTIFY_ENABLED=1"
  run notify_enabled
  [ "$status" -ne 0 ]
}

# Scenario: notify_configured returns false with no token.
# Expected: function returns 1.
@test "notify_configured returns false without token" {
  _load_notify
  unset MAINSPRING_TELEGRAM_BOT_TOKEN
  unset MAINSPRING_TELEGRAM_CHAT_ID
  run notify_configured
  [ "$status" -ne 0 ]
}

# Scenario: notify_configured returns true with both vars set.
# Expected: function returns 0.
@test "notify_configured returns true with both vars set" {
  _load_notify
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"
  notify_configured
}

# Scenario: start_notify_daemon does nothing when disabled.
# Expected: no pid file created.
@test "start_notify_daemon does nothing when disabled" {
  _load_notify
  unset MAINSPRING_NOTIFY_ENABLED
  start_notify_daemon
  local pid_file
  pid_file="$(_notify_pid_file)"
  [ ! -f "$pid_file" ]
}

# Scenario: A live daemon PID is behind the ledger past the stale threshold.
# Expected: start_notify_daemon terminates it and writes a new daemon PID.
@test "start_notify_daemon restarts stale live daemon" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"
  MAINSPRING_NOTIFY_STALE_SECONDS=1

  printf '{"verdict":"PASS"}\n' > "$WAVE_LEDGER_FILE"
  local state_dir pid_file old_pid new_pid
  state_dir="$(_notify_state_dir)"
  pid_file="$(_notify_pid_file)"
  printf '{"last_line_count":0,"last_activity_ts":1}\n' > "$state_dir/notify-state.json"

  old_pid="$(_start_fake_notifier)"
  echo "$old_pid" > "$pid_file"

  run start_notify_daemon
  [ "$status" -eq 0 ]
  [[ "$output" == *"daemon stale; restarting"* ]]

  wait "$old_pid" 2>/dev/null || true
  new_pid="$(cat "$pid_file")"
  [ -n "$new_pid" ]
  [ "$new_pid" != "$old_pid" ]

  stop_notify_daemon
}

# Scenario: A live daemon PID is already caught up with the ledger.
# Expected: start_notify_daemon keeps the existing PID.
@test "start_notify_daemon keeps healthy live daemon" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"

  printf '{"verdict":"PASS"}\n' > "$WAVE_LEDGER_FILE"
  local state_dir pid_file old_pid kept_pid now
  state_dir="$(_notify_state_dir)"
  pid_file="$(_notify_pid_file)"
  now="$(date +%s)"
  printf '{"last_line_count":1,"last_activity_ts":%s}\n' "$now" > "$state_dir/notify-state.json"
  printf 'notify: %s processed 1 new ledger line(s), 1 valid\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$(_notify_log_file)"

  old_pid="$(_start_fake_notifier)"
  echo "$old_pid" > "$pid_file"

  run start_notify_daemon
  [ "$status" -eq 0 ]
  kept_pid="$(cat "$pid_file")"
  [ "$kept_pid" = "$old_pid" ]

  kill "$old_pid" 2>/dev/null || true
  wait "$old_pid" 2>/dev/null || true
  rm -f "$pid_file"
}

# Scenario: The recorded notifier PID was killed before the next wave boundary.
# Expected: start_notify_daemon removes the dead PID file, starts a replacement,
# and returns success so wave execution is not blocked by notifier death.
@test "start_notify_daemon recovers from killed daemon pid" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"

  local pid_file dead_pid new_pid
  pid_file="$(_notify_pid_file)"

  sleep 60 &
  dead_pid=$!
  echo "$dead_pid" > "$pid_file"
  kill -9 "$dead_pid" 2>/dev/null || true
  wait "$dead_pid" 2>/dev/null || true
  if kill -0 "$dead_pid" 2>/dev/null; then
    false
  fi

  run start_notify_daemon
  [ "$status" -eq 0 ]
  [[ "$output" == *"stale pid file removed"* ]]

  new_pid="$(cat "$pid_file")"
  [ -n "$new_pid" ]
  [ "$new_pid" != "$dead_pid" ]
  kill -0 "$new_pid" 2>/dev/null

  stop_notify_daemon
}

# Scenario: operator shells and agent harnesses may clean up their process group
# after the command exits.
# Expected: start_notify_daemon uses the detached nohup/spawner path and leaves
# a live watcher PID behind for explicit notify-restart.
@test "start_notify_daemon detaches watcher through nohup when available" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"

  local stub_bin probe_file pid_file daemon_pid i
  stub_bin="$BATS_TEST_TMPDIR/bin"
  probe_file="$BATS_TEST_TMPDIR/nohup-probe"
  mkdir -p "$stub_bin"
  cat > "$stub_bin/nohup" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$NOHUP_PROBE_FILE"
exec "$@"
SH
  chmod +x "$stub_bin/nohup"
  export NOHUP_PROBE_FILE="$probe_file"

  PATH="$stub_bin:$PATH" start_notify_daemon >/dev/null 2>&1
  for i in {1..20}; do
    [ -s "$probe_file" ] && break
    sleep 0.1
  done

  [ -s "$probe_file" ]
  pid_file="$(_notify_pid_file)"
  daemon_pid="$(cat "$pid_file")"
  [ -n "$daemon_pid" ]
  kill -0 "$daemon_pid" 2>/dev/null

  stop_notify_daemon
}

# Scenario: A stale pid file points at an unrelated live process.
# Expected: start_notify_daemon removes the pid file without killing that
# process, then starts a real notifier daemon.
@test "start_notify_daemon ignores live foreign pid file" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"

  local pid_file foreign_pid new_pid
  pid_file="$(_notify_pid_file)"

  sleep 60 &
  foreign_pid=$!
  echo "$foreign_pid" > "$pid_file"

  run start_notify_daemon
  [ "$status" -eq 0 ]
  [[ "$output" == *"foreign pid file removed"* ]]
  kill -0 "$foreign_pid" 2>/dev/null

  new_pid="$(cat "$pid_file")"
  [ -n "$new_pid" ]
  [ "$new_pid" != "$foreign_pid" ]
  kill -0 "$new_pid" 2>/dev/null

  stop_notify_daemon
  kill "$foreign_pid" 2>/dev/null || true
  wait "$foreign_pid" 2>/dev/null || true
}

# Scenario: A live daemon PID is caught up, but notifier.log has only the
# startup line and no processed activity yet.
# Expected: start_notify_daemon treats it as warming up and keeps the PID.
@test "start_notify_daemon keeps live daemon during notifier log warmup" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"

  printf '{"verdict":"PASS"}\n' > "$WAVE_LEDGER_FILE"
  local state_dir pid_file old_pid kept_pid now
  state_dir="$(_notify_state_dir)"
  pid_file="$(_notify_pid_file)"
  now="$(date +%s)"
  printf '{"last_line_count":1,"last_activity_ts":%s}\n' "$now" > "$state_dir/notify-state.json"
  printf 'notify: watching %s\n' "$WAVE_LEDGER_FILE" > "$(_notify_log_file)"

  old_pid="$(_start_fake_notifier)"
  echo "$old_pid" > "$pid_file"

  run start_notify_daemon
  [ "$status" -eq 0 ]
  kept_pid="$(cat "$pid_file")"
  [ "$kept_pid" = "$old_pid" ]
  kill -0 "$old_pid" 2>/dev/null

  kill "$old_pid" 2>/dev/null || true
  wait "$old_pid" 2>/dev/null || true
  rm -f "$pid_file"
}

# Scenario: The health probe exits 2 because its invocation/config is invalid,
# not because JSON health reported a stale daemon.
# Expected: start_notify_daemon keeps the existing daemon instead of killing it.
@test "start_notify_daemon preserves daemon on health parser error" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"
  MAINSPRING_NOTIFY_STALE_SECONDS="soon"

  printf '{"verdict":"PASS"}\n' > "$WAVE_LEDGER_FILE"
  local state_dir pid_file old_pid kept_pid now
  state_dir="$(_notify_state_dir)"
  pid_file="$(_notify_pid_file)"
  now="$(date +%s)"
  printf '{"last_line_count":1,"last_activity_ts":%s}\n' "$now" > "$state_dir/notify-state.json"
  printf 'notify: %s processed 1 new ledger line(s), 1 valid\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$(_notify_log_file)"

  old_pid="$(_start_fake_notifier)"
  echo "$old_pid" > "$pid_file"

  run start_notify_daemon
  [ "$status" -eq 0 ]
  [[ "$output" == *"health check failed; keeping existing daemon"* ]]
  kept_pid="$(cat "$pid_file")"
  [ "$kept_pid" = "$old_pid" ]
  kill -0 "$old_pid" 2>/dev/null

  kill "$old_pid" 2>/dev/null || true
  wait "$old_pid" 2>/dev/null || true
  rm -f "$pid_file"
}

# Scenario: A failed health probe prints stale-looking text that is not JSON.
# Expected: the supervisor gate ignores it instead of restarting the daemon.
@test "_notify_health_is_stale requires parsed JSON status" {
  _load_notify

  run _notify_health_is_stale 'notify: parser failed before JSON {"status":"stale"}'
  [ "$status" -ne 0 ]

  run _notify_health_is_stale '{"status":"stale"}'
  [ "$status" -eq 0 ]
}

# Scenario: The pid file points at an unrelated live process.
# Expected: stop_notify_daemon removes the pid file without killing it.
@test "stop_notify_daemon ignores live foreign pid file" {
  _load_notify
  local pid_file foreign_pid
  pid_file="$(_notify_pid_file)"

  sleep 60 &
  foreign_pid=$!
  echo "$foreign_pid" > "$pid_file"

  run stop_notify_daemon
  [ "$status" -eq 0 ]
  [[ "$output" == *"foreign pid file removed"* ]]
  [ ! -f "$pid_file" ]
  kill -0 "$foreign_pid" 2>/dev/null

  kill "$foreign_pid" 2>/dev/null || true
  wait "$foreign_pid" 2>/dev/null || true
}

# Scenario: The pid file points at a real notifier process for another project.
# Expected: stop_notify_daemon removes the pid file without killing it because
# the command does not include this project's waves.jsonl path.
@test "stop_notify_daemon ignores notifier process for another ledger" {
  _load_notify
  local pid_file foreign_pid other_ledger
  pid_file="$(_notify_pid_file)"
  other_ledger="$TMPDIR_BATS/other-project/logs/waves.jsonl"
  mkdir -p "$(dirname "$other_ledger")"

  foreign_pid="$(_start_fake_notifier "$other_ledger")"
  echo "$foreign_pid" > "$pid_file"

  run stop_notify_daemon
  [ "$status" -eq 0 ]
  [[ "$output" == *"foreign pid file removed"* ]]
  [ ! -f "$pid_file" ]
  kill -0 "$foreign_pid" 2>/dev/null

  kill "$foreign_pid" 2>/dev/null || true
  wait "$foreign_pid" 2>/dev/null || true
}

# Scenario: The operator explicitly asks for a notifier restart.
# Expected: only the recorded notifier process is stopped and a replacement
# daemon is started from the same configured state.
@test "run_notify_restart replaces recorded notifier daemon" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"

  local pid_file old_pid new_pid kept_pid
  pid_file="$(_notify_pid_file)"
  old_pid="$(_start_fake_notifier)"
  echo "$old_pid" > "$pid_file"

  run run_notify_restart
  [ "$status" -eq 0 ]
  [[ "$output" == *"daemon stopped"* ]]
  [[ "$output" == *"daemon started"* ]]
  if kill -0 "$old_pid" 2>/dev/null; then
    false
  fi

  new_pid="$(cat "$pid_file")"
  [ -n "$new_pid" ]
  [ "$new_pid" != "$old_pid" ]
  kill -0 "$new_pid" 2>/dev/null

  stop_notify_daemon
}

# Scenario: notify-restart is a standalone operator command.
# Expected: the replacement daemon is not owned by the current shell cleanup
# trap, so reap_notify_daemon preserves it after run_notify_restart returns.
@test "run_notify_restart leaves replacement daemon running after cleanup" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"

  local pid_file old_pid new_pid
  pid_file="$(_notify_pid_file)"
  old_pid="$(_start_fake_notifier)"
  echo "$old_pid" > "$pid_file"

  run_notify_restart >/dev/null 2>&1
  new_pid="$(cat "$pid_file")"

  [ -n "$new_pid" ]
  [ "$new_pid" != "$old_pid" ]
  [ -z "${NOTIFY_DAEMON_PID:-}" ]
  reap_notify_daemon
  kept_pid="$(cat "$pid_file")"
  [ "$kept_pid" = "$new_pid" ]
  kill -0 "$new_pid" 2>/dev/null

  stop_notify_daemon
}

# Scenario: The operator asks for a notifier restart before enabling it.
# Expected: the command fails loudly instead of doing nothing.
@test "run_notify_restart requires notifications enabled" {
  _load_notify
  unset MAINSPRING_NOTIFY_ENABLED

  run run_notify_restart
  [ "$status" -eq 1 ]
  [[ "$output" == *"notifications disabled"* ]]
}

# Scenario: A notifier daemon was started by another process before this
# shell exits.
# Expected: cleanup reaping preserves the existing daemon and pid file.
@test "reap_notify_daemon preserves daemon not owned by current shell" {
  _load_notify
  local pid_file existing_pid kept_pid
  pid_file="$(_notify_pid_file)"

  sleep 60 &
  existing_pid=$!
  echo "$existing_pid" > "$pid_file"
  NOTIFY_DAEMON_PID=""

  reap_notify_daemon
  kept_pid="$(cat "$pid_file")"
  [ "$kept_pid" = "$existing_pid" ]
  kill -0 "$existing_pid" 2>/dev/null

  kill "$existing_pid" 2>/dev/null || true
  wait "$existing_pid" 2>/dev/null || true
  rm -f "$pid_file"
}

# Scenario: The current shell launched the notifier daemon and owns the PID.
# Expected: cleanup reaping terminates that child and removes its pid file.
@test "reap_notify_daemon removes daemon owned by current shell" {
  _load_notify
  local pid_file owned_pid
  pid_file="$(_notify_pid_file)"

  sleep 60 &
  owned_pid=$!
  echo "$owned_pid" > "$pid_file"
  NOTIFY_DAEMON_PID="$owned_pid"

  reap_notify_daemon
  [ ! -f "$pid_file" ]
  if kill -0 "$owned_pid" 2>/dev/null; then
    false
  fi
}

# Scenario: The current shell is exiting immediately after appending a final
# scheduler STOP row.
# Expected: cleanup waits for the owned notifier to catch up before killing it,
# so terminal notifications are not lost.
@test "reap_notify_daemon waits for owned daemon to drain pending ledger lines" {
  _load_notify
  local pid_file state_dir owned_pid updater start_ts end_ts now
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN=test-token
  MAINSPRING_TELEGRAM_CHAT_ID=12345
  MAINSPRING_NOTIFY_DRAIN_SECONDS=4
  pid_file="$(_notify_pid_file)"
  state_dir="$(_notify_state_dir)"
  printf '{"verdict":"STOP","failure_reason":"routing:idle_threshold"}\n' > "$WAVE_LEDGER_FILE"
  printf '{"last_line_count":0,"last_activity_ts":1}\n' > "$state_dir/notify-state.json"

  sleep 60 &
  owned_pid=$!
  echo "$owned_pid" > "$pid_file"
  NOTIFY_DAEMON_PID="$owned_pid"

  (
    sleep 1
    now="$(date +%s)"
    printf '{"last_line_count":1,"last_activity_ts":%s}\n' "$now" > "$state_dir/notify-state.json"
    printf 'notify: %s processed 1 new ledger line(s), 1 valid\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$(_notify_log_file)"
  ) &
  updater=$!

  start_ts="$(date +%s)"
  reap_notify_daemon
  end_ts="$(date +%s)"
  wait "$updater" 2>/dev/null || true

  [ ! -f "$pid_file" ]
  if kill -0 "$owned_pid" 2>/dev/null; then
    false
  fi
  [ $((end_ts - start_ts)) -ge 1 ]
}

# Scenario: The solo wave loop reaches a wave boundary.
# Expected: It re-checks the notifier daemon before picking work.
@test "run_wave_loop rechecks notifier at solo wave boundary" {
  local wave_loop_lib wave_loop_setup_lib wave_loop_state_lib ensure_calls stub_bin
  wave_loop_lib="$ROOT_DIR/lib/wave_loop.sh"
  wave_loop_setup_lib="$ROOT_DIR/lib/wave_loop_setup.sh"
  wave_loop_state_lib="$ROOT_DIR/lib/wave_loop_state.sh"
  ensure_calls="$TMPDIR_BATS/ensure-calls"
  stub_bin="$TMPDIR_BATS/bin"
  if [ ! -f "$wave_loop_lib" ]; then
    skip "required helper missing: $wave_loop_lib"
  fi

  mkdir -p "$stub_bin"
  printf '#!/bin/sh\nexit 0\n' > "$stub_bin/task-master"
  chmod +x "$stub_bin/task-master"
  PATH="$stub_bin:$PATH"

  MODE=taskmaster
  TOPOLOGY=solo
  ENGINE=codex
  REVIEW_ENGINE=codex
  MODEL_OVERRIDE=""
  REVIEW_MODEL_OVERRIDE=""
  CODEX_REASONING_EFFORT=xhigh
  RUN_ONCE=true
  PRD_PATH=""
  IDLE_WAVES=0
  MAX_IDLE_WAVES=1
  TASKMASTER_BASE_MISSION=""
  NIGHT_BASE_MISSION=""

  ensure_notify_daemon() {
    echo "called" >> "$ensure_calls"
  }
  append_wave_ledger() {
    :
  }

  source "$wave_loop_setup_lib"
  source "$wave_loop_state_lib"
  source "$wave_loop_lib"
  run run_wave_loop

  [ "$status" -eq 0 ]
  [ "$(wc -l < "$ensure_calls")" -eq 1 ]
  [[ "$output" == *"No actionable Task Master task found. Stopping."* ]]
}

# Scenario: Taskmaster prints non-empty scheduler text without an id and the
# JSON fallback also has no ready work.
# Expected: This is treated as a clean no-work stop, not as an infrastructure
# failure, while preserving the raw scheduler text in logs for diagnosis.
@test "run_wave_loop treats unparseable taskmaster next output as clean no-work stop" {
  local wave_loop_lib wave_loop_setup_lib wave_loop_state_lib ledger_args stub_bin
  wave_loop_lib="$ROOT_DIR/lib/wave_loop.sh"
  wave_loop_setup_lib="$ROOT_DIR/lib/wave_loop_setup.sh"
  wave_loop_state_lib="$ROOT_DIR/lib/wave_loop_state.sh"
  ledger_args="$TMPDIR_BATS/ledger-args"
  stub_bin="$TMPDIR_BATS/bin"
  if [ ! -f "$wave_loop_lib" ]; then
    skip "required helper missing: $wave_loop_lib"
  fi

  mkdir -p "$stub_bin"
  cat > "$stub_bin/task-master" <<'SH'
#!/bin/sh
case "$1" in
  next)
    printf 'No ready tasks. All candidate tasks are blocked or in review.\n'
    ;;
esac
SH
  chmod +x "$stub_bin/task-master"
  PATH="$stub_bin:$PATH"

  ROOT_DIR="$TMPDIR_BATS/root"
  mkdir -p "$ROOT_DIR"
  MODE=taskmaster
  TOPOLOGY=solo
  ENGINE=codex
  REVIEW_ENGINE=codex
  MODEL_OVERRIDE=""
  REVIEW_MODEL_OVERRIDE=""
  CODEX_REASONING_EFFORT=xhigh
  RUN_ONCE=true
  PRD_PATH=""
  IDLE_WAVES=0
  MAX_IDLE_WAVES=1
  TASKMASTER_BASE_MISSION=""
  NIGHT_BASE_MISSION=""

  ensure_notify_daemon() {
    :
  }
  fallback_taskmaster_next() {
    :
  }
  append_wave_ledger() {
    printf 'lane=%s verdict=%s reason=%s blocked=%s next=%s\n' \
      "$6" "${13}" "${14}" "${16}" "${17}" >> "$ledger_args"
  }

  source "$wave_loop_setup_lib"
  source "$wave_loop_state_lib"
  source "$wave_loop_lib"
  run run_wave_loop

  [ "$status" -eq 0 ]
  grep -q "lane=scheduler verdict=STOP reason=routing:no_actionable_task blocked=taskmaster_next_unparseable_no_ready" "$ledger_args"
  [[ "$output" == *"Could not parse task id from task-master next output"* ]]
  [[ "$output" == *"No ready tasks. All candidate tasks are blocked or in review."* ]]
  grep -q "Could not parse task id from task-master next output" "$LOG_DIR/latest-taskmaster.log"
  grep -q "No ready tasks. All candidate tasks are blocked or in review." "$LOG_DIR/latest-taskmaster-summary.log"
}

# Scenario: The solo wave loop stops after the idle threshold.
# Expected: It writes an explicit scheduler-stop ledger row so Telegram can
# notify the operator that the loop stopped.
@test "run_wave_loop records idle-threshold stop notification event" {
  local wave_loop_lib wave_loop_setup_lib wave_loop_state_lib ledger_args stub_bin
  wave_loop_lib="$ROOT_DIR/lib/wave_loop.sh"
  wave_loop_setup_lib="$ROOT_DIR/lib/wave_loop_setup.sh"
  wave_loop_state_lib="$ROOT_DIR/lib/wave_loop_state.sh"
  ledger_args="$TMPDIR_BATS/ledger-args"
  stub_bin="$TMPDIR_BATS/bin"
  if [ ! -f "$wave_loop_lib" ]; then
    skip "required helper missing: $wave_loop_lib"
  fi

  mkdir -p "$stub_bin" "$LOG_DIR"
  cat > "$stub_bin/task-master" <<'SH'
#!/bin/sh
case "$1" in
  next)
    printf 'Next task: #42\n'
    ;;
  show)
    printf 'Task details for %s\n' "$2"
    ;;
  set-status)
    exit 0
    ;;
esac
SH
  chmod +x "$stub_bin/task-master"
  PATH="$stub_bin:$PATH"

  ROOT_DIR="$TMPDIR_BATS/root"
  mkdir -p "$ROOT_DIR"
  MODE=taskmaster
  TOPOLOGY=solo
  ENGINE=codex
  REVIEW_ENGINE=codex
  MODEL_OVERRIDE=""
  REVIEW_MODEL_OVERRIDE=""
  CODEX_REASONING_EFFORT=xhigh
  RUN_ONCE=false
  PRD_PATH=""
  IDLE_WAVES=0
  MAX_IDLE_WAVES=1
  TASKMASTER_BASE_MISSION="base mission"
  NIGHT_BASE_MISSION=""

  ensure_notify_daemon() {
    :
  }
  fallback_taskmaster_next() {
    :
  }
  pick_taskmaster_work_item() {
    echo "42"
  }
  taskmaster_status_for_id() {
    echo "review"
  }
  count_wave_progress_files() {
    echo 0
  }
  print_wave_progress_files() {
    :
  }
  print_wave_scope_files() {
    :
  }
  append_wave_summary() {
    :
  }
  hash_file_sha256() {
    echo "prompt-sha"
  }
  git_status_short() {
    :
  }
  agent_mode_allows_no_product_change() {
    return 1
  }
  count_product_file_changes() {
    echo 0
  }
  run_ai_turn() {
    printf 'writer output\n' > "$4"
    return 0
  }
  append_wave_ledger() {
    printf 'wave=%s lane=%s verdict=%s reason=%s blocked=%s next=%s\n' \
      "$1" "$6" "${13}" "${14}" "${16}" "${17}" >> "$ledger_args"
  }

  source "$wave_loop_setup_lib"
  source "$wave_loop_state_lib"
  source "$wave_loop_lib"
  run run_wave_loop

  [ "$status" -eq 0 ]
  grep -q "lane=idle verdict=IDLE reason=engine:no_file_changes" "$ledger_args"
  grep -q "lane=scheduler-stop verdict=STOP reason=routing:idle_threshold blocked=idle_threshold" "$ledger_args"
  grep -q "Loop stopped after 1 consecutive idle waves" "$ledger_args"
  [[ "$output" == *"Stopping loop after 1 consecutive idle waves."* ]]
}

# Scenario: Reviewer transport fails during a solo wave.
# Expected: The wave ledger next action tells the operator to restore the reviewer gate.
@test "run_wave_loop records reviewer-unreachable next action" {
  local wave_loop_lib wave_loop_setup_lib wave_loop_state_lib write_scope_lib ledger_args status_calls writer_calls stub_bin
  wave_loop_lib="$ROOT_DIR/lib/wave_loop.sh"
  wave_loop_setup_lib="$ROOT_DIR/lib/wave_loop_setup.sh"
  wave_loop_state_lib="$ROOT_DIR/lib/wave_loop_state.sh"
  write_scope_lib="$ROOT_DIR/lib/write_scope.sh"
  ledger_args="$TMPDIR_BATS/ledger-args"
  status_calls="$TMPDIR_BATS/status-calls"
  writer_calls="$TMPDIR_BATS/writer-calls"
  stub_bin="$TMPDIR_BATS/bin"
  if [ ! -f "$wave_loop_lib" ]; then
    skip "required helper missing: $wave_loop_lib"
  fi
  if [ ! -f "$write_scope_lib" ]; then
    skip "required helper missing: $write_scope_lib"
  fi

  mkdir -p "$stub_bin" "$LOG_DIR"
  cat > "$stub_bin/task-master" <<'SH'
#!/bin/sh
case "$1" in
  next)
    printf 'Next task: #42\n'
    ;;
  show)
    printf 'Task details for %s\n' "$2"
    ;;
  set-status)
    printf '%s\n' "$*" >> "${STATUS_CALLS:?}"
    exit 0
    ;;
esac
SH
  chmod +x "$stub_bin/task-master"
  PATH="$stub_bin:$PATH"
  export STATUS_CALLS="$status_calls"

  ROOT_DIR="$TMPDIR_BATS/root"
  mkdir -p "$ROOT_DIR"
  MODE=taskmaster
  TOPOLOGY=solo
  ENGINE=codex
  REVIEW_ENGINE=claude
  MODEL_OVERRIDE=""
  REVIEW_MODEL_OVERRIDE=""
  CODEX_REASONING_EFFORT=xhigh
  RUN_ONCE=true
  PRD_PATH=""
  IDLE_WAVES=0
  MAX_IDLE_WAVES=1
  TASKMASTER_BASE_MISSION="base mission"
  NIGHT_BASE_MISSION=""

  ensure_notify_daemon() {
    :
  }
  fallback_taskmaster_next() {
    :
  }
  pick_taskmaster_work_item() {
    echo "42.1"
  }
  taskmaster_status_for_id() {
    echo "review"
  }
  count_wave_progress_files() {
    echo 1
  }
  print_wave_progress_files() {
    echo "lib/wave_loop.sh"
  }
  append_wave_summary() {
    :
  }
  hash_file_sha256() {
    echo "prompt-sha"
  }
  git_status_short() {
    :
  }
  run_ai_turn() {
    echo "writer" >> "$writer_calls"
    printf 'writer output\n' > "$4"
    return 0
  }
  apply_review_gate() {
    REVIEW_GATE_FAILURE_REASON="review:reviewer_unreachable"
    return 1
  }
  append_wave_ledger() {
    printf 'failure=%s\nnext=%s\n' "${14}" "${17}" > "$ledger_args"
  }

  source "$write_scope_lib"
  source "$wave_loop_setup_lib"
  source "$wave_loop_state_lib"
  source "$wave_loop_lib"
  run run_wave_loop

  [ "$status" -eq 0 ]
  grep -q "failure=review:reviewer_unreachable" "$ledger_args"
  grep -q "next=Restore the reviewer engine and rerun the review gate" "$ledger_args"
  [ "$(wc -l < "$writer_calls")" -eq 1 ]
  if grep -q -- "--status=done" "$status_calls"; then
    false
  fi
  grep -q -- "--status=review" "$status_calls"
  [[ "$output" == *"Skipping writer retry; the reviewer gate must be restored first."* ]]
}

# Scenario: A normal reviewer FAIL triggers the one-shot writer retry, then the
# retry's reviewer transport fails.
# Expected: The final wave ledger records reviewer_unreachable and the
# reviewer-restoration next action, so Telegram alerts do not hide the outage
# behind the original gate failure.
@test "run_wave_loop records reviewer-unreachable when retry review transport fails" {
  local wave_loop_lib wave_loop_setup_lib wave_loop_state_lib write_scope_lib ledger_args status_calls writer_calls stub_bin review_calls
  wave_loop_lib="$ROOT_DIR/lib/wave_loop.sh"
  wave_loop_setup_lib="$ROOT_DIR/lib/wave_loop_setup.sh"
  wave_loop_state_lib="$ROOT_DIR/lib/wave_loop_state.sh"
  write_scope_lib="$ROOT_DIR/lib/write_scope.sh"
  ledger_args="$TMPDIR_BATS/ledger-args"
  status_calls="$TMPDIR_BATS/status-calls"
  writer_calls="$TMPDIR_BATS/writer-calls"
  review_calls="$TMPDIR_BATS/review-calls"
  stub_bin="$TMPDIR_BATS/bin"
  if [ ! -f "$wave_loop_lib" ]; then
    skip "required helper missing: $wave_loop_lib"
  fi
  if [ ! -f "$write_scope_lib" ]; then
    skip "required helper missing: $write_scope_lib"
  fi

  mkdir -p "$stub_bin" "$LOG_DIR"
  touch "$review_calls"
  cat > "$stub_bin/task-master" <<'SH'
#!/bin/sh
case "$1" in
  next)
    printf 'Next task: #42\n'
    ;;
  show)
    printf 'Task details for %s\n' "$2"
    ;;
  set-status)
    printf '%s\n' "$*" >> "${STATUS_CALLS:?}"
    exit 0
    ;;
esac
SH
  chmod +x "$stub_bin/task-master"
  PATH="$stub_bin:$PATH"
  export STATUS_CALLS="$status_calls"

  ROOT_DIR="$TMPDIR_BATS/root"
  mkdir -p "$ROOT_DIR"
  MODE=taskmaster
  TOPOLOGY=solo
  ENGINE=codex
  REVIEW_ENGINE=claude
  MODEL_OVERRIDE=""
  REVIEW_MODEL_OVERRIDE=""
  CODEX_REASONING_EFFORT=xhigh
  RUN_ONCE=true
  PRD_PATH=""
  IDLE_WAVES=0
  MAX_IDLE_WAVES=1
  TASKMASTER_BASE_MISSION="base mission"
  NIGHT_BASE_MISSION=""

  ensure_notify_daemon() {
    :
  }
  fallback_taskmaster_next() {
    :
  }
  pick_taskmaster_work_item() {
    echo "42.1"
  }
  taskmaster_status_for_id() {
    echo "review"
  }
  count_wave_progress_files() {
    echo 1
  }
  print_wave_progress_files() {
    echo "lib/wave_loop.sh"
  }
  print_wave_scope_files() {
    echo "lib/wave_loop.sh"
  }
  append_wave_summary() {
    :
  }
  hash_file_sha256() {
    echo "prompt-sha"
  }
  git_status_short() {
    :
  }
  run_ai_turn() {
    echo "writer" >> "$writer_calls"
    printf 'writer output\n' > "$4"
    return 0
  }
  extract_review_field() {
    case "$2" in
      NEXT_ACTIONS) echo "Retry with focused reviewer feedback" ;;
      GAPS) echo "Retry gap" ;;
      REQUIRED_CHANGES) echo "Retry required change" ;;
      FILES_TO_TOUCH) echo "lib/wave_loop.sh" ;;
      TESTS_TO_RUN) echo "bash tests/bats/run.sh" ;;
      PASS_BAR) echo "retry review passes" ;;
    esac
  }
  apply_review_gate() {
    local call_count review_file
    call_count="$(wc -l < "$review_calls" | tr -d '[:space:]')"
    printf 'call\n' >> "$review_calls"
    if [ "$call_count" -eq 0 ]; then
      review_file="$LOG_DIR/taskmaster-review-20260430-wave1.log"
      cat > "$review_file" <<'REVIEW'
REVIEW_VERDICT: FAIL
GAPS: Retry gap
NEXT_ACTIONS: Retry with focused reviewer feedback
FILES_TO_TOUCH: lib/wave_loop.sh
REQUIRED_CHANGES: Retry required change
TESTS_TO_RUN: bash tests/bats/run.sh
PASS_BAR: retry review passes
REVIEW
      REVIEW_GATE_FAILURE_REASON="review:gate_failed"
      return 1
    fi
    REVIEW_GATE_FAILURE_REASON="review:reviewer_unreachable"
    return 1
  }
  append_wave_ledger() {
    printf 'failure=%s\nnext=%s\n' "${14}" "${17}" >> "$ledger_args"
  }

  source "$write_scope_lib"
  source "$wave_loop_setup_lib"
  source "$wave_loop_state_lib"
  source "$wave_loop_lib"
  run run_wave_loop

  [ "$status" -eq 0 ]
  grep -q "failure=review:reviewer_unreachable" "$ledger_args"
  grep -q "next=Restore the reviewer engine and rerun the review gate" "$ledger_args"
  [ "$(wc -l < "$writer_calls")" -eq 2 ]
  [ "$(wc -l < "$review_calls")" -eq 2 ]
  [[ "$output" == *"Reviewer was unreachable during retry review"* ]]
}

# Scenario: _notify_state_dir creates the state directory.
# Expected: directory exists.
@test "_notify_state_dir creates state directory" {
  _load_notify
  local state_dir
  state_dir="$(_notify_state_dir)"
  [ -d "$state_dir" ]
}

# Scenario: _notify_log_file returns expected path.
# Expected: path ends with notifier.log.
@test "_notify_log_file returns correct path" {
  _load_notify
  local log_file
  log_file="$(_notify_log_file)"
  [[ "$log_file" == *"/notifier.log" ]]
}

# Scenario: help text includes the canonical Telegram test command.
# Expected: short and full help show the human-facing command without exposing
# old flag spellings as an equal public path.
@test "help text includes canonical notify-test command" {
  source "$ROOT_DIR/lib/help.sh"
  run print_help
  [[ "$output" == *"mainspring notify-test"* ]]

  run print_help_full
  [[ "$output" == *"notify-test"* ]]
  [[ "$output" != *"notify-test / --notify-test"* ]]
}

# Scenario: operator health is requested while notifications are disabled.
# Expected: wrapper reports disabled status without calling Telegram.
@test "run_notify_health reports disabled notifier state" {
  _load_notify
  unset MAINSPRING_NOTIFY_ENABLED

  run run_notify_health --format json
  [ "$status" -eq 0 ]
  [[ "$output" == *'"status": "disabled"'* ]]
  [[ "$output" == *'"next_step": "enable-notifications"'* ]]
}

# Scenario: operator health receives an unsupported output format.
# Expected: wrapper fails before invoking the Python health probe.
@test "run_notify_health rejects bad output format" {
  _load_notify

  run run_notify_health --format yaml
  [ "$status" -eq 2 ]
  [[ "$output" == *"--format must be text or json"* ]]
}

# Scenario: operator health receives --format with no value.
# Expected: wrapper fails cleanly instead of tripping a shell shift error.
@test "run_notify_health rejects missing output format value" {
  _load_notify

  run run_notify_health --format
  [ "$status" -eq 2 ]
  [[ "$output" == *"--format requires a value"* ]]
}

# Scenario: notifications are enabled/configured but the stale threshold env is invalid.
# Expected: direct operator health returns structured config_error JSON.
@test "run_notify_health reports invalid stale threshold as config error" {
  _load_notify
  MAINSPRING_NOTIFY_ENABLED=1
  MAINSPRING_TELEGRAM_BOT_TOKEN="test-token"
  MAINSPRING_TELEGRAM_CHAT_ID="123456"
  MAINSPRING_NOTIFY_STALE_SECONDS="soon"

  run run_notify_health --format json
  [ "$status" -eq 2 ]
  [[ "$output" == *'"status":"config_error"'* ]]
  [[ "$output" == *'"reason":"invalid_stale_seconds"'* ]]
  [[ "$output" == *'"next_step":"fix-notify-stale-threshold"'* ]]
}

# Scenario: notifications are disabled and the stale threshold env is invalid.
# Expected: disabled setup truth wins because the threshold is irrelevant.
@test "run_notify_health ignores invalid stale threshold when disabled" {
  _load_notify
  unset MAINSPRING_NOTIFY_ENABLED
  MAINSPRING_NOTIFY_STALE_SECONDS="soon"

  run run_notify_health --format json
  [ "$status" -eq 0 ]
  [[ "$output" == *'"status": "disabled"'* ]]
  [[ "$output" == *'"next_step": "enable-notifications"'* ]]
}

# Scenario: help text includes notify-health.
# Expected: help output contains the command.
@test "help text includes notify-health" {
  source "$ROOT_DIR/lib/help.sh"
  run print_help
  [[ "$output" == *"notify-health"* ]]
}

# Scenario: help text includes notify-restart.
# Expected: help output contains the command.
@test "help text includes notify-restart" {
  source "$ROOT_DIR/lib/help.sh"
  run print_help
  [[ "$output" == *"notify-restart"* ]]
}

# Scenario: help text includes MAINSPRING_NOTIFY_ENABLED env var.
# Expected: help output mentions the env var.
@test "help text includes MAINSPRING_NOTIFY_ENABLED" {
  source "$ROOT_DIR/lib/help.sh"
  run print_help
  [[ "$output" == *"MAINSPRING_NOTIFY_ENABLED"* ]]
}

# Scenario: help text includes MAINSPRING_TELEGRAM_BOT_TOKEN.
# Expected: help output mentions the env var.
@test "help text includes MAINSPRING_TELEGRAM_BOT_TOKEN" {
  source "$ROOT_DIR/lib/help.sh"
  run print_help
  [[ "$output" == *"MAINSPRING_TELEGRAM_BOT_TOKEN"* ]]
}
