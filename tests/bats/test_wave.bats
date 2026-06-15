#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_wave.bats — exercise count_product_file_changes() from lib/wave.sh.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  COMMON_LIB="$ROOT_DIR/lib/common.sh"
  WAVE_LIB="$ROOT_DIR/lib/wave.sh"
}

_load_wave() {
  if [ ! -f "$WAVE_LIB" ]; then
    skip "required helper missing: $WAVE_LIB"
  fi
  if ! command -v rg >/dev/null 2>&1; then
    skip "rg (ripgrep) not installed"
  fi
  source "$COMMON_LIB"
  # Stub out task_metadata_for_id so wave.sh doesn't need python/taskmaster
  task_metadata_for_id() { echo ""; }
  source "$WAVE_LIB"
}

# Scenario: mixed list of source and docs files.
# Expected: only non-docs files are counted.
@test "count_product_file_changes counts source files, not docs" {
  _load_wave
  input="$(printf 'src/App.tsx\ndocs/readme.md\nserver/index.ts\n.taskmaster/tasks.json\n')"
  result="$(count_product_file_changes "$input")"
  [ "$result" = "2" ]
}

# Scenario: all docs/meta files.
# Expected: 0 product file changes.
@test "count_product_file_changes returns 0 for docs-only changes" {
  _load_wave
  input="$(printf 'docs/guide.md\nREADME.md\nCLAUDE.md\nscripts/foo.sh\n.taskmaster/config.json\n.mainspring/state/session.json\n.mainspring/logs/waves.jsonl\n')"
  result="$(count_product_file_changes "$input")"
  [ "$result" = "0" ]
}

# Scenario: a docs/portability task updates documentation instead of source code.
# Expected: docs/proof-only review validation is allowed for that task shape.
@test "task_allows_docs_only accepts portability docs gates" {
  _load_wave
  task_metadata_for_id() {
    echo "fresh clone docs/prd.md portability gate"
  }
  run task_allows_docs_only 6
  [ "$status" -eq 0 ]
}

# Scenario: a normal implementation task has only generic metadata.
# Expected: docs-only review validation is not allowed.
@test "task_allows_docs_only rejects generic implementation tasks" {
  _load_wave
  task_metadata_for_id() {
    echo "implementation cleanup with no launch proof"
  }
  run task_allows_docs_only 42
  [ "$status" -eq 1 ]
}

# Scenario: empty input.
# Expected: 0.
@test "count_product_file_changes returns 0 for empty input" {
  _load_wave
  result="$(count_product_file_changes "")"
  [ "$result" = "0" ]
}

# Scenario: whitespace-only input.
# Expected: 0.
@test "count_product_file_changes returns 0 for whitespace-only input" {
  _load_wave
  result="$(count_product_file_changes "   ")"
  [ "$result" = "0" ]
}

# Scenario: only source/product files.
# Expected: all counted.
@test "count_product_file_changes counts all product files" {
  _load_wave
  input="$(printf 'src/components/Foo.tsx\napps/example-app/server/routes.ts\nshared/utils.ts\n')"
  result="$(count_product_file_changes "$input")"
  [ "$result" = "3" ]
}

# Scenario: wave progress includes generated cache/state/build files and one source file.
# Expected: only the real source file counts as product evidence.
@test "count_product_file_changes ignores generated cache and state files" {
  _load_wave
  input="$(printf '.pytest_cache/v/cache/nodeids\n.ruff_cache/0.15.11/cache\n.taskmaster/tasks/tasks.json\n.gradle/8.10.2/fileHashes/fileHashes.bin\nbuild/test-results/test/TEST-Foo.xml\ndist/assets/app.js\ntarget/classes/App.class\nserver/tracker.db-shm\nserver/tracker.db-wal\npy/__pycache__/wave_log.cpython-314.pyc\nAGENTS.md\npy/wave_log.py\n')"
  result="$(count_product_file_changes "$input")"
  [ "$result" = "1" ]
}

# Scenario: retry and initial changed-file lists overlap and include blanks.
# Expected: merged list is stable, unique, and non-empty only.
@test "merge_changed_file_lists returns unique changed files" {
  _load_wave
  first="$(printf 'docs/note.md\nsrc/foo.ts\n')"
  second="$(printf '\nsrc/foo.ts\nsrc/bar.ts\n')"
  result="$(merge_changed_file_lists "$first" "$second")"
  [ "$result" = "$(printf 'docs/note.md\nsrc/bar.ts\nsrc/foo.ts')" ]
}

# Scenario: a writer touches ignored, generated, or sensitive paths after the wave marker.
# Expected: scope-audit discovery reports sensitive paths while omitting generated dist output and git indexes.
@test "print_wave_scope_files includes forbidden ignored-directory changes" {
  _load_wave
  project="$BATS_TEST_TMPDIR/project"
  ROOT_DIR="$project"
  marker="$BATS_TEST_TMPDIR/marker"
  mkdir -p "$project/src" "$project/node_modules/pkg" "$project/.git/hooks" "$project/dist/assets"
  touch -t 202001010000 "$marker"
  touch "$project/src/App.tsx"
  touch "$project/node_modules/pkg/index.js"
  touch "$project/.git/hooks/post-commit"
  touch "$project/.git/index"
  touch "$project/dist/assets/app.js"
  touch "$project/.env.local"

  result="$(print_wave_scope_files "$marker")"

  [[ "$result" == *"src/App.tsx"* ]]
  [[ "$result" == *"node_modules/pkg/index.js"* ]]
  [[ "$result" == *".git/hooks/post-commit"* ]]
  [[ "$result" != *".git/index"* ]]
  [[ "$result" != *"dist/assets/app.js"* ]]
  [[ "$result" == *".env.local"* ]]
}

# Scenario: normal wave progress discovery sees generated cache/state files.
# Expected: cache/state files and AGENTS.md are omitted from progress evidence.
@test "print_wave_progress_files omits generated cache and state files" {
  _load_wave
  project="$BATS_TEST_TMPDIR/project"
  ROOT_DIR="$project"
  marker="$BATS_TEST_TMPDIR/marker"
  mkdir -p \
    "$project/src" \
    "$project/.pytest_cache/v/cache" \
    "$project/.ruff_cache/0.15.11" \
    "$project/.taskmaster/tasks" \
    "$project/.gradle/8.10.2/fileHashes" \
    "$project/build/test-results/test" \
    "$project/py/__pycache__"
  touch -t 202001010000 "$marker"
  touch "$project/src/App.py"
  touch "$project/.pytest_cache/v/cache/nodeids"
  touch "$project/.ruff_cache/0.15.11/cache"
  touch "$project/.taskmaster/tasks/tasks.json"
  touch "$project/.gradle/8.10.2/fileHashes/fileHashes.bin"
  touch "$project/build/test-results/test/TEST-Foo.xml"
  touch "$project/server.db-wal"
  touch "$project/py/__pycache__/wave_log.cpython-314.pyc"
  touch "$project/AGENTS.md"

  result="$(print_wave_progress_files "$marker")"

  [[ "$result" == *"src/App.py"* ]]
  [[ "$result" != *".pytest_cache"* ]]
  [[ "$result" != *".ruff_cache"* ]]
  [[ "$result" != *".taskmaster"* ]]
  [[ "$result" != *".gradle"* ]]
  [[ "$result" != *"build/test-results"* ]]
  [[ "$result" != *"server.db-wal"* ]]
  [[ "$result" != *"__pycache__"* ]]
  [[ "$result" != *"AGENTS.md"* ]]
}

# Scenario: forbidden ignored-directory changes are discovered separately.
# Expected: normal product files are not reported by the forbidden-only helper.
@test "print_forbidden_wave_scope_files omits normal product changes" {
  _load_wave
  project="$BATS_TEST_TMPDIR/project"
  ROOT_DIR="$project"
  marker="$BATS_TEST_TMPDIR/marker"
  mkdir -p "$project/src" "$project/node_modules/pkg"
  touch -t 202001010000 "$marker"
  touch "$project/src/App.tsx"
  touch "$project/node_modules/pkg/index.js"

  result="$(print_forbidden_wave_scope_files "$marker")"

  [[ "$result" == *"node_modules/pkg/index.js"* ]]
  [[ "$result" != *"src/App.tsx"* ]]
}

# Scenario: writer output includes an explicit typecheck-failure marker.
# Expected: CI retry classifier returns the canonical engine failure leaf.
@test "classify_ci_failure_reason detects explicit typecheck marker" {
  _load_wave
  output_file="$BATS_TEST_TMPDIR/writer-output.txt"
  cat > "$output_file" <<'TXT'
npm run typecheck failed
CI_FAIL_REASON: typecheck-fail
TXT
  result="$(classify_ci_failure_reason "$output_file")"
  [ "$result" = "typecheck_fail" ]
}

# Scenario: retry budget is zero, exhausted, or still available.
# Expected: retry helper permits only positive budget with attempts below cap.
@test "auto_retry_ci_can_retry enforces retry cap" {
  _load_wave
  run auto_retry_ci_can_retry 0 0 typecheck_fail
  [ "$status" -ne 0 ]
  run auto_retry_ci_can_retry 1 1 typecheck_fail
  [ "$status" -ne 0 ]
  run auto_retry_ci_can_retry 2 1 typecheck_fail
  [ "$status" -eq 0 ]
}

# Scenario: building retry context from a captured failure output.
# Expected: context includes the readable reason, budget, and failure tail.
@test "build_auto_retry_ci_context includes failure output tail" {
  _load_wave
  output_file="$BATS_TEST_TMPDIR/writer-output.txt"
  echo "Typecheck failed in src/foo.ts" > "$output_file"
  result="$(build_auto_retry_ci_context typecheck_fail "$output_file" 1 2)"
  [[ "$result" == *"Detected CI failure: typecheck-fail"* ]]
  [[ "$result" == *"Auto-retry attempt: 1 of 2"* ]]
  [[ "$result" == *"Typecheck failed in src/foo.ts"* ]]
}

# Scenario: operator provides an external local CI log alongside writer output.
# Expected: retry context includes both the writer tail and the external log tail.
@test "build_auto_retry_ci_context includes external CI log tail" {
  _load_wave
  output_file="$BATS_TEST_TMPDIR/writer-output.txt"
  ci_log="$BATS_TEST_TMPDIR/ci.log"
  echo "writer saw npm test fail" > "$output_file"
  echo "hosted CI failure: tests/components/foo.test.ts" > "$ci_log"
  result="$(build_auto_retry_ci_context test_fail "$output_file" 1 2 "$ci_log")"
  [[ "$result" == *"Detected CI failure: test-fail"* ]]
  [[ "$result" == *"writer saw npm test fail"* ]]
  [[ "$result" == *"External CI log tail: $ci_log"* ]]
  [[ "$result" == *"hosted CI failure: tests/components/foo.test.ts"* ]]
}
