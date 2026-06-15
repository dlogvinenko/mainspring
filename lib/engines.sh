#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring engine dispatcher — unified writer/reviewer entry point
# Globals read: ENGINE, REVIEW_ENGINE, MODEL_OVERRIDE, REVIEW_MODEL_OVERRIDE,
#   CODEX_REASONING_EFFORT, MAINSPRING_PY_DIR
# Globals written: ACTIVE_CHILD_PID, ACTIVE_HEARTBEAT_PID

spawn_registered_engine() {
  # Args: engine role prompt raw_file display_file model pid_file usage_file
  # Writes the backgrounded subshell PID into pid_file (NOT stdout). Stdout
  # from the subshell stays on the operator terminal so live output is
  # still visible during a manual run; using $() to capture the function
  # would also slurp the writer's stream and corrupt the PID.
  local engine="$1"
  local role="$2"
  local prompt="$3"
  local raw_file="$4"
  local display_file="$5"
  local model="$6"
  local pid_file="$7"
  local usage_file="$8"
  local prompt_file records_file display_mode record
  local -a records cmd
  prompt_file="$(mktemp)"
  records_file="$(mktemp)"
  printf '%s' "$prompt" > "$prompt_file"

  if ! "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py" command \
      --engine "$engine" \
      --role "$role" \
      --prompt-file "$prompt_file" \
      --model "$model" \
      --reasoning-effort "$CODEX_REASONING_EFFORT" \
      --format nul > "$records_file"; then
    rm -f "$prompt_file" "$records_file"
    return 2
  fi
  while IFS= read -r -d '' record; do
    records+=("$record")
  done < "$records_file"
  rm -f "$prompt_file" "$records_file"
  if [ "${#records[@]}" -lt 2 ]; then
    echo "engine registry returned no command for $engine" >&2
    return 2
  fi
  display_mode="${records[0]#display_mode=}"
  cmd=("${records[@]:1}")

  if [ "$display_mode" = "plain" ]; then
    (
      MAINSPRING_ENGINE_USAGE_FILE="$usage_file" "${cmd[@]}" | tee "$raw_file" | tee "$display_file"
    ) &
  elif [ "$display_mode" = "stream-json" ]; then
    (
      MAINSPRING_ENGINE_USAGE_FILE="$usage_file" "${cmd[@]}" \
        | tee "$raw_file" \
        | CLAUDE_DISPLAY_FILE="$display_file" "$(mainspring_python)" "$MAINSPRING_PY_DIR/stream_json_prettify.py" --mode "$role"
    ) &
  else
    echo "Unknown engine display mode for $engine: $display_mode" >&2
    return 2
  fi
  echo "$!" >"$pid_file"
}

run_with_heartbeat() {
  local child_pid="$1"
  local label="$2"
  local raw_file="$3"
  local log_file="$4"
  # shellcheck disable=SC2034
  ACTIVE_CHILD_PID="$child_pid"

  (
    while kill -0 "$child_pid" 2>/dev/null; do
      echo "[$label] working..."
      sleep 10
    done
  ) &
  local heartbeat_pid=$!
  # shellcheck disable=SC2034
  ACTIVE_HEARTBEAT_PID="$heartbeat_pid"

  local exit_status=0
  if wait "$child_pid"; then
    exit_status=0
  else
    exit_status=$?
  fi
  if [ "$exit_status" -eq 141 ]; then
    exit_status=0
  fi
  kill "$heartbeat_pid" >/dev/null 2>&1 || true
  wait "$heartbeat_pid" >/dev/null 2>&1 || true
  # shellcheck disable=SC2034
  ACTIVE_CHILD_PID=""
  # shellcheck disable=SC2034
  ACTIVE_HEARTBEAT_PID=""
  cat "$raw_file" >> "$log_file"
  rm -f "$raw_file"
  return "$exit_status"
}

run_ai_turn() {
  local role="$1"
  local prompt="$2"
  local log_file="$3"
  local display_file="$4"

  local engine model label
  if [ "$role" = "writer" ]; then
    engine="$ENGINE"
    model="${MODEL_OVERRIDE:-}"
    label="$engine"
  else
    engine="$REVIEW_ENGINE"
    model="${REVIEW_MODEL_OVERRIDE:-}"
    label="review-$engine"
  fi

  local raw_file pid_file child_pid
  local usage_file
  raw_file="$(mktemp)"
  pid_file="$(mktemp)"
  usage_file="$(mktemp)"

  if ! spawn_registered_engine "$engine" "$role" "$prompt" "$raw_file" "$display_file" "$model" "$pid_file" "$usage_file"; then
    rm -f "$raw_file" "$pid_file" "$usage_file"
    return 2
  fi
  child_pid="$(cat "$pid_file")"
  rm -f "$pid_file"

  local exit_status=0
  if run_with_heartbeat "$child_pid" "$label" "$raw_file" "$log_file"; then
    exit_status=0
  else
    exit_status=$?
  fi
  if [ -n "${MAINSPRING_WAVE_USAGE_FILE:-}" ] && [ -s "$usage_file" ]; then
    mkdir -p "$(dirname "$MAINSPRING_WAVE_USAGE_FILE")"
    cat "$usage_file" >> "$MAINSPRING_WAVE_USAGE_FILE"
  fi
  rm -f "$usage_file"
  return "$exit_status"
}
