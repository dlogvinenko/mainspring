#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only Mainspring HUD snapshot.

This slice powers ``mainspring hud --once``, ``--json``, ``--watch``, and the
Rich live HUD. ``--rich --watch`` renders the Rich live view operators naturally
expect from that flag combination.

Usage:
    python3 hud.py [--ledger <waves.jsonl>] [--state-dir <path>]
        [--since <15m|1h|1d|ISO>] [--once|--watch] [--rich] [--json]
        [--width <cols>] [--interval <seconds>] [--iterations <count>]
        [--ansi|--no-ansi]
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

import metrics
import notify_telegram
from cli_runtime import run_cli


def _parse_timestamp(entry: dict, target_tz: tzinfo | None = None) -> datetime | None:
    value = entry.get("timestamp") or entry.get("ts")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(target_tz)


def _parse_since(value: str, now: datetime) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    unit = text[-1].lower()
    amount = text[:-1]
    if unit in {"m", "h", "d"} and amount:
        try:
            count = float(amount)
        except ValueError:
            raise ValueError(
                "--since must be a duration like 15m, 1h, 1d, or an ISO timestamp"
            ) from None
        if count < 0:
            raise ValueError("--since duration must not be negative")
        if unit == "m":
            return now - timedelta(minutes=count)
        if unit == "h":
            return now - timedelta(hours=count)
        return now - timedelta(days=count)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
            now.tzinfo
        )
    except ValueError as exc:
        raise ValueError(
            "--since must be a duration like 15m, 1h, 1d, or an ISO timestamp"
        ) from exc


def _filter_since(entries: list[dict], since: datetime | None) -> list[dict]:
    if since is None:
        return entries
    return [
        entry
        for entry in entries
        if (timestamp := _parse_timestamp(entry)) is not None and timestamp >= since
    ]


def _entry_summary(entry: dict, target_tz: tzinfo | None = None) -> dict:
    stopped_at = _parse_timestamp(entry, target_tz)
    duration_seconds = entry.get("duration_seconds") or 0
    try:
        duration_int = int(float(str(duration_seconds)))
    except (TypeError, ValueError):
        duration_int = 0
    started_at = (
        stopped_at - timedelta(seconds=max(0, duration_int))
        if stopped_at is not None
        else None
    )
    return {
        "wave_id": entry.get("wave_id") or "",
        "task_id": entry.get("task_id") or "",
        "pair": metrics._get_pair(entry),
        "topology": entry.get("topology") or "",
        "verdict": entry.get("verdict") or "",
        "exit_code": entry.get("exit_code"),
        "duration_seconds": duration_int,
        "failure_reason_class": entry.get("failure_reason_class")
        or metrics._failure_class(entry),
        "next_action": entry.get("next_action") or "",
        "product_files_changed": entry.get("product_files_changed"),
        "timestamp": entry.get("timestamp") or entry.get("ts") or "",
        "started_at": (
            started_at.isoformat(timespec="seconds") if started_at is not None else ""
        ),
        "stopped_at": (
            stopped_at.isoformat(timespec="seconds") if stopped_at is not None else ""
        ),
    }


def _entry_sort_key(entry: dict) -> tuple[datetime, str]:
    timestamp = _parse_timestamp(entry)
    if timestamp is None:
        timestamp = datetime.min.replace(tzinfo=timezone.utc)
    return timestamp, str(entry.get("wave_id") or "")


def _sorted_entries(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=_entry_sort_key)


def _last_log_line(log_dir: Path) -> str:
    path = log_dir / "latest.log"
    if not path.is_file():
        return ""
    last = ""
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                stripped = line.strip()
                if stripped:
                    last = stripped
    except OSError:
        return ""
    return last


def _ledger_state(
    ledger_path: Path, *, valid_entry_count: int, visible_entry_count: int
) -> dict:
    try:
        stat = ledger_path.stat()
    except OSError:
        return {
            "status": "missing",
            "reason": "ledger file is missing",
            "path": str(ledger_path),
            "size_bytes": None,
            "entries": visible_entry_count,
            "valid_entries": valid_entry_count,
        }
    if not ledger_path.is_file():
        return {
            "status": "unreadable",
            "reason": "ledger path is not a file",
            "path": str(ledger_path),
            "size_bytes": stat.st_size,
            "entries": visible_entry_count,
            "valid_entries": valid_entry_count,
        }
    if stat.st_size == 0:
        return {
            "status": "empty",
            "reason": "ledger file has no wave rows",
            "path": str(ledger_path),
            "size_bytes": stat.st_size,
            "entries": visible_entry_count,
            "valid_entries": valid_entry_count,
        }
    if valid_entry_count == 0:
        return {
            "status": "no_valid_entries",
            "reason": "ledger has bytes but no valid JSONL wave rows",
            "path": str(ledger_path),
            "size_bytes": stat.st_size,
            "entries": visible_entry_count,
            "valid_entries": valid_entry_count,
        }
    return {
        "status": "ok",
        "reason": "",
        "path": str(ledger_path),
        "size_bytes": stat.st_size,
        "entries": visible_entry_count,
        "valid_entries": valid_entry_count,
    }


def _quota_gauges(entries: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for entry in entries:
        for engine, field in (
            ("codex", "codex_short_delta_pct"),
            ("claude", "claude_short_delta"),
        ):
            used = metrics._parse_float(entry.get(field))
            if used is not None and used >= 0:
                latest[engine] = {
                    "short_used_pct": round(used, 1),
                    "short_remaining_pct": round(max(0.0, 100.0 - used), 1),
                    "source": field,
                }
        quota = entry.get("quota") if isinstance(entry.get("quota"), dict) else {}
        for engine, payload in quota.items():
            if not isinstance(payload, dict):
                continue
            used = metrics._parse_float(
                payload.get("short_used_pct")
                or payload.get("short_usage_pct")
                or payload.get("used_percent")
            )
            remaining = metrics._parse_float(
                payload.get("short_remaining_pct")
                or payload.get("short_remaining")
                or payload.get("remaining_percent")
            )
            if used is None and remaining is not None:
                used = max(0.0, 100.0 - remaining)
            if remaining is None and used is not None:
                remaining = max(0.0, 100.0 - used)
            if used is not None and used >= 0:
                latest[str(engine).strip().lower()] = {
                    "short_used_pct": round(used, 1),
                    "short_remaining_pct": round(remaining or 0.0, 1),
                    "source": "quota",
                }

    for engine in ("codex", "claude", "gemini"):
        latest.setdefault(
            engine,
            {
                "short_used_pct": None,
                "short_remaining_pct": None,
                "source": "missing",
            },
        )
    return dict(sorted(latest.items()))


def _read_json_dict(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :].strip()
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _pending_dispatch_count(dispatch: dict) -> int:
    pending_statuses = {"pending", "in_progress", "in-progress", "running"}
    count = 0
    for payload in dispatch.values():
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "pending")
        if status in pending_statuses:
            count += 1
    return count


def _active_team_status(state_dir: Path) -> list[dict]:
    teams: list[dict] = []
    team_root = state_dir / "team"
    team_dirs = {
        path.parent
        for pattern in ("*/config.json", "*/dispatch-ledger.json")
        for path in team_root.glob(pattern)
    }
    for team_dir in sorted(team_dirs):
        team_name = team_dir.name
        payload = _read_json_dict(team_dir / "config.json")
        dispatch = _read_json_dict(team_dir / "dispatch-ledger.json")
        status = payload.get("status") or payload.get("phase")
        if not status and dispatch:
            status = "dispatch-only"
        teams.append(
            {
                "name": team_name,
                "status": status or "unknown",
                "workers": payload.get("workers") or payload.get("team_size") or "",
                "pending_dispatches": _pending_dispatch_count(dispatch),
            }
        )
    return teams


def _active_taskmaster_tag(project_root: Path) -> str:
    state = _read_json_dict(project_root / ".taskmaster" / "state.json")
    tag = str(state.get("currentTag") or "").strip()
    return tag or "master"


def _load_taskmaster_tasks(project_root: Path) -> tuple[list[dict], str, Path] | None:
    tasks_file = project_root / ".taskmaster" / "tasks" / "tasks.json"
    try:
        payload = json.loads(tasks_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    tag = _active_taskmaster_tag(project_root)
    tag_payload = payload.get(tag)
    if not isinstance(tag_payload, dict):
        tag = "master" if isinstance(payload.get("master"), dict) else tag
        tag_payload = payload.get(tag)
    if not isinstance(tag_payload, dict):
        return None
    tasks = tag_payload.get("tasks")
    if not isinstance(tasks, list):
        return None
    return tasks, tag, tasks_file


def _taskmaster_leaf_items(tasks: list[dict]) -> list[dict]:
    leaves: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        subtasks = task.get("subtasks")
        if isinstance(subtasks, list) and subtasks:
            leaves.extend(sub for sub in subtasks if isinstance(sub, dict))
        else:
            leaves.append(task)
    return leaves


def _status_key(value: object) -> str:
    return str(value or "unknown").strip().lower().replace("-", "_")


def _progress_payload(
    *,
    source: str,
    path: Path,
    done: int,
    total: int,
    status_counts: dict[str, int] | None = None,
    tag: str = "",
) -> dict:
    percent = round((done / total) * 100) if total > 0 else None
    text = "unknown" if percent is None else f"{percent}% ({done}/{total})"
    return {
        "source": source,
        "path": str(path),
        "tag": tag,
        "done": done,
        "total": total,
        "percent": percent,
        "text": text,
        "status_counts": status_counts or {},
    }


def _taskmaster_progress(project_root: Path) -> dict | None:
    loaded = _load_taskmaster_tasks(project_root)
    if loaded is None:
        return None
    tasks, tag, tasks_file = loaded
    leaves = _taskmaster_leaf_items(tasks)
    status_counts: dict[str, int] = {}
    total = 0
    done = 0
    for item in leaves:
        status = _status_key(item.get("status"))
        if status in {"cancelled", "canceled"}:
            continue
        status_counts[status] = status_counts.get(status, 0) + 1
        total += 1
        if status in {"done", "complete", "completed"}:
            done += 1
    if total == 0:
        return None
    return _progress_payload(
        source="taskmaster",
        path=tasks_file,
        done=done,
        total=total,
        status_counts=dict(sorted(status_counts.items())),
        tag=tag,
    )


def _resolve_prd_path(project_root: Path, runtime: dict) -> Path | None:
    configured = str(runtime.get("prd_path") or "").strip()
    candidates: list[Path] = []
    if configured:
        path = Path(configured).expanduser()
        candidates.append(path if path.is_absolute() else project_root / path)
    candidates.append(project_root / "docs" / "prd.md")
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _prd_checkbox_progress(project_root: Path, runtime: dict) -> dict | None:
    prd_path = _resolve_prd_path(project_root, runtime)
    if prd_path is None:
        return None
    try:
        text = prd_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    total = 0
    done = 0
    for line in text.splitlines():
        match = re.match(r"\s*[-*]\s+\[([ xX])\]", line)
        if not match:
            continue
        total += 1
        if match.group(1).lower() == "x":
            done += 1
    if total == 0:
        return None
    return _progress_payload(
        source="prd_checkboxes",
        path=prd_path,
        done=done,
        total=total,
    )


def _project_progress(project: dict, runtime: dict) -> dict:
    if project.get("root_source") == "cwd_fallback" and not runtime.get("configured"):
        return {
            "source": "none",
            "path": "",
            "tag": "",
            "done": 0,
            "total": 0,
            "percent": None,
            "text": "unknown",
            "status_counts": {},
        }
    root = Path(str(project.get("root") or ""))
    progress = _taskmaster_progress(root)
    if progress is not None:
        return progress
    progress = _prd_checkbox_progress(root, runtime)
    if progress is not None:
        return progress
    return {
        "source": "none",
        "path": "",
        "tag": "",
        "done": 0,
        "total": 0,
        "percent": None,
        "text": "unknown",
        "status_counts": {},
    }


def _env_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _notification_stale_seconds() -> tuple[int, str]:
    raw = (os.environ.get("MAINSPRING_NOTIFY_STALE_SECONDS") or "").strip()
    if not raw:
        return notify_telegram.STALE_DAEMON_SECONDS, ""
    try:
        parsed = int(raw)
    except ValueError:
        return notify_telegram.STALE_DAEMON_SECONDS, raw
    if parsed < 0:
        return notify_telegram.STALE_DAEMON_SECONDS, raw
    return parsed, ""


def _read_pid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return _parse_pid(text)


def _parse_pid(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        pid = int(text)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _pid_is_running(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _pid_command(pid: int | None) -> str:
    if pid is None:
        return ""
    try:
        return subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1.0,
        ).strip()
    except Exception:
        return ""


def _is_runtime_session_command(command: str) -> bool:
    normalized = command.strip()
    if not normalized:
        return False
    if "codex app-server" in normalized:
        return False
    if "Reply exactly: ok" in normalized:
        return False
    if _is_mainspring_work_command(normalized):
        return True
    return any(
        marker in normalized for marker in ("omx team", "codex exec", "claude -p")
    )


def _lock_pid_info(state_dir: Path) -> tuple[int | None, Path | None]:
    candidates = [state_dir / "mainspring.lock"]
    for path in candidates:
        pid = _read_pid(path)
        if pid is not None:
            return pid, path
    return None, None


def _runtime_context(state_dir: Path, now: datetime) -> dict:
    session = _read_json_dict(state_dir / "session.json")
    last_run = _read_env_file(state_dir / "last-run.env")
    if not last_run:
        last_run = _read_env_file(state_dir.parent / "last-run.env")

    session_pid = _parse_pid(session.get("pid"))
    lock_pid, lock_path = _lock_pid_info(state_dir)
    session_pid_alive = _pid_is_running(session_pid)
    session_pid_command = _pid_command(session_pid) if session_pid_alive else ""
    session_pid_valid = session_pid_alive and _is_runtime_session_command(
        session_pid_command
    )
    rejected_session_pid = (
        session_pid if session_pid_alive and not session_pid_valid else None
    )
    pid = session_pid if session_pid_valid else lock_pid
    pid_alive = _pid_is_running(pid) if pid is not None else False
    started_at = (
        _parse_timestamp({"timestamp": session.get("started_at")}, now.tzinfo)
        if session_pid_valid
        else None
    )
    if started_at is None and lock_path is not None and pid_alive:
        try:
            started_at = datetime.fromtimestamp(
                lock_path.stat().st_mtime, tz=now.tzinfo
            )
        except OSError:
            started_at = None
    elapsed_seconds = None
    if started_at is not None:
        elapsed_seconds = max(0, int((now - started_at).total_seconds()))
    pair = last_run.get("PAIR_MODE") or ""
    if not pair:
        engine = last_run.get("ENGINE") or ""
        review_engine = last_run.get("REVIEW_ENGINE") or ""
        pair = f"{engine}+{review_engine}" if engine or review_engine else ""

    return {
        "session_id": session.get("session_id") or "",
        "started_at": (
            started_at.isoformat(timespec="seconds") if started_at is not None else ""
        ),
        "elapsed_seconds": elapsed_seconds,
        "pid": pid,
        "pid_alive": pid_alive,
        "pid_source": "session"
        if pid is not None and pid == session_pid
        else "lock"
        if pid is not None and pid == lock_pid
        else "",
        "rejected_session_pid": rejected_session_pid,
        "rejected_session_pid_command": session_pid_command
        if rejected_session_pid is not None
        else "",
        "cwd": session.get("cwd") or "",
        "mode": last_run.get("MODE") or "",
        "topology": last_run.get("TOPOLOGY") or "",
        "pair": pair,
        "engine": last_run.get("ENGINE") or "",
        "review_engine": last_run.get("REVIEW_ENGINE") or "",
        "speed_profile": last_run.get("SPEED_PROFILE") or "",
        "max_agents": last_run.get("MAX_AGENTS") or "",
        "prd_path": last_run.get("PRD_PATH") or "",
        "configured": bool(session or last_run),
    }


def _project_context(ledger_path: Path, state_dir: Path, runtime: dict) -> dict:
    candidates = [
        (
            "runtime_state_dir",
            str(state_dir.parent.parent)
            if state_dir.name == "state" and state_dir.parent.name == ".mainspring"
            else "",
        ),
        (
            "runtime_ledger",
            str(ledger_path.parent.parent.parent)
            if ledger_path.parent.name == "logs"
            and ledger_path.parent.parent.name == ".mainspring"
            else "",
        ),
        (
            "runtime_cwd",
            runtime.get("cwd") if isinstance(runtime.get("cwd"), str) else "",
        ),
    ]
    root_source, root_text = next(
        ((source, candidate) for source, candidate in candidates if candidate),
        ("cwd_fallback", ""),
    )
    root_path = Path(root_text).expanduser() if root_text else Path.cwd()
    try:
        resolved = root_path.resolve()
    except OSError:
        resolved = root_path
    return {
        "name": resolved.name or str(resolved),
        "root": str(resolved),
        "root_source": root_source,
        "runtime_dir": str(state_dir.parent),
        "ledger": str(ledger_path),
    }


def _notification_health(ledger_path: Path, state_dir: Path, now: datetime) -> dict:
    enabled = _env_enabled(os.environ.get("MAINSPRING_NOTIFY_ENABLED"))
    configured = bool(
        os.environ.get("MAINSPRING_TELEGRAM_BOT_TOKEN")
        and os.environ.get("MAINSPRING_TELEGRAM_CHAT_ID")
    )
    state_path = state_dir / "notify-state.json"
    pid_path = state_dir / "notifier.pid"
    base = {
        "enabled": enabled,
        "configured": configured,
        "state_path": str(state_path),
        "pid_path": str(pid_path),
        "pid": None,
        "process_running": None,
    }
    stale_seconds, stale_seconds_error = _notification_stale_seconds()
    if not enabled:
        guidance = notify_telegram.health_next_step(
            "disabled",
            "MAINSPRING_NOTIFY_ENABLED not set",
        )
        return {
            **base,
            "status": "disabled",
            "reason": "MAINSPRING_NOTIFY_ENABLED not set",
            **guidance,
            "pending_lines": None,
            "ledger_lines": None,
            "last_line_count": None,
            "stale_seconds": stale_seconds,
        }
    if not configured:
        guidance = notify_telegram.health_next_step(
            "unconfigured",
            "telegram token/chat id missing",
        )
        return {
            **base,
            "status": "unconfigured",
            "reason": "telegram token/chat id missing",
            **guidance,
            "pending_lines": None,
            "ledger_lines": None,
            "last_line_count": None,
            "stale_seconds": stale_seconds,
        }
    if stale_seconds_error:
        guidance = notify_telegram.health_next_step(
            "config_error",
            "invalid_stale_seconds",
        )
        return {
            **base,
            "status": "config_error",
            "reason": "invalid_stale_seconds",
            **guidance,
            "pending_lines": None,
            "ledger_lines": None,
            "last_line_count": None,
            "stale_seconds": stale_seconds,
            "invalid_stale_seconds": stale_seconds_error,
        }

    pid = _read_pid(pid_path)
    process_running = _pid_is_running(pid)
    health = notify_telegram.check_watch_health(
        ledger_path,
        notify_telegram.NotifyState(state_path),
        now=now.timestamp(),
        stale_seconds=stale_seconds,
        log_path=ledger_path.parent / "notifier.log",
    )
    common_health = {
        "pending_lines": health["pending_lines"],
        "ledger_lines": health["ledger_lines"],
        "last_line_count": health["last_line_count"],
        "stale_seconds": health["stale_seconds"],
        "pid": pid,
        "process_running": process_running,
    }
    if pid is None:
        guidance = notify_telegram.health_next_step("stale", "daemon_pid_missing")
        return {
            **base,
            **common_health,
            "status": "stale",
            "reason": "daemon_pid_missing",
            **guidance,
            "watch_status": health["status"],
            "watch_reason": health["reason"],
        }
    if not process_running:
        guidance = notify_telegram.health_next_step("stale", "daemon_pid_not_running")
        return {
            **base,
            **common_health,
            "status": "stale",
            "reason": "daemon_pid_not_running",
            **guidance,
            "watch_status": health["status"],
            "watch_reason": health["reason"],
        }
    return {
        **base,
        **common_health,
        "status": health["status"],
        "reason": health["reason"],
        "next_step": health["next_step"],
        "next_step_message": health["next_step_message"],
        "watch_status": health["status"],
        "watch_reason": health["reason"],
    }


def _today_entries(entries: list[dict], now: datetime) -> list[dict]:
    today = now.date()
    return [
        entry
        for entry in entries
        if (timestamp := _parse_timestamp(entry)) is not None
        and timestamp.astimezone(now.tzinfo).date() == today
    ]


def build_snapshot(
    ledger_path: Path,
    state_dir: Path,
    *,
    since: str = "",
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now().astimezone()
    all_entries = metrics.read_ledger(ledger_path)
    entries = _sorted_entries(_filter_since(all_entries, _parse_since(since, now)))
    today = _today_entries(entries, now)
    today_metrics = metrics.compute_metrics(today)
    current_wave = _entry_summary(entries[-1], now.tzinfo) if entries else None
    if current_wave is not None:
        current_wave["last_log_line"] = _last_log_line(ledger_path.parent)
    runtime = _runtime_context(state_dir, now)
    project = _project_context(ledger_path, state_dir, runtime)
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "project": project,
        "ledger": str(ledger_path),
        "ledger_state": _ledger_state(
            ledger_path,
            valid_entry_count=len(all_entries),
            visible_entry_count=len(entries),
        ),
        "state_dir": str(state_dir),
        "since": since,
        "entry_count": len(entries),
        "current_wave": current_wave,
        "runtime": runtime,
        "recent_waves": [_entry_summary(entry, now.tzinfo) for entry in entries[-10:]][
            ::-1
        ],
        "today": {
            "total_waves": today_metrics["total_waves"],
            "success_rate": today_metrics["success_rate"],
            "mean_duration_s": today_metrics["mean_duration_s"],
            "top_stuck_tasks": today_metrics["top_stuck_tasks"][:3],
        },
        "quota": _quota_gauges(entries),
        "active_teams": _active_team_status(state_dir),
        "notifications": _notification_health(ledger_path, state_dir, now),
        "progress": _project_progress(project, runtime),
    }


def _state_dir_for_runtime(runtime_dir: Path) -> Path:
    return runtime_dir / "state"


def _ledger_for_runtime(runtime_dir: Path) -> Path:
    return runtime_dir / "logs" / "waves.jsonl"


def _runtime_dir_from_project(project_root: Path) -> Path:
    return project_root / ".mainspring"


def _runtime_dir_from_path(path: Path) -> Path | None:
    candidates = [path, *path.parents]
    for candidate in candidates:
        if candidate.name == ".mainspring":
            return candidate
    return None


def _runtime_ref(
    runtime_dir: Path,
    *,
    source: str,
    process_pid: int | None = None,
) -> dict:
    return {
        "runtime_dir": runtime_dir,
        "state_dir": _state_dir_for_runtime(runtime_dir),
        "ledger_path": _ledger_for_runtime(runtime_dir),
        "source": source,
        "process_pid": process_pid,
    }


def _seed_runtime_ref(ledger_path: Path, state_dir: Path) -> dict:
    runtime_dir = state_dir.parent
    if state_dir.name != "state":
        runtime_dir = (
            ledger_path.parent.parent
            if ledger_path.parent.name == "logs"
            else state_dir.parent
        )
    return {
        "runtime_dir": runtime_dir,
        "state_dir": state_dir,
        "ledger_path": ledger_path,
        "source": "current",
        "process_pid": None,
    }


def _parse_process_row(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped:
        return None
    first, _, command = stripped.partition(" ")
    try:
        pid = int(first)
    except ValueError:
        return None
    return pid, command.strip()


def _read_process_rows() -> list[str]:
    try:
        output = subprocess.check_output(
            ["ps", "-axo", "pid=,command="],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    return output.splitlines()


def _pid_cwd(pid: int) -> Path | None:
    proc_cwd = Path("/proc") / str(pid) / "cwd"
    try:
        if proc_cwd.exists():
            return proc_cwd.resolve()
    except OSError:
        pass

    lsof = shutil.which("lsof")
    if not lsof:
        return None
    try:
        output = subprocess.check_output(
            [lsof, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=1.0,
        )
    except Exception:
        return None
    for line in output.splitlines():
        if line.startswith("n"):
            return Path(line[1:])
    return None


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _mainspring_argv_from_tokens(tokens: list[str]) -> list[str] | None:
    if not tokens:
        return None
    first = Path(tokens[0]).name
    if first in {"mainspring", "mainspring.sh"}:
        return tokens
    if first not in {"bash", "sh", "zsh", "fish"}:
        return None
    if len(tokens) > 1 and Path(tokens[1]).name in {"mainspring", "mainspring.sh"}:
        return tokens[1:]
    for index, token in enumerate(tokens[1:-1], start=1):
        if token in {"-c", "-lc", "-ilc"}:
            return _mainspring_argv_from_tokens(_split_command(tokens[index + 1]))
    return None


def _mainspring_argv(command: str) -> list[str] | None:
    return _mainspring_argv_from_tokens(_split_command(command))


def _mainspring_command_index(tokens: list[str]) -> int | None:
    if not tokens:
        return None
    first = Path(tokens[0]).name
    if first in {"mainspring", "mainspring.sh"}:
        return 0
    if first in {"bash", "sh", "zsh", "fish"} and len(tokens) > 1:
        second = Path(tokens[1]).name
        if second in {"mainspring", "mainspring.sh"}:
            return 1
    return None


def _is_notify_command(command: str) -> bool:
    return any(
        Path(token).name == "notify_telegram.py" for token in _split_command(command)
    )


def _project_from_command(command: str, cwd: Path | None) -> Path | None:
    tokens = _mainspring_argv(command) or _split_command(command)
    for index, token in enumerate(tokens):
        if token == "--project" and index + 1 < len(tokens):
            path = Path(tokens[index + 1])
            return path if path.is_absolute() or cwd is None else cwd / path
        if token.startswith("--project="):
            path = Path(token.split("=", 1)[1])
            return path if path.is_absolute() or cwd is None else cwd / path

    match = re.search(
        r"(?:^|[;&|]\s*)cd\s+((?:'[^']+')|(?:\"[^\"]+\")|[^\s;&|]+)", command
    )
    if match:
        raw = match.group(1)
        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = [raw.strip("'\"")]
        if parts:
            path = Path(parts[0])
            return path if path.is_absolute() or cwd is None else cwd / path
    return None


def _ledger_from_command(command: str, cwd: Path | None) -> Path | None:
    for token in _split_command(command):
        if token.endswith("waves.jsonl"):
            path = Path(token)
            return path if path.is_absolute() or cwd is None else cwd / path
    return None


def _is_mainspring_work_command(command: str) -> bool:
    tokens = _mainspring_argv(command)
    if tokens is None:
        return False
    utility_subcommands = {
        "--doctor",
        "--help",
        "--status",
        "decompose",
        "doctor",
        "engines",
        "help",
        "hud",
        "init",
        "last-run",
        "limits",
        "next",
        "notify-health",
        "notify-restart",
        "notify-test",
        "replay",
        "scope-check",
        "status",
        "stop",
        "validate-prd",
    }
    value_flags = {
        "--auto-retry-ci",
        "--auto-retry-ci-log",
        "--config",
        "--engine",
        "--max-agents",
        "--mode",
        "--model",
        "--pair",
        "--prd",
        "--preset",
        "--project",
        "--reasoning",
        "--review-engine",
        "--review-model",
        "--retry-task",
        "--speed-profile",
        "--topology",
    }
    subcommand = ""
    next_index = 1
    while next_index < len(tokens):
        candidate = tokens[next_index]
        if candidate in value_flags:
            next_index += 2
            continue
        if any(candidate.startswith(f"{flag}=") for flag in value_flags):
            next_index += 1
            continue
        if candidate.startswith("-"):
            next_index += 1
            continue
        subcommand = candidate
        break
    return subcommand not in utility_subcommands


def _runtime_refs_from_processes(
    process_rows: list[str] | None = None,
    *,
    cwd_resolver=_pid_cwd,
) -> list[dict]:
    refs: list[dict] = []
    rows = _read_process_rows() if process_rows is None else process_rows
    for row in rows:
        parsed = _parse_process_row(row)
        if parsed is None:
            continue
        pid, command = parsed
        is_mainspring_command = _mainspring_argv(command) is not None
        is_notify_command = _is_notify_command(command)
        if not is_mainspring_command and not is_notify_command:
            continue
        cwd = cwd_resolver(pid)
        ledger = _ledger_from_command(command, cwd)
        if ledger is not None:
            runtime_dir = _runtime_dir_from_path(ledger)
            if runtime_dir is not None:
                refs.append(_runtime_ref(runtime_dir, source=f"process:{pid}"))
                continue
        project = _project_from_command(command, cwd)
        if project is None:
            project = cwd
        if project is not None:
            refs.append(
                _runtime_ref(
                    _runtime_dir_from_project(project),
                    source=f"process:{pid}",
                    process_pid=pid if _is_mainspring_work_command(command) else None,
                )
            )
    return refs


def _default_search_roots() -> list[Path]:
    home = Path.home()
    roots = [
        Path.cwd(),
        home / "Projects",
        home / "Documents",
        home / "Desktop",
        home / "Code",
        home / "dev",
        home / "src",
    ]
    return roots


def _runtime_refs_from_search_roots(search_roots: list[Path]) -> list[dict]:
    refs: list[dict] = []
    skip_names = {
        ".cache",
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "__pycache__",
        "Library",
        "node_modules",
    }
    seen_roots: set[Path] = set()
    for root in search_roots:
        try:
            root = root.expanduser().resolve()
        except OSError:
            root = root.expanduser()
        if root in seen_roots or not root.is_dir():
            continue
        seen_roots.add(root)
        visited = 0
        for current, dirnames, _filenames in os.walk(root):
            visited += 1
            if visited > 20000:
                break
            current_path = Path(current)
            if current_path.name == ".mainspring":
                refs.append(_runtime_ref(current_path, source="scan"))
                dirnames[:] = []
                continue
            dirnames[:] = [
                name
                for name in dirnames
                if name not in skip_names
                and (not name.startswith(".") or name == ".mainspring")
            ]
    return refs


def discover_runtime_refs(
    seed_ledger_path: Path,
    seed_state_dir: Path,
    *,
    search_roots: list[Path] | None = None,
    process_rows: list[str] | None = None,
    cwd_resolver=_pid_cwd,
) -> list[dict]:
    refs = [_seed_runtime_ref(seed_ledger_path, seed_state_dir)]
    refs.extend(_runtime_refs_from_processes(process_rows, cwd_resolver=cwd_resolver))
    roots = _default_search_roots() if search_roots is None else search_roots
    refs.extend(_runtime_refs_from_search_roots(roots))

    unique: dict[str, dict] = {}
    for ref in refs:
        runtime_dir = Path(ref["runtime_dir"]).expanduser()
        try:
            key = str(runtime_dir.resolve())
        except OSError:
            key = str(runtime_dir)
        if key not in unique:
            unique[key] = {
                **ref,
                "runtime_dir": runtime_dir,
                "state_dir": Path(ref["state_dir"]).expanduser(),
                "ledger_path": Path(ref["ledger_path"]).expanduser(),
                "process_pid": ref.get("process_pid"),
            }
    return list(unique.values())


def _snapshot_activity_time(snapshot: dict) -> datetime:
    candidates = [
        (snapshot.get("current_wave") or {}).get("stopped_at"),
        (snapshot.get("current_wave") or {}).get("started_at"),
        (snapshot.get("current_wave") or {}).get("timestamp"),
        (snapshot.get("runtime") or {}).get("started_at"),
    ]
    for value in candidates:
        parsed = _parse_timestamp({"timestamp": value})
        if parsed is not None:
            return parsed
    ledger = Path(str(snapshot.get("ledger") or ""))
    try:
        return datetime.fromtimestamp(ledger.stat().st_mtime).astimezone()
    except OSError:
        return datetime.min.replace(tzinfo=timezone.utc).astimezone()


def _consecutive_failure_count(recent_waves: list[dict], current: dict) -> int:
    if str(current.get("verdict") or "").upper() not in {"FAIL", "ERROR"}:
        return 0
    task_id = str(current.get("task_id") or "")
    count = 0
    for wave in recent_waves:
        if task_id and str(wave.get("task_id") or "") != task_id:
            break
        if str(wave.get("verdict") or "").upper() not in {"FAIL", "ERROR"}:
            break
        count += 1
    return count


def _runtime_started_after_last_wave(
    runtime: dict,
    current: dict,
    now: datetime | None,
) -> bool:
    runtime_started_at = _parse_timestamp(
        {"timestamp": runtime.get("started_at") or ""}
    )
    wave_stopped_at = _parse_timestamp({"timestamp": current.get("stopped_at") or ""})
    return (
        runtime_started_at is not None
        and wave_stopped_at is not None
        and (now is None or runtime_started_at <= now)
        and runtime_started_at > wave_stopped_at
    )


def _operator_state(
    live: bool,
    current: dict,
    consecutive_failures: int,
    *,
    restarted_after_last_wave: bool = False,
) -> str:
    if not live:
        return "STALE"
    if restarted_after_last_wave:
        return "RUNNING"
    verdict = str(current.get("verdict") or "").upper()
    if verdict in {"FAIL", "ERROR"}:
        return "STUCK" if consecutive_failures >= 3 else "RETRY"
    if verdict == "IDLE":
        return "IDLE"
    if verdict == "PASS":
        return "OK"
    return "LIVE"


def _operator_state_label(state: object, verdict: object = "") -> str:
    normalized = str(state or "").upper()
    result = str(verdict or "").upper()
    if normalized in {"RUNNING", "LIVE"}:
        return "Running"
    if normalized == "OK":
        return "Waiting"
    if normalized == "STUCK":
        return "Blocked"
    if normalized == "RETRY":
        return "Failed"
    if normalized == "IDLE":
        return "Stopped cleanly"
    if normalized == "STALE":
        if result in {"FAIL", "ERROR"}:
            return "Failed"
        return "Not running"
    return "Waiting"


def _operator_state_style(state: object, verdict: object = "") -> str:
    label = _operator_state_label(state, verdict)
    if label == "Running":
        return "green"
    if label == "Waiting":
        return "cyan"
    if label == "Blocked":
        return "red"
    if label == "Failed":
        return "yellow"
    if label == "Not running":
        return "cyan"
    if label == "Stopped cleanly":
        return "green"
    return "white"


def _operator_state_border_style(state: object, verdict: object = "") -> str:
    return _operator_state_style(state, verdict).replace("bold ", "")


def _operator_next_action(state: str, current: dict, notifications: dict) -> str:
    if state == "RUNNING":
        verdict = str(current.get("verdict") or "").strip()
        stopped = _human_time(current.get("stopped_at"))
        previous = f" Previous wave: {verdict} at {stopped}." if verdict else ""
        return f"Running now; waiting for the next wave result.{previous}"
    next_action = str(current.get("next_action") or "").strip()
    if next_action:
        return next_action
    notify_step = str(notifications.get("next_step") or "").strip()
    if notify_step and notify_step != "none":
        return str(notifications.get("next_step_message") or notify_step)
    if state == "STUCK":
        return "Inspect the latest summary, fix the repeated blocker, then restart with mainspring --last-run."
    if state == "RETRY":
        return "Watch the next wave or stop with mainspring stop --force if it repeats."
    if state == "IDLE":
        return (
            "No actionable work was found; check mainspring next or Taskmaster status."
        )
    if state == "STALE":
        return "Use mainspring hud --all-runtimes to inspect past runs, or restart from the project."
    return "No action needed."


def _run_display_fields(run: dict) -> tuple[str, str, str]:
    state = str(run.get("operator_state") or "").upper()
    if state == "RUNNING":
        return "Running now", "-", "-"
    verdict = str(run.get("verdict") or "-")
    reason = str(run.get("failure_reason_class") or "-")
    failure_count = run.get("consecutive_failures")
    failures = str(failure_count if failure_count not in {None, ""} else "-")
    return verdict, reason, failures


def _run_start_display(run: dict) -> str:
    state = str(run.get("operator_state") or "").upper()
    if state in {"RUNNING", "LIVE"}:
        return _human_time(run.get("started_at"))
    return _human_time(run.get("last_started_at"))


def _global_run_row(snapshot: dict, source: str) -> dict:
    project = snapshot.get("project") or {}
    runtime = snapshot.get("runtime") or {}
    current = snapshot.get("current_wave") or {}
    recent_waves = snapshot.get("recent_waves") or []
    notifications = snapshot.get("notifications") or {}
    progress = snapshot.get("progress") or {}
    root = Path(str(project.get("root") or ""))
    tag = notify_telegram.read_taskmaster_tag(root if str(root) else None)
    live = bool(runtime.get("pid_alive"))
    consecutive_failures = _consecutive_failure_count(recent_waves, current)
    generated_at = _parse_timestamp({"timestamp": snapshot.get("generated_at") or ""})
    restarted_after_last_wave = live and _runtime_started_after_last_wave(
        runtime,
        current,
        generated_at,
    )
    state = _operator_state(
        live,
        current,
        consecutive_failures,
        restarted_after_last_wave=restarted_after_last_wave,
    )
    return {
        "status": "live" if live else "stale",
        "operator_state": state,
        "project": project.get("name") or "-",
        "folder": project.get("root") or "-",
        "runtime_dir": project.get("runtime_dir") or "-",
        "source": source,
        "pid": runtime.get("pid"),
        "started_at": runtime.get("started_at") or "",
        "runtime_started_after_last_wave": restarted_after_last_wave,
        "elapsed_seconds": runtime.get("elapsed_seconds"),
        "mode": runtime.get("mode") or "",
        "topology": runtime.get("topology") or "",
        "pair": runtime.get("pair") or current.get("pair") or "",
        "task_id": current.get("task_id") or "",
        "taskmaster_tag": tag,
        "wave_id": current.get("wave_id") or "",
        "progress": progress,
        "progress_text": progress.get("text") or "unknown",
        "progress_percent": progress.get("percent"),
        "progress_source": progress.get("source") or "none",
        "verdict": current.get("verdict") or "",
        "failure_reason_class": current.get("failure_reason_class") or "",
        "consecutive_failures": consecutive_failures,
        "next_action": _operator_next_action(state, current, notifications),
        "last_started_at": current.get("started_at") or "",
        "last_stopped_at": current.get("stopped_at") or "",
        "ledger_status": (snapshot.get("ledger_state") or {}).get("status") or "",
        "telegram_status": notifications.get("status") or "",
        "active_teams": snapshot.get("active_teams") or [],
        "activity_at": _snapshot_activity_time(snapshot).isoformat(timespec="seconds"),
    }


def build_global_snapshot(
    seed_ledger_path: Path,
    seed_state_dir: Path,
    *,
    since: str = "",
    now: datetime | None = None,
    search_roots: list[Path] | None = None,
    process_rows: list[str] | None = None,
    cwd_resolver=_pid_cwd,
    include_stale: bool = False,
) -> dict:
    now = now or datetime.now().astimezone()
    refs = discover_runtime_refs(
        seed_ledger_path,
        seed_state_dir,
        search_roots=search_roots,
        process_rows=process_rows,
        cwd_resolver=cwd_resolver,
    )
    snapshots: list[dict] = []
    rows: list[dict] = []
    for ref in refs:
        snapshot = build_snapshot(
            Path(ref["ledger_path"]),
            Path(ref["state_dir"]),
            since=since,
            now=now,
        )
        process_pid = _parse_pid(ref.get("process_pid"))
        if process_pid is not None and _pid_is_running(process_pid):
            snapshot["runtime"]["pid"] = process_pid
            snapshot["runtime"]["pid_alive"] = True
            snapshot["runtime"]["pid_source"] = "process"
        interesting = (
            snapshot["runtime"].get("configured")
            or snapshot["runtime"].get("pid_alive")
            or snapshot["entry_count"] > 0
            or snapshot.get("active_teams")
            or Path(ref["runtime_dir"]).exists()
        )
        if not include_stale and not snapshot["runtime"].get("pid_alive"):
            continue
        if not interesting:
            continue
        snapshot["discovery_source"] = ref["source"]
        snapshots.append(snapshot)
        rows.append(_global_run_row(snapshot, str(ref["source"])))

    def sort_key(row: dict) -> tuple[int, float, str]:
        parsed = _parse_timestamp({"timestamp": row.get("activity_at")})
        timestamp = parsed.timestamp() if parsed is not None else 0.0
        return (0 if row["status"] == "live" else 1, -timestamp, row["folder"])

    rows.sort(key=sort_key)
    live_count = sum(1 for row in rows if row["status"] == "live")
    needs_action_count = sum(
        1 for row in rows if row.get("operator_state") in {"STUCK", "RETRY"}
    )
    return {
        "scope": "global",
        "generated_at": now.isoformat(timespec="seconds"),
        "since": since,
        "run_count": len(rows),
        "live_count": live_count,
        "stale_count": len(rows) - live_count,
        "needs_action_count": needs_action_count,
        "runs": rows,
        "snapshots": snapshots,
    }


def _display_width(width: int | None = None) -> int:
    if width is not None:
        return max(40, width)
    return max(40, shutil.get_terminal_size((100, 24)).columns)


def _clip_line(text: object, width: int) -> str:
    line = str(text)
    if len(line) <= width:
        return line
    if width <= 3:
        return line[:width]
    return line[: width - 3] + "..."


def _compact_middle(value: object, max_chars: int) -> str:
    text = str(value or "")
    if max_chars < 5 or len(text) <= max_chars:
        return text
    keep = max_chars - 3
    left = max(1, keep // 2)
    right = max(1, keep - left)
    return f"{text[:left]}...{text[-right:]}"


def _human_time(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def format_text(snapshot: dict, *, width: int | None = None) -> str:
    display_width = _display_width(width)
    lines = ["Mainspring project snapshot"]

    def append(text: object) -> None:
        lines.append(_clip_line(text, display_width))

    project = snapshot.get("project") or {}
    append(f"Folder: {project.get('root') or '-'}")
    append(f"Ledger path: {project.get('ledger') or snapshot.get('ledger') or '-'}")

    current = snapshot.get("current_wave")
    if current:
        append(
            "Current wave: "
            f"id={current['wave_id'] or '?'} task_id={current['task_id'] or '-'} "
            f"pair={current['pair']} verdict={current['verdict'] or '?'} "
            f"duration={current['duration_seconds']}s "
            f"started={_human_time(current.get('started_at'))} "
            f"stopped={_human_time(current.get('stopped_at'))}"
        )
        if current.get("last_log_line"):
            append(f"Last log: {current['last_log_line']}")
    else:
        append("Current wave: none")

    ledger_state = snapshot.get("ledger_state") or {}
    ledger_status = ledger_state.get("status") or "unknown"
    ledger_reason = ledger_state.get("reason") or ""
    ledger_entries = ledger_state.get("entries", snapshot.get("entry_count", 0))
    ledger_valid_entries = ledger_state.get("valid_entries", ledger_entries)
    append(
        "Ledger: "
        f"{ledger_status}, entries={ledger_entries}"
        f", valid={ledger_valid_entries}"
        f"{f' ({ledger_reason})' if ledger_reason else ''}"
    )

    runtime = snapshot.get("runtime") or {}
    if runtime.get("configured"):
        runtime_state = "live" if runtime.get("pid_alive") else "stale"
        elapsed = runtime.get("elapsed_seconds")
        elapsed_text = "" if elapsed is None else f" elapsed={elapsed}s"
        append(
            "Runtime: "
            f"{runtime_state} "
            f"{runtime.get('mode') or '-'}/{runtime.get('topology') or '-'} "
            f"pair={runtime.get('pair') or '-'} "
            f"speed={runtime.get('speed_profile') or '-'} "
            f"agents={runtime.get('max_agents') or '-'}"
            f"{elapsed_text}"
        )
    else:
        append("Runtime: none")

    progress = snapshot.get("progress") or {}
    progress_tag = progress.get("tag")
    progress_tag_text = f" tag={progress_tag}" if progress_tag else ""
    append(
        "Progress: "
        f"{progress.get('text') or 'unknown'} "
        f"source={progress.get('source') or 'none'}"
        f"{progress_tag_text}"
    )

    today = snapshot["today"]
    append(
        "Today: "
        f"{today['total_waves']} waves, {today['success_rate']}% pass, "
        f"mean {today['mean_duration_s']}s"
    )

    quota_parts = []
    for engine, payload in snapshot["quota"].items():
        used = payload.get("short_used_pct")
        quota_parts.append(
            f"{engine} {'unknown' if used is None else str(used) + '% used'}"
        )
    append("Quota: " + ", ".join(quota_parts))

    teams = snapshot.get("active_teams") or []
    if teams:
        append(
            "Active teams: "
            + ", ".join(f"{team['name']}({team['status']})" for team in teams)
        )
    else:
        append("Active teams: none")

    notifications = snapshot.get("notifications") or {}
    notification_status = notifications.get("status") or "unknown"
    notification_reason = notifications.get("reason") or ""
    pending = notifications.get("pending_lines")
    pending_text = "" if pending is None else f", pending={pending}"
    append(
        "Notifications: "
        f"{notification_status}"
        f"{f' ({notification_reason}{pending_text})' if notification_reason else pending_text}"
    )
    if notifications.get("next_step") not in {None, "", "none"}:
        append(
            "Notifications next: "
            f"{notifications.get('next_step_message') or notifications.get('next_step')}"
        )

    recent = snapshot.get("recent_waves") or []
    if recent:
        lines.append("")
        lines.append("Recent waves:")
        for wave in recent:
            append(
                f"  - {wave['wave_id'] or '?'} task={wave['task_id'] or '-'} "
                f"{wave['pair']} {wave['verdict'] or '?'} "
                f"start={_human_time(wave.get('started_at'))} "
                f"stop={_human_time(wave.get('stopped_at'))} "
                f"{wave['duration_seconds']}s"
            )
    return "\n".join(lines)


def format_global_text(snapshot: dict, *, width: int | None = None) -> str:
    display_width = _display_width(width)
    lines = ["Mainspring", "=========="]

    def append(text: object) -> None:
        lines.append(_clip_line(text, display_width))

    append(
        "Runs:  "
        f"{snapshot.get('run_count', 0)} total, "
        f"{snapshot.get('live_count', 0)} live, "
        f"{snapshot.get('stale_count', 0)} past, "
        f"{snapshot.get('needs_action_count', 0)} needs action"
    )
    append(
        "View: all projects on this machine. Live runs first; newest activity first."
    )

    runs = snapshot.get("runs") or []
    if not runs:
        append("State: IDLE - no Mainspring work is running")
        append("")
        append("This is healthy if you expected no active jobs.")
        append("If a run should be active, start or resume it from the project folder.")
        append("")
        append("Start / Resume")
        append("  new run in a project    cd /path/to/project && mainspring")
        append("  resume saved setup      mainspring --last-run")
        append("  inspect saved setup     mainspring last-run")
        append("")
        append("Observe")
        append("  current project status  mainspring status")
        append("  include past runs       mainspring hud --all-runtimes")
        append("")
        append("Notifications / Safety")
        append("  telegram health         mainspring notify-health --format json")
        append("  send telegram test      mainspring notify-test")
        append("  stop current project    mainspring stop --force")
        append("")
        append("Expected live view: rich dashboard in an interactive terminal.")
        append("If you see this plain snapshot there, run: mainspring doctor")
        return "\n".join(lines)

    append("")
    append("Runs:")
    for run in runs:
        state = str(run.get("operator_state") or run.get("status") or "?").upper()
        state_label = _operator_state_label(state, run.get("verdict"))
        pid = run.get("pid") or "-"
        tag = run.get("taskmaster_tag") or "-"
        task = run.get("task_id") or "-"
        wave = _compact_middle(run.get("wave_id") or "-", 28)
        pair = run.get("pair") or "-"
        started = _run_start_display(run)
        stopped = _human_time(run.get("last_stopped_at"))
        current, issue, failures = _run_display_fields(run)
        previous = run.get("verdict") or "-"
        telegram = run.get("telegram_status") or "-"
        next_action = run.get("next_action") or "-"
        project = run.get("project") or "-"
        folder = run.get("folder") or "-"
        if state == "RUNNING":
            append(f"- {state_label} | {project}")
            append(f"  Folder: {folder}")
            append(
                f"  PID: {pid} | Tag: {tag} | Task: {task} | "
                f"Progress: {run.get('progress_text') or 'unknown'}"
            )
            append(f"  Pair: {pair} | Started: {started} | Now: {current}")
            append(
                f"  Previous wave: {wave} | Previous result: {previous} | "
                f"Last stop: {stopped}"
            )
            append(f"  Telegram: {telegram} | Next: Watch this run in HUD")
        else:
            append(f"- {state_label} | {project}")
            append(f"  Folder: {folder}")
            append(
                f"  PID: {pid} | Tag: {tag} | Task: {task} | "
                f"Progress: {run.get('progress_text') or 'unknown'}"
            )
            append(f"  Wave: {wave} | Pair: {pair}")
            append(f"  Last start: {started} | Last stop: {stopped}")
            append(f"  Result: {current} | Reason: {issue} | Fails: {failures}")
            append(f"  Telegram: {telegram}")
            append(f"  Next: {next_action}")
    return "\n".join(lines)


def format_rich(snapshot: dict):
    """Return a Rich renderable for the live HUD."""
    try:
        from rich import box
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rich is required for hud --rich") from exc

    project = snapshot.get("project") or {}
    current = snapshot.get("current_wave") or {}

    summary = Table.grid(expand=True)
    summary.add_column("Panel", style="cyan", no_wrap=True, width=10)
    summary.add_column("Value", ratio=1, overflow="fold")
    summary.add_row(
        "Folder",
        Text(str(project.get("root") or "-")),
    )
    if current:
        verdict = str(current.get("verdict") or "?")
        verdict_style = {
            "PASS": "green",
            "FAIL": "red",
            "ERROR": "red",
        }.get(verdict.upper(), "yellow")
        current_line = Text.assemble(
            ("wave=", "dim"),
            _compact_middle(current.get("wave_id") or "?", 36),
            (" task_id=", "dim"),
            str(current.get("task_id") or "-"),
            (" pair=", "dim"),
            str(current.get("pair") or "-"),
            (" verdict=", "dim"),
            Text(verdict, style=verdict_style),
            (" duration=", "dim"),
            f"{current.get('duration_seconds') or 0}s",
            (" started=", "dim"),
            _human_time(current.get("started_at")),
            (" stopped=", "dim"),
            _human_time(current.get("stopped_at")),
        )
        if current.get("last_log_line"):
            current_line.append(" log=", style="dim")
            current_line.append(str(current["last_log_line"]))
        summary.add_row("Current", current_line)
    else:
        summary.add_row("Current", Text("none", style="dim"))

    runtime = snapshot.get("runtime") or {}
    runtime_state = "live" if runtime.get("pid_alive") else "stale"
    summary.add_row(
        "Runtime",
        Text(
            f"{runtime_state} {runtime.get('mode') or '-'}/"
            f"{runtime.get('topology') or '-'} pair={runtime.get('pair') or '-'} "
            f"speed={runtime.get('speed_profile') or '-'} "
            f"agents={runtime.get('max_agents') or '-'}"
        ),
    )

    progress = snapshot.get("progress") or {}
    progress_parts = [
        str(progress.get("text") or "unknown"),
        f"source={progress.get('source') or 'none'}",
    ]
    if progress.get("tag"):
        progress_parts.append(f"tag={progress.get('tag')}")
    summary.add_row("Progress", Text(" ".join(progress_parts)))

    today = snapshot.get("today") or {}
    summary.add_row(
        "Today",
        Text(
            f"{today.get('total_waves', 0)} waves, "
            f"{today.get('success_rate', 0)}% pass, "
            f"mean {today.get('mean_duration_s', 0)}s"
        ),
    )

    notifications = snapshot.get("notifications") or {}
    pending = notifications.get("pending_lines")
    next_step = notifications.get("next_step") or "none"
    summary.add_row(
        "Telegram",
        Text(
            f"{notifications.get('status') or '?'}"
            f" reason={notifications.get('reason') or '-'}"
            f" pending={'-' if pending is None else pending}"
            f" next={next_step}"
        ),
    )

    quota_parts = []
    for engine, payload in (snapshot.get("quota") or {}).items():
        used = payload.get("short_used_pct")
        remaining = payload.get("short_remaining_pct")
        quota_parts.append(
            f"{engine}:"
            f"{'-' if used is None else str(used) + '%'}"
            f"/{'-' if remaining is None else str(remaining) + '%'}"
            f"({payload.get('source') or '-'})"
        )
    if not snapshot.get("quota"):
        quota_parts.append("missing")
    summary.add_row("Quota", Text(", ".join(quota_parts)))

    team_parts = []
    for team in snapshot.get("active_teams") or []:
        team_parts.append(
            f"{team.get('name') or '-'}:"
            f"{team.get('status') or '-'}"
            f" workers={team.get('workers') or '-'}"
            f" pending={team.get('pending_dispatches', 0)}"
        )
    if not snapshot.get("active_teams"):
        team_parts.append("none")
    summary.add_row("Teams", Text(", ".join(team_parts)))

    recent_table = Table(
        title="Recent waves (newest stopped first)",
        expand=True,
        box=box.SIMPLE_HEAD,
        show_edge=False,
        pad_edge=False,
    )
    recent_table.add_column("Wave ID", no_wrap=True, overflow="ellipsis", max_width=28)
    recent_table.add_column("Task ID", no_wrap=True, overflow="ellipsis", max_width=8)
    recent_table.add_column("Started", no_wrap=True, overflow="ellipsis")
    recent_table.add_column("Stopped", no_wrap=True, overflow="ellipsis")
    recent_table.add_column("Pair", overflow="ellipsis")
    recent_table.add_column("Verdict", no_wrap=True, overflow="ellipsis")
    recent_table.add_column("Duration", justify="right", no_wrap=True)
    for wave in snapshot.get("recent_waves") or []:
        verdict_text = str(wave.get("verdict") or "?")
        verdict_style = {
            "PASS": "green",
            "FAIL": "red",
            "ERROR": "red",
        }.get(verdict_text.upper(), "yellow")
        recent_table.add_row(
            _compact_middle(wave.get("wave_id") or "?", 28),
            str(wave.get("task_id") or "-"),
            _human_time(wave.get("started_at")),
            _human_time(wave.get("stopped_at")),
            str(wave.get("pair") or "-"),
            Text(verdict_text, style=verdict_style),
            f"{wave.get('duration_seconds') or 0}s",
        )
    if not snapshot.get("recent_waves"):
        recent_table.add_row("-", "-", "-", "-", "-", "-", "-")

    ledger = snapshot.get("ledger_state") or {}
    ledger_text = (
        f"{ledger.get('status') or 'unknown'} "
        f"entries={ledger.get('entries', snapshot.get('entry_count', 0))} "
        f"valid={ledger.get('valid_entries', 0)}"
    )
    ledger_reason = ledger.get("reason") or ""
    if ledger_reason:
        ledger_text = f"{ledger_text} ({ledger_reason})"

    return Group(
        Panel(
            Text(
                f"Mainspring | {snapshot.get('generated_at', '')} | {ledger_text}",
                style="bold",
            ),
            border_style="blue",
        ),
        summary,
        recent_table,
    )


def format_global_rich(snapshot: dict):
    """Return a Rich renderable for the global live HUD."""
    try:
        from rich.console import Group
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rich is required for hud --rich") from exc

    title = Panel(
        Text.assemble(
            ("Mainspring", "bold"),
            " | ",
            (snapshot.get("generated_at", ""), "dim"),
            " | ",
            (f"{snapshot.get('live_count', 0)} live", "green"),
            " / ",
            (f"{snapshot.get('needs_action_count', 0)} needs action", "red"),
            " / ",
            (f"{snapshot.get('stale_count', 0)} past", "yellow"),
        ),
        border_style="blue",
    )

    if not snapshot.get("runs"):
        empty = Table.grid(expand=True)
        empty.add_column("Label", style="bold cyan", no_wrap=True, width=22)
        empty.add_column("Value", ratio=1, overflow="fold")
        empty.add_row(
            "State", Text("IDLE - no Mainspring work is running", style="bold green")
        )
        empty.add_row(
            "Meaning", "No active Mainspring run was discovered on this machine."
        )
        empty.add_row("Start new work", "cd /path/to/project && mainspring")
        empty.add_row("Resume saved setup", "mainspring --last-run")
        empty.add_row("Inspect saved setup", "mainspring last-run")
        empty.add_row("Current project", "mainspring status")
        empty.add_row("Past runs", "mainspring hud --all-runtimes")
        empty.add_row("Telegram health", "mainspring notify-health --format json")
        empty.add_row("Stop current project", "mainspring stop --force")
        return Group(title, Panel(empty, title="Ready To Start", border_style="green"))

    cards = [title]
    for run in snapshot.get("runs") or []:
        state = str(run.get("operator_state") or run.get("status") or "?").upper()
        current, issue, failures = _run_display_fields(run)
        state_label = _operator_state_label(state, run.get("verdict"))
        state_style = _operator_state_style(state, run.get("verdict"))
        current_style = {
            "RUNNING": "green",
            "RUNNING NOW": "green",
            "PASS": "green",
            "FAIL": "red",
            "ERROR": "red",
            "IDLE": "cyan",
        }.get(current.upper(), "yellow")

        details = Table.grid(expand=True)
        details.add_column("Label", style="bold cyan", no_wrap=True, width=16)
        details.add_column("Value", ratio=1, overflow="fold")
        details.add_row("State", Text(state_label, style=state_style))
        details.add_row("Folder", str(run.get("folder") or "-"))
        details.add_row("PID", str(run.get("pid") or "-"))
        details.add_row(
            "Tag / Task",
            f"{run.get('taskmaster_tag') or '-'} / {run.get('task_id') or '-'}",
        )
        details.add_row("Progress", str(run.get("progress_text") or "unknown"))
        details.add_row("Wave", _compact_middle(run.get("wave_id") or "-", 44))
        details.add_row("Pair", str(run.get("pair") or "-"))
        details.add_row("Started", _run_start_display(run))
        details.add_row("Last stop", _human_time(run.get("last_stopped_at")))
        details.add_row("Now", Text(current, style=current_style))
        details.add_row("Issue", issue)
        details.add_row("Failures", failures)
        details.add_row("Telegram", str(run.get("telegram_status") or "-"))
        details.add_row("Next", str(run.get("next_action") or "-"))

        title_text = Text.assemble(
            (state_label, state_style),
            "  ",
            (str(run.get("project") or "-"), "bold"),
        )
        cards.append(
            Panel(
                details,
                title=title_text,
                border_style=_operator_state_border_style(state, run.get("verdict")),
            )
        )
    return Group(*cards)


def rich_live_snapshot(
    ledger_path: Path,
    state_dir: Path,
    *,
    since: str = "",
    width: int | None = None,
    interval: float = 1.0,
    iterations: int | None = None,
    ansi: bool | None = None,
    global_scope: bool = False,
    search_roots: list[Path] | None = None,
    include_stale: bool = False,
    stream=sys.stdout,
    sleep=time.sleep,
) -> None:
    """Render a Rich live HUD, with finite iterations for smoke tests."""
    try:
        from rich.console import Console
        from rich.live import Live
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("rich is required for hud --rich") from exc

    console_kwargs: dict[str, object] = {"file": stream}
    if width is not None:
        console_kwargs["width"] = width
    if ansi is not None:
        console_kwargs["force_terminal"] = ansi
    console = Console(**console_kwargs)
    refresh_per_second = 4.0 if interval <= 0 else max(0.5, min(10.0, 1.0 / interval))
    if global_scope:
        renderable = format_global_rich(
            build_global_snapshot(
                ledger_path,
                state_dir,
                since=since,
                search_roots=search_roots,
                include_stale=include_stale,
            )
        )
    else:
        renderable = format_rich(build_snapshot(ledger_path, state_dir, since=since))

    with Live(
        renderable,
        console=console,
        refresh_per_second=refresh_per_second,
        redirect_stdout=False,
        redirect_stderr=False,
        screen=False,
        transient=False,
    ) as live:
        live.update(renderable, refresh=True)
        frames = 1
        while iterations is None or frames < iterations:
            sleep(interval)
            if global_scope:
                renderable = format_global_rich(
                    build_global_snapshot(
                        ledger_path,
                        state_dir,
                        since=since,
                        search_roots=search_roots,
                        include_stale=include_stale,
                    )
                )
            else:
                renderable = format_rich(
                    build_snapshot(ledger_path, state_dir, since=since)
                )
            live.update(renderable, refresh=True)
            frames += 1


def watch_snapshot(
    ledger_path: Path,
    state_dir: Path,
    *,
    since: str = "",
    width: int | None = None,
    interval: float = 1.0,
    iterations: int | None = None,
    ansi: bool | None = None,
    global_scope: bool = False,
    search_roots: list[Path] | None = None,
    include_stale: bool = False,
    stream=sys.stdout,
    sleep=time.sleep,
) -> None:
    frames = 0
    use_ansi = (
        bool(getattr(stream, "isatty", lambda: False)()) if ansi is None else ansi
    )
    while True:
        if global_scope:
            snapshot = build_global_snapshot(
                ledger_path,
                state_dir,
                since=since,
                search_roots=search_roots,
                include_stale=include_stale,
            )
            rendered = format_global_text(snapshot, width=width)
        else:
            snapshot = build_snapshot(ledger_path, state_dir, since=since)
            rendered = format_text(snapshot, width=width)
        if use_ansi:
            stream.write("\033[2J\033[H")
        elif frames > 0:
            stream.write("\n")
        stream.write(rendered)
        stream.write("\n")
        stream.flush()
        frames += 1
        if iterations is not None and frames >= iterations:
            return
        sleep(interval)


def _usage(stream=sys.stderr) -> None:
    print(
        """Mainspring HUD

Shows operator health for Mainspring runs.

Default:
  mainspring hud
    Global dashboard for all discovered Mainspring runs on this machine.
    In an interactive terminal it opens the live Rich dashboard. In captured
    output it prints one bounded snapshot.

Copy/paste commands:
  Each row below is a complete runnable command.
  live dashboard              mainspring hud
  one global snapshot         mainspring hud --once
  only this project           mainspring hud --local --once
  include past runs           mainspring hud --all-runtimes
  automation JSON             mainspring hud --json --once
  plain live refresh          mainspring hud --watch --interval 2
  stop this project           mainspring stop --force

Fields:
  Project, Folder, PID, Tag, Task, Wave, Pair, Started, Last Stop, Result,
  Reason, Fails, Telegram, Progress, Next.

Usage:
  mainspring hud [--global|--local] [--all-runtimes] [--once|--watch]
    [--rich] [--json] [--since <15m|1h|1d|ISO>] [--width <cols>]
    [--interval <seconds>] [--iterations <count>] [--ansi|--no-ansi]""",
        file=stream,
    )


def _default_runtime_dir() -> Path:
    configured = os.environ.get("MAINSPRING_RUNTIME_DIR")
    if configured:
        return Path(configured)
    if Path(".mainspring").exists():
        return Path(".mainspring")
    return Path(".mainspring")


def _default_state_dir(runtime_dir: Path) -> Path:
    configured = os.environ.get("MAINSPRING_STATE_DIR")
    if configured:
        return Path(configured)
    return runtime_dir / "state"


def _rich_available() -> bool:
    try:
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


def _cli_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    no_args = not args
    runtime_dir = _default_runtime_dir()
    ledger_path = runtime_dir / "logs" / "waves.jsonl"
    state_dir = _default_state_dir(runtime_dir)
    since = ""
    output_json = False
    watch = False
    rich_mode = False
    global_scope = False
    include_stale = False
    auto_live = False
    once = False
    width: int | None = None
    interval = 1.0
    iterations: int | None = None
    ansi: bool | None = None
    search_roots: list[Path] = []

    index = 0
    while index < len(args):
        arg = args[index]
        if arg in {"--help", "-h"}:
            _usage(sys.stdout)
            return 0
        if arg == "--ledger" and index + 1 < len(args):
            ledger_path = Path(args[index + 1])
            index += 2
        elif arg == "--ledger":
            print("hud: --ledger requires a value", file=sys.stderr)
            return 2
        elif arg == "--state-dir" and index + 1 < len(args):
            state_dir = Path(args[index + 1])
            index += 2
        elif arg == "--state-dir":
            print("hud: --state-dir requires a value", file=sys.stderr)
            return 2
        elif arg == "--since" and index + 1 < len(args):
            since = args[index + 1]
            index += 2
        elif arg == "--since":
            print("hud: --since requires a value", file=sys.stderr)
            return 2
        elif arg == "--json":
            output_json = True
            index += 1
        elif arg == "--global":
            global_scope = True
            index += 1
        elif arg == "--local":
            global_scope = False
            index += 1
        elif arg == "--all-runtimes":
            include_stale = True
            index += 1
        elif arg == "--auto-live":
            auto_live = True
            index += 1
        elif arg == "--search-root" and index + 1 < len(args):
            search_roots.append(Path(args[index + 1]))
            index += 2
        elif arg == "--search-root":
            print("hud: --search-root requires a value", file=sys.stderr)
            return 2
        elif arg == "--watch":
            watch = True
            index += 1
        elif arg == "--rich":
            rich_mode = True
            index += 1
        elif arg == "--width" and index + 1 < len(args):
            try:
                width = int(args[index + 1])
            except ValueError:
                print("hud: --width must be an integer", file=sys.stderr)
                return 2
            index += 2
        elif arg == "--width":
            print("hud: --width requires a value", file=sys.stderr)
            return 2
        elif arg == "--interval" and index + 1 < len(args):
            try:
                interval = float(args[index + 1])
            except ValueError:
                print("hud: --interval must be a number", file=sys.stderr)
                return 2
            if interval < 0:
                print("hud: --interval must not be negative", file=sys.stderr)
                return 2
            index += 2
        elif arg == "--interval":
            print("hud: --interval requires a value", file=sys.stderr)
            return 2
        elif arg == "--iterations" and index + 1 < len(args):
            try:
                iterations = int(args[index + 1])
            except ValueError:
                print("hud: --iterations must be an integer", file=sys.stderr)
                return 2
            if iterations < 1:
                print("hud: --iterations must be at least 1", file=sys.stderr)
                return 2
            index += 2
        elif arg == "--iterations":
            print("hud: --iterations requires a value", file=sys.stderr)
            return 2
        elif arg == "--ansi":
            ansi = True
            index += 1
        elif arg == "--no-ansi":
            ansi = False
            index += 1
        elif arg == "--once":
            once = True
            index += 1
        else:
            print(f"Unknown or incomplete flag: {arg}", file=sys.stderr)
            _usage()
            return 2

    if output_json and (watch or rich_mode):
        print("hud: --json cannot be combined with live HUD modes", file=sys.stderr)
        return 2
    stdout_is_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())
    if (
        (auto_live or no_args)
        and not once
        and not watch
        and not rich_mode
        and not output_json
        and stdout_is_tty
    ):
        watch = True
        rich_mode = _rich_available()
    if iterations is not None and not (watch or rich_mode):
        print("hud: --iterations requires --watch or --rich", file=sys.stderr)
        return 2
    if once and rich_mode and iterations is None:
        iterations = 1

    try:
        if rich_mode:
            rich_live_snapshot(
                ledger_path,
                state_dir,
                since=since,
                width=width,
                interval=interval,
                iterations=iterations,
                ansi=ansi,
                global_scope=global_scope,
                search_roots=search_roots or None,
                include_stale=include_stale,
            )
            return 0
        if watch:
            watch_snapshot(
                ledger_path,
                state_dir,
                since=since,
                width=width,
                interval=interval,
                iterations=iterations,
                ansi=ansi,
                global_scope=global_scope,
                search_roots=search_roots or None,
                include_stale=include_stale,
            )
            return 0
        if global_scope:
            snapshot = build_global_snapshot(
                ledger_path,
                state_dir,
                since=since,
                search_roots=search_roots or None,
                include_stale=include_stale,
            )
        else:
            snapshot = build_snapshot(ledger_path, state_dir, since=since)
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError) as exc:
        print(f"hud: {exc}", file=sys.stderr)
        return 2
    if output_json:
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        if global_scope:
            print(format_global_text(snapshot, width=width))
        else:
            print(format_text(snapshot, width=width))
    return 0


if __name__ == "__main__":
    run_cli(_cli_main)
