#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring Taskmaster integration wrappers
# Globals read: ROOT_DIR, MAINSPRING_PY_DIR
# Globals written: none

task_metadata_for_id() {
  local target_id="$1"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" task-metadata "$ROOT_DIR/.taskmaster/tasks/tasks.json" "$target_id"
}

taskmaster_status_for_id() {
  local target_id="$1"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" task-status "$ROOT_DIR/.taskmaster/tasks/tasks.json" "$target_id"
}

pick_taskmaster_work_item() {
  local target_id="$1"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" pick-work-item "$ROOT_DIR/.taskmaster/tasks/tasks.json" "$target_id"
}

taskmaster_parent_rollup_status() {
  local target_id="$1"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" parent-rollup "$ROOT_DIR/.taskmaster/tasks/tasks.json" "$target_id"
}

fallback_taskmaster_next() {
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" fallback-next "$ROOT_DIR/.taskmaster/tasks/tasks.json"
}

collect_parallel_taskmaster_items() {
  local limit="$1"
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" collect-parallel "$ROOT_DIR/.taskmaster/tasks/tasks.json" --limit "$limit"
}

taskmaster_team_skip_reason() {
  "$(mainspring_python)" "$MAINSPRING_PY_DIR/taskmaster.py" team-skip-reason "$ROOT_DIR/.taskmaster/tasks/tasks.json"
}
