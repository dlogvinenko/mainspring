#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring wave loop — main pick→write→review→log→decide cycle.
# Depends on the sourced common/log/wave/engine/review/team/prompt/notify helpers
# and the globals initialized by mainspring.sh plus wave_loop_setup.sh.

run_wave_loop() {
  initialize_wave_loop_logs
  local TEAM_PREFLIGHT_STATUS
  if run_team_preflight_if_needed; then
    TEAM_PREFLIGHT_STATUS=0
  else
    TEAM_PREFLIGHT_STATUS=$?
  fi
  if [ "${TEAM_PREFLIGHT_RESULT:-continue}" = "done" ]; then
    return "$TEAM_PREFLIGHT_STATUS"
  fi
  # --- Solo wave loop ---
  local AUTO_RETRY_CI_ATTEMPT=0
  local AUTO_RETRY_CI_CONTEXT=""
  local AUTO_RETRY_CI_TASK_ID=""
  local AUTO_RETRY_CI_WORK_ID=""
  local AUTO_RETRY_CI_NEXT_OUTPUT=""
  local AUTO_RETRY_CI_TASK_DETAILS=""
  while true; do
    ensure_notify_daemon
    initialize_solo_wave_state
    local NEXT_OUTPUT TASK_DETAILS PROMPT
    if [ -n "${MAINSPRING_REPLAY_PROMPT_FILE:-}" ]; then
      # Prompt-backed replay intentionally avoids Taskmaster mutation even if a
      # caller accidentally keeps the original taskmaster mode.
      MODE="night"
      if [ ! -f "$MAINSPRING_REPLAY_PROMPT_FILE" ]; then
        append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "${MAINSPRING_REPLAY_TARGET_ID:-replay}" "replay-setup" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "1" "" "ERROR" "routing:missing_replay_prompt" "0" "" "Provide a readable MAINSPRING_REPLAY_PROMPT_FILE or rebuild the replay from an available wave snapshot." "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT"
        echo "Replay prompt file not found: $MAINSPRING_REPLAY_PROMPT_FILE" >&2
        return 1
      fi
      TASK_ID="${MAINSPRING_REPLAY_TARGET_ID:-replay}"
      WORK_ID="$TASK_ID"
      TASK_STATUS_BEFORE="replay"
      NEXT_OUTPUT="REPLAY_PROMPT_FILE: $MAINSPRING_REPLAY_PROMPT_FILE"
      TASK_DETAILS="Replay prompt snapshot for ${MAINSPRING_REPLAYED_FROM:-unknown wave}"
      PROMPT="$(cat "$MAINSPRING_REPLAY_PROMPT_FILE")"
      {
        echo "=== WAVE $WAVE | $(date) ==="
        echo "Mode: replay-prompt"
        echo "Replay source: ${MAINSPRING_REPLAYED_FROM:-unknown}"
        echo "Replay prompt: $MAINSPRING_REPLAY_PROMPT_FILE"
        echo
      } >> "$LOG_FILE"
    elif [ "$MODE" = "taskmaster" ]; then
      if [ "${MAINSPRING_REPLAY_LIVE_RECONSTRUCTION:-}" = "1" ]; then
        TASK_ID="${MAINSPRING_REPLAY_TARGET_ID:-}"
        WORK_ID="$TASK_ID"
        if [ -z "${WORK_ID// }" ]; then
          append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "replay" "replay-setup" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "1" "" "ERROR" "routing:missing_replay_target" "0" "" "Provide a replay row with task_id/work_id, or replay a prompt-backed row instead." "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT"
          echo "Replay live reconstruction requires MAINSPRING_REPLAY_TARGET_ID." >&2
          return 1
        fi
        TASK_STATUS_BEFORE="$(taskmaster_status_for_id "$WORK_ID" 2>/dev/null || true)"
        TASK_DETAILS="$(task-master show "$WORK_ID" 2>/dev/null || true)"
        if [ -z "${TASK_DETAILS// }" ]; then
          append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "$WORK_ID" "replay-setup" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "1" "" "ERROR" "routing:replay_target_unavailable" "0" "" "Restore the recorded Taskmaster item or use a prompt-backed replay snapshot." "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT" "$TASK_STATUS_BEFORE"
          echo "Replay target not available in current Taskmaster state: $WORK_ID" >&2
          return 1
        fi

        NEXT_OUTPUT="REPLAY_LIVE_RECONSTRUCTION: #$WORK_ID from ${MAINSPRING_REPLAYED_FROM:-unknown wave}"

        echo "--- Replay live reconstruction work item $WORK_ID ---"
        printf '%s\n' "$NEXT_OUTPUT"
        echo "--- Taskmaster show $WORK_ID ---"
        printf '%s\n' "$TASK_DETAILS"
        echo ""

        {
          echo "=== WAVE $WAVE | $(date) ==="
          echo "Mode: taskmaster-live-replay"
          echo "Replay source: ${MAINSPRING_REPLAYED_FROM:-unknown}"
          echo "Original mode: ${MAINSPRING_REPLAY_ORIGINAL_MODE:-unknown}"
          echo "Work ID: $WORK_ID"
          printf '%s\n' "$NEXT_OUTPUT"
          echo "---"
          printf '%s\n' "$TASK_DETAILS"
          echo
        } >> "$LOG_FILE"

        PROMPT="$TASKMASTER_BASE_MISSION

Replay live reconstruction context:
- This source row has no prompt snapshot, so this wave rebuilds from current Taskmaster state.
- Original wave: ${MAINSPRING_REPLAYED_FROM:-unknown}
- Recorded work item: $WORK_ID
- Do not call task-master next or switch to another work item.
- Do not mark Taskmaster status done; replay provenance is recorded in waves.jsonl.

Current Task ID: $WORK_ID
Current Work Item ID: $WORK_ID

Task Master replay output:
$NEXT_OUTPUT

Task Master show $WORK_ID:
$TASK_DETAILS"
      elif [ -n "${AUTO_RETRY_CI_CONTEXT// }" ] && [ -n "${AUTO_RETRY_CI_WORK_ID// }" ]; then
        TASK_ID="$AUTO_RETRY_CI_TASK_ID"
        WORK_ID="$AUTO_RETRY_CI_WORK_ID"
        NEXT_OUTPUT="${AUTO_RETRY_CI_NEXT_OUTPUT:-AUTO_RETRY_CI retry for #$WORK_ID}"
        TASK_STATUS_BEFORE="$(taskmaster_status_for_id "$WORK_ID" 2>/dev/null || true)"
        task-master set-status --id="$WORK_ID" --status=in-progress >/dev/null 2>&1 || true
        TASK_DETAILS="$(task-master show "$WORK_ID" 2>/dev/null || true)"
        if [ -z "${TASK_DETAILS// }" ]; then
          TASK_DETAILS="$AUTO_RETRY_CI_TASK_DETAILS"
        fi

        echo "--- Auto-retry CI work item $WORK_ID ---"
        printf '%s\n' "$NEXT_OUTPUT"
        echo "--- Taskmaster show $WORK_ID ---"
        printf '%s\n' "$TASK_DETAILS"
        echo ""

        {
          echo "=== WAVE $WAVE | $(date) ==="
          echo "Mode: taskmaster"
          echo "Auto-retry CI attempt: $AUTO_RETRY_CI_ATTEMPT/${AUTO_RETRY_CI:-0}"
          echo "Task ID: $TASK_ID"
          echo "Work ID: $WORK_ID"
          printf '%s\n' "$NEXT_OUTPUT"
          echo "---"
          printf '%s\n' "$TASK_DETAILS"
          echo
        } >> "$LOG_FILE"

        PROMPT="$TASKMASTER_BASE_MISSION

Current Task ID: $TASK_ID
Current Work Item ID: $WORK_ID

Task Master next output:
$NEXT_OUTPUT

Task Master show $WORK_ID:
$TASK_DETAILS"
      else
      NEXT_OUTPUT="$(task-master next 2>/dev/null || true)"
      if [ -z "${NEXT_OUTPUT// }" ]; then
        record_no_actionable_task_stop \
          "taskmaster_next_empty" \
          "No actionable Task Master task found. Stopping." \
          "Inspect Taskmaster blocked/review statuses before launching new work."
        break
      fi

      TASK_ID="$(printf '%s\n' "$NEXT_OUTPUT" | sed -n 's/.*#\([0-9][0-9.]*\).*/\1/p' | head -n 1)"
      if [ -z "$TASK_ID" ]; then
        TASK_ID="$(fallback_taskmaster_next)"
        if [ -z "${TASK_ID// }" ]; then
          record_no_actionable_task_stop \
            "taskmaster_next_unparseable_no_ready" \
            "Could not parse task id from task-master next output, and fallback found no ready task. Stopping." \
            "Inspect Taskmaster next output and blocked/review statuses before launching new work." \
            "$NEXT_OUTPUT"
          break
        fi
        NEXT_OUTPUT="FALLBACK_READY_TASK: #$TASK_ID"
      fi

      WORK_ID="$(pick_taskmaster_work_item "$TASK_ID")"
      if [ -z "${WORK_ID// }" ]; then
        if handle_empty_taskmaster_parent; then
          break
        fi
        continue
      fi
      if [ "$WORK_ID" = "$TASK_ID" ]; then
        TASK_STATUS_BEFORE="$(taskmaster_status_for_id "$TASK_ID" 2>/dev/null || true)"
        task-master set-status --id="$TASK_ID" --status=in-progress >/dev/null 2>&1 || true
      else
        TASK_STATUS_BEFORE="$(taskmaster_status_for_id "$WORK_ID" 2>/dev/null || true)"
        task-master set-status --id="$WORK_ID" --status=in-progress >/dev/null 2>&1 || true
      fi
      TASK_DETAILS="$(task-master show "$WORK_ID" 2>/dev/null || true)"

      echo "--- Taskmaster next ---"
      printf '%s\n' "$NEXT_OUTPUT"
      echo "--- Taskmaster show $WORK_ID ---"
      printf '%s\n' "$TASK_DETAILS"
      echo ""

      {
        echo "=== WAVE $WAVE | $(date) ==="
        echo "Mode: taskmaster"
        echo "Task ID: $TASK_ID"
        echo "Work ID: $WORK_ID"
        printf '%s\n' "$NEXT_OUTPUT"
        echo "---"
        printf '%s\n' "$TASK_DETAILS"
        echo
      } >> "$LOG_FILE"

      PROMPT="$TASKMASTER_BASE_MISSION

Current Task ID: $TASK_ID
Current Work Item ID: $WORK_ID

Task Master next output:
$NEXT_OUTPUT

Task Master show $WORK_ID:
$TASK_DETAILS"
      fi
    else
      local PRD_BRIEF
      PRD_BRIEF="$(build_prd_brief "$PRD_PATH")"

      {
        echo "=== WAVE $WAVE | $(date) ==="
        echo "Mode: night"
        echo "PRD: $PRD_PATH"
        echo
      } >> "$LOG_FILE"

      PROMPT="$NIGHT_BASE_MISSION

PRD brief:
$PRD_BRIEF

Use this PRD brief as the routing context.
If you need deeper detail from the PRD, read only the relevant section(s) from the file instead of dumping the entire document into context."
    fi

    if [ -n "${AUTO_RETRY_CI_CONTEXT// }" ]; then
      PROMPT="$PROMPT

Auto-retry CI context:
$AUTO_RETRY_CI_CONTEXT

Retry instructions:
- This is an opt-in --auto-retry-ci recovery wave. Do not switch tasks.
- Treat the failing verification output above as the current source of truth.
- Fix the root cause, rerun the failing verification, and include the evidence in close-out."
    fi

    PROMPT="$(apply_agent_mode_to_prompt "$PROMPT" "${AGENT_MODE:-code}")"

    WAVE_PROMPT_FILE="$LOG_DIR/${MODE}-prompt-wave${WAVE}.md"
    printf '%s\n' "$PROMPT" > "$WAVE_PROMPT_FILE"
    WAVE_PROMPT_SHA256="$(hash_file_sha256 "$WAVE_PROMPT_FILE" 2>/dev/null || true)"
    WAVE_GIT_HEAD="$(git rev-parse HEAD 2>/dev/null || true)"
    WAVE_GIT_STATUS="$(git_status_short)"
    if [ "$MODE" = "night" ] && [ -n "${PRD_PATH:-}" ]; then
      WAVE_PRD_PATH="$PRD_PATH"
    fi

    local WAVE_DISPLAY_FILE WAVE_USAGE_FILE EXIT_CODE WAVE_PROGRESS_COUNT WAVE_PROGRESS_FILES WAVE_SCOPE_FILES WAVE_SCOPE_MARKER
    WAVE_DISPLAY_FILE="$(mktemp)"
    WAVE_USAGE_FILE="$LOG_DIR/${MODE}-usage-wave${WAVE}.jsonl"
    rm -f "$WAVE_USAGE_FILE"
    export MAINSPRING_WAVE_USAGE_FILE="$WAVE_USAGE_FILE"
    WAVE_SCOPE_MARKER="$(mktemp)"
    EXIT_CODE=0
    if run_ai_turn writer "$PROMPT" "$LOG_FILE" "$WAVE_DISPLAY_FILE"; then
      EXIT_CODE=0
    else
      EXIT_CODE=$?
    fi
    WAVE_PROGRESS_COUNT="$(count_wave_progress_files "$WAVE_MARKER")"
    WAVE_PROGRESS_FILES="$(print_wave_progress_files "$WAVE_MARKER")"
    WAVE_SCOPE_FILES="$(print_wave_scope_files "$WAVE_SCOPE_MARKER")"
    append_wave_summary "$SUMMARY_FILE" "$WAVE" "$MODE" "$ENGINE" "$EXIT_CODE" "$WAVE_DISPLAY_FILE"
    rm -f "$WAVE_MARKER"
    rm -f "$WAVE_SCOPE_MARKER"

    echo ""
    echo "=== WAVE $WAVE finished at $(date) with exit code $EXIT_CODE ==="
    echo "Meaningful files changed this wave: $WAVE_PROGRESS_COUNT"
    if [ -n "${WAVE_PROGRESS_FILES// }" ]; then
      echo "$WAVE_PROGRESS_FILES"
    fi
    echo ""
    {
      echo "=== WAVE $WAVE finished at $(date) with exit code $EXIT_CODE ==="
      echo "Meaningful files changed this wave: $WAVE_PROGRESS_COUNT"
      if [ -n "${WAVE_PROGRESS_FILES// }" ]; then
        printf '%s\n' "$WAVE_PROGRESS_FILES"
      fi
      echo
    } >> "$LOG_FILE"

    if [ $EXIT_CODE -ne 0 ]; then
      local ENGINE_FAILURE_REASON ENGINE_FAILURE_NEXT_ACTION
      ENGINE_FAILURE_REASON="$(classify_engine_failure_reason "$ENGINE" "$EXIT_CODE" "$WAVE_DISPLAY_FILE")"
      ENGINE_FAILURE_NEXT_ACTION="Inspect $LOG_FILE and rerun only after the worker error is understood."
      if [ "$ENGINE_FAILURE_REASON" = "engine:quota" ]; then
        ENGINE_FAILURE_NEXT_ACTION="Wait for quota reset or switch to an available registered pair before rerunning."
      fi
      local CI_FAILURE_REASON CI_FAILURE_LABEL
      CI_FAILURE_REASON="$(classify_ci_failure_reason "$WAVE_DISPLAY_FILE" 2>/dev/null || true)"
      CI_FAILURE_LABEL="$(ci_failure_label "$CI_FAILURE_REASON")"
      if [ "$MODE" = "taskmaster" ] && [ -n "${WORK_ID:-$TASK_ID}" ]; then
        TASK_STATUS_AFTER="$(taskmaster_status_for_id "${WORK_ID:-$TASK_ID}" 2>/dev/null || true)"
      fi
      if auto_retry_ci_can_retry "${AUTO_RETRY_CI:-0}" "$AUTO_RETRY_CI_ATTEMPT" "$CI_FAILURE_REASON"; then
        AUTO_RETRY_CI_ATTEMPT=$((AUTO_RETRY_CI_ATTEMPT + 1))
        AUTO_RETRY_CI_CONTEXT="$(build_auto_retry_ci_context "$CI_FAILURE_REASON" "$WAVE_DISPLAY_FILE" "$AUTO_RETRY_CI_ATTEMPT" "${AUTO_RETRY_CI:-0}" "${AUTO_RETRY_CI_LOG:-}")"
        AUTO_RETRY_CI_TASK_ID="$TASK_ID"
        AUTO_RETRY_CI_WORK_ID="${WORK_ID:-$TASK_ID}"
        AUTO_RETRY_CI_NEXT_OUTPUT="$NEXT_OUTPUT"
        AUTO_RETRY_CI_TASK_DETAILS="$TASK_DETAILS"
        ENGINE_FAILURE_NEXT_ACTION="Auto-retry CI attempt $AUTO_RETRY_CI_ATTEMPT/${AUTO_RETRY_CI:-0}: retry the same work item with the captured $CI_FAILURE_LABEL output injected into the next writer prompt."
        append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "${WORK_ID:-$TASK_ID}" "execution" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "$EXIT_CODE" "$WAVE_PROGRESS_FILES" "ERROR" "engine:$CI_FAILURE_REASON" "$AUTO_RETRY_CI_ATTEMPT" "" "$ENGINE_FAILURE_NEXT_ACTION" "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT" "$TASK_STATUS_BEFORE" "$TASK_STATUS_AFTER" "$WAVE_PROMPT_FILE" "$WAVE_PROMPT_SHA256" "$WAVE_GIT_HEAD" "$WAVE_GIT_STATUS" "$WAVE_PRD_PATH" "$WAVE_USAGE_FILE"
        echo "Auto-retry CI detected $CI_FAILURE_LABEL. Retrying same work item on next wave ($AUTO_RETRY_CI_ATTEMPT/${AUTO_RETRY_CI:-0})."
        echo "Auto-retry CI detected $CI_FAILURE_LABEL. Retrying same work item on next wave ($AUTO_RETRY_CI_ATTEMPT/${AUTO_RETRY_CI:-0})." >> "$LOG_FILE"
        rm -f "$WAVE_DISPLAY_FILE"
        echo "Pausing 10s before next wave..."
        echo "Pausing 10s before next wave..." >> "$LOG_FILE"
        sleep 10
        WAVE=$((WAVE + 1))
        continue
      fi
      if [ -n "${CI_FAILURE_REASON// }" ]; then
        ENGINE_FAILURE_REASON="engine:$CI_FAILURE_REASON"
        ENGINE_FAILURE_NEXT_ACTION="Auto-retry CI budget exhausted or disabled. Inspect the captured $CI_FAILURE_LABEL output before rerunning."
      fi
      AUTO_RETRY_CI_CONTEXT=""
      AUTO_RETRY_CI_TASK_ID=""
      AUTO_RETRY_CI_WORK_ID=""
      AUTO_RETRY_CI_NEXT_OUTPUT=""
      AUTO_RETRY_CI_TASK_DETAILS=""
      append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "${WORK_ID:-$TASK_ID}" "execution" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "$EXIT_CODE" "$WAVE_PROGRESS_FILES" "ERROR" "$ENGINE_FAILURE_REASON" "$AUTO_RETRY_CI_ATTEMPT" "" "$ENGINE_FAILURE_NEXT_ACTION" "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT" "$TASK_STATUS_BEFORE" "$TASK_STATUS_AFTER" "$WAVE_PROMPT_FILE" "$WAVE_PROMPT_SHA256" "$WAVE_GIT_HEAD" "$WAVE_GIT_STATUS" "$WAVE_PRD_PATH" "$WAVE_USAGE_FILE"
      echo "Worker exited non-zero. Stopping loop."
      echo "Worker exited non-zero. Stopping loop." >> "$LOG_FILE"
      rm -f "$WAVE_DISPLAY_FILE"
      return $EXIT_CODE
    fi

    local WAVE_VERDICT="PASS"
    local WAVE_FAILURE_REASON=""
    local WAVE_RETRY_COUNT=0
    local WAVE_NEXT_ACTION="Continue with next Taskmaster-ready item."
    local WAVE_LEDGER_PHASE="review"
    local WAVE_PRODUCT_CHANGE_COUNT
    local AGENT_MODE_ALLOWS_NO_CHANGE=false
    WAVE_PRODUCT_CHANGE_COUNT="$(count_product_file_changes "$WAVE_PROGRESS_FILES")"
    if agent_mode_allows_no_product_change "${AGENT_MODE:-code}"; then
      AGENT_MODE_ALLOWS_NO_CHANGE=true
    fi
    AUTO_RETRY_CI_ATTEMPT=0
    AUTO_RETRY_CI_CONTEXT=""
    AUTO_RETRY_CI_TASK_ID=""
    AUTO_RETRY_CI_WORK_ID=""
    AUTO_RETRY_CI_NEXT_OUTPUT=""
    AUTO_RETRY_CI_TASK_DETAILS=""

    if [ "$WAVE_PROGRESS_COUNT" -eq 0 ] && [ "$AGENT_MODE_ALLOWS_NO_CHANGE" != true ]; then
      WAVE_VERDICT="IDLE"
      WAVE_FAILURE_REASON="engine:no_file_changes"
      WAVE_LEDGER_PHASE="idle"
      WAVE_NEXT_ACTION="Continue only until idle streak threshold, then stop or inspect scheduler state."
      IDLE_WAVES=$((IDLE_WAVES + 1))
      echo "No meaningful file changes detected this wave. Idle streak: $IDLE_WAVES/$MAX_IDLE_WAVES"
      echo "No meaningful file changes detected this wave. Idle streak: $IDLE_WAVES/$MAX_IDLE_WAVES" >> "$LOG_FILE"
    else
      IDLE_WAVES=0
      if [ "$AGENT_MODE_ALLOWS_NO_CHANGE" = true ] && [ "$WAVE_PRODUCT_CHANGE_COUNT" -eq 0 ]; then
        WAVE_NEXT_ACTION="${AGENT_MODE:-code} advisory wave passed review; keep implementation work in review until a code-mode wave ships product changes."
        echo "No product/source file changes detected, but ${AGENT_MODE:-code} mode allows advisory no-edit output. Sending wave to review gate."
        echo "No product/source file changes detected, but ${AGENT_MODE:-code} mode allows advisory no-edit output. Sending wave to review gate." >> "$LOG_FILE"
      fi
      local scope_violations
      scope_violations=""
      if ! scope_violations="$(printf '%s\n' "$WAVE_SCOPE_FILES" | check_write_scope 2>&1)"; then
        WAVE_VERDICT="FAIL"
        WAVE_FAILURE_REASON="scope:violation"
        WAVE_LEDGER_PHASE="review"
        WAVE_NEXT_ACTION="Remove forbidden path changes, rerun verification, and rerun the same item before reviewer gate."
        REVIEW_GATE_FAILURE_REASON="scope:violation"
        if [ "$MODE" = "taskmaster" ] && [ -n "${WORK_ID:-}" ]; then
          task-master set-status --id="$WORK_ID" --status=review >/dev/null 2>&1 || true
          TASK_STATUS_AFTER="$(taskmaster_status_for_id "$WORK_ID" 2>/dev/null || true)"
        fi
        echo "Write-scope violation detected. Failing closed before review gate."
        printf '%s\n' "$scope_violations"
        {
          echo "Write-scope violation detected. Failing closed before review gate."
          printf '%s\n' "$scope_violations"
          echo
        } >> "$LOG_FILE"
        append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "${WORK_ID:-$TASK_ID}" "$WAVE_LEDGER_PHASE" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "$EXIT_CODE" "$WAVE_PROGRESS_FILES" "$WAVE_VERDICT" "$WAVE_FAILURE_REASON" "$WAVE_RETRY_COUNT" "" "$WAVE_NEXT_ACTION" "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT" "$TASK_STATUS_BEFORE" "$TASK_STATUS_AFTER" "$WAVE_PROMPT_FILE" "$WAVE_PROMPT_SHA256" "$WAVE_GIT_HEAD" "$WAVE_GIT_STATUS" "$WAVE_PRD_PATH" "$WAVE_USAGE_FILE"
        rm -f "$WAVE_DISPLAY_FILE"
        if [ "$RUN_ONCE" = true ]; then
          echo "Run-once mode enabled. Stopping after write-scope fail on wave $WAVE."
          echo "Run-once mode enabled. Stopping after write-scope fail on wave $WAVE." >> "$LOG_FILE"
          break
        fi
        echo "Pausing 10s before next wave..."
        echo "Pausing 10s before next wave..." >> "$LOG_FILE"
        sleep 10
        WAVE=$((WAVE + 1))
        continue
      fi
      if [ "$MODE" = "taskmaster" ] && [ -n "${WORK_ID:-}" ]; then
        task-master set-status --id="$WORK_ID" --status=review >/dev/null 2>&1 || true
        TASK_STATUS_AFTER="$(taskmaster_status_for_id "$WORK_ID" 2>/dev/null || true)"
      fi
      REVIEW_GATE_FAILURE_REASON=""
      if ! apply_review_gate "$MODE" "${WORK_ID:-$TASK_ID}" "$WAVE_PROGRESS_FILES" "$WAVE_DISPLAY_FILE" "$WAVE"; then
        local review_failure_reason
        review_failure_reason="${REVIEW_GATE_FAILURE_REASON:-review:gate_failed}"
        local review_next_action
        review_next_action="Repair the same item using the generated review repair instructions."
        local latest_review
        latest_review="$(ls -1t "$LOG_DIR"/${MODE}-review-*-wave${WAVE}.log 2>/dev/null | head -n 1 || true)"
        if [ "$review_failure_reason" = "review:reviewer_unreachable" ]; then
          review_next_action="Restore the reviewer engine and rerun the review gate for the same item; no writer retry or auto-pass is trusted until the reviewer returns exit code 0."
          echo "Reviewer was unreachable. Skipping writer retry; the reviewer gate must be restored first."
          echo "Reviewer was unreachable. Skipping writer retry; the reviewer gate must be restored first." >> "$LOG_FILE"
        elif [ "$MODE" = "taskmaster" ] && [ -n "${WORK_ID:-}" ] && [ -n "$latest_review" ]; then
          local retry_actions retry_gaps retry_files retry_required retry_tests retry_pass_bar retry_prompt retry_display retry_exit
          local retry_marker retry_progress_count retry_progress_files retry_scope_files review_progress_files
          retry_actions=""
          retry_gaps=""
          retry_files=""
          retry_required=""
          retry_tests=""
          retry_pass_bar=""
          retry_prompt=""
          retry_display=""
          retry_exit=0
          retry_marker=""
          retry_progress_count=0
          retry_progress_files=""
          retry_scope_files=""
          review_progress_files="$WAVE_PROGRESS_FILES"
          retry_actions="$(extract_review_field "$latest_review" "NEXT_ACTIONS")"
          retry_gaps="$(extract_review_field "$latest_review" "GAPS")"
          retry_files="$(extract_review_field "$latest_review" "FILES_TO_TOUCH")"
          retry_required="$(extract_review_field "$latest_review" "REQUIRED_CHANGES")"
          retry_tests="$(extract_review_field "$latest_review" "TESTS_TO_RUN")"
          retry_pass_bar="$(extract_review_field "$latest_review" "PASS_BAR")"
          if [ -n "${retry_actions// }" ] || [ -n "${retry_gaps// }" ] || [ -n "${retry_required// }" ]; then
            echo "Reviewer failed the wave. Running one retry with reviewer feedback..."
            echo "Reviewer failed the wave. Running one retry with reviewer feedback..." >> "$LOG_FILE"
            retry_display="$(mktemp)"
            retry_prompt="$TASKMASTER_BASE_MISSION

Current Task ID: $TASK_ID
Current Work Item ID: $WORK_ID

Task Master next output:
$NEXT_OUTPUT

Task Master show $WORK_ID:
$TASK_DETAILS

Reviewer feedback from the failed review:
GAPS: ${retry_gaps:-none provided}
NEXT_ACTIONS: ${retry_actions:-none provided}
FILES_TO_TOUCH: ${retry_files:-none provided}
REQUIRED_CHANGES: ${retry_required:-none provided}
TESTS_TO_RUN: ${retry_tests:-none provided}
PASS_BAR: ${retry_pass_bar:-none provided}

Do not start a different task. Fix this same work item according to the reviewer feedback, re-verify it, and produce a stronger close-out."
            retry_prompt="$(apply_agent_mode_to_prompt "$retry_prompt" "${AGENT_MODE:-code}")"

            retry_exit=0
            retry_marker="$(mktemp)"
            if run_ai_turn writer "$retry_prompt" "$LOG_FILE" "$retry_display"; then
              retry_exit=0
            else
              retry_exit=$?
            fi
            retry_progress_count="$(count_wave_progress_files "$retry_marker")"
            retry_progress_files="$(print_wave_progress_files "$retry_marker")"
            retry_scope_files="$(print_wave_scope_files "$retry_marker")"
            rm -f "$retry_marker"
            review_progress_files="$(merge_changed_file_lists "$WAVE_PROGRESS_FILES" "$retry_progress_files")"
            echo "Retry meaningful files changed: $retry_progress_count"
            if [ -n "${retry_progress_files// }" ]; then
              echo "$retry_progress_files"
            fi
            {
              echo "Retry meaningful files changed: $retry_progress_count"
              if [ -n "${retry_progress_files// }" ]; then
                printf '%s\n' "$retry_progress_files"
              fi
              echo
            } >> "$LOG_FILE"
            cat "$retry_display" >> "$SUMMARY_FILE"
            if [ "$retry_exit" -eq 0 ]; then
              local retry_scope_violations
              retry_scope_violations=""
              if ! retry_scope_violations="$(merge_changed_file_lists "$WAVE_SCOPE_FILES" "$retry_scope_files" | check_write_scope 2>&1)"; then
                review_failure_reason="scope:violation"
                review_next_action="Remove forbidden path changes, rerun verification, and rerun the same item before reviewer gate."
                REVIEW_GATE_FAILURE_REASON="scope:violation"
                echo "Write-scope violation detected in retry. Failing closed before review gate."
                printf '%s\n' "$retry_scope_violations"
                {
                  echo "Write-scope violation detected in retry. Failing closed before review gate."
                  printf '%s\n' "$retry_scope_violations"
                  echo
                } >> "$LOG_FILE"
              elif apply_review_gate "$MODE" "$WORK_ID" "$review_progress_files" "$retry_display" "${WAVE}.retry"; then
                if [ "$MODE" = "taskmaster" ] && [ -n "${WORK_ID:-$TASK_ID}" ]; then
                  TASK_STATUS_AFTER="$(taskmaster_status_for_id "${WORK_ID:-$TASK_ID}" 2>/dev/null || true)"
                fi
                append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "${WORK_ID:-$TASK_ID}" "review-retry" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "$EXIT_CODE" "$review_progress_files" "PASS" "" "1" "" "Continue with next Taskmaster-ready item." "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT" "$TASK_STATUS_BEFORE" "$TASK_STATUS_AFTER" "$WAVE_PROMPT_FILE" "$WAVE_PROMPT_SHA256" "$WAVE_GIT_HEAD" "$WAVE_GIT_STATUS" "$WAVE_PRD_PATH" "$WAVE_USAGE_FILE"
                if [ "$MODE" = "taskmaster" ] && [ "${TASK_STATUS_AFTER:-}" = "done" ]; then
                  auto_checkpoint_dirty_tree "Post-review PASS checkpoint from mainspring task ${WORK_ID:-$TASK_ID}." "$AUTO_CHECKPOINT" "$LOG_FILE" "${AUTO_CHECKPOINT_DENY_PATHS[@]}" || true
                fi
                rm -f "$retry_display"
                rm -f "$WAVE_DISPLAY_FILE"
                if [ "$RUN_ONCE" = true ]; then
                  echo "Run-once mode enabled. Stopping after wave $WAVE."
                  echo "Run-once mode enabled. Stopping after wave $WAVE." >> "$LOG_FILE"
                  break
                fi
                echo "Pausing 10s before next wave..."
                echo "Pausing 10s before next wave..." >> "$LOG_FILE"
                sleep 10
                WAVE=$((WAVE + 1))
                continue
              else
                local retry_review_failure_reason
                retry_review_failure_reason="${REVIEW_GATE_FAILURE_REASON:-review:gate_failed}"
                if [ -n "${retry_review_failure_reason// }" ]; then
                  review_failure_reason="$retry_review_failure_reason"
                fi
                if [ "$retry_review_failure_reason" = "review:reviewer_unreachable" ]; then
                  review_next_action="Restore the reviewer engine and rerun the review gate for the same item; no writer retry or auto-pass is trusted until the reviewer returns exit code 0."
                  echo "Reviewer was unreachable during retry review. Skipping further writer retry; the reviewer gate must be restored first."
                  echo "Reviewer was unreachable during retry review. Skipping further writer retry; the reviewer gate must be restored first." >> "$LOG_FILE"
                fi
              fi
            fi
            rm -f "$retry_display"
          fi
        fi
        if [ "$MODE" = "taskmaster" ] && [ -n "${WORK_ID:-$TASK_ID}" ]; then
          TASK_STATUS_AFTER="$(taskmaster_status_for_id "${WORK_ID:-$TASK_ID}" 2>/dev/null || true)"
        fi
        append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "${WORK_ID:-$TASK_ID}" "review" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "$EXIT_CODE" "$WAVE_PROGRESS_FILES" "FAIL" "$review_failure_reason" "0" "" "$review_next_action" "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT" "$TASK_STATUS_BEFORE" "$TASK_STATUS_AFTER" "$WAVE_PROMPT_FILE" "$WAVE_PROMPT_SHA256" "$WAVE_GIT_HEAD" "$WAVE_GIT_STATUS" "$WAVE_PRD_PATH" "$WAVE_USAGE_FILE"
        echo "Review gate returned FAIL. Leaving work item in review and continuing to the next wave."
        echo "Review gate returned FAIL. Leaving work item in review and continuing to the next wave." >> "$LOG_FILE"
        rm -f "$WAVE_DISPLAY_FILE"
        if [ "$RUN_ONCE" = true ]; then
          echo "Run-once mode enabled. Stopping after review fail on wave $WAVE."
          echo "Run-once mode enabled. Stopping after review fail on wave $WAVE." >> "$LOG_FILE"
          break
        fi
        echo "Pausing 10s before next wave..."
        echo "Pausing 10s before next wave..." >> "$LOG_FILE"
        sleep 10
        WAVE=$((WAVE + 1))
        continue
      fi
    fi

    if [ "$MODE" = "taskmaster" ] && [ -n "${WORK_ID:-$TASK_ID}" ]; then
      TASK_STATUS_AFTER="$(taskmaster_status_for_id "${WORK_ID:-$TASK_ID}" 2>/dev/null || true)"
    fi
    append_wave_ledger "$WAVE" "$MODE" "$TOPOLOGY" "" "${WORK_ID:-$TASK_ID}" "$WAVE_LEDGER_PHASE" "$ENGINE" "$REVIEW_ENGINE" "$WAVE_START_EPOCH" "$(date +%s)" "$EXIT_CODE" "$WAVE_PROGRESS_FILES" "$WAVE_VERDICT" "$WAVE_FAILURE_REASON" "$WAVE_RETRY_COUNT" "" "$WAVE_NEXT_ACTION" "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT" "$TASK_STATUS_BEFORE" "$TASK_STATUS_AFTER" "$WAVE_PROMPT_FILE" "$WAVE_PROMPT_SHA256" "$WAVE_GIT_HEAD" "$WAVE_GIT_STATUS" "$WAVE_PRD_PATH" "$WAVE_USAGE_FILE"
    if [ "$MODE" = "taskmaster" ] && [ "$WAVE_VERDICT" = "PASS" ] && [ "${TASK_STATUS_AFTER:-}" = "done" ]; then
      auto_checkpoint_dirty_tree "Post-review PASS checkpoint from mainspring task ${WORK_ID:-$TASK_ID}." "$AUTO_CHECKPOINT" "$LOG_FILE" "${AUTO_CHECKPOINT_DENY_PATHS[@]}" || true
    fi
    rm -f "$WAVE_DISPLAY_FILE"

    if [ "$RUN_ONCE" = true ]; then
      echo "Run-once mode enabled. Stopping after wave $WAVE."
      echo "Run-once mode enabled. Stopping after wave $WAVE." >> "$LOG_FILE"
      break
    fi

    if [ "$IDLE_WAVES" -ge "$MAX_IDLE_WAVES" ]; then
      echo "Stopping loop after $IDLE_WAVES consecutive idle waves."
      echo "Stopping loop after $IDLE_WAVES consecutive idle waves." >> "$LOG_FILE"
      local STOP_EPOCH
      STOP_EPOCH="$(date +%s)"
      append_wave_ledger "${WAVE}-stop" "$MODE" "$TOPOLOGY" "" "${WORK_ID:-$TASK_ID}" "scheduler-stop" "$ENGINE" "$REVIEW_ENGINE" "$STOP_EPOCH" "$STOP_EPOCH" "0" "" "STOP" "routing:idle_threshold" "0" "idle_threshold" "Loop stopped after $IDLE_WAVES consecutive idle waves. Inspect Taskmaster review/blocked status or restart with mainspring --last-run when ready." "$WAVE_LEDGER_FILE" "$MODEL_OVERRIDE" "$REVIEW_MODEL_OVERRIDE" "$CODEX_REASONING_EFFORT" "$TASK_STATUS_BEFORE" "$TASK_STATUS_AFTER" "$WAVE_PROMPT_FILE" "$WAVE_PROMPT_SHA256" "$WAVE_GIT_HEAD" "$WAVE_GIT_STATUS" "$WAVE_PRD_PATH"
      break
    fi

    echo "Pausing 10s before next wave..."
    echo "Pausing 10s before next wave..." >> "$LOG_FILE"
    sleep 10
    WAVE=$((WAVE + 1))
  done
}
