#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# install.sh — install Mainspring Method skill into Claude Code
# Usage: ./install.sh [--force] [--link]
#
#   (default)  Copy skill into ~/.claude/skills/mainspring-method/
#   --force    Overwrite existing install
#   --link     Symlink instead of copy (for development; updates in repo reflect immediately)

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/skill"
DEST="${HOME}/.claude/skills/mainspring-method"

assert_safe_dest() {
  local expected="${HOME}/.claude/skills/mainspring-method"
  case "$DEST" in
    ""|"/"|"$HOME"|"$HOME/"|"$HOME/.claude"|"$HOME/.claude/skills")
      echo "Refusing unsafe install destination: $DEST" >&2
      exit 1
      ;;
  esac
  if [ "$DEST" != "$expected" ]; then
    echo "Refusing unexpected install destination: $DEST" >&2
    echo "Expected: $expected" >&2
    exit 1
  fi
}

FORCE=0
LINK=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --link)  LINK=1 ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's|^# \?||'
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

if [ ! -d "$SRC" ]; then
  echo "Skill source not found at $SRC" >&2
  echo "Run this script from inside its containing directory, or check that 'skill/' exists." >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
assert_safe_dest

if [ -e "$DEST" ]; then
  if [ "$FORCE" -eq 1 ]; then
    echo "Removing existing install at $DEST"
    rm -rf "$DEST"
  else
    echo "Already installed at $DEST"
    echo "Pass --force to reinstall, or --force --link to switch to a symlink."
    exit 1
  fi
fi

if [ "$LINK" -eq 1 ]; then
  ln -s "$SRC" "$DEST"
  echo "Linked: $DEST -> $SRC"
else
  cp -R "$SRC" "$DEST"
  echo "Installed: $DEST"
fi

echo ""
echo "── Triggering ──────────────────────────────────────────"
echo "The skill auto-activates on phrases like:"
echo "  'let's build X', 'plan for Y', 'refactor Z',"
echo "  'new feature', 'PRD', 'method', 'doctrine'"
echo ""
echo "It skips trivial work (single-file fixes, simple questions, in-flight work)."
echo "Force-invoke with: 'apply the Mainspring Method to X'"
echo ""
echo "Done."
