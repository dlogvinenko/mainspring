#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring wizard — interactive setup, pair mode, presets, settings persistence
# Globals read/written: MODE, ENGINE, REVIEW_ENGINE, MODEL_OVERRIDE,
#   REVIEW_MODEL_OVERRIDE, PAIR_MODE, SPEED_PROFILE, MAX_AGENTS, TOPOLOGY,
#   RUN_ONCE, PRD_PATH, CODEX_REASONING_EFFORT, AUTO_RETRY_CI, AUTO_CHECKPOINT,
#   AUTO_RETRY_CI_LOG, DEFAULT_CODEX_MODEL, DEFAULT_FAST_CODEX_MODEL, DEFAULT_CLAUDE_MODEL,
#   LAST_RUN_FILE, ROOT_DIR, MAINSPRING_PY_DIR, SCRIPT_DIR, RUNTIME_DIR,
#   STATE_DIR, LOG_DIR
# Depends on: usage.sh (print_usage_snapshot)

print_wizard_noninteractive_guidance() {
  echo "Mainspring needs an interactive terminal or piped answers for the guided setup." >&2
  echo "Pipe wizard answers, reopen an interactive terminal, or run one of these explicit commands:" >&2
  echo "  mainspring last-run          inspect saved setup, if any" >&2
  echo "  mainspring --last-run        resume saved setup, if any" >&2
  echo "  mainspring --dry-run --once  preview default setup with zero API calls" >&2
  echo "  mainspring init checkout-redesign  scaffold PRD-backed starter docs" >&2
  echo "    replace checkout-redesign with your feature name" >&2
}

prime_wizard_stdin() {
  local queue_file
  [ -t 0 ] && return 0
  [ "${MAINSPRING_WIZARD_STDIN_PRIMED:-false}" = true ] && return 0

  queue_file="$(mktemp "${TMPDIR:-/tmp}/mainspring-wizard-answers.XXXXXX")" || queue_file="${TMPDIR:-/tmp}/mainspring-wizard-answers.$$"
  cat > "$queue_file"
  if [ -s "$queue_file" ]; then
    MAINSPRING_WIZARD_ANSWER_QUEUE="$queue_file"
    MAINSPRING_WIZARD_STDIN_PRIMED=true
    return 0
  fi

  rm -f "$queue_file"
  print_wizard_noninteractive_guidance
  exit 2
}

read_queued_wizard_answer() {
  local queue_file="${MAINSPRING_WIZARD_ANSWER_QUEUE:-}"
  local next_queue
  [ -n "$queue_file" ] || return 1
  [ -f "$queue_file" ] || return 1
  [ -s "$queue_file" ] || return 1

  IFS= read -r choice < "$queue_file" || choice=""
  next_queue="${queue_file}.next"
  tail -n +2 "$queue_file" > "$next_queue" || true
  mv "$next_queue" "$queue_file"
  return 0
}

prompt_choice() {
  local prompt="$1"
  shift
  local options=("$@")
  local i=1
  local choice=""
  echo "$prompt" >&2
  for opt in "${options[@]}"; do
    echo "  $i) $opt" >&2
    i=$((i+1))
  done
  while true; do
    printf "> " >&2
    if read_queued_wizard_answer; then
      :
    elif [ -n "${MAINSPRING_WIZARD_ANSWER_QUEUE:-}" ]; then
      echo "" >&2
      print_wizard_noninteractive_guidance
      rm -f "$MAINSPRING_WIZARD_ANSWER_QUEUE"
      exit 2
    elif ! read -r choice; then
      echo "" >&2
      print_wizard_noninteractive_guidance
      exit 2
    fi
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#options[@]}" ]; then
      echo "$choice"
      return
    fi
    echo "Enter a number between 1 and ${#options[@]}." >&2
  done
}

_load_config_file() {
  local source_file="$1"
  local loaded
  if ! loaded="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/last_run.py" load "$source_file" 2>&1)"; then
    echo "$loaded" >&2
    exit 1
  fi
  while IFS=$'\t' read -r key value; do
    case "$key" in
      MODE)
        [ "${USER_SET_MODE:-false}" = true ] || MODE="$value"
        ;;
      PAIR_MODE)
        [ "${USER_SET_PAIR_MODE:-false}" = true ] || PAIR_MODE="$value"
        ;;
      ENGINE)
        [ "${USER_SET_ENGINE:-false}" = true ] || ENGINE="$value"
        ;;
      MODEL_OVERRIDE)
        [ "${USER_SET_MODEL_OVERRIDE:-false}" = true ] || MODEL_OVERRIDE="$value"
        ;;
      REVIEW_ENGINE)
        [ "${USER_SET_REVIEW_ENGINE:-false}" = true ] || REVIEW_ENGINE="$value"
        ;;
      REVIEW_MODEL_OVERRIDE)
        [ "${USER_SET_REVIEW_MODEL_OVERRIDE:-false}" = true ] || REVIEW_MODEL_OVERRIDE="$value"
        ;;
      CODEX_REASONING_EFFORT)
        [ "${USER_SET_CODEX_REASONING_EFFORT:-false}" = true ] || CODEX_REASONING_EFFORT="$value"
        ;;
      SPEED_PROFILE)
        [ "${USER_SET_SPEED_PROFILE:-false}" = true ] || SPEED_PROFILE="$value"
        ;;
      MAX_AGENTS)
        [ "${USER_SET_MAX_AGENTS:-false}" = true ] || MAX_AGENTS="$value"
        ;;
      AUTO_RETRY_CI)
        [ "${USER_SET_AUTO_RETRY_CI:-false}" = true ] || AUTO_RETRY_CI="$value"
        ;;
      AUTO_RETRY_CI_LOG)
        [ "${USER_SET_AUTO_RETRY_CI_LOG:-false}" = true ] || AUTO_RETRY_CI_LOG="$value"
        ;;
      TOPOLOGY)
        [ "${USER_SET_TOPOLOGY:-false}" = true ] || TOPOLOGY="$value"
        ;;
      RUN_ONCE)
        [ "${USER_SET_RUN_ONCE:-false}" = true ] || RUN_ONCE="$value"
        ;;
      AGENT_MODE)
        [ "${USER_SET_AGENT_MODE:-false}" = true ] || AGENT_MODE="$value"
        ;;
      PRD_PATH)
        [ "${USER_SET_PRD_PATH:-false}" = true ] || PRD_PATH="$value"
        ;;
      AUTO_CHECKPOINT)
        [ "${USER_SET_AUTO_CHECKPOINT:-false}" = true ] || AUTO_CHECKPOINT="$value"
        ;;
    esac
  done <<< "$loaded"
}

load_mainspring_yaml() {
  local config_file="$1"
  [ -f "$config_file" ] || return 0
  _load_config_file "$config_file"
}

apply_pair_mode() {
  local pair="$1"
  local writer reviewer
  writer="${pair%%+*}"
  reviewer="${pair#*+}"
  if [ -z "$writer" ] || [ -z "$reviewer" ] || [ "$writer" = "$pair" ] || [[ "$reviewer" == *"+"* ]]; then
    echo "Unknown pair mode: $pair"
    exit 1
  fi
  if ! "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py" validate --engine "$writer" --role writer >/dev/null; then
    echo "Unknown pair mode: $pair"
    exit 1
  fi
  if ! "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py" validate --engine "$reviewer" --role reviewer >/dev/null; then
    echo "Unknown pair mode: $pair"
    exit 1
  fi
  [ "${USER_SET_ENGINE:-false}" = true ] || ENGINE="$writer"
  [ "${USER_SET_REVIEW_ENGINE:-false}" = true ] || REVIEW_ENGINE="$reviewer"
}

load_last_run_settings() {
  if [ ! -f "$LAST_RUN_FILE" ]; then
    echo "No last-run settings found at $LAST_RUN_FILE"
    exit 1
  fi
  _load_config_file "$LAST_RUN_FILE"
}

# shellcheck disable=SC2120
show_last_run_settings() {
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/last_run.py" show "$LAST_RUN_FILE" --project "$ROOT_DIR" "$@"
}

offer_last_run_resume() {
  [ "${WIZARD_ALLOW_LAST_RUN_OFFER:-false}" = true ] || return 1
  [ -n "${LAST_RUN_FILE:-}" ] || return 1
  [ -f "$LAST_RUN_FILE" ] || return 1

  echo "Saved setup found for this project:"
  if ! show_last_run_settings; then
    echo ""
    echo "Saved setup could not be read; continuing with manual setup." >&2
    echo ""
    return 1
  fi
  echo ""

  local resume_choice
  resume_choice="$(prompt_choice 'Use saved setup?' 'Continue with saved setup' 'Choose setup manually')"
  if [ "$resume_choice" = "1" ]; then
    load_last_run_settings
    echo ""
    echo "Continuing with saved setup."
    echo 'Run `mainspring --last-run --dry-run` to preview this path without API calls.'
    echo ""
    return 0
  fi

  echo ""
  return 1
}

save_last_run_settings() {
  MODE="$MODE" \
  PAIR_MODE="$PAIR_MODE" \
  ENGINE="$ENGINE" \
  MODEL_OVERRIDE="$MODEL_OVERRIDE" \
  REVIEW_ENGINE="$REVIEW_ENGINE" \
  REVIEW_MODEL_OVERRIDE="$REVIEW_MODEL_OVERRIDE" \
  CODEX_REASONING_EFFORT="$CODEX_REASONING_EFFORT" \
  SPEED_PROFILE="$SPEED_PROFILE" \
  MAX_AGENTS="$MAX_AGENTS" \
  AUTO_RETRY_CI="$AUTO_RETRY_CI" \
  AUTO_RETRY_CI_LOG="$AUTO_RETRY_CI_LOG" \
  AGENT_MODE="$AGENT_MODE" \
  TOPOLOGY="$TOPOLOGY" \
  RUN_ONCE="$RUN_ONCE" \
  PRD_PATH="$PRD_PATH" \
  AUTO_CHECKPOINT="$AUTO_CHECKPOINT" \
    "$(mainspring_python)" "$MAINSPRING_PY_DIR/last_run.py" save > "$LAST_RUN_FILE"
}

apply_default_models_for_current_pair() {
  if [ -z "$MODEL_OVERRIDE" ]; then
    MODEL_OVERRIDE="$(engine_default_model "$ENGINE")"
  fi

  if [ -z "$REVIEW_MODEL_OVERRIDE" ]; then
    REVIEW_MODEL_OVERRIDE="$(engine_default_model "$REVIEW_ENGINE")"
  fi
}

engine_default_model() {
  local engine="$1"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py" default-model "$engine"
}

require_engine_ready() {
  local engine="$1"
  local role="$2"
  local model="${3:-}"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py" validate \
    --engine "$engine" \
    --role "$role" \
    --model "$model" \
    --require-execution \
    --require-executable
}

disabled_pairs_state_dir() {
  if [ -n "${MAINSPRING_STATE_DIR:-}" ]; then
    echo "$MAINSPRING_STATE_DIR"
    return 0
  fi
  if [ -n "${LOG_DIR:-}" ]; then
    echo "$(dirname "$LOG_DIR")/state"
    return 0
  fi
  echo "${STATE_DIR:-$ROOT_DIR/.mainspring/state}"
}

list_disabled_pair_modes() {
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/metrics.py" disabled-pairs "$(disabled_pairs_state_dir)" 2>/dev/null || true
}

pair_mode_is_disabled() {
  local pair="$1"
  local disabled
  while IFS= read -r disabled; do
    [ "$disabled" = "$pair" ] && return 0
  done < <(list_disabled_pair_modes)
  return 1
}

run_wizard() {
  prime_wizard_stdin

  echo "=== Mainspring Wizard ==="
  echo ""

  if offer_last_run_resume; then
    return 0
  fi

  print_usage_snapshot

  local mode_choice
  mode_choice="$(prompt_choice 'Choose execution source:' 'Taskmaster backlog' 'PRD-driven night mode')"
  if [ "$mode_choice" = "1" ]; then
    MODE="taskmaster"
  else
    MODE="night"
  fi
  echo ""

  local pair_choice pair_index
  local pair_modes=()
  local pair_labels=()
  local disabled_pairs
  disabled_pairs="$(list_disabled_pair_modes | tr '\n' ' ')"
  if [ -n "${disabled_pairs// /}" ]; then
    echo "Auto-disabled pairs hidden from defaults: $disabled_pairs" >&2
  fi
  if ! pair_mode_is_disabled "claude+codex"; then
    pair_modes+=("claude+codex")
    pair_labels+=("Claude(${DEFAULT_CLAUDE_MODEL}) + Codex(${DEFAULT_CODEX_MODEL}) (Default / Recommended)")
  fi
  if ! pair_mode_is_disabled "codex+codex"; then
    pair_modes+=("codex+codex")
    pair_labels+=("Codex(${DEFAULT_CODEX_MODEL}) + Codex(${DEFAULT_CODEX_MODEL})")
  fi
  if ! pair_mode_is_disabled "claude+claude"; then
    pair_modes+=("claude+claude")
    pair_labels+=("Claude(${DEFAULT_CLAUDE_MODEL}) + Claude(${DEFAULT_CLAUDE_MODEL})")
  fi
  if ! pair_mode_is_disabled "codex+claude"; then
    pair_modes+=("codex+claude")
    pair_labels+=("Codex(${DEFAULT_CODEX_MODEL}) + Claude(${DEFAULT_CLAUDE_MODEL})")
  fi
  if [ "${#pair_modes[@]}" -eq 0 ]; then
    echo "All saved pairs are disabled; showing all pairs for manual override." >&2
    pair_modes=("claude+codex" "codex+codex" "claude+claude" "codex+claude")
    pair_labels=(
      "Claude(${DEFAULT_CLAUDE_MODEL}) + Codex(${DEFAULT_CODEX_MODEL}) (Default / Recommended)"
      "Codex(${DEFAULT_CODEX_MODEL}) + Codex(${DEFAULT_CODEX_MODEL})"
      "Claude(${DEFAULT_CLAUDE_MODEL}) + Claude(${DEFAULT_CLAUDE_MODEL})"
      "Codex(${DEFAULT_CODEX_MODEL}) + Claude(${DEFAULT_CLAUDE_MODEL})"
    )
  elif [ -n "${disabled_pairs// /}" ]; then
    pair_modes+=("manual")
    pair_labels+=("Manual pair override (reactivate or test a disabled pair)")
  fi

  pair_choice="$(prompt_choice 'Choose writer+reviewer pair:' "${pair_labels[@]}")"
  pair_index=$((pair_choice - 1))
  if [ "${pair_modes[$pair_index]}" = "manual" ]; then
    printf "Pair mode (<writer>+<reviewer>, e.g. claude+codex or gemini+claude)> " >&2
    read -r PAIR_MODE
  else
    PAIR_MODE="${pair_modes[$pair_index]}"
  fi
  apply_pair_mode "$PAIR_MODE"
  echo ""

  local model_choice engine_default
  engine_default="$(engine_default_model "$ENGINE")"
  if [ "$ENGINE" = "codex" ]; then
    model_choice="$(prompt_choice 'Choose Codex model:' "${DEFAULT_CODEX_MODEL} (Default)" 'gpt-5.4-mini' "$DEFAULT_FAST_CODEX_MODEL" 'Custom')"
    case "$model_choice" in
      1) MODEL_OVERRIDE="$DEFAULT_CODEX_MODEL" ;;
      2) MODEL_OVERRIDE="gpt-5.4-mini" ;;
      3) MODEL_OVERRIDE="$DEFAULT_FAST_CODEX_MODEL" ;;
      4)
        printf "Custom Codex model> "
        read -r MODEL_OVERRIDE
        ;;
    esac
  elif [ "$ENGINE" = "claude" ]; then
    model_choice="$(prompt_choice 'Choose Claude Code model:' "${DEFAULT_CLAUDE_MODEL} (Default)" 'sonnet' 'Custom')"
    case "$model_choice" in
      1) MODEL_OVERRIDE="$DEFAULT_CLAUDE_MODEL" ;;
      2) MODEL_OVERRIDE="sonnet" ;;
      3)
        printf "Custom Claude model> "
        read -r MODEL_OVERRIDE
        ;;
    esac
  else
    model_choice="$(prompt_choice "Choose ${ENGINE} model:" "${engine_default:-default} (Default)" 'Custom')"
    case "$model_choice" in
      1) MODEL_OVERRIDE="$engine_default" ;;
      2)
        printf "Custom ${ENGINE} model> "
        read -r MODEL_OVERRIDE
        ;;
    esac
  fi
  echo ""

  local review_model_choice review_engine_default
  review_engine_default="$(engine_default_model "$REVIEW_ENGINE")"
  if [ "$REVIEW_ENGINE" = "codex" ]; then
    review_model_choice="$(prompt_choice 'Choose reviewer Codex model:' "${DEFAULT_CODEX_MODEL} (Default)" 'gpt-5.4-mini' "$DEFAULT_FAST_CODEX_MODEL" 'Custom')"
    case "$review_model_choice" in
      1) REVIEW_MODEL_OVERRIDE="$DEFAULT_CODEX_MODEL" ;;
      2) REVIEW_MODEL_OVERRIDE="gpt-5.4-mini" ;;
      3) REVIEW_MODEL_OVERRIDE="$DEFAULT_FAST_CODEX_MODEL" ;;
      4)
        printf "Custom reviewer Codex model> "
        read -r REVIEW_MODEL_OVERRIDE
        ;;
    esac
  elif [ "$REVIEW_ENGINE" = "claude" ]; then
    review_model_choice="$(prompt_choice 'Choose reviewer Claude model:' "${DEFAULT_CLAUDE_MODEL} (Default)" 'sonnet' 'Custom')"
    case "$review_model_choice" in
      1) REVIEW_MODEL_OVERRIDE="$DEFAULT_CLAUDE_MODEL" ;;
      2) REVIEW_MODEL_OVERRIDE="sonnet" ;;
      3)
        printf "Custom reviewer Claude model> "
        read -r REVIEW_MODEL_OVERRIDE
        ;;
    esac
  else
    review_model_choice="$(prompt_choice "Choose reviewer ${REVIEW_ENGINE} model:" "${review_engine_default:-default} (Default)" 'Custom')"
    case "$review_model_choice" in
      1) REVIEW_MODEL_OVERRIDE="$review_engine_default" ;;
      2)
        printf "Custom reviewer ${REVIEW_ENGINE} model> "
        read -r REVIEW_MODEL_OVERRIDE
        ;;
    esac
  fi
  echo ""

  local agent_mode_choice
  agent_mode_choice="$(prompt_choice 'Choose writer role mode:' 'code (implementation default)' 'debug (root-cause repair)' 'architect (advisory, no edits)' 'ask (answer/research, no edits)')"
  case "$agent_mode_choice" in
    1) AGENT_MODE="code" ;;
    2) AGENT_MODE="debug" ;;
    3) AGENT_MODE="architect" ;;
    4) AGENT_MODE="ask" ;;
  esac
  echo ""

  local speed_choice
  speed_choice="$(prompt_choice 'Choose speed profile:' 'standard' 'fast' 'max (Recommended for throughput)')"
  case "$speed_choice" in
    1) SPEED_PROFILE="standard" ;;
    2) SPEED_PROFILE="fast" ;;
    3) SPEED_PROFILE="max" ;;
  esac
  echo ""

  local agent_choice
  agent_choice="$(prompt_choice 'Choose max agent count:' '2' '4' '6 (Max)')"
  case "$agent_choice" in
    1) MAX_AGENTS="2" ;;
    2) MAX_AGENTS="4" ;;
    3) MAX_AGENTS="6" ;;
  esac
  echo ""

  local topology_choice
  topology_choice="$(prompt_choice 'Choose execution topology:' 'Solo writer + reviewer loop (Recommended first run)' 'Team parallel workers (requires team backend + tmux)')"
  case "$topology_choice" in
    1) TOPOLOGY="solo" ;;
    2) TOPOLOGY="team" ;;
  esac
  echo ""

  local style_choice
  style_choice="$(prompt_choice 'Choose run style:' 'AFK loop (keep going)' 'One by one (single wave / --once)')"
  if [ "$style_choice" = "2" ]; then
    RUN_ONCE=true
  else
    RUN_ONCE=false
  fi
  echo ""

  if [ "$MODE" = "night" ]; then
    local default_prd=""
    if [ -f "$ROOT_DIR/docs/prd.md" ]; then
      default_prd="$ROOT_DIR/docs/prd.md"
    elif [ -f "$ROOT_DIR/PRD.md" ]; then
      default_prd="$ROOT_DIR/PRD.md"
    fi
    if [ -n "$default_prd" ]; then
      echo "PRD default found:"
      echo "  $default_prd"
      printf "Use this PRD? [Y/n/custom path] "
      read -r prd_reply
      case "${prd_reply:-Y}" in
        n|N)
          printf "PRD path> "
          read -r PRD_PATH
          ;;
        /*|./*|../*)
          PRD_PATH="$prd_reply"
          ;;
        *)
          PRD_PATH="$default_prd"
          ;;
      esac
    else
      printf "PRD path> "
      read -r PRD_PATH
    fi
    echo ""
  fi

  echo "Selection:"
  echo "  Mode:   $MODE"
  echo "  Pair:   ${PAIR_MODE:-$ENGINE+$REVIEW_ENGINE}"
  echo "  Engine: $ENGINE"
  echo "  Model:  ${MODEL_OVERRIDE:-default}"
  echo "  Review: ${REVIEW_ENGINE:-auto-opposite} (${REVIEW_MODEL_OVERRIDE:-default})"
  echo "  Speed:  $SPEED_PROFILE"
  echo "  Agents: $MAX_AGENTS"
  echo "  Writer mode: ${AGENT_MODE:-code}"
  echo "  Topology: $TOPOLOGY"
  echo "  Run:    $([ "$RUN_ONCE" = true ] && echo 'one-shot' || echo 'continuous loop')"
  [ "$MODE" = "night" ] && echo "  PRD:    $PRD_PATH"
  echo ""
}

# ---------------------------------------------------------------------------
# Presets — load/list env-file presets from the packaged presets/ directory.
# ---------------------------------------------------------------------------

list_presets() {
  local presets_dir="$SCRIPT_DIR/presets"
  echo "=== Available Presets ==="
  echo ""
  if [ ! -d "$presets_dir" ] || [ -z "$(ls -A "$presets_dir"/*.env 2>/dev/null)" ]; then echo "  (no presets found in $presets_dir)"; return 0; fi
  local f name desc
  for f in "$presets_dir"/*.env; do
    name="$(basename "$f" .env)"
    desc="$(sed -n 's/^# *//p' "$f" | head -1)"
    printf "  %-24s %s\n" "$name" "${desc:-(no description)}"
  done
  echo ""
  echo "Use: mainspring --preset <name> [flags]"
}

load_preset() {
  local name="$1"
  local presets_dir="$SCRIPT_DIR/presets"
  local preset_file="$presets_dir/${name}.env"
  case "$name" in
    ""|*/*|*\\*|*".."*|*[!A-Za-z0-9._-]*)
      echo "Invalid preset name: $name" >&2; echo "Use: mainspring --list-presets" >&2; exit 2 ;;
  esac
  if [ ! -f "$preset_file" ]; then
    echo "Preset not found: $name" >&2
    echo "Available presets:" >&2
    if [ -d "$presets_dir" ]; then
      for f in "$presets_dir"/*.env; do
        [ -f "$f" ] && echo "  $(basename "$f" .env)" >&2
      done
    fi
    exit 1
  fi
  echo "Loading preset: $name ($preset_file)"
  _load_config_file "$preset_file"
}

print_engine_command_preview() {
  local engine="$1"
  local role="$2"
  local model="$3"
  local prompt_label="$4"
  local preview
  if preview="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py" command \
      --engine "$engine" \
      --role "$role" \
      --prompt "$prompt_label" \
      --model "$model" \
      --reasoning-effort "$CODEX_REASONING_EFFORT" \
      --format text 2>&1)"; then
    echo "  $preview"
  else
    echo "  unavailable: $preview"
  fi
}

print_engine_dependency_check() {
  local engine="$1"
  local role="$2"
  local label="$3"
  local model="${4:-}"
  local result
  if result="$(require_engine_ready "$engine" "$role" "$model" 2>&1)"; then
    echo "  $label: ready"
    return 0
  fi
  echo "  $label: NOT READY"
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    echo "    - $line"
  done <<< "$result"
  return 1
}
