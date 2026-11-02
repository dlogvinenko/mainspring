#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# shellcheck disable=SC2034
# Mainspring autonomous loop
#
# Purpose
#   Run a PRD-first autonomous engineering loop using either:
#   1. Taskmaster as the task source (`taskmaster` mode)
#   2. A Product Requirements Document as the planning source (`night` mode)
#
# Operating model
#   - Wizard-first when launched with no args
#   - Separate writer engine and reviewer engine
#   - Separate autonomous lane and manual/prod/live lane
#   - Hard review gate before Taskmaster work can be considered done
#   - Idle-wave detection to stop wasting hours on non-progress
#
# Modes
#   taskmaster
#     Source of truth is Taskmaster. The worker asks Taskmaster for the next
#     actionable task, opens its details, implements it, verifies it, and is
#     expected to mark it done when complete.
#
#   night
#     Source of truth is a PRD. The worker reads a compact PRD brief, then
#     picks the next highest-value autonomous product slice. This is intended
#     for overnight or background product progress when you want execution to
#     continue without hand-feeding Taskmaster tasks.
#
# Engines
#   Built-in adapters include Claude CLI, Codex CLI, and LiteLLM-backed provider
#   routes such as Gemini, Grok, OpenAI, Anthropic, Azure, OpenRouter, Mistral,
#   Ollama, and generic OpenAI-compatible local servers.
#
# Defaults
#   mode   = taskmaster
#   pair   = claude+codex
#
# Public CLI contract
#   `mainspring --help` is the short operator surface.
#   `mainspring help --full` is the complete command and environment contract.
#   Keep this launcher focused on bootstrapping and dispatch; do not duplicate
#   long flag lists here, because stale comments mislead public users and agents.
#
# Behavior notes
#   - Logs are written to the resolved runtime dir (`.mainspring/logs/` for
#     fresh projects)
#   - `.mainspring.yaml` loads after presets and before execution; CLI flags win
#   - `--once` executes a single wave and exits
#   - in `night` mode, the script auto-detects `docs/prd.md` or `PRD.md` if
#     `--prd` is omitted
#   - cloud Claude MCP autoload is disabled to reduce unattended noise
#
# Examples
#   mainspring
#   mainspring hud
#   mainspring taskmaster --pair claude+codex --once
#   mainspring night --prd docs/prd.md --pair codex+claude --once
#   mainspring night --prd docs/prd.md --engine ollama --model 'ollama/qwen3:8b' \
#     --review-engine codex --review-model gpt-5.5 --dry-run --once

set -euo pipefail

# Path resolution: in source-checkout mode the script lives at the repo root,
# so ROOT_DIR defaults to SCRIPT_DIR. --project <path> is the explicit override
# for driving another project from that checkout. Packaged console-script runs
# set MAINSPRING_PROJECT_ROOT to the caller's working directory and marks
# MAINSPRING_CONSOLE_ENTRYPOINT=1; a direct source checkout ignores leaked env
# roots unless --project is provided.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Pre-scan args for --project / --project=<path>; a real flag parse with
# proper validation happens later, but ROOT_DIR has to be resolved before any
# library is sourced.
MAINSPRING_PROJECT_ROOT_FROM_FLAG=""
__ms_args=("$@")
for ((__ms_i = 0; __ms_i < ${#__ms_args[@]}; __ms_i++)); do
  case "${__ms_args[$__ms_i]}" in
    --project)
      __ms_next=$((__ms_i + 1))
      if [ "$__ms_next" -lt "${#__ms_args[@]}" ] && [[ "${__ms_args[$__ms_next]}" != --* ]]; then
        MAINSPRING_PROJECT_ROOT_FROM_FLAG="${__ms_args[$__ms_next]}"
      fi
      ;;
    --project=*)
      MAINSPRING_PROJECT_ROOT_FROM_FLAG="${__ms_args[$__ms_i]#--project=}"
      ;;
  esac
done

mainspring_resolve_existing_dir() {
  local label="$1"
  local path="$2"
  if [ ! -d "$path" ]; then
    echo "$label path not found or not a directory: $path" >&2
    exit 2
  fi
  cd "$path" && pwd
}

mainspring_script_dir_is_source_tree() {
  [ -f "$SCRIPT_DIR/mainspring.sh" ] &&
    [ -f "$SCRIPT_DIR/py/mainspring_bootstrap.py" ] &&
    [ -f "$SCRIPT_DIR/lib/cli.sh" ] &&
    [ -f "$SCRIPT_DIR/pyproject.toml" ]
}

if [ -n "$MAINSPRING_PROJECT_ROOT_FROM_FLAG" ]; then
  ROOT_DIR="$(mainspring_resolve_existing_dir "--project" "$MAINSPRING_PROJECT_ROOT_FROM_FLAG")"
elif [ -n "${MAINSPRING_PROJECT_ROOT:-}" ] && { [ "${MAINSPRING_CONSOLE_ENTRYPOINT:-}" = "1" ] || ! mainspring_script_dir_is_source_tree; }; then
  ROOT_DIR="$(mainspring_resolve_existing_dir "MAINSPRING_PROJECT_ROOT" "$MAINSPRING_PROJECT_ROOT")"
else
  ROOT_DIR="$SCRIPT_DIR"
fi
unset -f mainspring_resolve_existing_dir
unset -f mainspring_script_dir_is_source_tree
unset __ms_args __ms_i __ms_next MAINSPRING_PROJECT_ROOT_FROM_FLAG
MAINSPRING_PY_DIR="$SCRIPT_DIR/py"
cd "$ROOT_DIR"

mainspring_env_default() {
  local primary_name="$1"
  local default_value="${2-}"
  local primary_value
  primary_value="${!primary_name-}"
  if [ -n "$primary_value" ]; then
    printf '%s' "$primary_value"
    return 0
  fi
  printf '%s' "$default_value"
}

mainspring_resolve_path() {
  local path="$1"
  if [ -z "$path" ]; then
    return 0
  fi
  case "$path" in
    /*) printf '%s' "$path" ;;
    *) printf '%s' "$ROOT_DIR/$path" ;;
  esac
}

MAINSPRING_RUNTIME_DIR_CONFIGURED="$(mainspring_env_default MAINSPRING_RUNTIME_DIR "")"
if [ -n "$MAINSPRING_RUNTIME_DIR_CONFIGURED" ]; then
  RUNTIME_DIR="$(mainspring_resolve_path "$MAINSPRING_RUNTIME_DIR_CONFIGURED")"
elif [ -d "$ROOT_DIR/.mainspring" ]; then
  RUNTIME_DIR="$ROOT_DIR/.mainspring"
else
  RUNTIME_DIR="$ROOT_DIR/.mainspring"
fi
STATE_DIR="$(mainspring_resolve_path "$(mainspring_env_default MAINSPRING_STATE_DIR "$RUNTIME_DIR/state")")"
TEAM_DIR="$RUNTIME_DIR/team"
export MAINSPRING_RUNTIME_DIR="$RUNTIME_DIR"
export MAINSPRING_STATE_DIR="$STATE_DIR"
mkdir -p "$RUNTIME_DIR" "$STATE_DIR"

# Bootstrap PATH for non-login shells (fish/bash/cron)
export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
mainspring_load_fnm_env_json() {
  command -v fnm >/dev/null 2>&1 || return 1
  command -v python3 >/dev/null 2>&1 || return 1

  local fnm_line fnm_key fnm_value fnm_output fnm_loaded=false
  fnm_output="$(
    if fnm env --json 2>/dev/null | python3 "$MAINSPRING_PY_DIR/fnm_env.py"; then
      exit 0
    else
      # The helper is the second pipeline entry; its failure rejects all output.
      exit "${PIPESTATUS[1]}"
    fi
  )" || return 1
  while IFS= read -r fnm_line; do
    fnm_key="${fnm_line%%=*}"
    fnm_value="${fnm_line#*=}"
    case "$fnm_key" in
      MAINSPRING_FNM_BIN)
        [ -d "$fnm_value" ] && export PATH="$fnm_value:$PATH"
        [ -d "$fnm_value" ] && fnm_loaded=true
        ;;
      FNM_COREPACK_ENABLED|FNM_NODE_DIST_MIRROR|FNM_VERSION_FILE_STRATEGY|FNM_RESOLVE_ENGINES|FNM_ARCH|FNM_MULTISHELL_PATH|FNM_DIR|FNM_LOGLEVEL)
        export "$fnm_key=$fnm_value"
        ;;
    esac
  done <<< "$fnm_output"
  [ "$fnm_loaded" = true ]
}

if ! mainspring_load_fnm_env_json; then
  # Glob fallback: pick the first matching fnm-managed node binary dir.
  for FNM_BIN_DIR in "$HOME"/.local/share/fnm/node-versions/*/installation/bin; do
    if [ -d "$FNM_BIN_DIR" ]; then
      export PATH="$FNM_BIN_DIR:$PATH"
      break
    fi
  done
fi
MAINSPRING_PATH_PREFIX_RESOLVED="$(mainspring_env_default MAINSPRING_PATH_PREFIX "")"
if [ -n "$MAINSPRING_PATH_PREFIX_RESOLVED" ]; then
  export PATH="$MAINSPRING_PATH_PREFIX_RESOLVED:$PATH"
fi

# ---------------------------------------------------------------------------
# Global state — shared across all sourced modules
# See lib/common.sh header for the full categorized globals contract.
# ACTIVE_CHILD_PID / ACTIVE_HEARTBEAT_PID are the only mutable cross-module
# globals: set by engines.sh:run_with_heartbeat, read by cleanup_children
# trap below.  They must be global because bash traps have no parameters.
# ---------------------------------------------------------------------------
MODE="taskmaster"
ENGINE="$(mainspring_env_default MAINSPRING_ENGINE claude)"
REVIEW_ENGINE="$(mainspring_env_default MAINSPRING_REVIEW_ENGINE codex)"
DEFAULT_CODEX_MODEL="$(mainspring_env_default MAINSPRING_DEFAULT_CODEX_MODEL gpt-5.5)"
DEFAULT_FAST_CODEX_MODEL="$(mainspring_env_default MAINSPRING_DEFAULT_FAST_CODEX_MODEL gpt-5.3-codex-spark)"
DEFAULT_CLAUDE_MODEL="$(mainspring_env_default MAINSPRING_DEFAULT_CLAUDE_MODEL opus)"
CODEX_REASONING_EFFORT="$(mainspring_env_default MAINSPRING_CODEX_REASONING_EFFORT xhigh)"
RUN_ONCE=false
AGENT_MODE="$(mainspring_env_default MAINSPRING_AGENT_MODE code)"
PRD_PATH=""
MODEL_OVERRIDE=""
REVIEW_MODEL_OVERRIDE=""
PAIR_MODE=""
SPEED_PROFILE="$(mainspring_env_default MAINSPRING_SPEED_PROFILE max)"
MAX_AGENTS="$(mainspring_env_default MAINSPRING_MAX_AGENTS 6)"
AUTO_RETRY_CI="$(mainspring_env_default MAINSPRING_AUTO_RETRY_CI 0)"
AUTO_RETRY_CI_LOG="$(mainspring_env_default MAINSPRING_AUTO_RETRY_CI_LOG "")"
RETRY_TASK_IDS=()
TOPOLOGY="$(mainspring_env_default MAINSPRING_TOPOLOGY solo)"
SELF_TEST=false
SELF_TEST_ALL=false
DOCTOR=false
DOCTOR_ARGS=()
STATUS=false
STATUS_ARGS=()
REPAIR_STATE=false
STOP_PROCESSES=false
STOP_ARGS=()
DRY_RUN=false
FORCE_REPAIR=false
RESTART_TEAM=false
METRICS=false
METRICS_DAYS=""
METRICS_SINCE=""
METRICS_FORMAT=""
METRICS_ROUTING=false
HUD=false
HUD_ARGS=()
ENGINES=false
ENGINES_ARGS=()
WIZARD=false
WIZARD_ALLOW_LAST_RUN_OFFER=false
LAST_RUN=false
LAST_RUN_INFO=false
LAST_RUN_INFO_ARGS=()
PRESET=""
LIST_PRESETS=false
CONFIG_FILE="${MAINSPRING_CONFIG_FILE:-$ROOT_DIR/.mainspring.yaml}"
NOTIFY_TEST=false
NOTIFY_TEST_ARGS=()
NOTIFY_HEALTH=false
NOTIFY_HEALTH_ARGS=()
NOTIFY_RESTART=false
NOTIFY_RESTART_ARGS=()
REPLAY=false
REPLAY_ARGS=()
VALIDATE_PRD=false
VALIDATE_PRD_ARGS=()
LIMITS=false
LIMITS_ARGS=()
METHOD_INIT=false
METHOD_INIT_ARGS=()
METHOD_DECOMPOSE=false
METHOD_DECOMPOSE_ARGS=()
SCOPE_CHECK=false
SCOPE_CHECK_ARGS=()
METHOD_NEXT=false
METHOD_NEXT_ARGS=()
NOTIFY_DAEMON_PID=""
ORIGINAL_ARGC=$#
ACTIVE_CHILD_PID=""
ACTIVE_HEARTBEAT_PID=""
LOCK_FILE="$STATE_DIR/mainspring.lock"
LAST_RUN_FILE="$STATE_DIR/last-run.env"
IDLE_WAVES=0
MAX_IDLE_WAVES="$(mainspring_env_default MAINSPRING_MAX_IDLE_WAVES 2)"
LOG_DIR="$RUNTIME_DIR/logs"
AUTO_TMUX="$(mainspring_env_default MAINSPRING_AUTO_TMUX true)"
TEAM_FALLBACK_TO_SOLO="$(mainspring_env_default MAINSPRING_TEAM_FALLBACK_TO_SOLO true)"
TEAM_SUPERVISE="$(mainspring_env_default MAINSPRING_TEAM_SUPERVISE true)"
TEAM_POLL_SECONDS="$(mainspring_env_default MAINSPRING_TEAM_POLL_SECONDS 30)"
SELF_HEAL="$(mainspring_env_default MAINSPRING_SELF_HEAL true)"
STALE_PROCESS_MINUTES="$(mainspring_env_default MAINSPRING_STALE_PROCESS_MINUTES 30)"
AUTO_CHECKPOINT="$(mainspring_env_default MAINSPRING_AUTO_CHECKPOINT true)"
WAVE_LEDGER_FILE="$LOG_DIR/waves.jsonl"

USER_SET_MODE=false
USER_SET_ENGINE=false
USER_SET_REVIEW_ENGINE=false
USER_SET_MODEL_OVERRIDE=false
USER_SET_REVIEW_MODEL_OVERRIDE=false
USER_SET_PAIR_MODE=false
USER_SET_SPEED_PROFILE=false
USER_SET_MAX_AGENTS=false
USER_SET_AUTO_RETRY_CI=false
USER_SET_AUTO_RETRY_CI_LOG=false
USER_SET_TOPOLOGY=false
USER_SET_RUN_ONCE=false
USER_SET_PRD_PATH=false
USER_SET_AGENT_MODE=false
USER_SET_CODEX_REASONING_EFFORT=false
USER_SET_AUTO_CHECKPOINT=false

AUTO_CHECKPOINT_DENY_PATHS=(
  ':(exclude).mainspring/**'
  ':(exclude)node_modules/**'
  ':(exclude)dist/**'
  ':(exclude)coverage/**'
  ':(exclude)playwright-report/**'
  ':(exclude)test-results/**'
  ':(exclude)screenshots/**'
  ':(exclude)**/screenshots/**'
  ':(exclude)**/__pycache__/**'
  ':(exclude)**/*.pyc'
  ':(exclude).env'
  ':(exclude).env.*'
  ':(exclude)**/.env'
  ':(exclude)**/.env.*'
  ':(exclude)**/*.log'
  ':(exclude)**/*.pem'
  ':(exclude)**/*.key'
  ':(exclude)**/*secret*'
  ':(exclude)**/*credential*'
  ':(exclude)**/*.sqlite'
  ':(exclude)**/*.sqlite3'
  ':(exclude)**/*.db'
  ':(exclude)**/*.db-shm'
  ':(exclude)**/*.db-wal'
  ':(exclude)**/*.png'
  ':(exclude)**/*.jpg'
  ':(exclude)**/*.jpeg'
  ':(exclude)**/*.webp'
  ':(exclude)**/*.gif'
)

# ---------------------------------------------------------------------------
# Source modular libraries (P2-4)
# Order matters: later modules may depend on functions from earlier ones.
# ---------------------------------------------------------------------------
source "$SCRIPT_DIR/lib/common.sh"
source "$SCRIPT_DIR/lib/log.sh"
source "$SCRIPT_DIR/lib/lock.sh"
source "$SCRIPT_DIR/lib/taskmaster_helpers.sh"
source "$SCRIPT_DIR/lib/wave.sh"
source "$SCRIPT_DIR/lib/status.sh"
source "$SCRIPT_DIR/lib/usage.sh"
source "$SCRIPT_DIR/lib/doctor.sh"
source "$SCRIPT_DIR/lib/wizard.sh"
source "$SCRIPT_DIR/lib/dry_run.sh"
source "$SCRIPT_DIR/lib/engines.sh"
source "$SCRIPT_DIR/lib/self_test.sh"
source "$SCRIPT_DIR/lib/review.sh"
source "$SCRIPT_DIR/lib/write_scope.sh"
source "$SCRIPT_DIR/lib/team.sh"
source "$SCRIPT_DIR/lib/team_supervision.sh"
source "$SCRIPT_DIR/lib/help.sh"
source "$SCRIPT_DIR/lib/work_mode_help.sh"
source "$SCRIPT_DIR/lib/prompts.sh"
source "$SCRIPT_DIR/lib/notify.sh"
source "$SCRIPT_DIR/lib/wave_loop_setup.sh"
source "$SCRIPT_DIR/lib/wave_loop_state.sh"
source "$SCRIPT_DIR/lib/wave_loop.sh"

# ---------------------------------------------------------------------------
# Process cleanup — must stay in main since it references global PIDs + lock
# ---------------------------------------------------------------------------
cleanup_children() {
  if [ -n "${ACTIVE_HEARTBEAT_PID:-}" ]; then
    kill "$ACTIVE_HEARTBEAT_PID" >/dev/null 2>&1 || true
    wait "$ACTIVE_HEARTBEAT_PID" >/dev/null 2>&1 || true
    ACTIVE_HEARTBEAT_PID=""
  fi
  if [ -n "${ACTIVE_CHILD_PID:-}" ]; then
    # Snapshot the owned pipeline and its descendants before signalling parents.
    # A CLI may ignore TERM or leave subprocesses behind when its parent exits.
    local pid pid_list="" live_pid_list attempt stop_signal
    local -a active_pids=()
    while IFS= read -r pid; do
      active_pids+=("$pid")
      pid_list="${pid_list:+$pid_list,}$pid"
    done < <(ps -axo pid=,ppid= | awk -v root="$ACTIVE_CHILD_PID" '
      { parent[$1] = $2 }
      END {
        for (pid in parent) {
          ancestor = pid
          while (ancestor in parent && ancestor != root && parent[ancestor] != ancestor)
            ancestor = parent[ancestor]
          if (ancestor == root) print pid
        }
      }')
    if [ "${#active_pids[@]}" -eq 0 ]; then
      active_pids=("$ACTIVE_CHILD_PID")
      pid_list="$ACTIVE_CHILD_PID"
    fi
    for stop_signal in TERM KILL; do
      attempt=0
      while :; do
        # Permanently drop exited/zombie IDs before signalling or escalating.
        active_pids=()
        live_pid_list=""
        while IFS= read -r pid; do
          active_pids+=("$pid")
          live_pid_list="${live_pid_list:+$live_pid_list,}$pid"
        done < <(ps -o pid=,stat= -p "$pid_list" 2>/dev/null |
          awk '$2 !~ /^Z/ { print $1 }')
        pid_list="$live_pid_list"
        [ -n "$pid_list" ] || break 2
        if [ "$attempt" -eq 0 ]; then
          kill -"$stop_signal" "${active_pids[@]}" >/dev/null 2>&1 || true
        fi
        [ "$attempt" -lt 20 ] || break
        sleep 0.1
        attempt=$((attempt + 1))
      done
    done
    wait "$ACTIVE_CHILD_PID" >/dev/null 2>&1 || true
    ACTIVE_CHILD_PID=""
  fi
  reap_notify_daemon
  release_lock
}

# A signal must end the run: returning from the trap would resume the wave loop
# without the lock. Exit with the conventional 128+signal status.
stop_on_signal() {
  trap - INT TERM
  cleanup_children
  exit "$1"
}

trap cleanup_children EXIT
trap 'stop_on_signal 130' INT
trap 'stop_on_signal 143' TERM

# ---------------------------------------------------------------------------
# CLI parsing and runtime dispatch
# ---------------------------------------------------------------------------
source "$SCRIPT_DIR/lib/cli.sh"
source "$SCRIPT_DIR/lib/dispatch.sh"

parse_cli_args "$@"
run_mainspring
