#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Taskmaster JSON operations for Mainspring.

Subcommands:
    status-summary      Print task status counts + scheduler decision + integrity.
    scope-summary       Print scope safety analysis for the next work item.
    task-metadata       Print title + description for a given task/subtask ID.
    task-status         Print status for a task/subtask ID.
    pick-work-item      Print the next ready subtask ID within a parent task.
    parent-rollup       Print rollup status for a parent task's subtasks.
    next                Print the next blocker-aware work item ID.
    fallback-next       Print the next ready top-level task ID (fallback scheduler).
    collect-parallel    Print JSONL of parallel-safe work items for team fanout.
    team-skip-reason    Print why ready work was skipped by team visibility rules.
    scope-check         Audit backlog atomicity against Mainspring Method rules.

Usage:
    python3 taskmaster.py status-summary <tasks.json>
    python3 taskmaster.py scope-summary <tasks.json> [--plugins-ignored]
    python3 taskmaster.py task-metadata <tasks.json> <target_id>
    python3 taskmaster.py task-status <tasks.json> <target_id>
    python3 taskmaster.py pick-work-item <tasks.json> <target_id>
    python3 taskmaster.py parent-rollup <tasks.json> <target_id>
    python3 taskmaster.py next <tasks.json> [--active-prd <path>]
    python3 taskmaster.py fallback-next <tasks.json>
    python3 taskmaster.py collect-parallel <tasks.json> [--limit N]
    python3 taskmaster.py team-skip-reason <tasks.json>
    python3 taskmaster.py scope-check <tasks.json>
"""

from __future__ import annotations

from cli_runtime import run_cli

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

DEFAULT_TEAM_EXCLUDE_PREFIXES = ".claude"
DEFAULT_TASKMASTER_DISPLAY_PATH = ".taskmaster/tasks/tasks.json"
ACTIVE_STATUSES = {"pending", "in-progress", "review", "blocked"}
MANUAL_BLOCKER_RE = re.compile(
    r"\b(secret|api\s+key|sign[- ]off|submission|live\s+account|human\s+review)\b",
    re.IGNORECASE,
)
ACCEPTANCE_RE = re.compile(
    r"\b(acceptance\s+criteria|definition\s+of\s+done|done\s+when|success\s+criteria)\b",
    re.IGNORECASE,
)
TEST_PLAN_RE = re.compile(
    r"\b(test\s+plan|test\s+strategy|targeted\s+tests?|manual\s+verification|"
    r"verification|pytest|vitest|bats|typecheck|build)\b",
    re.IGNORECASE,
)
OVERSIZED_EFFORT_RE = re.compile(
    r"(>\s*half[- ]day|more\s+than\s+half[- ]day|full[- ]day|"
    r"\b(?:[5-9]|[1-9][0-9]+)\s*(?:h|hr|hrs|hours)\b|"
    r"\b(?:1|[2-9]|[1-9][0-9]+)\s*(?:day|days)\b)",
    re.IGNORECASE,
)
VAGUE_TITLE_RE = re.compile(
    r"^\s*(?:improve|clean\s+up|cleanup|make\s+better|polish|enhance)\b",
    re.IGNORECASE,
)


def _active_tag(tasks_file: str) -> str:
    """Resolve the active Task Master tag for *tasks_file*.

    Order:
    1. ``MAINSPRING_TASKMASTER_TAG`` env var (explicit override).
    2. ``state.json`` adjacent to ``tasks_file`` (Task Master writes
       ``currentTag`` there when ``task-master use-tag`` runs).
    3. Fall back to ``master``.
    """
    env_tag = os.environ.get("MAINSPRING_TASKMASTER_TAG", "").strip()
    if env_tag:
        return env_tag

    state_path = Path(tasks_file).parent.parent / "state.json"
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            tag = str(state.get("currentTag") or "").strip()
            if tag:
                return tag
        except Exception:
            pass

    return "master"


def _load_tasks(tasks_file: str) -> list[dict]:
    path = Path(tasks_file)
    obj = json.loads(path.read_text(encoding="utf-8"))
    tag = _active_tag(tasks_file)
    tasks = obj.get(tag, {}).get("tasks", [])
    if not isinstance(tasks, list):
        raise TypeError("Selected Taskmaster tag tasks must be an array")
    return tasks


def _display_tasks_path(tasks_file: str) -> str:
    path = Path(tasks_file)
    parts = path.parts
    needle = (".taskmaster", "tasks", "tasks.json")
    for index in range(0, max(len(parts) - len(needle) + 1, 0)):
        if parts[index : index + len(needle)] == needle:
            return DEFAULT_TASKMASTER_DISPLAY_PATH
    if path.is_absolute():
        try:
            return str(path.relative_to(Path.cwd()))
        except ValueError:
            return path.name or str(path)
    return str(path)


def _format_tasks_load_error(command: str, tasks_file: str, exc: Exception) -> str:
    display_path = _display_tasks_path(tasks_file)
    if isinstance(exc, FileNotFoundError):
        return (
            f"{command}: Taskmaster backlog not found at {display_path}\n"
            "Run mainspring init checkout-redesign to scaffold a Product "
            "Requirements Document (PRD); replace checkout-redesign with your "
            "feature name. Or pass a Taskmaster tasks.json path."
        )
    if isinstance(exc, json.JSONDecodeError):
        return f"{command}: Taskmaster backlog is not valid JSON: {display_path}"
    if isinstance(exc, PermissionError):
        return f"{command}: Taskmaster backlog is not readable: {display_path}"
    return f"{command}: unable to read Taskmaster backlog: {display_path}"


def _rank(status: str) -> int:
    return {"in-progress": 0, "pending": 1, "review": 2}.get(status, 99)


def _dep_done(dep_id: str, by_id: dict[str, dict]) -> bool:
    task = by_id.get(str(dep_id))
    return bool(task and task.get("status") == "done")


def _task_deps_done(task: dict, by_id: dict[str, dict]) -> bool:
    dependencies = task.get("dependencies")
    return dependencies is None or (
        isinstance(dependencies, list)
        and all(_dep_done(dep, by_id) for dep in dependencies)
    )


def _sub_deps_done(task: dict, sub: dict) -> bool:
    dependencies = sub.get("dependencies", [])
    if dependencies is None:
        dependencies = []
    if not isinstance(dependencies, list):
        return False
    done = {
        str(s.get("id"))
        for s in task.get("subtasks", []) or []
        if s.get("status") == "done"
    }
    return all(str(dep) in done for dep in dependencies)


def _find_task_item(tasks_file: str, target_id: str) -> dict | None:
    """Return the task or subtask matching *target_id*."""
    for task in _load_tasks(tasks_file):
        if str(task.get("id")) == target_id:
            return task
        for sub in task.get("subtasks", []) or []:
            sid = f"{task.get('id')}.{sub.get('id')}"
            if sid == target_id:
                return sub
    return None


def _team_exclude_prefixes() -> list[str]:
    raw = os.environ.get("MAINSPRING_TEAM_EXCLUDE_PREFIXES")
    if raw is None:
        raw = DEFAULT_TEAM_EXCLUDE_PREFIXES
    elif raw.strip():
        raw = f"{DEFAULT_TEAM_EXCLUDE_PREFIXES}:{raw}"
    else:
        raw = DEFAULT_TEAM_EXCLUDE_PREFIXES
    return [
        part.strip().removeprefix("./").rstrip("/")
        for part in raw.replace(",", ":").split(":")
        if part.strip()
    ]


def _task_scope_text(task: dict, sub: dict | None = None) -> str:
    parts: list[str] = []
    for source in (task, sub):
        if not source:
            continue
        for key in ("title", "description", "details", "testStrategy"):
            value = source.get(key)
            if value:
                parts.append(str(value))
    return "\n".join(parts)


def _item_text(item: dict) -> str:
    parts: list[str] = []
    for key in ("title", "description", "details", "testStrategy"):
        value = item.get(key)
        if value:
            parts.append(str(value))
    return "\n".join(parts)


def _title_is_vague(title: str) -> bool:
    words = re.findall(r"[A-Za-z0-9_+-]+", title)
    return bool(VAGUE_TITLE_RE.search(title)) and len(words) <= 5


def _has_acceptance_criteria(item: dict) -> bool:
    return bool(ACCEPTANCE_RE.search(_item_text(item)))


def _has_test_plan(item: dict) -> bool:
    test_strategy = str(item.get("testStrategy") or "").strip()
    if test_strategy:
        return True
    return bool(TEST_PLAN_RE.search(_item_text(item)))


def _declares_oversized_effort(item: dict) -> bool:
    return bool(OVERSIZED_EFFORT_RE.search(_item_text(item)))


def _contains_manual_blocker(item: dict) -> bool:
    return bool(MANUAL_BLOCKER_RE.search(_item_text(item)))


def _int_or_zero(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _load_active_prd_state(active_prd_file: str | None) -> tuple[str, list[str]]:
    if not active_prd_file:
        return "", []
    path = Path(active_prd_file)
    if not path.exists():
        return "", []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "", []

    active_phase = str(
        data.get("active_phase") or data.get("current_phase") or ""
    ).strip()
    raw_order = data.get("phase_order") or data.get("phases") or []
    phase_order: list[str] = []
    if isinstance(raw_order, list):
        for item in raw_order:
            if isinstance(item, dict):
                label = item.get("id") or item.get("name") or item.get("title")
            else:
                label = item
            if label:
                phase_order.append(str(label).strip())
    return active_phase, phase_order


def _phase_score(item_text: str, active_phase: str, phase_order: list[str]) -> int:
    if not active_phase:
        return 0
    normalized_text = _normalize_label(item_text)
    active_label = _normalize_label(active_phase)
    if active_label and active_label in normalized_text:
        return 0

    normalized_order = [_normalize_label(label) for label in phase_order]
    active_index = (
        normalized_order.index(active_label) if active_label in normalized_order else -1
    )
    for index, label in enumerate(normalized_order):
        if not label or label not in normalized_text:
            continue
        if active_index >= 0 and index > active_index:
            return 20 + index
        if active_index >= 0 and index < active_index:
            return 10 + index
        return 5 + index
    return 1


def _mentions_team_excluded_path(task: dict, sub: dict | None = None) -> bool:
    return _matching_team_excluded_prefix(task, sub) is not None


def _matching_team_excluded_prefix(task: dict, sub: dict | None = None) -> str | None:
    prefixes = _team_exclude_prefixes()
    if not prefixes:
        return None
    text = _task_scope_text(task, sub)
    for prefix in prefixes:
        if prefix and prefix in text:
            return prefix
    return None


def _team_skip_reason_for_prefix(prefix: str | None) -> str:
    return "routing:plugin_invisible"


# ── status-summary ─────────────────────────────────────────────────────


def cmd_status_summary(tasks_file: str) -> None:
    """Print task status counts, scheduler decision, and integrity checks."""
    try:
        tasks = _load_tasks(tasks_file)
    except Exception as exc:
        print(f"Taskmaster: unreadable ({exc})")
        return

    counts = Counter(str(task.get("status") or "unknown") for task in tasks)
    print(
        "Taskmaster: "
        + " ".join(
            f"{s}={counts.get(s, 0)}"
            for s in ["done", "review", "in-progress", "pending", "blocked", "deferred"]
        )
    )

    by_id = {str(task.get("id")): task for task in tasks}
    integrity_warnings: list[str] = []
    for task in tasks:
        if task.get("status") != "done":
            continue
        active_children = [
            f"{task.get('id')}.{sub.get('id')}"
            for sub in task.get("subtasks", []) or []
            if str(sub.get("status") or "")
            in {"pending", "in-progress", "review", "blocked"}
        ]
        if active_children:
            integrity_warnings.append(
                f"parent #{task.get('id')} is done but has active children: "
                f"{','.join(active_children[:8])}"
            )

    candidates: list[tuple[int, int, dict]] = []
    for task in tasks:
        status = str(task.get("status") or "")
        if status not in {"pending", "in-progress", "review"}:
            continue
        if not _task_deps_done(task, by_id):
            continue
        candidates.append((_rank(status), int(task.get("id") or 0), task))

    if not candidates:
        print("scheduler: STOP_BLOCKED no ready top-level task")
        _print_integrity(integrity_warnings)
        return

    _, _, task = sorted(candidates)[0]
    task_id = str(task.get("id"))
    title = str(task.get("title") or "").strip()
    subs = task.get("subtasks", []) or []
    contradictions: list[str] = []
    ready_subs: list[tuple[int, str, str]] = []
    review_subs: list[str] = []
    blocked_subs: list[str] = []
    for sub in subs:
        sub_status = str(sub.get("status") or "")
        sid = f"{task_id}.{sub.get('id')}"
        if sub_status == "blocked":
            blocked_subs.append(sid)
        if sub_status == "review":
            review_subs.append(sid)
        deps_ok = _sub_deps_done(task, sub)
        if sub_status in {"pending", "in-progress", "review"} and deps_ok:
            ready_subs.append((_rank(sub_status), sid, sub_status))
        if sub_status in {"pending", "in-progress", "review"} and not deps_ok:
            contradictions.append(
                f"{sid} status={sub_status} has unmet subtask dependencies"
            )

    if contradictions:
        print(f"scheduler: REPAIR_STATUS #{task_id} {title}")
        for item in contradictions[:6]:
            print(f"  - {item}")
    elif not subs:
        lane = (
            "SELECT_REVIEW"
            if task.get("status") == "review"
            else "SELECT_IMPLEMENTATION"
        )
        print(f"scheduler: {lane} #{task_id} {title}")
    elif ready_subs:
        _, sid, sub_status = sorted(ready_subs)[0]
        lane = "SELECT_REVIEW" if sub_status == "review" else "SELECT_IMPLEMENTATION"
        print(f"scheduler: {lane} #{sid} from parent #{task_id} {title}")
    elif review_subs:
        print(
            f"scheduler: SELECT_REVIEW #{review_subs[0]} from parent #{task_id} {title}"
        )
    elif blocked_subs:
        print(
            f"scheduler: STOP_BLOCKED #{task_id} "
            f"blocked children={','.join(blocked_subs[:6])}"
        )
    else:
        print(f"scheduler: REPAIR_STATUS #{task_id} no ready child and no rollup path")

    _print_integrity(integrity_warnings)


def _print_integrity(warnings: list[str]) -> None:
    if warnings:
        print("integrity: REPAIR_STATUS")
        for w in warnings[:8]:
            print(f"  - {w}")
    else:
        print("integrity: ok")


# ── scope-summary ──────────────────────────────────────────────────────


def cmd_scope_summary(tasks_file: str, plugins_ignored: bool = False) -> None:
    """Print scope safety analysis for the next work item."""
    try:
        tasks = _load_tasks(tasks_file)
    except Exception as exc:
        print(_format_tasks_load_error("scope", tasks_file, exc))
        return

    by_id = {str(task.get("id")): task for task in tasks}

    def text_for(*items: dict | None) -> str:
        chunks: list[str] = []
        for item in items:
            if not item:
                continue
            for key in ("title", "description", "details", "testStrategy"):
                value = item.get(key)
                if value:
                    chunks.append(str(value))
        return "\n".join(chunks)

    parents: list[tuple[int, int, dict]] = []
    for task in tasks:
        status = str(task.get("status") or "")
        if status not in {"pending", "in-progress", "review"}:
            continue
        if _task_deps_done(task, by_id):
            parents.append((_rank(status), int(task.get("id") or 0), task))

    if not parents:
        print("scope: no ready top-level Taskmaster item")
        return

    _, _, task = sorted(parents)[0]
    task_id = str(task.get("id"))
    selected_id = task_id
    selected_sub: dict | None = None
    ready_subs: list[tuple[int, int, dict]] = []
    for sub in task.get("subtasks", []) or []:
        status = str(sub.get("status") or "")
        if status in {"pending", "in-progress", "review"} and _sub_deps_done(task, sub):
            ready_subs.append((_rank(status), int(sub.get("id") or 0), sub))
    if ready_subs:
        _, _, selected_sub = sorted(ready_subs)[0]
        selected_id = f"{task_id}.{selected_sub.get('id')}"

    text = text_for(task, selected_sub)
    excluded_prefix = _matching_team_excluded_prefix(task, selected_sub)
    paths = sorted(
        set(
            re.findall(
                r"(?:(?:apps|src|server|tests|docs|scripts|plugins)/[A-Za-z0-9_./@+-]+)",
                text,
            )
        )
    )
    print(
        f"scope: selected=#{selected_id} "
        f"excluded_scope={str(bool(excluded_prefix)).lower()} "
        f"root_ignores_excluded={str(plugins_ignored).lower()}"
    )
    if paths:
        print("scope paths: " + ", ".join(paths[:8]))
    if excluded_prefix:
        print(
            f"scope warning: selected work mentions excluded prefix '{excluded_prefix}'; "
            "team fanout will skip this task."
        )


# ── task-metadata ──────────────────────────────────────────────────────


def cmd_task_metadata(tasks_file: str, target_id: str) -> None:
    """Print title and description for a task/subtask ID."""
    item = _find_task_item(tasks_file, target_id)
    if item:
        print((item.get("title") or "").strip())
        print((item.get("description") or "").strip())


def cmd_task_status(tasks_file: str, target_id: str) -> None:
    """Print status for a task/subtask ID."""
    item = _find_task_item(tasks_file, target_id)
    if item:
        print((item.get("status") or "").strip())


# ── pick-work-item ─────────────────────────────────────────────────────


def cmd_pick_work_item(tasks_file: str, target_id: str) -> None:
    """Print the next ready subtask ID within a parent task."""
    for task in _load_tasks(tasks_file):
        if str(task.get("id")) != target_id:
            continue
        subs = task.get("subtasks", []) or []
        candidates: list[tuple[int, str]] = []
        for sub in subs:
            status = sub.get("status")
            if status in ("pending", "in-progress", "review") and _sub_deps_done(
                task, sub
            ):
                sid = f"{task.get('id')}.{sub.get('id')}"
                candidates.append((_rank(status), sid))
        if candidates:
            candidates.sort()
            print(candidates[0][1])
        else:
            print(target_id if not subs else "")
        return
    print(target_id)


# ── parent-rollup ─────────────────────────────────────────────────────


def cmd_parent_rollup(tasks_file: str, target_id: str) -> None:
    """Print rollup status for a parent task's subtasks."""
    for task in _load_tasks(tasks_file):
        if str(task.get("id")) != target_id:
            continue
        subtasks = task.get("subtasks", []) or []
        if not subtasks:
            print("")
            return
        statuses = {str(sub.get("status") or "") for sub in subtasks}
        active = {"pending", "in-progress", "review"}
        if statuses & active:
            print("")
        elif "blocked" in statuses:
            print("blocked")
        elif statuses <= {"done", "deferred"}:
            print("done")
        else:
            print("")
        return
    print("")


# ── next ───────────────────────────────────────────────────────────────


def cmd_next(tasks_file: str, active_prd_file: str | None = None) -> int:
    """Print the next blocker-aware task or subtask ID."""
    try:
        tasks = _load_tasks(tasks_file)
    except Exception as exc:
        print(_format_tasks_load_error("next", tasks_file, exc), file=sys.stderr)
        return 2

    active_phase, phase_order = _load_active_prd_state(active_prd_file)
    by_id = {str(t.get("id")): t for t in tasks}
    candidates: list[tuple[int, int, int, int, str]] = []

    for task in tasks:
        task_status = str(task.get("status") or "")
        if task_status not in ("pending", "in-progress", "review"):
            continue
        if not _task_deps_done(task, by_id):
            continue

        parent_id = _int_or_zero(task.get("id"))
        subtasks = task.get("subtasks", []) or []
        if subtasks:
            for sub in subtasks:
                sub_status = str(sub.get("status") or "")
                if sub_status not in ("pending", "in-progress", "review"):
                    continue
                if not _sub_deps_done(task, sub):
                    continue
                item_id = f"{task.get('id')}.{sub.get('id')}"
                text = _task_scope_text(task, sub)
                candidates.append(
                    (
                        _phase_score(text, active_phase, phase_order),
                        _rank(sub_status),
                        parent_id,
                        _int_or_zero(sub.get("id")),
                        item_id,
                    )
                )
        else:
            text = _task_scope_text(task)
            candidates.append(
                (
                    _phase_score(text, active_phase, phase_order),
                    _rank(task_status),
                    parent_id,
                    0,
                    str(task.get("id")),
                )
            )

    if not candidates:
        return 1

    candidates.sort()
    print(candidates[0][4])
    return 0


# ── fallback-next ──────────────────────────────────────────────────────


def cmd_fallback_next(tasks_file: str) -> None:
    """Print the next ready top-level task ID (fallback scheduler)."""
    tasks = _load_tasks(tasks_file)
    by_id = {str(t.get("id")): t for t in tasks}

    candidates: list[tuple[int, int, str]] = []
    for task in tasks:
        if task.get("status") not in ("pending", "in-progress", "review"):
            continue
        if not _task_deps_done(task, by_id):
            continue
        subs = task.get("subtasks", []) or []
        if subs:
            statuses = {str(sub.get("status") or "") for sub in subs}
            has_actionable_child = bool(statuses & {"pending", "in-progress", "review"})
            can_rollup_done = statuses <= {"done", "deferred"}
            if not has_actionable_child and not can_rollup_done:
                continue
        candidates.append(
            (_rank(task.get("status")), int(str(task.get("id"))), str(task.get("id")))
        )

    if candidates:
        candidates.sort()
        print(candidates[0][2])
    else:
        print("")


# ── collect-parallel ───────────────────────────────────────────────────


def cmd_collect_parallel(tasks_file: str, limit: int = 4) -> None:
    """Print JSONL of parallel-safe work items for team fanout."""
    limit = max(1, min(6, limit))
    tasks = _load_tasks(tasks_file)
    by_id = {str(t.get("id")): t for t in tasks}

    def extracted_scope(task: dict, sub: dict | None = None) -> list[str]:
        text = _task_scope_text(task, sub)
        paths = set(
            re.findall(
                r"(?:(?:apps|src|server|tests|docs|scripts|plugins)/[A-Za-z0-9_./@+-]+)",
                text,
            )
        )
        if not paths:
            paths.add(f".taskmaster/{task.get('id')}")
        return sorted(paths)

    def scope_conflicts(scope: list[str], selected_scopes: list[list[str]]) -> bool:
        current = set(scope)
        for existing in selected_scopes:
            for left in current:
                for right in existing:
                    if (
                        left == right
                        or left.startswith(right.rstrip("/") + "/")
                        or right.startswith(left.rstrip("/") + "/")
                    ):
                        return True
        return False

    items: list[dict] = []
    selected_parent_ids: set[str] = set()
    selected_scopes: list[list[str]] = []

    for task in tasks:
        task_status = task.get("status")
        if task_status not in ("pending", "in-progress", "review"):
            continue
        if not _task_deps_done(task, by_id):
            continue

        parent_id = str(task.get("id"))
        if parent_id in selected_parent_ids:
            continue

        subtasks = task.get("subtasks", []) or []
        ready_subs: list[dict] = []
        for sub in subtasks:
            if sub.get("status") not in ("pending", "in-progress", "review"):
                continue
            if not _sub_deps_done(task, sub):
                continue
            if _mentions_team_excluded_path(task, sub):
                continue
            scope = extracted_scope(task, sub)
            if scope_conflicts(scope, selected_scopes):
                continue
            sub["_omx_scope"] = scope
            ready_subs.append(sub)

        if ready_subs:
            sub = ready_subs[0]
            items.append(
                {
                    "id": f"{task.get('id')}.{sub.get('id')}",
                    "parent": parent_id,
                    "title": sub.get("title") or "",
                    "description": sub.get("description") or "",
                    "scope": sub.get("_omx_scope") or extracted_scope(task, sub),
                }
            )
            selected_parent_ids.add(parent_id)
            selected_scopes.append(sub.get("_omx_scope") or extracted_scope(task, sub))
        elif not subtasks and not _mentions_team_excluded_path(task):
            scope = extracted_scope(task)
            if scope_conflicts(scope, selected_scopes):
                continue
            items.append(
                {
                    "id": parent_id,
                    "parent": "",
                    "title": task.get("title") or "",
                    "description": task.get("description") or "",
                    "scope": scope,
                }
            )
            selected_parent_ids.add(parent_id)
            selected_scopes.append(scope)

    for item in items[:limit]:
        print(json.dumps(item, ensure_ascii=False))


def cmd_team_skip_reason(tasks_file: str) -> None:
    """Print the routing failure reason when ready work is team-invisible."""
    tasks = _load_tasks(tasks_file)
    by_id = {str(t.get("id")): t for t in tasks}

    for task in tasks:
        if task.get("status") not in ("pending", "in-progress", "review"):
            continue
        if not _task_deps_done(task, by_id):
            continue

        subtasks = task.get("subtasks", []) or []
        if subtasks:
            for sub in subtasks:
                if sub.get("status") not in ("pending", "in-progress", "review"):
                    continue
                if not _sub_deps_done(task, sub):
                    continue
                excluded_prefix = _matching_team_excluded_prefix(task, sub)
                if excluded_prefix:
                    print(_team_skip_reason_for_prefix(excluded_prefix))
                    return
        else:
            excluded_prefix = _matching_team_excluded_prefix(task)
            if excluded_prefix:
                print(_team_skip_reason_for_prefix(excluded_prefix))
                return

    print("")


# ── scope-check ────────────────────────────────────────────────────────


def cmd_scope_check(tasks_file: str) -> int:
    """Audit active Taskmaster items against Mainspring Method commandments."""
    try:
        tasks = _load_tasks(tasks_file)
    except Exception as exc:
        print(_format_tasks_load_error("scope-check", tasks_file, exc))
        return 2

    last_phase_id = max((_int_or_zero(task.get("id")) for task in tasks), default=0)
    violations: list[dict[str, str]] = []

    def add_violation(item_id: str, code: str, message: str, fix: str) -> None:
        violations.append(
            {
                "severity": "HIGH",
                "id": item_id,
                "code": code,
                "message": message,
                "fix": fix,
            }
        )

    def check_item(parent: dict, item: dict, item_id: str) -> None:
        title = str(item.get("title") or "").strip()
        parent_id = _int_or_zero(parent.get("id"))

        if title and _title_is_vague(title):
            add_violation(
                item_id,
                "vague-title",
                f'title is too vague: "{title}"',
                "rewrite the title with a concrete surface, file, or outcome",
            )

        if _contains_manual_blocker(item) and parent_id != last_phase_id:
            add_violation(
                item_id,
                "manual-blocker-phase",
                "manual blocker appears before the last phase",
                "split the manual action into a blocked task in the final phase",
            )

        if not _has_acceptance_criteria(item):
            add_violation(
                item_id,
                "missing-acceptance",
                "missing explicit acceptance criteria",
                "add mechanically verifiable Acceptance criteria",
            )

        if not _has_test_plan(item):
            add_violation(
                item_id,
                "missing-test-plan",
                "missing explicit test plan",
                "add targeted tests or manual verification commands",
            )

        if _declares_oversized_effort(item):
            add_violation(
                item_id,
                "oversized-effort",
                "estimated effort is larger than half-day",
                "split the task until each child is half-day or smaller",
            )

    checked = 0
    for task in tasks:
        task_status = str(task.get("status") or "")
        if task_status not in ACTIVE_STATUSES:
            continue

        parent_id = str(task.get("id"))
        subtasks = task.get("subtasks", []) or []
        active_subtasks = [
            sub for sub in subtasks if str(sub.get("status") or "") in ACTIVE_STATUSES
        ]
        if active_subtasks:
            for sub in active_subtasks:
                checked += 1
                check_item(task, sub, f"{parent_id}.{sub.get('id')}")
        else:
            checked += 1
            check_item(task, task, parent_id)

    high_count = sum(1 for violation in violations if violation["severity"] == "HIGH")
    if not violations:
        print(f"scope-check: 0 violations ({checked} active items checked)")
        return 0

    print(
        f"scope-check: {len(violations)} violation(s), "
        f"high={high_count} ({checked} active items checked)"
    )
    for violation in violations:
        print(
            f"{violation['severity']} {violation['id']} "
            f"{violation['code']}: {violation['message']}"
        )
        print(f"  fix: {violation['fix']}")
    return 1 if high_count else 0


# ── CLI entry ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: taskmaster.py <status-summary|scope-summary|task-metadata|"
            "task-status|pick-work-item|parent-rollup|next|fallback-next|"
            "collect-parallel|team-skip-reason|scope-check> [args]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    subcmd = args[0]
    if subcmd == "status-summary":
        if len(args) < 2:
            print("Usage: taskmaster.py status-summary <tasks.json>", file=sys.stderr)
            raise SystemExit(2)
        cmd_status_summary(args[1])
    elif subcmd == "scope-summary":
        if len(args) < 2:
            print(
                "Usage: taskmaster.py scope-summary <tasks.json> [--plugins-ignored]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        plugins_ignored = "--plugins-ignored" in args
        cmd_scope_summary(args[1], plugins_ignored)
    elif subcmd == "task-metadata":
        if len(args) < 3:
            print(
                "Usage: taskmaster.py task-metadata <tasks.json> <target_id>",
                file=sys.stderr,
            )
            raise SystemExit(2)
        cmd_task_metadata(args[1], args[2])
    elif subcmd == "task-status":
        if len(args) < 3:
            print(
                "Usage: taskmaster.py task-status <tasks.json> <target_id>",
                file=sys.stderr,
            )
            raise SystemExit(2)
        cmd_task_status(args[1], args[2])
    elif subcmd == "pick-work-item":
        if len(args) < 3:
            print(
                "Usage: taskmaster.py pick-work-item <tasks.json> <target_id>",
                file=sys.stderr,
            )
            raise SystemExit(2)
        cmd_pick_work_item(args[1], args[2])
    elif subcmd == "parent-rollup":
        if len(args) < 3:
            print(
                "Usage: taskmaster.py parent-rollup <tasks.json> <target_id>",
                file=sys.stderr,
            )
            raise SystemExit(2)
        cmd_parent_rollup(args[1], args[2])
    elif subcmd == "next":
        if len(args) >= 2 and args[1] in {"--help", "-h"}:
            print(
                """Usage: mainspring next [path/to/tasks.json]

Print the next blocker-aware Taskmaster work item without mutating the backlog.
Skips blocked tasks and unresolved dependencies, and prefers the active PRD
phase recorded in .mainspring/state/active-prd.json when present.

Examples:
  mainspring next
  mainspring next .taskmaster/tasks/tasks.json
"""
            )
            raise SystemExit(0)
        if len(args) < 2:
            print(
                "Usage: mainspring next [path/to/tasks.json]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        active_prd_file = None
        if "--active-prd" in args:
            idx = args.index("--active-prd")
            if idx + 1 >= len(args):
                print("Usage: --active-prd requires a path", file=sys.stderr)
                raise SystemExit(2)
            active_prd_file = args[idx + 1]
        raise SystemExit(cmd_next(args[1], active_prd_file))
    elif subcmd == "fallback-next":
        if len(args) < 2:
            print("Usage: taskmaster.py fallback-next <tasks.json>", file=sys.stderr)
            raise SystemExit(2)
        cmd_fallback_next(args[1])
    elif subcmd == "collect-parallel":
        if len(args) < 2:
            print(
                "Usage: taskmaster.py collect-parallel <tasks.json> [--limit N]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        limit = 4
        if "--limit" in args:
            idx = args.index("--limit")
            if idx + 1 < len(args):
                try:
                    limit = int(args[idx + 1])
                except ValueError:
                    pass
        cmd_collect_parallel(args[1], limit)
    elif subcmd == "team-skip-reason":
        if len(args) < 2:
            print("Usage: taskmaster.py team-skip-reason <tasks.json>", file=sys.stderr)
            raise SystemExit(2)
        cmd_team_skip_reason(args[1])
    elif subcmd == "scope-check":
        if len(args) >= 2 and args[1] in {"--help", "-h"}:
            print(
                """Usage: mainspring scope-check [path/to/tasks.json]

Audit active Taskmaster items before execution. Flags vague titles, missing
acceptance criteria, missing test plans, oversized tasks, and manual blockers
that are not deferred to the final phase.

Examples:
  mainspring scope-check
  mainspring scope-check .taskmaster/tasks/tasks.json
"""
            )
            raise SystemExit(0)
        if len(args) < 2:
            print(
                "Usage: mainspring scope-check [path/to/tasks.json]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        raise SystemExit(cmd_scope_check(args[1]))
    else:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    run_cli(main)
