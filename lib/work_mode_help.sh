#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Command-specific help for public work modes.
# Globals read: none
# Globals written: none

print_taskmaster_help() {
  cat <<'EOF'
Usage: mainspring taskmaster [--once] [--topology solo|team] [engine flags]

Run bounded writer/reviewer work from the Taskmaster backlog.

Use this when .taskmaster/tasks/tasks.json is already the source of truth. The
worker picks the next ready item, implements only that item, runs verification,
records wave evidence, and stops cleanly on missing backlog, failed preflight,
review failure, scope violation, or idle/no-work loops.

Examples:
  mainspring taskmaster --once
  mainspring taskmaster --once --pair codex+claude
  mainspring taskmaster --topology solo --pair codex+codex
  mainspring taskmaster --topology team --pair codex+codex --max-agents 6

Useful checks:
  mainspring next
  mainspring scope-check
  mainspring hud
  mainspring status
EOF
}

print_night_help() {
  cat <<'EOF'
Usage: mainspring night --prd <path> [--once] [--topology solo|team] [engine flags]

Run bounded writer/reviewer work from a Product Requirements Document (PRD).

Use this when the PRD should choose the next useful product slice. The worker
reads the PRD, selects a coherent slice, implements it, runs verification,
records wave evidence, and stops cleanly on missing PRD, failed preflight,
review failure, scope violation, or idle/no-work loops.

Examples:
  mainspring night --prd docs/prd.md --once
  mainspring night --prd docs/prd.md --once --pair codex+claude
  mainspring night --prd docs/prd.md --topology solo --pair codex+codex
  mainspring night --prd docs/prd.md --engine ollama --model 'ollama/qwen3:8b' --review-engine codex --review-model gpt-5.5 --dry-run --once

Useful checks:
  mainspring validate-prd docs/prd.md
  mainspring decompose docs/prd.md --phase P1
  mainspring hud
  mainspring status
EOF
}
