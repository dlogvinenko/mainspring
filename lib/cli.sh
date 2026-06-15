#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring CLI argument parsing.
# shellcheck disable=SC2034

require_cli_value() {
  local flag="$1"
  local value="${2-}"
  local kind="${3:-value}"
  if [ $# -lt 2 ] || [ -z "$value" ] || [[ "$value" == --* ]]; then
    echo "$flag requires a $kind"
    echo "Run: mainspring --help"
    exit 2
  fi
}

parse_cli_args() {
  ORIGINAL_ARGC=$#
  while [ $# -gt 0 ]; do
    case "$1" in
      taskmaster|night)
        MODE="$1"
        USER_SET_MODE=true
        case "${2:-}" in
          --help|-h)
            if [ "$MODE" = "taskmaster" ]; then
              print_taskmaster_help
            else
              print_night_help
            fi
            exit 0
            ;;
        esac
        shift
        ;;
      --engine)
        require_cli_value "$1" "${2-}"
        ENGINE="${2:-}"
        USER_SET_ENGINE=true
        shift 2
        ;;
      --pair)
        require_cli_value "$1" "${2-}"
        PAIR_MODE="${2:-}"
        USER_SET_PAIR_MODE=true
        shift 2
        ;;
      --once)
        RUN_ONCE=true
        USER_SET_RUN_ONCE=true
        shift
        ;;
      --mode)
        require_cli_value "$1" "${2-}"
        AGENT_MODE="${2:-}"
        USER_SET_AGENT_MODE=true
        shift 2
        ;;
      --prd)
        require_cli_value "$1" "${2-}"
        PRD_PATH="${2:-}"
        USER_SET_PRD_PATH=true
        shift 2
        ;;
      --model)
        require_cli_value "$1" "${2-}"
        MODEL_OVERRIDE="${2:-}"
        USER_SET_MODEL_OVERRIDE=true
        shift 2
        ;;
      --review-engine)
        require_cli_value "$1" "${2-}"
        REVIEW_ENGINE="${2:-}"
        USER_SET_REVIEW_ENGINE=true
        shift 2
        ;;
      --review-model)
        require_cli_value "$1" "${2-}"
        REVIEW_MODEL_OVERRIDE="${2:-}"
        USER_SET_REVIEW_MODEL_OVERRIDE=true
        shift 2
        ;;
      --speed-profile)
        require_cli_value "$1" "${2-}"
        SPEED_PROFILE="${2:-}"
        USER_SET_SPEED_PROFILE=true
        shift 2
        ;;
      --max-agents)
        require_cli_value "$1" "${2-}"
        MAX_AGENTS="${2:-}"
        USER_SET_MAX_AGENTS=true
        shift 2
        ;;
      --auto-retry-ci)
        require_cli_value "$1" "${2-}"
        AUTO_RETRY_CI="${2:-}"
        USER_SET_AUTO_RETRY_CI=true
        shift 2
        ;;
      --auto-retry-ci-log)
        require_cli_value "$1" "${2-}"
        AUTO_RETRY_CI_LOG="${2:-}"
        USER_SET_AUTO_RETRY_CI_LOG=true
        shift 2
        ;;
      --retry-task)
        require_cli_value "$1" "${2-}"
        RETRY_TASK_IDS+=("${2:-}")
        shift 2
        ;;
      --topology)
        require_cli_value "$1" "${2-}"
        TOPOLOGY="${2:-}"
        USER_SET_TOPOLOGY=true
        shift 2
        ;;
      --wizard)
        WIZARD=true
        shift
        ;;
      --last-run)
        LAST_RUN=true
        shift
        ;;
      last-run)
        LAST_RUN_INFO=true
        shift
        LAST_RUN_INFO_ARGS=("$@")
        set --
        ;;
      --self-test)
        SELF_TEST=true
        shift
        ;;
      --self-test-all)
        SELF_TEST_ALL=true
        shift
        ;;
      doctor|--doctor)
        DOCTOR=true
        shift
        DOCTOR_ARGS=("$@")
        set --
        ;;
      status|--status)
        STATUS=true
        shift
        STATUS_ARGS=("$@")
        set --
        ;;
      --repair-state)
        REPAIR_STATE=true
        shift
        ;;
      stop)
        STOP_PROCESSES=true
        shift
        STOP_ARGS=("$@")
        set --
        ;;
      --dry-run)
        DRY_RUN=true
        shift
        ;;
      --force)
        FORCE_REPAIR=true
        shift
        ;;
      --restart-team)
        RESTART_TEAM=true
        shift
        ;;
      --metrics)
        METRICS=true
        shift
        ;;
      --routing)
        METRICS_ROUTING=true
        shift
        ;;
      --days)
        require_cli_value "$1" "${2-}"
        METRICS_DAYS="${2:-}"
        shift 2
        ;;
      --since)
        require_cli_value "$1" "${2-}"
        METRICS_SINCE="${2:-}"
        shift 2
        ;;
      --format)
        require_cli_value "$1" "${2-}"
        METRICS_FORMAT="${2:-text}"
        shift 2
        ;;
      --preset)
        require_cli_value "$1" "${2-}"
        PRESET="${2:-}"
        shift 2
        ;;
      --list-presets)
        LIST_PRESETS=true
        shift
        ;;
      notify-test|--notify-test)
        NOTIFY_TEST=true
        shift
        NOTIFY_TEST_ARGS=("$@")
        set --
        ;;
      notify-health)
        NOTIFY_HEALTH=true
        shift
        NOTIFY_HEALTH_ARGS=("$@")
        set --
        ;;
      notify-restart)
        NOTIFY_RESTART=true
        shift
        NOTIFY_RESTART_ARGS=("$@")
        set --
        ;;
      hud)
        HUD=true
        shift
        HUD_ARGS=("$@")
        set --
        ;;
      engines)
        ENGINES=true
        shift
        ENGINES_ARGS=("$@")
        set --
        ;;
      replay)
        REPLAY=true
        shift
        REPLAY_ARGS=("$@")
        set --
        ;;
      limits)
        LIMITS=true
        shift
        LIMITS_ARGS=("$@")
        set --
        ;;
      validate-prd)
        VALIDATE_PRD=true
        shift
        VALIDATE_PRD_ARGS=("$@")
        set --
        ;;
      init)
        METHOD_INIT=true
        shift
        METHOD_INIT_ARGS=("$@")
        set --
        ;;
      decompose)
        METHOD_DECOMPOSE=true
        shift
        METHOD_DECOMPOSE_ARGS=("$@")
        set --
        ;;
      scope-check)
        SCOPE_CHECK=true
        shift
        SCOPE_CHECK_ARGS=("$@")
        set --
        ;;
      next)
        METHOD_NEXT=true
        shift
        METHOD_NEXT_ARGS=("$@")
        set --
        ;;
      help)
        shift
        case "${1:-}" in
          --full|full)
            print_help_full
            exit 0
            ;;
          ""|--short|short)
            print_help
            exit 0
            ;;
          *)
            echo "Unknown help argument: $1"
            echo ""
            print_help
            exit 2
            ;;
        esac
        ;;
      --help|-h)
        print_help
        exit 0
        ;;
      --version)
        print_version
        exit 0
        ;;
      --project)
        # Consumed in mainspring.sh top-scope to set ROOT_DIR before libs load.
        require_cli_value "$1" "${2-}"
        shift 2
        ;;
      --project=*)
        # Consumed in mainspring.sh top-scope.
        if [ -z "${1#--project=}" ]; then
          echo "--project requires a value"
          echo "Run: mainspring --help"
          exit 2
        fi
        shift
        ;;
      *)
        if [[ "$1" == --* ]]; then
          echo "Unknown argument: $1"
        else
          echo "Unknown command: $1"
        fi
        echo "Run: mainspring --help"
        exit 1
        ;;
    esac
  done
}
