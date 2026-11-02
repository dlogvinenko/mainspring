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
  source "$COMMON_LIB"
  # Stub out task_metadata_for_id so wave.sh doesn't need python/taskmaster
  task_metadata_for_id() { echo ""; }
  source "$WAVE_LIB"
}

_declared_tools_without_ripgrep() {
  local tool_path="$BATS_TEST_TMPDIR/declared-tools"
  local tool executable
  mkdir -p "$tool_path"
  for tool in awk basename cat cut date dirname find grep head mkdir mktemp rm sed seq sleep sort stat tail tr uname wc; do
    executable="$(type -P "$tool")"
    [ -n "$executable" ] || return 1
    ln -s "$executable" "$tool_path/$tool" || return 1
  done
  printf '%s\n' "$tool_path"
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

# Scenario: a source install has ordinary POSIX tools but no optional search tool.
# Expected: the existing category priority and docs-only matching still work.
@test "CI and docs classifiers work with declared tools without ripgrep" {
  local tool_path output_file category
  tool_path="$(_declared_tools_without_ripgrep)"
  run /usr/bin/env "PATH=$tool_path" /bin/bash --noprofile --norc -c 'command -v rg'
  [ "$status" -eq 1 ]

  output_file="$BATS_TEST_TMPDIR/classifier-output.txt"
  for category in typecheck_fail lint_fail test_fail; do
    case "$category" in
      typecheck_fail) printf '%s\n' 'Tests failed' 'Lint failed' 'Typecheck failed' > "$output_file" ;;
      lint_fail) printf '%s\n' 'Tests failed' 'Lint failed' > "$output_file" ;;
      test_fail) printf '%s\n' 'Tests failed' > "$output_file" ;;
    esac
    run /usr/bin/env "PATH=$tool_path" /bin/bash --noprofile --norc -c \
      'source "$1"; classify_ci_failure_reason "$2"' synthetic "$WAVE_LIB" "$output_file"
    [ "$status" -eq 0 ]
    [ "$output" = "$category" ]
  done

  printf '%s\n' 'ordinary writer output' > "$output_file"
  run /usr/bin/env "PATH=$tool_path" /bin/bash --noprofile --norc -c \
    'source "$1"; classify_ci_failure_reason "$2"' synthetic "$WAVE_LIB" "$output_file"
  [ "$status" -eq 1 ]
  [ -z "$output" ]

  printf '%s\n' 'fresh-clone portability gate' > "$output_file"
  run /usr/bin/env "PATH=$tool_path" /bin/bash --noprofile --norc -c \
    'source "$1"; task_metadata_for_id() { cat "$1"; }; task_allows_docs_only "$2"' \
    synthetic "$WAVE_LIB" "$output_file"
  [ "$status" -eq 0 ]
  printf '%s\n' 'ordinary implementation' > "$output_file"
  run /usr/bin/env "PATH=$tool_path" /bin/bash --noprofile --norc -c \
    'source "$1"; task_metadata_for_id() { cat "$1"; }; task_allows_docs_only "$2"' \
    synthetic "$WAVE_LIB" "$output_file"
  [ "$status" -eq 1 ]
}

# Scenario: a missing optional search binary previously erased a known CI reason.
# Expected: the real loop retains failure attribution and the configured retry.
@test "clean error and retry routes work without ripgrep" {
  local tool_path scenario case_dir project
  tool_path="$(_declared_tools_without_ripgrep)"
  for scenario in clean_failed_no_retry clean_ci_retry; do
    case_dir="$BATS_TEST_TMPDIR/$scenario-case"
    project="$BATS_TEST_TMPDIR/$scenario-project"
    run /usr/bin/env "PATH=$tool_path" /bin/bash --noprofile --norc \
      "$ROOT_DIR/tests/bats/native_loop_harness.sh" "$ROOT_DIR" "$project" "$scenario" "$case_dir"
    if [ "$scenario" = clean_failed_no_retry ]; then
      [ "$status" -eq 1 ]
      [ "$(wc -l < "$case_dir/writers" | tr -d ' ')" -eq 1 ]
      [ ! -s "$case_dir/checkpoints" ]
    else
      [ "$status" -eq 0 ]
      grep -q 'PASS|' "$case_dir/ledger"
      [ "$(wc -l < "$case_dir/writers" | tr -d ' ')" -eq 2 ]
      [ "$(wc -l < "$case_dir/checkpoints" | tr -d ' ')" -eq 1 ]
    fi
    grep -q 'ERROR|engine:typecheck_fail' "$case_dir/ledger"
    ! grep -q 'scope:violation' "$case_dir/ledger"
  done
}

# Scenario: the public launcher is used on the same declared-tool installation.
# Expected: a dry run resolves normally without invoking a model or notifier.
@test "public dry run supports declared tools without ripgrep" {
  local tool_path project python
  tool_path="$(_declared_tools_without_ripgrep)"
  project="$BATS_TEST_TMPDIR/public-project"
  mkdir -p "$project"
  python="${MAINSPRING_PY:-$(type -P python3)}"
  run /usr/bin/env "PATH=$tool_path" "MAINSPRING_PY=$python" MAINSPRING_NOTIFY_ENABLED=0 \
    "$ROOT_DIR/mainspring.sh" --project "$project" taskmaster --dry-run --once
  [ "$status" -eq 0 ]
  [[ "$output" == *"Writer engine:"* ]]
  [[ "$output" == *"Reviewer engine:"* ]]
  [[ "$output" != *"command not found"* ]]
}

# Scenario: raw compiler output can mix an ASCII marker with undecodable bytes.
# Expected: caller locale never erases the known category or docs-only marker.
@test "wave matching retains markers beside invalid UTF-8 bytes" {
  local tool_path utf8_locale locale_name output_file placement
  tool_path="$(_declared_tools_without_ripgrep)"
  utf8_locale=""
  while IFS= read -r locale_name; do
    case "$locale_name" in
      *UTF-8|*utf8|*utf-8) utf8_locale="$locale_name"; break ;;
    esac
  done < <(locale -a)
  [ -n "$utf8_locale" ]

  output_file="$BATS_TEST_TMPDIR/raw-output.txt"
  for placement in prefix suffix; do
    if [ "$placement" = prefix ]; then
      printf '\377Typecheck failed\n' > "$output_file"
    else
      printf 'Typecheck failed\377\n' > "$output_file"
    fi
    run /usr/bin/env "PATH=$tool_path" "LC_ALL=$utf8_locale" /bin/bash --noprofile --norc -c \
      'source "$1"; classify_ci_failure_reason "$2"' synthetic "$WAVE_LIB" "$output_file"
    [ "$status" -eq 0 ]
    [ "$output" = typecheck_fail ]
  done

  printf '\377documentation\n' > "$output_file"
  run /usr/bin/env "PATH=$tool_path" "LC_ALL=$utf8_locale" /bin/bash --noprofile --norc -c \
    'source "$1"; task_metadata_for_id() { cat "$1"; }; task_allows_docs_only "$2"' \
    synthetic "$WAVE_LIB" "$output_file"
  [ "$status" -eq 0 ]
}
