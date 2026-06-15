#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_log.bats — exercise append_wave_summary() from lib/log.sh
#   and build_review_prompt() / append_review_ledgers() from review.sh.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  COMMON_LIB="$ROOT_DIR/lib/common.sh"
  LOG_LIB="$ROOT_DIR/lib/log.sh"
  REVIEW_LIB="$ROOT_DIR/lib/review.sh"
  PROMPTS_LIB="$ROOT_DIR/lib/prompts.sh"
  WAVE_LIB="$ROOT_DIR/lib/wave.sh"
  MAINSPRING_PY_DIR="$ROOT_DIR/py"
  TMPDIR_BATS="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR_BATS"
  unset MAINSPRING_WAVE_ID_OVERRIDE
  unset MAINSPRING_REPLAYED_FROM
  unset MAINSPRING_REPLAY_OVERRIDES
}

_load_log() {
  if [ ! -f "$LOG_LIB" ]; then
    skip "required helper missing: $LOG_LIB"
  fi
  source "$COMMON_LIB"
  source "$LOG_LIB"
}

_load_review() {
  if [ ! -f "$REVIEW_LIB" ]; then
    skip "required helper missing: $REVIEW_LIB"
  fi
  if ! command -v rg >/dev/null 2>&1; then
    skip "rg (ripgrep) not installed"
  fi
  source "$COMMON_LIB"
  task_metadata_for_id() { echo "$1"; }
  source "$WAVE_LIB"
  source "$PROMPTS_LIB"
  source "$REVIEW_LIB"
}

# Scenario: append_wave_summary with a non-empty display file.
# Expected: summary file contains wave header and display content.
@test "append_wave_summary writes wave header and display content" {
  _load_log
  local summary="$TMPDIR_BATS/summary.log"
  local display="$TMPDIR_BATS/display.log"
  echo "Some writer output here" > "$display"
  append_wave_summary "$summary" "3" "taskmaster" "claude" "0" "$display"
  [ -f "$summary" ]
  grep -q "WAVE 3 SUMMARY" "$summary"
  grep -q "Mode: taskmaster" "$summary"
  grep -q "Engine: claude" "$summary"
  grep -q "Exit code: 0" "$summary"
  grep -q "Some writer output here" "$summary"
}

# Scenario: append_wave_summary with an empty display file.
# Expected: summary says "[no human-readable engine output captured]".
@test "append_wave_summary reports missing output for empty display file" {
  _load_log
  local summary="$TMPDIR_BATS/summary.log"
  local display="$TMPDIR_BATS/display.log"
  touch "$display"
  append_wave_summary "$summary" "1" "night" "codex" "1" "$display"
  grep -q "no human-readable engine output captured" "$summary"
}

# Scenario: A replay run supplies a save-as wave id and provenance.
# Expected: append_wave_ledger writes the override id and replay metadata.
@test "append_wave_ledger writes replay provenance when supplied" {
  _load_log
  local ledger="$TMPDIR_BATS/waves.jsonl"
  MAINSPRING_WAVE_ID_OVERRIDE="replay-1"
  MAINSPRING_REPLAYED_FROM="w1"
  MAINSPRING_REPLAY_OVERRIDES='{"replay_wave_id":"replay-1"}'

  append_wave_ledger "1" "night" "solo" "" "" "replay" "claude" "codex" "1000" "1005" "0" "" "PASS" "" "0" "" "" "$ledger" "" "" "xhigh"

  grep -q '"wave_id": "replay-1"' "$ledger"
  grep -q '"replayed_from": "w1"' "$ledger"
  grep -q '"replay_wave_id": "replay-1"' "$ledger"
}

# Scenario: append_wave_ledger receives a LiteLLM usage sidecar.
# Expected: the wave ledger carries explicit cost and per-role token usage.
@test "append_wave_ledger writes usage and cost from sidecar" {
  _load_log
  local ledger="$TMPDIR_BATS/waves.jsonl"
  local usage="$TMPDIR_BATS/usage.jsonl"
  printf '%s\n' \
    '{"role":"writer","usage":{"input_tokens":10,"output_tokens":4},"cost_usd":0.001,"cost_source":"litellm.completion_cost"}' \
    '{"role":"reviewer","usage":{"input_tokens":6,"output_tokens":2},"cost_usd":0.0005,"cost_source":"litellm.completion_cost"}' \
    > "$usage"

  append_wave_ledger "2" "night" "solo" "" "" "review" "litellm" "codex" "1000" "1005" "0" "docs/prd.md" "PASS" "" "0" "" "" "$ledger" "gpt-5.5" "" "xhigh" "" "" "" "" "" "" "" "$usage"

  grep -q '"cost_usd": 0.0015' "$ledger"
  grep -q '"usage"' "$ledger"
  grep -q '"writer"' "$ledger"
  grep -q '"reviewer"' "$ledger"
}

# Scenario: build_review_prompt includes mode and task id.
# Expected: prompt string contains the mode and target id.
@test "build_review_prompt includes mode and target_id" {
  _load_review
  local display="$TMPDIR_BATS/display.log"
  echo "test output" > "$display"
  result="$(build_review_prompt "taskmaster" "42.3" "$display" "src/App.tsx")"
  [[ "$result" == *"Mode: taskmaster"* ]]
  [[ "$result" == *"Task or slice id: 42.3"* ]]
  [[ "$result" == *"Writer role mode: code"* ]]
  [[ "$result" == *"src/App.tsx"* ]]
}

# Scenario: role-mode prompt contract is appended to the writer prompt.
# Expected: debug mode adds root-cause instructions without changing the base prompt.
@test "apply_agent_mode_to_prompt appends debug writer contract" {
  _load_review
  result="$(apply_agent_mode_to_prompt "Base prompt" "debug")"
  [[ "$result" == *"Base prompt"* ]]
  [[ "$result" == *"Writer role mode: debug"* ]]
  [[ "$result" == *"root cause"* ]]
}

# Scenario: architect mode is advisory and no-edit.
# Expected: changed files make hard validation fail even if the review says PASS.
@test "architect mode review validation rejects changed files" {
  _load_review
  AGENT_MODE="architect"
  local rf="$TMPDIR_BATS/review-pass.txt"
  cat > "$rf" <<'REVIEW'
REVIEW_VERDICT: PASS
CHAPTERS: Mainspring P-Comp-11
CHAPTER_SCORE_DELTA: +1
COMPETITOR_DELTA: +1
LAUNCH_DELTA: +1
PRODUCT_SCORE: 800
STRENGTHS: clear
GAPS: none
NEXT_ACTIONS: none
VERIFICATION_EVIDENCE: prompt checked
FAIL_REASON_CATEGORY: none
FILES_TO_TOUCH: none
REQUIRED_CHANGES: none
TESTS_TO_RUN: none
PASS_BAR: advisory pass
RATIONALE: valid advisory output
REVIEW
  run review_output_hard_validate "$rf" "42.3" "src/App.tsx"
  [ "$status" -eq 1 ]
  [[ "$output" == *"architect mode is no-edit"* ]]
}

# Scenario: append_review_ledgers creates ledger files and appends rows.
# Expected: all three ledger files exist with the expected data.
@test "append_review_ledgers creates and appends to ledger files" {
  _load_review
  ROOT_DIR="$TMPDIR_BATS"
  mkdir -p "$TMPDIR_BATS/.taskmaster/docs"
  local rf="$TMPDIR_BATS/review.txt"
  cat > "$rf" <<'REVIEW'
REVIEW_VERDICT: PASS
CHAPTERS: Ch6
CHAPTER_SCORE_DELTA: +40
COMPETITOR_DELTA: +15
LAUNCH_DELTA: +10
PRODUCT_SCORE: 720
STRENGTHS: good
GAPS: minor
NEXT_ACTIONS: test
RATIONALE: solid
REVIEW
  append_review_ledgers "$rf" "42" "5"
  [ -f "$TMPDIR_BATS/.taskmaster/docs/chapter-score-ledger.md" ]
  [ -f "$TMPDIR_BATS/.taskmaster/docs/competitor-delta-ledger.md" ]
  [ -f "$TMPDIR_BATS/.taskmaster/docs/launch-blocker-ledger.md" ]
  grep -q "Ch6" "$TMPDIR_BATS/.taskmaster/docs/chapter-score-ledger.md"
  grep -q "+15" "$TMPDIR_BATS/.taskmaster/docs/competitor-delta-ledger.md"
  grep -q "+10" "$TMPDIR_BATS/.taskmaster/docs/launch-blocker-ledger.md"
}
