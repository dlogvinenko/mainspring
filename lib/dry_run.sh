#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring dry-run reporting.

run_dry_run() {
  echo "=== Mainspring Dry Run ==="
  echo ""
  echo "Resolved settings:"
  echo "  Mode:              $MODE"
  echo "  Pair:              ${PAIR_MODE:-$ENGINE+$REVIEW_ENGINE}"
  echo "  Writer engine:     $ENGINE"
  echo "  Writer model:      ${MODEL_OVERRIDE:-default}"
  echo "  Reviewer engine:   $REVIEW_ENGINE"
  echo "  Reviewer model:    ${REVIEW_MODEL_OVERRIDE:-default}"
  echo "  Speed profile:     $SPEED_PROFILE"
  echo "  Max agents:        $MAX_AGENTS"
  echo "  Writer mode:       ${AGENT_MODE:-code}"
  echo "  Auto-retry CI:     $AUTO_RETRY_CI"
  echo "  Auto-retry CI log: ${AUTO_RETRY_CI_LOG:-none}"
  echo "  Topology:          $TOPOLOGY"
  echo "  Run once:          $RUN_ONCE"
  echo "  Auto-checkpoint:   $AUTO_CHECKPOINT"
  echo "  Reasoning effort:  $CODEX_REASONING_EFFORT"
  echo "  Runtime dir:       ${RUNTIME_DIR:-$ROOT_DIR/.mainspring}"
  echo "  State dir:         ${STATE_DIR:-$ROOT_DIR/.mainspring/state}"
  echo "  Log dir:           $LOG_DIR"
  echo "  Lock file:         $LOCK_FILE"
  echo "  Wave ledger:       $WAVE_LEDGER_FILE"
  echo "  Last-run file:     $LAST_RUN_FILE"
  echo "  Config file:       ${CONFIG_FILE:-$ROOT_DIR/.mainspring.yaml}"
  [ "$MODE" = "night" ] && echo "  PRD path:          ${PRD_PATH:-(auto-detect)}"
  echo ""

  echo "Writer command:"
  print_engine_command_preview "$ENGINE" "writer" "${MODEL_OVERRIDE:-$(engine_default_model "$ENGINE")}" "<prompt>"
  echo ""

  echo "Reviewer command:"
  print_engine_command_preview "$REVIEW_ENGINE" "reviewer" "${REVIEW_MODEL_OVERRIDE:-$(engine_default_model "$REVIEW_ENGINE")}" "<review-prompt>"
  echo ""

  echo "Registered engines:"
  if ! "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_registry.py" | sed 's/^/  /'; then
    echo "  engine registry: MISSING"
  fi
  echo ""

  echo "Dependency checks:"
  local ok=true
  print_engine_dependency_check "$ENGINE" "writer" "$ENGINE readiness" "${MODEL_OVERRIDE:-$(engine_default_model "$ENGINE")}" || ok=false
  print_engine_dependency_check "$REVIEW_ENGINE" "reviewer" "$REVIEW_ENGINE readiness" "${REVIEW_MODEL_OVERRIDE:-$(engine_default_model "$REVIEW_ENGINE")}" || ok=false
  if [ "$MODE" = "taskmaster" ]; then
    if command -v task-master >/dev/null 2>&1; then
      echo "  task-master:       found"
    else
      echo "  task-master:       MISSING"
      ok=false
    fi
    if [ -d "$ROOT_DIR/.taskmaster" ]; then
      echo "  .taskmaster/:      present"
    else
      echo "  .taskmaster/:      MISSING"
      ok=false
    fi
    if [ "$TOPOLOGY" = "team" ]; then
      if command -v omx >/dev/null 2>&1; then
        echo "  team backend:      found"
      else
        echo "  team backend:      MISSING"
        ok=false
      fi
    fi
  fi
  if [ "$MODE" = "night" ]; then
    local resolved_prd="$PRD_PATH"
    if [ -z "$resolved_prd" ]; then
      if [ -f "$ROOT_DIR/docs/prd.md" ]; then
        resolved_prd="$ROOT_DIR/docs/prd.md"
      elif [ -f "$ROOT_DIR/PRD.md" ]; then
        resolved_prd="$ROOT_DIR/PRD.md"
      fi
    fi
    if [ -n "$resolved_prd" ] && [ -f "$resolved_prd" ]; then
      echo "  PRD file:          found ($resolved_prd)"
    else
      echo "  PRD file:          MISSING"
      ok=false
    fi
  fi
  echo ""

  if [ "$ok" = true ]; then
    echo "Status: READY — all dependencies satisfied. Zero API calls made."
  else
    echo "Status: NOT READY — missing dependencies (see above). Zero API calls made."
  fi
}
