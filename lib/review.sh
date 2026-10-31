#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring review gate — prompt build, validation, repair instructions
# Globals read: ROOT_DIR, LOG_DIR, MODE, REVIEW_ENGINE, REVIEW_MODEL_OVERRIDE,
#   SUMMARY_FILE, MAINSPRING_PY_DIR, AGENT_MODE
# Globals written: none
# Depends on: engines.sh (run_ai_turn), wave.sh (count_product_file_changes,
#   task_allows_docs_only), taskmaster_helpers.sh (task_metadata_for_id)

writer_output_fingerprint() {
  local display_file="$1"
  if [ ! -f "$display_file" ]; then
    echo "present=false"
    echo "bytes=0"
    echo "crc32=missing"
    return 0
  fi

  local byte_count checksum
  byte_count="$(wc -c < "$display_file" 2>/dev/null | tr -d '[:space:]' || true)"
  [ -n "$byte_count" ] || byte_count=0
  echo "present=true"
  echo "bytes=$byte_count"

  checksum="$(cksum "$display_file" 2>/dev/null | awk '{print $1}' || true)"
  if [ -n "$checksum" ]; then
    echo "crc32=$checksum"
  else
    echo "crc32=unavailable"
  fi
}

build_review_prompt() {
  local mode="$1"
  local target_id="$2"
  local display_file="$3"
  local changed_files="$4"
  cat <<EOF
You are the review gate.

FIRST read (skip any that are not present):
- AGENTS.md
- CLAUDE.md
- docs/prd.md

Review the just-completed wave.

Mode: $mode
Task or slice id: $target_id
Writer role mode: ${AGENT_MODE:-code}

Changed files:
$changed_files

Writer output fingerprint:
$(writer_output_fingerprint "$display_file")

Writer report / human-readable output:
$(cat "$display_file" 2>/dev/null)

$(agent_mode_review_contract "${AGENT_MODE:-code}")

Rules:
- Do not be polite.
- FAIL if the work is shallow, mostly scaffolding, mostly docs without real feature value, weakly verified, or not a real chapter/competitor/launch delta.
- PASS only if this wave materially improves product quality.

Return your verdict as a fenced JSON block with exactly these fields:

\`\`\`json
{
  "verdict": "PASS or FAIL",
  "chapters": "which PRD chapters improved",
  "chapter_delta": "+N or -N or 0",
  "competitor_delta": "+N or -N or 0",
  "launch_delta": "+N or -N or 0",
  "product_score": 0-1000,
  "strengths": "what was done well",
  "gaps": "what is still missing",
  "next_actions": "concrete next steps",
  "verification_evidence": "what was verified and how",
  "rationale": "why this verdict",
  "fail_reason_category": "none or category",
  "files_to_touch": "files that need work",
  "required_changes": "what must change to pass",
  "tests_to_run": "which tests to run",
  "pass_bar": "what would make this pass"
}
\`\`\`

If you cannot produce valid JSON, fall back to this exact line format:
REVIEW_VERDICT: PASS or FAIL
CHAPTERS: ...
CHAPTER_SCORE_DELTA: ...
COMPETITOR_DELTA: ...
LAUNCH_DELTA: ...
PRODUCT_SCORE: ...
STRENGTHS: ...
GAPS: ...
NEXT_ACTIONS: ...
VERIFICATION_EVIDENCE: ...
FAIL_REASON_CATEGORY: ...
FILES_TO_TOUCH: ...
REQUIRED_CHANGES: ...
TESTS_TO_RUN: ...
PASS_BAR: ...
RATIONALE: ...
EOF
}

append_review_ledgers() {
  local review_file="$1"
  local target_id="$2"
  local wave="$3"
  local chapter_ledger="$ROOT_DIR/.taskmaster/docs/chapter-score-ledger.md"
  local competitor_ledger="$ROOT_DIR/.taskmaster/docs/competitor-delta-ledger.md"
  local launch_ledger="$ROOT_DIR/.taskmaster/docs/launch-blocker-ledger.md"

  local verdict chapters chapter_delta competitor_delta launch_delta
  verdict="$(extract_review_field "$review_file" "REVIEW_VERDICT")"
  chapters="$(extract_review_field "$review_file" "CHAPTERS")"
  chapter_delta="$(extract_review_field "$review_file" "CHAPTER_SCORE_DELTA")"
  competitor_delta="$(extract_review_field "$review_file" "COMPETITOR_DELTA")"
  launch_delta="$(extract_review_field "$review_file" "LAUNCH_DELTA")"

  [ -f "$chapter_ledger" ] || printf "# Chapter Score Ledger\n\n| Time | Wave | Target | Chapters | Delta | Verdict |\n|---|---:|---|---|---|---|\n" > "$chapter_ledger"
  [ -f "$competitor_ledger" ] || printf "# Competitor Delta Ledger\n\n| Time | Wave | Target | Delta | Verdict |\n|---|---:|---|---|---|\n" > "$competitor_ledger"
  [ -f "$launch_ledger" ] || printf "# Launch Blocker Ledger\n\n| Time | Wave | Target | Launch Delta | Verdict |\n|---|---:|---|---|---|\n" > "$launch_ledger"

  printf "| %s | %s | %s | %s | %s | %s |\n" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$wave" "$target_id" "${chapters:-unknown}" "${chapter_delta:-unknown}" "${verdict:-unknown}" >> "$chapter_ledger"
  printf "| %s | %s | %s | %s | %s |\n" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$wave" "$target_id" "${competitor_delta:-unknown}" "${verdict:-unknown}" >> "$competitor_ledger"
  printf "| %s | %s | %s | %s | %s |\n" "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$wave" "$target_id" "${launch_delta:-unknown}" "${verdict:-unknown}" >> "$launch_ledger"
}

review_output_hard_validate() {
  local review_file="$1"
  local target_id="$2"
  local changed_files="$3"
  local reasons=()

  # Use parse_review.py validate for field-level checks
  local validate_output
  validate_output="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" validate "$review_file" 2>&1)"
  local validate_rc=$?
  if [ "$validate_rc" -ne 0 ]; then
    if [ -n "$validate_output" ]; then
      while IFS= read -r line; do
        [ -n "$line" ] && reasons+=("$line")
      done <<< "$validate_output"
    else
      reasons+=("review parser failed with exit status $validate_rc")
    fi
  fi

  local product_change_count
  product_change_count="$(count_product_file_changes "$changed_files")"
  if agent_mode_allows_no_product_change "${AGENT_MODE:-code}"; then
    local advisory_user_change_count
    advisory_user_change_count="$(printf '%s\n' "$changed_files" \
      | awk '
          NF &&
          $0 !~ /^(\.mainspring\/|\.pytest_cache\/|\.ruff_cache\/|\.taskmaster\/tasks(\/|$)|\.taskmaster\/backups\/)/ &&
          $0 !~ /(^|\/)__pycache__\// &&
          $0 !~ /\.pyc$/ &&
          $0 != "AGENTS.md" { count++ }
          END { print count + 0 }
        ')"
    if [ "$advisory_user_change_count" -gt 0 ]; then
      reasons+=("${AGENT_MODE:-code} mode is no-edit, but non-bookkeeping file changes were detected")
    fi
  fi
  if [ "$product_change_count" -eq 0 ] && ! task_allows_docs_only "$target_id" && ! agent_mode_allows_no_product_change "${AGENT_MODE:-code}"; then
    reasons+=("no product/source file changes detected for a non-doc task")
  fi

  if [ "${#reasons[@]}" -gt 0 ]; then
    printf '%s\n' "${reasons[@]}"
    return 1
  fi
  return 0
}

write_review_repair_instructions() {
  local review_file="$1"
  local target_id="$2"
  local review_log="$3"

  # Parse all fields in one call via parse_review.py
  local verdict fail_reason files_to_touch required_changes tests_to_run pass_bar gaps next_actions
  verdict="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" field "$review_file" REVIEW_VERDICT 2>/dev/null || true)"
  fail_reason="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" field "$review_file" FAIL_REASON_CATEGORY 2>/dev/null || true)"
  files_to_touch="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" field "$review_file" FILES_TO_TOUCH 2>/dev/null || true)"
  required_changes="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" field "$review_file" REQUIRED_CHANGES 2>/dev/null || true)"
  tests_to_run="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" field "$review_file" TESTS_TO_RUN 2>/dev/null || true)"
  pass_bar="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" field "$review_file" PASS_BAR 2>/dev/null || true)"
  gaps="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" field "$review_file" GAPS 2>/dev/null || true)"
  next_actions="$("$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" field "$review_file" NEXT_ACTIONS 2>/dev/null || true)"

  local repair_note
  repair_note="Review repair target for Task Master $target_id

Review verdict: ${verdict:-unknown}
Fail reason category: ${fail_reason:-unknown}
Files to touch: ${files_to_touch:-unknown}
Required changes: ${required_changes:-unknown}
Tests to run: ${tests_to_run:-unknown}
Pass bar: ${pass_bar:-unknown}
Gaps: ${gaps:-unknown}
Next actions: ${next_actions:-unknown}

Do not switch tasks. Repair this exact item, rerun the listed tests, and leave the item in review for the next review gate."

  local safe_target
  safe_target="$(printf '%s' "$target_id" | tr -c 'A-Za-z0-9._-' '-')"
  local repair_file="$LOG_DIR/review-repair-${safe_target}.md"
  printf '%s\n' "$repair_note" > "$repair_file"
  echo "Review repair instructions written: $repair_file" | tee -a "$review_log"
  if [ "$MODE" = "taskmaster" ] && [ -n "$target_id" ]; then
    if printf '%s' "$target_id" | grep -q '\.'; then
      task-master update-subtask --id="$target_id" --prompt="$repair_note" >/dev/null 2>&1 || true
    else
      task-master update-task --id="$target_id" --prompt="$repair_note" >/dev/null 2>&1 || true
    fi
  fi
}

apply_review_gate() {
  local mode="$1"
  local target_id="$2"
  local changed_files="$3"
  local display_file="$4"
  local wave="$5"
  REVIEW_GATE_FAILURE_REASON=""
  local review_log
  review_log="$LOG_DIR/${mode}-review-$(date +%Y%m%d-%H%M%S)-wave${wave}.log"
  local review_display
  review_display="$(mktemp)"
  local review_prompt
  review_prompt="$(build_review_prompt "$mode" "$target_id" "$display_file" "$changed_files")"

  echo "--- Review gate ($REVIEW_ENGINE:${REVIEW_MODEL_OVERRIDE:-default}) ---"
  local review_exit=0
  if run_ai_turn reviewer "$review_prompt" "$review_log" "$review_display"; then
    review_exit=0
  else
    review_exit=$?
    REVIEW_GATE_FAILURE_REASON="review:reviewer_unreachable"
    local partial_review_output
    partial_review_output="$(cat "$review_display" 2>/dev/null || true)"
    cat > "$review_display" <<EOF
\`\`\`json
{
  "verdict": "FAIL",
  "chapters": "none",
  "chapter_delta": "0",
  "competitor_delta": "0",
  "launch_delta": "0",
  "product_score": 0,
  "strengths": "none",
  "gaps": "Reviewer engine exited nonzero before a trusted verdict could be accepted.",
  "next_actions": "Restore the reviewer engine and rerun the review gate for this same wave.",
  "verification_evidence": "reviewer exit code $review_exit",
  "rationale": "The reviewer is the only gate; nonzero reviewer exit must fail closed regardless of partial output.",
  "fail_reason_category": "review:reviewer_unreachable",
  "files_to_touch": "none",
  "required_changes": "No writer retry should be trusted until the reviewer is reachable.",
  "tests_to_run": "rerun the failed review gate",
  "pass_bar": "reviewer returns a complete PASS review with exit code 0"
}
\`\`\`
EOF
    {
      echo "Reviewer engine exited non-zero before returning a verdict."
      echo "Review gate failure reason: review:reviewer_unreachable"
      if [ -n "$partial_review_output" ]; then
        echo "Partial reviewer output ignored because reviewer exited non-zero:"
        printf '%s\n' "$partial_review_output"
      fi
      cat "$review_display"
    } >> "$review_log"
  fi

  cat "$review_display" >> "$SUMMARY_FILE"
  append_review_ledgers "$review_display" "$target_id" "$wave"

  if [ "$review_exit" -ne 0 ]; then
    if [ "$mode" = "taskmaster" ] && [ -n "$target_id" ]; then
      task-master set-status --id="$target_id" --status=review >/dev/null 2>&1 || true
    fi
    write_review_repair_instructions "$review_display" "$target_id" "$review_log"
    echo "Review gate failed closed because reviewer exited non-zero. See: $review_log"
    cat "$review_display"
    rm -f "$review_display"
    return 1
  fi

  local hard_fail_reasons=""
  if hard_fail_reasons="$(review_output_hard_validate "$review_display" "$target_id" "$changed_files" 2>&1)"; then
    if [ "$mode" = "taskmaster" ] && [ -n "$target_id" ] && agent_mode_closes_taskmaster_item "${AGENT_MODE:-code}"; then
      task-master set-status --id="$target_id" --status=done >/dev/null 2>&1 || true
    elif [ "$mode" = "taskmaster" ] && [ -n "$target_id" ]; then
      task-master set-status --id="$target_id" --status=review >/dev/null 2>&1 || true
    fi
    rm -f "$review_display"
    return 0
  fi

  if [ "$mode" = "taskmaster" ] && [ -n "$target_id" ]; then
    task-master set-status --id="$target_id" --status=review >/dev/null 2>&1 || true
  fi
  [ -n "$REVIEW_GATE_FAILURE_REASON" ] || REVIEW_GATE_FAILURE_REASON="review:gate_failed"
  write_review_repair_instructions "$review_display" "$target_id" "$review_log"
  echo "Hard review validation failed:" | tee -a "$review_log"
  printf '%s\n' "$hard_fail_reasons" | tee -a "$review_log"
  echo "Review gate failed. See: $review_log"
  cat "$review_display"
  rm -f "$review_display"
  return 1
}

extract_review_field() {
  local review_file="$1"
  local field="$2"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/parse_review.py" field "$review_file" "$field" 2>/dev/null || true
}
