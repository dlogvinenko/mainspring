#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_review.bats — exercise extract_review_field() and review_output_hard_validate()
#   from lib/review.sh.
# Post-P4-1: these functions now delegate to parse_review.py (JSON-strict + markdown fallback).

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  COMMON_LIB="$ROOT_DIR/lib/common.sh"
  WAVE_LIB="$ROOT_DIR/lib/wave.sh"
  PROMPTS_LIB="$ROOT_DIR/lib/prompts.sh"
  REVIEW_LIB="$ROOT_DIR/lib/review.sh"
  MAINSPRING_PY_DIR="$ROOT_DIR/py"
  export MAINSPRING_PY_DIR
  TMPDIR_BATS="$(mktemp -d)"
}

teardown() {
  rm -rf "$TMPDIR_BATS"
}

_load_review() {
  if [ ! -f "$REVIEW_LIB" ]; then
    skip "required helper missing: $REVIEW_LIB"
  fi
  if ! command -v rg >/dev/null 2>&1; then
    skip "rg (ripgrep) not installed"
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    skip "python3 not installed"
  fi
  source "$COMMON_LIB"
  # Stub task_metadata_for_id to avoid python dependency
  task_metadata_for_id() { echo "$1"; }
  source "$WAVE_LIB"
  source "$PROMPTS_LIB"
  source "$REVIEW_LIB"
}

_write_full_review_markdown() {
  local file="$1"
  cat > "$file" <<'REVIEW'
REVIEW_VERDICT: PASS
CHAPTERS: Ch6 Web Product
CHAPTER_SCORE_DELTA: +40
COMPETITOR_DELTA: +15
LAUNCH_DELTA: +10
PRODUCT_SCORE: 720
STRENGTHS: solid vertical slice
GAPS: missing e2e
NEXT_ACTIONS: add integration tests
VERIFICATION_EVIDENCE: vitest run passes
FAIL_REASON_CATEGORY: none
FILES_TO_TOUCH: src/App.tsx
REQUIRED_CHANGES: none
TESTS_TO_RUN: npm test
PASS_BAR: all four gates green
RATIONALE: real product improvement
REVIEW
}

_write_full_review_json() {
  local file="$1"
  cat > "$file" <<'REVIEW'
Here is my review:

```json
{
  "verdict": "PASS",
  "chapters": "Ch6 Web Product",
  "chapter_delta": "+40",
  "competitor_delta": "+15",
  "launch_delta": "+10",
  "product_score": 720,
  "strengths": "solid vertical slice",
  "gaps": "missing e2e",
  "next_actions": "add integration tests",
  "verification_evidence": "vitest run passes",
  "rationale": "real product improvement",
  "fail_reason_category": "none",
  "files_to_touch": "src/App.tsx",
  "required_changes": "none",
  "tests_to_run": "npm test",
  "pass_bar": "all four gates green"
}
```
REVIEW
}

# --- extract_review_field tests (markdown format) ---

# Scenario: extract a field that exists in the review file (markdown).
# Expected: returns the field value.
@test "extract_review_field returns field value from markdown" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_markdown "$rf"
  result="$(extract_review_field "$rf" "REVIEW_VERDICT")"
  [ "$result" = "PASS" ]
}

# Scenario: extract a field with a complex value (markdown).
# Expected: returns the full value after the colon.
@test "extract_review_field returns multi-word value from markdown" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_markdown "$rf"
  result="$(extract_review_field "$rf" "STRENGTHS")"
  [ "$result" = "solid vertical slice" ]
}

# Scenario: extract a field that does not exist.
# Expected: returns empty string.
@test "extract_review_field returns empty for missing field" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_markdown "$rf"
  result="$(extract_review_field "$rf" "NONEXISTENT_FIELD")"
  [ -z "$result" ]
}

# --- extract_review_field tests (JSON format) ---

# Scenario: extract a field from JSON-fenced review.
# Expected: returns the field value via JSON parser.
@test "extract_review_field returns field value from JSON" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_json "$rf"
  result="$(extract_review_field "$rf" "REVIEW_VERDICT")"
  [ "$result" = "PASS" ]
}

# Scenario: extract a multi-word value from JSON-fenced review.
# Expected: returns the full value.
@test "extract_review_field returns multi-word value from JSON" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_json "$rf"
  result="$(extract_review_field "$rf" "STRENGTHS")"
  [ "$result" = "solid vertical slice" ]
}

# --- review_output_hard_validate tests (markdown) ---

# Scenario: review_output_hard_validate with a fully valid PASS review + source changes.
# Expected: returns 0 (pass).
@test "review_output_hard_validate passes for complete PASS markdown review" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_markdown "$rf"
  local changed="src/App.tsx\nserver/routes.ts"
  run review_output_hard_validate "$rf" "42" "$changed"
  [ "$status" -eq 0 ]
}

# Scenario: review_output_hard_validate with FAIL verdict (markdown).
# Expected: returns 1 with reason.
@test "review_output_hard_validate fails when markdown verdict is FAIL" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_markdown "$rf"
  sed -i '' 's/^REVIEW_VERDICT: PASS/REVIEW_VERDICT: FAIL/' "$rf"
  run review_output_hard_validate "$rf" "42" "src/App.tsx"
  [ "$status" -eq 1 ]
  [[ "$output" == *"review verdict is not PASS"* ]]
}

# Scenario: review_output_hard_validate with missing required fields (markdown).
# Expected: returns 1 with specific field names.
@test "review_output_hard_validate fails for missing markdown fields" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  echo "REVIEW_VERDICT: PASS" > "$rf"
  run review_output_hard_validate "$rf" "42" "src/App.tsx"
  [ "$status" -eq 1 ]
  [[ "$output" == *"missing CHAPTERS"* ]]
  [[ "$output" == *"missing RATIONALE"* ]]
}

# --- review_output_hard_validate tests (JSON) ---

# Scenario: review_output_hard_validate with a fully valid PASS JSON review.
# Expected: returns 0 (pass).
@test "review_output_hard_validate passes for complete PASS JSON review" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_json "$rf"
  local changed="src/App.tsx\nserver/routes.ts"
  run review_output_hard_validate "$rf" "42" "$changed"
  [ "$status" -eq 0 ]
}

# Scenario: a docs/portability task updates PRD status and generated runtime
# evidence rather than source code.
# Expected: hard validation accepts the PASS because the Taskmaster item is a
# docs-only gate.
@test "review_output_hard_validate allows portability docs evidence" {
  _load_review
  task_metadata_for_id() {
    echo "fresh clone docs/prd.md portability gate"
  }
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_json "$rf"
  local changed
  changed="$(printf 'docs/prd.md\n.mainspring/state/fresh-clone-smoke-evidence.json\n')"
  run review_output_hard_validate "$rf" "6" "$changed"
  [ "$status" -eq 0 ]
}

# Scenario: a normal implementation task tries to pass review with only docs
# and generated runtime evidence.
# Expected: hard validation still rejects the PASS because the task is not a
# docs-only gate.
@test "review_output_hard_validate rejects docs-only evidence for non-doc tasks" {
  _load_review
  task_metadata_for_id() {
    echo "implementation cleanup with no launch proof"
  }
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_json "$rf"
  local changed
  changed="$(printf 'docs/prd.md\n.mainspring/state/fresh-clone-smoke-evidence.json\n')"
  run review_output_hard_validate "$rf" "42" "$changed"
  [ "$status" -eq 1 ]
  [[ "$output" == *"no product/source file changes detected for a non-doc task"* ]]
}

# Scenario: ask mode updates Taskmaster bookkeeping while leaving product/docs untouched.
# Expected: the no-edit review can pass because scheduler bookkeeping is not writer output.
@test "review_output_hard_validate allows ask mode Taskmaster bookkeeping" {
  _load_review
  AGENT_MODE="ask"
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_json "$rf"
  local changed=".taskmaster/tasks/tasks.json"
  run review_output_hard_validate "$rf" "42" "$changed"
  [ "$status" -eq 0 ]
}

# Scenario: ask mode writer edits a docs file.
# Expected: no-edit validation fails even though docs are not product/source changes.
@test "review_output_hard_validate rejects ask mode user file edits" {
  _load_review
  AGENT_MODE="ask"
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_json "$rf"
  local changed
  changed="$(printf '.taskmaster/tasks/tasks.json\ndocs/guide.md\n')"
  run review_output_hard_validate "$rf" "42" "$changed"
  [ "$status" -eq 1 ]
  [[ "$output" == *"ask mode is no-edit, but non-bookkeeping file changes were detected"* ]]
}

# Scenario: review_output_hard_validate with FAIL verdict (JSON).
# Expected: returns 1 with reason.
@test "review_output_hard_validate fails when JSON verdict is FAIL" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  _write_full_review_json "$rf"
  # Replace PASS with FAIL in the JSON
  sed -i '' 's/"verdict": "PASS"/"verdict": "FAIL"/' "$rf"
  run review_output_hard_validate "$rf" "42" "src/App.tsx"
  [ "$status" -eq 1 ]
  [[ "$output" == *"review verdict is not PASS"* ]]
}

# Scenario: review_output_hard_validate with malformed product_score.
# Expected: returns 1 with machine-readable product score validation reason.
@test "review_output_hard_validate fails when product_score is not numeric" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  cat > "$rf" <<'REVIEW'
```json
{
  "verdict": "PASS",
  "chapters": "Ch6 Web Product",
  "chapter_delta": "+40",
  "competitor_delta": "+15",
  "launch_delta": "+10",
  "product_score": "high",
  "strengths": "solid vertical slice",
  "gaps": "missing e2e",
  "next_actions": "add integration tests",
  "verification_evidence": "vitest run passes",
  "rationale": "real product improvement",
  "fail_reason_category": "none",
  "files_to_touch": "src/App.tsx",
  "required_changes": "none",
  "tests_to_run": "npm test",
  "pass_bar": "all four gates green"
}
```
REVIEW
  run review_output_hard_validate "$rf" "42" "src/App.tsx"
  [ "$status" -eq 1 ]
  [[ "$output" == *"invalid_type:PRODUCT_SCORE"* ]]
}

# Scenario: review_output_hard_validate with malformed launch_delta.
# Expected: returns 1 with machine-readable delta validation reason.
@test "review_output_hard_validate fails when launch_delta is not numeric" {
  _load_review
  local rf="$TMPDIR_BATS/review.txt"
  cat > "$rf" <<'REVIEW'
```json
{
  "verdict": "PASS",
  "chapters": "Ch6 Web Product",
  "chapter_delta": "+40",
  "competitor_delta": "+15",
  "launch_delta": "ready",
  "product_score": 720,
  "strengths": "solid vertical slice",
  "gaps": "missing e2e",
  "next_actions": "add integration tests",
  "verification_evidence": "vitest run passes",
  "rationale": "real product improvement",
  "fail_reason_category": "none",
  "files_to_touch": "src/App.tsx",
  "required_changes": "none",
  "tests_to_run": "npm test",
  "pass_bar": "all four gates green"
}
```
REVIEW

  run review_output_hard_validate "$rf" "42" "src/App.tsx"

  [ "$status" -eq 1 ]
  [[ "$output" == *"invalid_type:LAUNCH_DELTA"* ]]
}

# --- build_review_prompt tests ---

# Scenario: build_review_prompt includes JSON format instruction.
# Expected: prompt contains fenced JSON template.
@test "build_review_prompt requests fenced JSON output" {
  _load_review
  local df="$TMPDIR_BATS/display.txt"
  echo "writer output" > "$df"
  result="$(build_review_prompt "taskmaster" "42" "$df" "src/App.tsx")"
  [[ "$result" == *'```json'* ]]
  [[ "$result" == *'"verdict"'* ]]
  [[ "$result" == *'"chapters"'* ]]
  [[ "$result" == *'"rationale"'* ]]
}

# Scenario: build_review_prompt still includes fallback format.
# Expected: prompt contains legacy FIELD: format as fallback.
@test "build_review_prompt includes markdown fallback format" {
  _load_review
  local df="$TMPDIR_BATS/display.txt"
  echo "writer output" > "$df"
  result="$(build_review_prompt "taskmaster" "42" "$df" "src/App.tsx")"
  [[ "$result" == *"REVIEW_VERDICT:"* ]]
  [[ "$result" == *"RATIONALE:"* ]]
}

# Scenario: build_review_prompt includes a byte-level fingerprint for writer output.
# Expected: reviewer prompt proves the display file was present and non-empty.
@test "build_review_prompt includes writer output fingerprint" {
  _load_review
  local df="$TMPDIR_BATS/display.txt"
  printf 'writer output' > "$df"

  result="$(build_review_prompt "taskmaster" "42" "$df" "src/App.tsx")"

  [[ "$result" == *"Writer output fingerprint:"* ]]
  [[ "$result" == *"present=true"* ]]
  [[ "$result" == *"bytes=13"* ]]
  [[ "$result" == *"crc32="* ]]
  [[ "$result" == *"Writer report / human-readable output:"* ]]
  [[ "$result" == *"writer output"* ]]
}

# Scenario: build_review_prompt is called with a missing display file.
# Expected: prompt records the missing fingerprint instead of pretending output exists.
@test "build_review_prompt fingerprints missing writer output" {
  _load_review
  local df="$TMPDIR_BATS/missing-display.txt"

  result="$(build_review_prompt "taskmaster" "42" "$df" "src/App.tsx")"

  [[ "$result" == *"Writer output fingerprint:"* ]]
  [[ "$result" == *"present=false"* ]]
  [[ "$result" == *"bytes=0"* ]]
  [[ "$result" == *"crc32=missing"* ]]
}

# Scenario: reviewer engine exits before producing a verdict.
# Expected: apply_review_gate fails closed, records reviewer_unreachable, and never marks done.
@test "apply_review_gate fails closed when reviewer is unreachable" {
  _load_review
  ROOT_DIR="$TMPDIR_BATS/root"
  LOG_DIR="$TMPDIR_BATS/logs"
  SUMMARY_FILE="$TMPDIR_BATS/summary.log"
  MODE="taskmaster"
  REVIEW_ENGINE="claude"
  REVIEW_MODEL_OVERRIDE=""
  TASK_MASTER_CALLS="$TMPDIR_BATS/task-master-calls.log"
  export TASK_MASTER_CALLS
  mkdir -p "$ROOT_DIR/.taskmaster/docs" "$LOG_DIR" "$TMPDIR_BATS/bin"
  touch "$SUMMARY_FILE" "$TASK_MASTER_CALLS"
  cat > "$TMPDIR_BATS/bin/task-master" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$TASK_MASTER_CALLS"
exit 0
SH
  chmod +x "$TMPDIR_BATS/bin/task-master"
  PATH="$TMPDIR_BATS/bin:$PATH"
  export PATH
  run_ai_turn() {
    return 77
  }
  local df="$TMPDIR_BATS/display.txt"
  echo "writer output" > "$df"
  local out="$TMPDIR_BATS/review.out"

  run apply_review_gate "taskmaster" "42" "src/App.tsx" "$df" "outage"

  [ "$status" -eq 1 ]
  printf '%s\n' "$output" > "$out"
  grep -q "review:reviewer_unreachable" "$SUMMARY_FILE"
  grep -q "review:reviewer_unreachable" "$LOG_DIR"/taskmaster-review-*-waveoutage.log
  grep -q -- "--status=review" "$TASK_MASTER_CALLS"
  if grep -q -- "--status=done" "$TASK_MASTER_CALLS"; then
    false
  fi
}

# Scenario: reviewer process writes a complete PASS JSON block but exits nonzero.
# Expected: apply_review_gate ignores partial PASS output and fails closed as reviewer_unreachable.
@test "apply_review_gate ignores partial PASS output when reviewer exits nonzero" {
  _load_review
  ROOT_DIR="$TMPDIR_BATS/root"
  LOG_DIR="$TMPDIR_BATS/logs"
  SUMMARY_FILE="$TMPDIR_BATS/summary.log"
  MODE="taskmaster"
  REVIEW_ENGINE="claude"
  REVIEW_MODEL_OVERRIDE=""
  TASK_MASTER_CALLS="$TMPDIR_BATS/task-master-calls.log"
  export TASK_MASTER_CALLS
  mkdir -p "$ROOT_DIR/.taskmaster/docs" "$LOG_DIR" "$TMPDIR_BATS/bin"
  touch "$SUMMARY_FILE" "$TASK_MASTER_CALLS"
  cat > "$TMPDIR_BATS/bin/task-master" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$TASK_MASTER_CALLS"
exit 0
SH
  chmod +x "$TMPDIR_BATS/bin/task-master"
  PATH="$TMPDIR_BATS/bin:$PATH"
  export PATH
  run_ai_turn() {
    cat > "$4" <<'REVIEW'
```json
{
  "verdict": "PASS",
  "chapters": "Unsafe partial pass",
  "chapter_delta": "+99",
  "competitor_delta": "+99",
  "launch_delta": "+99",
  "product_score": 999,
  "strengths": "partial output",
  "gaps": "none",
  "next_actions": "mark done",
  "verification_evidence": "none",
  "rationale": "partial pass before transport failure",
  "fail_reason_category": "none",
  "files_to_touch": "none",
  "required_changes": "none",
  "tests_to_run": "none",
  "pass_bar": "none"
}
```
REVIEW
    return 77
  }
  local df="$TMPDIR_BATS/display.txt"
  echo "writer output" > "$df"

  run apply_review_gate "taskmaster" "42" "src/App.tsx" "$df" "partial"

  [ "$status" -eq 1 ]
  grep -q '"verdict": "FAIL"' "$SUMMARY_FILE"
  grep -q "review:reviewer_unreachable" "$SUMMARY_FILE"
  if grep -q "Unsafe partial pass" "$SUMMARY_FILE"; then
    false
  fi
  grep -q "Partial reviewer output ignored" "$LOG_DIR"/taskmaster-review-*-wavepartial.log
  grep -q "Unsafe partial pass" "$LOG_DIR"/taskmaster-review-*-wavepartial.log
  grep -q -- "--status=review" "$TASK_MASTER_CALLS"
  if grep -q -- "--status=done" "$TASK_MASTER_CALLS"; then
    false
  fi
}
