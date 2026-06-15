#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring bats test harness
# Usage: bash tests/bats/run.sh
set -euo pipefail
BATS_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v bats >/dev/null 2>&1; then
  echo "bats-core not found; install via: brew install bats-core" >&2
  exit 1
fi

tap_file="$(mktemp)"
normalized_tap_file="$(mktemp)"
trap 'rm -f "$tap_file" "$normalized_tap_file"' EXIT

set +e
bats "$BATS_DIR"/test_*.bats | tee "$tap_file"
bats_status="${PIPESTATUS[0]}"
set -e

if [ "$bats_status" -eq 0 ]; then
  exit 0
fi

if grep -q '^not ok ' "$tap_file"; then
  exit "$bats_status"
fi

tr -d '\r' < "$tap_file" > "$normalized_tap_file"
plan_count="$(awk '/^1\.\.[0-9]+$/ { sub(/^1\.\./, ""); plan = $0 } END { print plan }' "$normalized_tap_file")"
ok_count="$(grep -Ec '^ok [0-9]+' "$normalized_tap_file" || true)"
if [ -n "$plan_count" ] && [ "$ok_count" = "$plan_count" ]; then
  echo "bats: runner returned $bats_status after all $ok_count tests passed; normalizing"
  exit 0
fi

echo "bats: runner returned $bats_status; TAP plan=${plan_count:-unknown} ok=$ok_count" >&2
exit "$bats_status"
