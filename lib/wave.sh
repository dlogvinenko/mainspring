#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring wave progress tracking
# Globals read: ROOT_DIR, MAINSPRING_PY_DIR
# Globals written: none
# Depends on: taskmaster_helpers.sh (task_metadata_for_id)

task_allows_docs_only() {
  local target_id="$1"
  local meta
  meta="$(task_metadata_for_id "$target_id")"
  if printf '%s' "$meta" | rg -qi "$(docs_only_task_pattern)"; then
    return 0
  fi
  return 1
}

docs_only_task_pattern() {
  printf '%s' \
    'docs|documentation|glossary|reference|changelog|runbook|' \
    'privacy|compliance|legal|operator|execution baseline|' \
    'deployment templates|fresh[- ]clone|fresh box|portability gate'
}

count_product_file_changes() {
  local changed_files="$1"
  if [ -z "${changed_files// }" ]; then
    echo 0
    return
  fi
  printf '%s\n' "$changed_files" \
    | awk '
        NF &&
        $0 !~ /^(\.mainspring\/|\.pytest_cache\/|\.ruff_cache\/|docs\/|\.taskmaster\/|README\.md$|CLAUDE\.md$|AGENTS\.md$|scripts\/)/ &&
        $0 !~ /(^|\/)(build|target|dist|\.gradle|\.next|\.nuxt|\.turbo|\.vite)\// &&
        $0 !~ /(^|\/)__pycache__\// &&
        $0 !~ /\.(db|sqlite|sqlite3)-(shm|wal)$/ &&
        $0 !~ /\.pyc$/ &&
        $0 !~ /\.md$/ { count++ }
        END { print count + 0 }
      '
}

merge_changed_file_lists() {
  local first="$1"
  local second="$2"
  printf '%s\n%s\n' "$first" "$second" \
    | sed '/^[[:space:]]*$/d' \
    | sort -u
}

print_forbidden_wave_scope_files() {
  local marker_file="$1"
  local root
  {
    for root in \
      "$ROOT_DIR/node_modules" \
      "$ROOT_DIR/coverage" \
      "$ROOT_DIR/playwright-report" \
      "$ROOT_DIR/test-results"; do
      if [ -e "$root" ]; then
        find "$root" -type f -newer "$marker_file"
      fi
    done
    if [ -e "$ROOT_DIR/.git/hooks" ]; then
      find "$ROOT_DIR/.git/hooks" -type f -newer "$marker_file"
    fi
    if [ -f "$ROOT_DIR/.git/config" ] && [ "$ROOT_DIR/.git/config" -nt "$marker_file" ]; then
      printf '%s\n' "$ROOT_DIR/.git/config"
    fi
    find "$ROOT_DIR" \
      \( \
        -path "$ROOT_DIR/.git" -o \
        -path "$ROOT_DIR/node_modules" -o \
        -path "$ROOT_DIR/dist" -o \
        -path "$ROOT_DIR/coverage" -o \
        -path "$ROOT_DIR/playwright-report" -o \
        -path "$ROOT_DIR/test-results" -o \
        -path "$ROOT_DIR/.mainspring" \
      \) -prune -o \
      -type f \
      -newer "$marker_file" \
      \( -name '.env' -o -name '.env.*' -o -name '.secret' -o -name '.secret.*' \) \
      -print
  } | sed "s#^$ROOT_DIR/##" | sort -u
}

print_wave_scope_files() {
  local marker_file="$1"
  local progress_files forbidden_files
  progress_files="$(print_wave_progress_files "$marker_file")"
  forbidden_files="$(print_forbidden_wave_scope_files "$marker_file")"
  merge_changed_file_lists "$progress_files" "$forbidden_files"
}

classify_ci_failure_reason() {
  local display_file="$1"
  [ -f "$display_file" ] || return 1
  if rg -qi '(CI_FAIL_REASON|FAIL_REASON_CATEGORY):[[:space:]]*type(check)?[-_ ]fail|npm run typecheck|tsc .*error TS|Typecheck failed|typecheck failed' "$display_file"; then
    echo "typecheck_fail"
    return 0
  fi
  if rg -qi '(CI_FAIL_REASON|FAIL_REASON_CATEGORY):[[:space:]]*lint[-_ ]fail|npm run lint|eslint .*error|Lint failed|lint failed' "$display_file"; then
    echo "lint_fail"
    return 0
  fi
  if rg -qi '(CI_FAIL_REASON|FAIL_REASON_CATEGORY):[[:space:]]*test[-_ ]fail|npx vitest run|npm test|Tests? failed|test failed|vitest.*failed' "$display_file"; then
    echo "test_fail"
    return 0
  fi
  return 1
}

ci_failure_label() {
  case "$1" in
    typecheck_fail) echo "typecheck-fail" ;;
    lint_fail) echo "lint-fail" ;;
    test_fail) echo "test-fail" ;;
    *) echo "$1" ;;
  esac
}

auto_retry_ci_can_retry() {
  local limit="$1"
  local attempt="$2"
  local reason="$3"
  [[ "$limit" =~ ^[0-9]+$ ]] || return 1
  [[ "$attempt" =~ ^[0-9]+$ ]] || return 1
  [ "$limit" -gt 0 ] || return 1
  [ -n "${reason// }" ] || return 1
  [ "$attempt" -lt "$limit" ]
}

build_auto_retry_ci_context() {
  local reason="$1"
  local display_file="$2"
  local attempt="$3"
  local limit="$4"
  local external_log_file="${5:-}"
  local label
  label="$(ci_failure_label "$reason")"
  {
    echo "Detected CI failure: $label"
    echo "Auto-retry attempt: $attempt of $limit"
    echo "Previous failing wave output tail:"
    if [ -s "$display_file" ]; then
      tail -n 120 "$display_file"
    else
      echo "[no human-readable engine output captured]"
    fi
    if [ -n "${external_log_file// }" ]; then
      echo ""
      echo "External CI log tail: $external_log_file"
      if [ -r "$external_log_file" ]; then
        tail -n 160 "$external_log_file"
      else
        echo "[external CI log unavailable]"
      fi
    fi
  }
}

count_wave_progress_files() {
  local marker_file="$1"
  find "$ROOT_DIR" \
    -type f \
    -newer "$marker_file" \
    ! -path "$ROOT_DIR/.git/*" \
    ! -path "$ROOT_DIR/node_modules/*" \
    ! -path "$ROOT_DIR/build/*" \
    ! -path "$ROOT_DIR/target/*" \
    ! -path "$ROOT_DIR/.gradle/*" \
    ! -path "$ROOT_DIR/.next/*" \
    ! -path "$ROOT_DIR/.nuxt/*" \
    ! -path "$ROOT_DIR/.turbo/*" \
    ! -path "$ROOT_DIR/.vite/*" \
    ! -path "$ROOT_DIR/dist/*" \
    ! -path "$ROOT_DIR/.mainspring/*" \
    ! -path "$ROOT_DIR/.pytest_cache/*" \
    ! -path "$ROOT_DIR/.ruff_cache/*" \
    ! -path "$ROOT_DIR/.taskmaster/*" \
    ! -path "*/__pycache__/*" \
    ! -path "$ROOT_DIR/playwright-report/*" \
    ! -path "$ROOT_DIR/test-results/*" \
    ! -path "$ROOT_DIR/coverage/*" \
    ! -name '*.tsbuildinfo' \
    ! -name '*.db-shm' \
    ! -name '*.db-wal' \
    ! -name '*.sqlite-shm' \
    ! -name '*.sqlite-wal' \
    ! -name '*.sqlite3-shm' \
    ! -name '*.sqlite3-wal' \
    ! -name '*.pyc' \
    ! -name 'AGENTS.md' \
    ! -name '.DS_Store' \
    | wc -l | tr -d ' '
}

print_wave_progress_files() {
  local marker_file="$1"
  find "$ROOT_DIR" \
    -type f \
    -newer "$marker_file" \
    ! -path "$ROOT_DIR/.git/*" \
    ! -path "$ROOT_DIR/node_modules/*" \
    ! -path "$ROOT_DIR/build/*" \
    ! -path "$ROOT_DIR/target/*" \
    ! -path "$ROOT_DIR/.gradle/*" \
    ! -path "$ROOT_DIR/.next/*" \
    ! -path "$ROOT_DIR/.nuxt/*" \
    ! -path "$ROOT_DIR/.turbo/*" \
    ! -path "$ROOT_DIR/.vite/*" \
    ! -path "$ROOT_DIR/dist/*" \
    ! -path "$ROOT_DIR/.mainspring/*" \
    ! -path "$ROOT_DIR/.pytest_cache/*" \
    ! -path "$ROOT_DIR/.ruff_cache/*" \
    ! -path "$ROOT_DIR/.taskmaster/*" \
    ! -path "*/__pycache__/*" \
    ! -path "$ROOT_DIR/playwright-report/*" \
    ! -path "$ROOT_DIR/test-results/*" \
    ! -path "$ROOT_DIR/coverage/*" \
    ! -name '*.tsbuildinfo' \
    ! -name '*.db-shm' \
    ! -name '*.db-wal' \
    ! -name '*.sqlite-shm' \
    ! -name '*.sqlite-wal' \
    ! -name '*.sqlite3-shm' \
    ! -name '*.sqlite3-wal' \
    ! -name '*.pyc' \
    ! -name 'AGENTS.md' \
    ! -name '.DS_Store' \
    | sed "s#^$ROOT_DIR/##" \
    | sed -n '1,80p'
}
