#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring Telegram notification daemon management
# Globals read: MAINSPRING_PY_DIR, LOG_DIR, STATE_DIR, WAVE_LEDGER_FILE
# Globals written: NOTIFY_DAEMON_PID

# State dir for notification daemon
_notify_state_dir() {
  local state_dir
  state_dir="${STATE_DIR:-$(dirname "$LOG_DIR")/state}"
  mkdir -p "$state_dir"
  echo "$state_dir"
}

# PID file for the notification daemon
_notify_pid_file() {
  echo "$(_notify_state_dir)/notifier.pid"
}

# Log file for the notification daemon
_notify_log_file() {
  echo "$LOG_DIR/notifier.log"
}

_notify_stale_seconds() {
  echo "${MAINSPRING_NOTIFY_STALE_SECONDS:-3600}"
}

_notify_drain_seconds() {
  echo "${MAINSPRING_NOTIFY_DRAIN_SECONDS:-8}"
}

_notify_health_is_stale() {
  local health_output="$1"
  local status
  status="$(printf '%s' "$health_output" | "$(mainspring_python)" "$MAINSPRING_PY_DIR/team_status.py" --field status 2>/dev/null || true)"
  [ "$status" = "stale" ]
}

_notify_pid_command() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null || true
}

_notify_pid_is_notifier() {
  local pid="$1"
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac

  local command_line
  command_line="$(_notify_pid_command "$pid")"
  case "$command_line" in
    *notify_telegram.py*) ;;
    *) return 1 ;;
  esac

  # A notifier from another project also runs notify_telegram.py. Treat it as
  # foreign unless its command line includes this runtime's ledger path.
  case "$command_line" in
    *"$WAVE_LEDGER_FILE"*) return 0 ;;
    *) return 1 ;;
  esac
}

_notify_stale_seconds_is_valid() {
  local value="$1"
  case "$value" in
    ''|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

_notify_json_escape() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value//$'\n'/\\n}"
  value="${value//$'\r'/\\r}"
  value="${value//$'\t'/\\t}"
  printf '%s' "$value"
}

_notify_health_config_error() {
  local output_format="$1"
  local invalid_value="$2"
  local message="Set MAINSPRING_NOTIFY_STALE_SECONDS to a non-negative integer number of seconds, or unset it to use the default."
  local escaped_invalid escaped_message
  escaped_invalid="$(_notify_json_escape "$invalid_value")"
  escaped_message="$(_notify_json_escape "$message")"
  case "$output_format" in
    json)
      printf '{"configured":true,"enabled":true,"invalid_stale_seconds":"%s","last_line_count":null,"ledger_lines":null,"next_step":"fix-notify-stale-threshold","next_step_message":"%s","pending_lines":null,"reason":"invalid_stale_seconds","stale_seconds":null,"status":"config_error"}\n' "$escaped_invalid" "$escaped_message"
      ;;
    *)
      printf 'notify: health status=config_error reason=invalid_stale_seconds pending=none ledger_lines=none last_line_count=none next_step=fix-notify-stale-threshold next_step_message=%s\n' "$message"
      ;;
  esac
}

# Check if notification daemon is enabled via env
notify_enabled() {
  local enabled
  enabled="${MAINSPRING_NOTIFY_ENABLED:-0}"
  case "$enabled" in
    1|[Tt][Rr][Uu][Ee]|[Yy][Ee][Ss]|[Oo][Nn]) return 0 ;;
    *) return 1 ;;
  esac
}

# Check if notification env vars are configured
notify_configured() {
  local token chat_id
  token="${MAINSPRING_TELEGRAM_BOT_TOKEN:-}"
  chat_id="${MAINSPRING_TELEGRAM_CHAT_ID:-}"
  [ -n "$token" ] && [ -n "$chat_id" ]
}

# Start the notification daemon in the background.
# Daemon failure never blocks a wave — errors go to notifier.log.
start_notify_daemon() {
  if ! notify_enabled; then
    return 0
  fi
  if ! notify_configured; then
    echo "notify: enabled but MAINSPRING_TELEGRAM_BOT_TOKEN / MAINSPRING_TELEGRAM_CHAT_ID not set" >&2
    return 0
  fi

  local pid_file log_file state_dir
  pid_file="$(_notify_pid_file)"
  log_file="$(_notify_log_file)"
  state_dir="$(_notify_state_dir)"

  # Check if already running
  if [ -f "$pid_file" ]; then
    local existing_pid
    existing_pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ -n "$existing_pid" ] && kill -0 "$existing_pid" 2>/dev/null; then
      if ! _notify_pid_is_notifier "$existing_pid"; then
        echo "notify: foreign pid file removed ($existing_pid)" >&2
        rm -f "$pid_file"
      else
        local health_output health_status stale_seconds
        stale_seconds="$(_notify_stale_seconds)"
        health_output="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/notify_telegram.py" health "$WAVE_LEDGER_FILE" \
          --state-dir "$state_dir" \
          --log-file "$log_file" \
          --pid-file "$pid_file" \
          --stale-seconds "$stale_seconds" \
          --format json 2>&1)"
        health_status=$?
        if [ "$health_status" -eq 2 ] && _notify_health_is_stale "$health_output"; then
          echo "notify: daemon stale; restarting pid $existing_pid ($health_output)" >&2
          kill "$existing_pid" 2>/dev/null || true
          rm -f "$pid_file"
        else
          if [ "$health_status" -ne 0 ]; then
            echo "notify: health check failed; keeping existing daemon ($health_output)" >&2
          fi
          return 0  # already running
        fi
      fi
    else
      echo "notify: stale pid file removed (${existing_pid:-empty})" >&2
      rm -f "$pid_file"
    fi
  fi

  mkdir -p "$LOG_DIR"
  local -a daemon_cmd
  daemon_cmd=("$(mainspring_python)" "$MAINSPRING_PY_DIR/notify_telegram.py" watch "$WAVE_LEDGER_FILE" --state-dir "$state_dir")
  if command -v nohup >/dev/null 2>&1; then
    nohup "$(mainspring_python)" "$MAINSPRING_PY_DIR/detach_exec.py" \
      "${daemon_cmd[@]}" </dev/null >> "$log_file" 2>&1 &
  else
    "$(mainspring_python)" "$MAINSPRING_PY_DIR/detach_exec.py" \
      "${daemon_cmd[@]}" </dev/null >> "$log_file" 2>&1 &
  fi
  local daemon_pid=$!
  echo "$daemon_pid" > "$pid_file"
  # shellcheck disable=SC2034
  NOTIFY_DAEMON_PID="$daemon_pid"
  echo "notify: daemon started (pid $daemon_pid)" >&2
}

ensure_notify_daemon() {
  start_notify_daemon
}

# Stop the notification daemon if running.
stop_notify_daemon() {
  local pid_file
  pid_file="$(_notify_pid_file)"
  if [ ! -f "$pid_file" ]; then
    return 0
  fi
  local daemon_pid
  daemon_pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -n "$daemon_pid" ] && kill -0 "$daemon_pid" 2>/dev/null; then
    if _notify_pid_is_notifier "$daemon_pid"; then
      kill "$daemon_pid" 2>/dev/null || true
      wait "$daemon_pid" 2>/dev/null || true
      echo "notify: daemon stopped (pid $daemon_pid)" >&2
    else
      echo "notify: foreign pid file removed ($daemon_pid)" >&2
    fi
  fi
  rm -f "$pid_file"
  # shellcheck disable=SC2034
  NOTIFY_DAEMON_PID=""
}

# Reap the notifier daemon only if this process launched it.
reap_notify_daemon() {
  local daemon_pid pid_file recorded_pid
  daemon_pid="${NOTIFY_DAEMON_PID:-}"
  if [ -z "$daemon_pid" ]; then
    return 0
  fi

  wait_notify_daemon_drain "$daemon_pid"
  kill "$daemon_pid" 2>/dev/null || true
  wait "$daemon_pid" 2>/dev/null || true

  pid_file="$(_notify_pid_file)"
  if [ -f "$pid_file" ]; then
    recorded_pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [ "$recorded_pid" = "$daemon_pid" ]; then
      rm -f "$pid_file"
    fi
  fi
  # shellcheck disable=SC2034
  NOTIFY_DAEMON_PID=""
}

wait_notify_daemon_drain() {
  local daemon_pid="$1"
  if ! notify_enabled || ! notify_configured; then
    return 0
  fi
  if [ -z "$daemon_pid" ] || ! kill -0 "$daemon_pid" 2>/dev/null; then
    return 0
  fi

  local drain_seconds stale_seconds started now health_output pending_lines
  drain_seconds="$(_notify_drain_seconds)"
  case "$drain_seconds" in
    ''|*[!0-9]*) drain_seconds=8 ;;
  esac
  stale_seconds="$(_notify_stale_seconds)"
  if ! _notify_stale_seconds_is_valid "$stale_seconds"; then
    stale_seconds=3600
  fi

  started="$(date +%s)"
  while :; do
    health_output="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/notify_telegram.py" health "$WAVE_LEDGER_FILE" \
      --state-dir "$(_notify_state_dir)" \
      --log-file "$(_notify_log_file)" \
      --pid-file "$(_notify_pid_file)" \
      --stale-seconds "$stale_seconds" \
      --format json 2>/dev/null || true)"
    pending_lines="$(printf '%s' "$health_output" | "$(mainspring_python)" "$MAINSPRING_PY_DIR/team_status.py" --field pending-lines 2>/dev/null || true)"
    if [ "${pending_lines:-0}" = "0" ]; then
      return 0
    fi

    now="$(date +%s)"
    if [ $((now - started)) -ge "$drain_seconds" ]; then
      echo "notify: daemon still has ${pending_lines:-unknown} pending ledger line(s); stopping after ${drain_seconds}s drain wait" >&2
      return 0
    fi
    sleep 1
  done
}

# Send a test notification (for --notify-test flag).
run_notify_test() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --help|-h)
        echo "Usage: mainspring notify-test"
        echo ""
        echo "Send one Telegram test message using the current project context."
        echo "Requires MAINSPRING_TELEGRAM_BOT_TOKEN and MAINSPRING_TELEGRAM_CHAT_ID."
        return 0
        ;;
      *)
        echo "notify: unknown notify-test flag: $1" >&2
        return 2
        ;;
    esac
  done

  if ! notify_configured; then
    echo "notify: MAINSPRING_TELEGRAM_BOT_TOKEN and MAINSPRING_TELEGRAM_CHAT_ID required" >&2
    return 1
  fi
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/notify_telegram.py" test
}

run_notify_restart() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --help|-h)
        echo "Usage: mainspring notify-restart"
        echo ""
        echo "Restart only the recorded Telegram notifier daemon for this project."
        echo "Validates notifier.pid before stopping anything, ignores unrelated PIDs,"
        echo "and leaves the replacement watcher running."
        echo ""
        echo "Typical recovery:"
        echo "  mainspring notify-health --format json"
        echo "  mainspring notify-restart"
        echo "  mainspring notify-test"
        return 0
        ;;
      *)
        echo "notify: unknown notify-restart flag: $1" >&2
        return 2
        ;;
    esac
  done

  if ! notify_enabled; then
    echo "notify: notifications disabled; set MAINSPRING_NOTIFY_ENABLED=1 first" >&2
    return 1
  fi
  if ! notify_configured; then
    echo "notify: MAINSPRING_TELEGRAM_BOT_TOKEN and MAINSPRING_TELEGRAM_CHAT_ID required" >&2
    return 1
  fi

  stop_notify_daemon
  start_notify_daemon
  # notify-restart is an operator command that should leave the replacement
  # daemon running after this CLI process exits. Wave-loop auto-starts keep the
  # PID owned so the exit trap can drain and reap them.
  # shellcheck disable=SC2034
  NOTIFY_DAEMON_PID=""
}

# Print an operator-facing notification health snapshot. This does not start
# or stop the daemon and does not call the Telegram API.
run_notify_health() {
  local output_format="text"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --format)
        if [ "$#" -lt 2 ]; then
          echo "notify: --format requires a value" >&2
          return 2
        fi
        output_format="${2:-}"
        shift 2
        ;;
      --json)
        output_format="json"
        shift
        ;;
      --help|-h)
        echo "Usage: mainspring notify-health [--format text|json]"
        echo ""
        echo "Inspect Telegram notifier health without starting/stopping it or calling Telegram."
        echo "Checks enabled/configured state, notifier.pid, notifier.log, pending ledger"
        echo "lines, and the stale threshold."
        echo ""
        echo "Statuses:"
        echo "  disabled       notifications are off"
        echo "  unconfigured   bot token or chat id is missing"
        echo "  starting       daemon is warming up"
        echo "  healthy        caught up; no action needed"
        echo "  stale          restart the notifier before trusting alerts"
        echo "  config_error   fix notification env/config"
        echo ""
        echo "JSON output includes next_step and next_step_message for agents."
        echo "Recovery:"
        echo "  mainspring notify-health --format json"
        echo "  mainspring notify-restart"
        echo "  mainspring notify-test"
        return 0
        ;;
      *)
        echo "notify: unknown notify-health flag: $1" >&2
        return 2
        ;;
    esac
  done
  case "$output_format" in
    text|json) ;;
    *)
      echo "notify: --format must be text or json" >&2
      return 2
      ;;
  esac

  local stale_seconds
  stale_seconds="$(_notify_stale_seconds)"
  if notify_enabled && notify_configured && ! _notify_stale_seconds_is_valid "$stale_seconds"; then
    _notify_health_config_error "$output_format" "$stale_seconds"
    return 2
  fi
  if ! _notify_stale_seconds_is_valid "$stale_seconds"; then
    stale_seconds="3600"
  fi

  "$(mainspring_python)" "$MAINSPRING_PY_DIR/notify_telegram.py" operator-health "$WAVE_LEDGER_FILE" \
    --state-dir "$(_notify_state_dir)" \
    --log-file "$(_notify_log_file)" \
    --pid-file "$(_notify_pid_file)" \
    --stale-seconds "$stale_seconds" \
    --format "$output_format"
}
