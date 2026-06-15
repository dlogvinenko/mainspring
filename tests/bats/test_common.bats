#!/usr/bin/env bats
# SPDX-License-Identifier: Apache-2.0
# test_common.bats — exercise utility functions from lib/common.sh.

setup() {
  ROOT_DIR="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  COMMON_LIB="$ROOT_DIR/lib/common.sh"
}

_load_common() {
  if [ ! -f "$COMMON_LIB" ]; then
    skip "required helper missing: $COMMON_LIB"
  fi
  source "$COMMON_LIB"
}

# Scenario: count_nonempty_lines with mixed content (non-empty + blank lines).
# Expected: only non-empty lines are counted.
@test "count_nonempty_lines counts only non-empty lines" {
  _load_common
  result="$(printf 'a\n\nb\n  \nc\n' | count_nonempty_lines)"
  [ "$result" = "3" ]
}

# Scenario: count_nonempty_lines with all-blank input.
# Expected: returns 0.
@test "count_nonempty_lines returns 0 for blank input" {
  _load_common
  result="$(printf '\n  \n\n' | count_nonempty_lines)"
  [ "$result" = "0" ]
}

# Scenario: count_nonempty_lines with no input at all.
# Expected: returns 0.
@test "count_nonempty_lines returns 0 for empty input" {
  _load_common
  result="$(printf '' | count_nonempty_lines)"
  [ "$result" = "0" ]
}

# Scenario: print_limited_lines with default limit (20).
# Expected: only the first 20 non-empty lines are printed.
@test "print_limited_lines respects default limit of 20" {
  _load_common
  input=""
  for i in $(seq 1 30); do input+="line$i\n"; done
  result="$(printf "$input" | print_limited_lines | wc -l | tr -d ' ')"
  [ "$result" = "20" ]
}

# Scenario: print_limited_lines with custom limit.
# Expected: only the first N non-empty lines are printed.
@test "print_limited_lines respects custom limit" {
  _load_common
  result="$(printf 'a\nb\nc\nd\ne\n' | print_limited_lines 3 | wc -l | tr -d ' ')"
  [ "$result" = "3" ]
}

# Scenario: print_limited_lines filters out blank lines.
# Expected: blank lines do not count toward the limit.
@test "print_limited_lines skips blank lines" {
  _load_common
  result="$(printf 'a\n\nb\n\nc\n' | print_limited_lines 10)"
  [ "$(echo "$result" | wc -l | tr -d ' ')" = "3" ]
}

# Scenario: format_epoch_local with a valid epoch timestamp.
# Expected: returns a human-readable date string (not "unknown").
@test "format_epoch_local formats a valid epoch" {
  _load_common
  result="$(format_epoch_local 1714100000)"
  [ "$result" != "unknown" ]
  [ -n "$result" ]
}

# Scenario: format_epoch_local with empty input.
# Expected: returns "unknown".
@test "format_epoch_local returns unknown for empty input" {
  _load_common
  result="$(format_epoch_local "")"
  [ "$result" = "unknown" ]
}
