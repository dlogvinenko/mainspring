#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring post-parse dispatch and run preflight.
# shellcheck disable=SC2034

run_mainspring() {
  # ---------------------------------------------------------------------------
  # Post-parse setup: wizard, pair mode, subcommand dispatch
  # ---------------------------------------------------------------------------
  # ---------------------------------------------------------------------------
  # --list-presets exits immediately (no lock, no wizard)
  # ---------------------------------------------------------------------------
  if [ "$LIST_PRESETS" = true ]; then
    list_presets
    exit 0
  fi

  # ---------------------------------------------------------------------------
  # --preset loads a preset env file before other resolution
  # ---------------------------------------------------------------------------
  if [ -n "$PRESET" ]; then
    load_preset "$PRESET"
  fi

  load_mainspring_yaml "$CONFIG_FILE"

  if [ "$ORIGINAL_ARGC" -eq 0 ]; then
    WIZARD=true
    WIZARD_ALLOW_LAST_RUN_OFFER=true
  fi

  if [ "$LAST_RUN_INFO" = true ]; then
    local last_run_info_arg_count=0
    if declare -p LAST_RUN_INFO_ARGS >/dev/null 2>&1; then
      set +u
      last_run_info_arg_count="${#LAST_RUN_INFO_ARGS[@]}"
      set -u
    fi
    if [ "$last_run_info_arg_count" -gt 0 ]; then
      show_last_run_settings "${LAST_RUN_INFO_ARGS[@]}"
    else
      show_last_run_settings
    fi
    exit $?
  fi

  if [ "$LAST_RUN" = true ]; then
    load_last_run_settings
    echo "=== Reusing last run settings ==="
    echo "  Mode:   $MODE"
    echo "  Pair:   ${PAIR_MODE:-$ENGINE+$REVIEW_ENGINE}"
    echo "  Writer: $ENGINE (${MODEL_OVERRIDE:-default})"
    echo "  Review: $REVIEW_ENGINE (${REVIEW_MODEL_OVERRIDE:-default})"
    echo "  Speed:  ${SPEED_PROFILE:-max}"
    echo "  Agents: ${MAX_AGENTS:-6}"
    echo "  Writer mode: ${AGENT_MODE:-code}"
    echo "  CI retry: ${AUTO_RETRY_CI:-0}"
    echo "  CI log: ${AUTO_RETRY_CI_LOG:-none}"
    echo "  Topology: ${TOPOLOGY:-solo}"
    echo "  Run:    $([ "$RUN_ONCE" = true ] && echo 'one-shot' || echo 'continuous loop')"
    [ "$MODE" = "night" ] && echo "  PRD:    $PRD_PATH"
    echo ""
    WIZARD=false
  fi

  if [ "$WIZARD" = true ]; then
    run_wizard
  fi

  if [ -n "$PAIR_MODE" ]; then
    apply_pair_mode "$PAIR_MODE"
  fi

  apply_default_models_for_current_pair

  case "$TOPOLOGY" in
    team|solo) ;;
    *)
      echo "Unknown topology: $TOPOLOGY"
      exit 1
      ;;
  esac

  if ! [[ "$AUTO_RETRY_CI" =~ ^[0-9]+$ ]]; then
    echo "Invalid --auto-retry-ci value: $AUTO_RETRY_CI (expected non-negative integer)"
    exit 1
  fi

  if ! agent_mode_is_valid "$AGENT_MODE"; then
    echo "Invalid --mode value: $AGENT_MODE (expected architect, code, debug, or ask)"
    exit 1
  fi

  if [ -n "${AUTO_RETRY_CI_LOG// }" ]; then
    if [ ! -f "$AUTO_RETRY_CI_LOG" ] || [ ! -r "$AUTO_RETRY_CI_LOG" ]; then
      echo "Invalid --auto-retry-ci-log path: $AUTO_RETRY_CI_LOG (expected readable file)"
      exit 1
    fi
  fi

  if [ "$METRICS" != true ]; then
    if [ -n "${METRICS_DAYS:-}" ]; then
      echo "--days requires --metrics"
      exit 2
    fi
    if [ "$METRICS_ROUTING" = true ]; then
      echo "--routing requires --metrics"
      exit 2
    fi
    if [ -n "${METRICS_FORMAT:-}" ]; then
      echo "--format requires a command that accepts --format"
      exit 2
    fi
  fi

  if [ "$METRICS" != true ] && [ -n "${METRICS_SINCE:-}" ]; then
    echo "--since requires --metrics"
    exit 2
  fi

  if [ "$MODE" = "night" ] && [ "$TOPOLOGY" = "team" ]; then
    echo "Team topology is currently taskmaster-only. Falling back to solo topology for night mode."
    TOPOLOGY="solo"
  fi

  # ---------------------------------------------------------------------------
  # Subcommand dispatch (non-loop commands exit here)
  # ---------------------------------------------------------------------------

  # Standalone --dry-run: print resolved settings and would-execute commands, no API calls.
  if [ "$DRY_RUN" = true ] && [ "$REPAIR_STATE" = false ]; then
    run_dry_run
    exit 0
  fi

  if [ "$NOTIFY_TEST" = true ]; then
    if [ "${#NOTIFY_TEST_ARGS[@]}" -gt 0 ]; then
      run_notify_test "${NOTIFY_TEST_ARGS[@]}"
    else
      run_notify_test
    fi
    exit $?
  fi

  if [ "$NOTIFY_HEALTH" = true ]; then
    if [ "${#NOTIFY_HEALTH_ARGS[@]}" -gt 0 ]; then
      run_notify_health "${NOTIFY_HEALTH_ARGS[@]}"
    else
      run_notify_health
    fi
    exit $?
  fi

  if [ "$NOTIFY_RESTART" = true ]; then
    if [ "${#NOTIFY_RESTART_ARGS[@]}" -gt 0 ]; then
      run_notify_restart "${NOTIFY_RESTART_ARGS[@]}"
    else
      run_notify_restart
    fi
    exit $?
  fi

  if [ "$METRICS" = true ]; then
    metrics_args=("$WAVE_LEDGER_FILE")
    [ -n "$METRICS_DAYS" ] && metrics_args+=(--days "$METRICS_DAYS")
    [ -n "$METRICS_SINCE" ] && metrics_args+=(--since "$METRICS_SINCE")
    [ -n "$PAIR_MODE" ] && metrics_args+=(--pair "$PAIR_MODE")
    [ "$METRICS_ROUTING" = true ] && metrics_args+=(--routing)
    if [ "$METRICS_ROUTING" = true ] && [ -z "$METRICS_DAYS" ] && [ -z "$METRICS_SINCE" ]; then
      metrics_args+=(--days "14")
    fi
    [ -n "$METRICS_FORMAT" ] && metrics_args+=(--format "$METRICS_FORMAT")
    "$(mainspring_python)" "$MAINSPRING_PY_DIR/metrics.py" "${metrics_args[@]}"
    exit $?
  fi

  if [ "$HUD" = true ]; then
    local hud_scope="global"
    local hud_custom_paths=false
    local hud_auto_live=false
    local hud_arg_count=0
    local hud_arg
    if declare -p HUD_ARGS >/dev/null 2>&1; then
      set +u
      hud_arg_count="${#HUD_ARGS[@]}"
      set -u
    fi
    if [ "$hud_arg_count" -eq 0 ]; then
      hud_auto_live=true
    fi
    if [ "$hud_arg_count" -gt 0 ]; then
      for hud_arg in "${HUD_ARGS[@]}"; do
        case "$hud_arg" in
          --global) hud_scope="global" ;;
          --local) hud_scope="local" ;;
          --ledger|--state-dir) hud_custom_paths=true ;;
        esac
      done
    fi
    if [ "$hud_scope" = "global" ] && [ "$hud_custom_paths" = false ]; then
      if [ "$hud_auto_live" = true ]; then
        "$(mainspring_python)" "$MAINSPRING_PY_DIR/hud.py" --global --auto-live --ledger "$WAVE_LEDGER_FILE" --state-dir "$STATE_DIR"
      else
        "$(mainspring_python)" "$MAINSPRING_PY_DIR/hud.py" --global --ledger "$WAVE_LEDGER_FILE" --state-dir "$STATE_DIR" "${HUD_ARGS[@]}"
      fi
    else
      if [ "$hud_arg_count" -gt 0 ]; then
        "$(mainspring_python)" "$MAINSPRING_PY_DIR/hud.py" --ledger "$WAVE_LEDGER_FILE" --state-dir "$STATE_DIR" "${HUD_ARGS[@]}"
      else
        "$(mainspring_python)" "$MAINSPRING_PY_DIR/hud.py" --ledger "$WAVE_LEDGER_FILE" --state-dir "$STATE_DIR"
      fi
    fi
    exit $?
  fi

  if [ "$ENGINES" = true ]; then
    if [ "${#ENGINES_ARGS[@]}" -gt 0 ]; then
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py" "${ENGINES_ARGS[@]}"
    else
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py"
    fi
    exit $?
  fi

  if [ "$REPLAY" = true ]; then
    if [ "${#REPLAY_ARGS[@]}" -gt 0 ]; then
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/replay.py" "${REPLAY_ARGS[@]}"
    else
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/replay.py"
    fi
    exit $?
  fi

  if [ "$VALIDATE_PRD" = true ]; then
    if [ "${#VALIDATE_PRD_ARGS[@]}" -gt 0 ]; then
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/prd_validate.py" "${VALIDATE_PRD_ARGS[@]}"
    else
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/prd_validate.py"
    fi
    exit $?
  fi

  if [ "$LIMITS" = true ]; then
    if [ "${#LIMITS_ARGS[@]}" -gt 0 ]; then
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/limits.py" --ledger "$WAVE_LEDGER_FILE" "${LIMITS_ARGS[@]}"
    else
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/limits.py" --ledger "$WAVE_LEDGER_FILE"
    fi
    exit $?
  fi

  if [ "$METHOD_INIT" = true ]; then
    if [ "${#METHOD_INIT_ARGS[@]}" -gt 0 ]; then
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/method_init.py" "${METHOD_INIT_ARGS[@]}"
    else
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/method_init.py"
    fi
    exit $?
  fi

  if [ "$METHOD_DECOMPOSE" = true ]; then
    if [ "${#METHOD_DECOMPOSE_ARGS[@]}" -gt 0 ]; then
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/decompose.py" "${METHOD_DECOMPOSE_ARGS[@]}"
    else
      "$(mainspring_python)" "$MAINSPRING_PY_DIR/decompose.py"
    fi
    exit $?
  fi

  if [ "$SCOPE_CHECK" = true ]; then
    if [ "${#SCOPE_CHECK_ARGS[@]}" -eq 0 ]; then
      SCOPE_CHECK_ARGS=("$ROOT_DIR/.taskmaster/tasks/tasks.json")
    fi
    "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" scope-check "${SCOPE_CHECK_ARGS[@]}"
    exit $?
  fi

  if [ "$METHOD_NEXT" = true ]; then
    if [ "${#METHOD_NEXT_ARGS[@]}" -eq 0 ]; then
      METHOD_NEXT_ARGS=("$ROOT_DIR/.taskmaster/tasks/tasks.json")
    fi
    if [[ " ${METHOD_NEXT_ARGS[*]} " != *" --active-prd "* ]]; then
      METHOD_NEXT_ARGS+=("--active-prd" "$STATE_DIR/active-prd.json")
    fi
    "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" next "${METHOD_NEXT_ARGS[@]}"
    exit $?
  fi

  if [ "$DOCTOR" = true ]; then
    if [ "${#DOCTOR_ARGS[@]}" -gt 0 ]; then
      run_doctor "${DOCTOR_ARGS[@]}"
    else
      run_doctor
    fi
    exit $?
  fi

  if [ "$STATUS" = true ]; then
    if [ "${#STATUS_ARGS[@]}" -gt 0 ]; then
      run_status_report "${STATUS_ARGS[@]}"
    else
      run_status_report
    fi
    exit $?
  fi

  if [ "$REPAIR_STATE" = true ]; then
    repair_state "$DRY_RUN" "$FORCE_REPAIR"
    exit $?
  fi

  if [ "$STOP_PROCESSES" = true ]; then
    local stop_arg_count=0
    if declare -p STOP_ARGS >/dev/null 2>&1; then
      set +u
      stop_arg_count="${#STOP_ARGS[@]}"
      set -u
    fi
    if [ "$stop_arg_count" -gt 0 ]; then
      stop_processes "${STOP_ARGS[@]}"
    else
      stop_processes
    fi
    exit $?
  fi

  if [ "$RESTART_TEAM" = true ]; then
    restart_active_teams
  fi

  self_heal_runtime_state

  acquire_lock

  require_engine_ready "$ENGINE" "writer" "${MODEL_OVERRIDE:-$(engine_default_model "$ENGINE")}" || exit 1
  require_engine_ready "$REVIEW_ENGINE" "reviewer" "${REVIEW_MODEL_OVERRIDE:-$(engine_default_model "$REVIEW_ENGINE")}" || exit 1

  mkdir -p "$LOG_DIR"

  if [ "$SELF_TEST" = true ]; then
    run_self_test
    exit $?
  fi

  if [ "$SELF_TEST_ALL" = true ]; then
    run_all_self_tests
    exit $?
  fi

  save_last_run_settings

  if [ "$MODE" = "taskmaster" ]; then
    command -v task-master >/dev/null 2>&1 || { echo "task-master missing from PATH"; exit 1; }
    [ -d "$ROOT_DIR/.taskmaster" ] || { echo ".taskmaster directory not found in $ROOT_DIR"; exit 1; }
    if [ "$TOPOLOGY" = "team" ]; then
      command -v omx >/dev/null 2>&1 || { echo "team backend command missing from PATH"; exit 1; }
    fi
  fi

  if [ "$MODE" = "night" ]; then
    if [ -z "$PRD_PATH" ]; then
      if [ -f "$ROOT_DIR/docs/prd.md" ]; then
        PRD_PATH="$ROOT_DIR/docs/prd.md"
      elif [ -f "$ROOT_DIR/PRD.md" ]; then
        PRD_PATH="$ROOT_DIR/PRD.md"
      else
        echo "PRD file not found. Pass it explicitly with --prd <path>."
        exit 1
      fi
    fi
    [ -f "$PRD_PATH" ] || { echo "PRD file not found: $PRD_PATH"; exit 1; }
  fi

  export ENABLE_CLAUDEAI_MCP_SERVERS=false

  # ---------------------------------------------------------------------------
  # Auto-launch notification daemon (if MAINSPRING_NOTIFY_ENABLED=1)
  # ---------------------------------------------------------------------------
  start_notify_daemon

  # ---------------------------------------------------------------------------
  # Main wave loop
  # ---------------------------------------------------------------------------
  run_wave_loop
  exit $?
}
