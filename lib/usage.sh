#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring engine usage/quota snapshots
# Globals read: MAINSPRING_PY_DIR
# Globals written: none

codex_usage_snapshot() {
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_quota.py" codex
}

claude_usage_snapshot() {
  local probe_file
  probe_file="$(mktemp)"
  if claude -p --dangerously-skip-permissions --verbose --output-format stream-json --include-partial-messages 'Reply exactly: ok' >"$probe_file" 2>/dev/null; then
    "$(mainspring_python)" "$MAINSPRING_PY_DIR/engine_quota.py" claude "$probe_file"
  else
    echo "Claude Code|short_remaining=unknown|short_window=unknown|short_reset=unknown|long_remaining=unknown|long_window=unknown|long_reset=unknown|status=probe-failed"
  fi
  rm -f "$probe_file"
}

print_usage_snapshot() {
  echo "Usage snapshot (best effort):"
  local codex_line
  codex_line="$(codex_usage_snapshot)"
  local claude_line
  claude_line="$(claude_usage_snapshot)"

  local codex_short_remaining codex_short_window codex_short_reset codex_long_remaining codex_long_window codex_long_reset codex_plan
  codex_short_remaining="$(printf '%s' "$codex_line" | sed -n 's/.*short_remaining=\([^|]*\).*/\1/p')"
  codex_short_window="$(printf '%s' "$codex_line" | sed -n 's/.*short_window=\([^|]*\).*/\1/p')"
  codex_short_reset="$(printf '%s' "$codex_line" | sed -n 's/.*short_reset=\([^|]*\).*/\1/p')"
  codex_long_remaining="$(printf '%s' "$codex_line" | sed -n 's/.*long_remaining=\([^|]*\).*/\1/p')"
  codex_long_window="$(printf '%s' "$codex_line" | sed -n 's/.*long_window=\([^|]*\).*/\1/p')"
  codex_long_reset="$(printf '%s' "$codex_line" | sed -n 's/.*long_reset=\([^|]*\).*/\1/p')"
  codex_plan="$(printf '%s' "$codex_line" | sed -n 's/.*plan=\([^|]*\).*/\1/p')"

  local claude_short_remaining claude_short_window claude_short_reset claude_long_remaining claude_long_window claude_long_reset claude_status
  claude_short_remaining="$(printf '%s' "$claude_line" | sed -n 's/.*short_remaining=\([^|]*\).*/\1/p')"
  claude_short_window="$(printf '%s' "$claude_line" | sed -n 's/.*short_window=\([^|]*\).*/\1/p')"
  claude_short_reset="$(printf '%s' "$claude_line" | sed -n 's/.*short_reset=\([^|]*\).*/\1/p')"
  claude_long_remaining="$(printf '%s' "$claude_line" | sed -n 's/.*long_remaining=\([^|]*\).*/\1/p')"
  claude_long_window="$(printf '%s' "$claude_line" | sed -n 's/.*long_window=\([^|]*\).*/\1/p')"
  claude_long_reset="$(printf '%s' "$claude_line" | sed -n 's/.*long_reset=\([^|]*\).*/\1/p')"
  claude_status="$(printf '%s' "$claude_line" | sed -n 's/.*status=\([^|]*\).*/\1/p')"

  [ -n "$codex_short_reset" ] && [ "$codex_short_reset" != "unknown" ] && codex_short_reset="$(format_epoch_local "$codex_short_reset")"
  [ -n "$codex_long_reset" ] && [ "$codex_long_reset" != "unknown" ] && codex_long_reset="$(format_epoch_local "$codex_long_reset")"
  [ -n "$claude_short_reset" ] && [ "$claude_short_reset" != "unknown" ] && claude_short_reset="$(format_epoch_local "$claude_short_reset")"
  [ -n "$claude_long_reset" ] && [ "$claude_long_reset" != "unknown" ] && claude_long_reset="$(format_epoch_local "$claude_long_reset")"

  echo "  Codex (${codex_plan:-unknown}):"
  echo "    - Short window remaining: ${codex_short_remaining:-unknown}% (${codex_short_window:-unknown}), reset ${codex_short_reset:-unknown}"
  echo "    - Long window remaining:  ${codex_long_remaining:-unknown}% (${codex_long_window:-unknown}), reset ${codex_long_reset:-unknown}"
  echo "  Claude Code:"
  echo "    - Short window remaining: ${claude_short_remaining:-not exposed} (${claude_short_window:-unknown}), reset ${claude_short_reset:-unknown}"
  echo "    - Long window remaining:  ${claude_long_remaining:-not exposed} (${claude_long_window:-not exposed}), reset ${claude_long_reset:-not exposed}"
  echo "    - Live status: ${claude_status:-unknown}"
  echo "      Official interactive command: /status"
  echo ""
}
