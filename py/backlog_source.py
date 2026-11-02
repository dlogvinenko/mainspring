# SPDX-License-Identifier: Apache-2.0
"""Backlog source protocol and Taskmaster-backed adapter."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

ACTIONABLE_STATUSES = {"pending", "in-progress", "review"}


class BacklogSourceError(RuntimeError):
    """Raised when a backlog source cannot complete a requested mutation."""


@dataclass(frozen=True)
class BacklogItem:
    """Normalized backlog item exposed by Mainspring backlog sources."""

    id: str
    title: str = ""
    description: str = ""
    status: str = ""
    parent_id: str | None = None
    details: str = ""
    test_strategy: str = ""


class BacklogSource(Protocol):
    """Common interface for backlog providers.

    v1.0 ships only the Taskmaster adapter. Future adapters should preserve
    these fail-closed mutation semantics instead of silently swallowing errors.
    """

    def list_ready_tasks(
        self,
        *,
        active_prd_file: str | Path | None = None,
        limit: int | None = None,
    ) -> list[BacklogItem]:
        """Return ready backlog items in scheduler order."""

    def get_details(self, item_id: str) -> BacklogItem | None:
        """Return normalized details for a backlog item, if present."""

    def mark_done(self, item_id: str) -> None:
        """Mark a backlog item done or raise ``BacklogSourceError``."""

    def mark_blocked(self, item_id: str, reason: str) -> None:
        """Mark a backlog item blocked or raise ``BacklogSourceError``."""


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _rank(status: str) -> int:
    return {"in-progress": 0, "pending": 1, "review": 2}.get(status, 99)


def _int_or_zero(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _normalize_label(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _dep_done(dep_id: str, by_id: dict[str, dict]) -> bool:
    task = by_id.get(str(dep_id))
    return bool(task and task.get("status") == "done")


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


def _item_text(task: dict, sub: dict | None = None) -> str:
    chunks: list[str] = []
    for source in (task, sub):
        if not source:
            continue
        for key in ("title", "description", "details", "testStrategy"):
            value = source.get(key)
            if value:
                chunks.append(str(value))
    return "\n".join(chunks)


def _load_active_prd_state(active_prd_file: str | Path | None) -> tuple[str, list[str]]:
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


def _backlog_item_from_task(task: dict) -> BacklogItem:
    task_id = str(task.get("id"))
    return BacklogItem(
        id=task_id,
        title=str(task.get("title") or ""),
        description=str(task.get("description") or ""),
        status=str(task.get("status") or ""),
        details=str(task.get("details") or ""),
        test_strategy=str(task.get("testStrategy") or ""),
    )


def _backlog_item_from_subtask(task: dict, sub: dict) -> BacklogItem:
    parent_id = str(task.get("id"))
    sub_id = f"{parent_id}.{sub.get('id')}"
    return BacklogItem(
        id=sub_id,
        title=str(sub.get("title") or ""),
        description=str(sub.get("description") or ""),
        status=str(sub.get("status") or ""),
        parent_id=parent_id,
        details=str(sub.get("details") or ""),
        test_strategy=str(sub.get("testStrategy") or ""),
    )


class TaskmasterJsonBacklogSource:
    """Backlog source adapter for ``.taskmaster/tasks/tasks.json``."""

    def __init__(
        self,
        tasks_file: str | Path,
        *,
        taskmaster_bin: str = "task-master",
        command_runner: CommandRunner = subprocess.run,
    ) -> None:
        self.tasks_file = Path(tasks_file)
        self.taskmaster_bin = taskmaster_bin
        self.command_runner = command_runner

    def _load_tasks(self) -> list[dict]:
        data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
        return data.get("master", {}).get("tasks", [])

    def list_ready_tasks(
        self,
        *,
        active_prd_file: str | Path | None = None,
        limit: int | None = None,
    ) -> list[BacklogItem]:
        tasks = self._load_tasks()
        active_phase, phase_order = _load_active_prd_state(active_prd_file)
        by_id = {str(task.get("id")): task for task in tasks}
        candidates: list[tuple[int, int, int, int, BacklogItem]] = []

        for task in tasks:
            task_status = str(task.get("status") or "")
            if task_status not in ACTIONABLE_STATUSES:
                continue
            deps = task.get("dependencies", [])
            if deps is None:
                deps = []
            if not isinstance(deps, list) or not all(
                _dep_done(dep, by_id) for dep in deps
            ):
                continue

            parent_id = _int_or_zero(task.get("id"))
            subtasks = task.get("subtasks", []) or []
            if subtasks:
                for sub in subtasks:
                    sub_status = str(sub.get("status") or "")
                    if sub_status not in ACTIONABLE_STATUSES:
                        continue
                    if not _sub_deps_done(task, sub):
                        continue
                    candidates.append(
                        (
                            _phase_score(
                                _item_text(task, sub),
                                active_phase,
                                phase_order,
                            ),
                            _rank(sub_status),
                            parent_id,
                            _int_or_zero(sub.get("id")),
                            _backlog_item_from_subtask(task, sub),
                        )
                    )
            else:
                candidates.append(
                    (
                        _phase_score(_item_text(task), active_phase, phase_order),
                        _rank(task_status),
                        parent_id,
                        0,
                        _backlog_item_from_task(task),
                    )
                )

        candidates.sort(key=lambda row: row[:4])
        items = [row[4] for row in candidates]
        if limit is None:
            return items
        return items[: max(0, limit)]

    def get_details(self, item_id: str) -> BacklogItem | None:
        for task in self._load_tasks():
            if str(task.get("id")) == item_id:
                return _backlog_item_from_task(task)
            parent_id = str(task.get("id"))
            for sub in task.get("subtasks", []) or []:
                if f"{parent_id}.{sub.get('id')}" == item_id:
                    return _backlog_item_from_subtask(task, sub)
        return None

    def mark_done(self, item_id: str) -> None:
        self._set_status(item_id, "done")

    def mark_blocked(self, item_id: str, reason: str) -> None:
        reason = reason.strip()
        if reason:
            update_command = "update-subtask" if "." in item_id else "update-task"
            self._run_taskmaster(
                [
                    self.taskmaster_bin,
                    update_command,
                    f"--id={item_id}",
                    f"--prompt=Blocked by Mainspring: {reason}",
                ]
            )
        self._set_status(item_id, "blocked")

    def _set_status(self, item_id: str, status: str) -> None:
        self._run_taskmaster(
            [
                self.taskmaster_bin,
                "set-status",
                f"--id={item_id}",
                f"--status={status}",
            ]
        )

    def _run_taskmaster(self, argv: Sequence[str]) -> None:
        try:
            result = self.command_runner(
                list(argv),
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise BacklogSourceError(f"{argv[0]} command not found") from exc

        if result.returncode == 0:
            return

        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        raise BacklogSourceError(
            f"{argv[0]} {argv[1]} failed with exit code {result.returncode}{suffix}"
        )
