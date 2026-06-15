#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring post-wave write-scope guard
# Globals read: none
# Globals written: none

check_write_scope() {
  local offenders=()
  local path
  while IFS= read -r path; do
    [ -z "${path// }" ] && continue
    case "$path" in
      .env|.env.*|.secret|.secret.*|*/.env|*/.env.*|*/.secret|*/.secret.*)
        offenders+=("$path")
        continue
        ;;
      .git/index|*/.git/index|.git/index.lock|*/.git/index.lock)
        continue
        ;;
      node_modules/*|*/node_modules/*|.git/*|*/.git/*)
        offenders+=("$path")
        continue
        ;;
      build/*|*/build/*|target/*|*/target/*|dist/*|*/dist/*|.gradle/*|*/.gradle/*|.next/*|*/.next/*|.nuxt/*|*/.nuxt/*|.turbo/*|*/.turbo/*|.vite/*|*/.vite/*)
        continue
        ;;
      *.db-shm|*.db-wal|*.sqlite-shm|*.sqlite-wal|*.sqlite3-shm|*.sqlite3-wal)
        continue
        ;;
      coverage/*|*/coverage/*|playwright-report/*|*/playwright-report/*|test-results/*|*/test-results/*)
        offenders+=("$path")
        continue
        ;;
      src/*|apps/*|tests/*|e2e/*|docs/*|.taskmaster/*|scripts/*|shared/*|server/*|public/*|plugins/*)
        continue
        ;;
      *)
        continue
        ;;
    esac
  done

  if [ "${#offenders[@]}" -gt 0 ]; then
    printf 'write_scope violation: %s\n' "${offenders[@]}" >&2
    return 1
  fi
  return 0
}
