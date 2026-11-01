#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Team dispatch operations for Mainspring.

Subcommands:
    dispatch         Parse items JSONL, round-robin dispatch to team workers.
    counts           List team tasks and print pending/in_progress/completed/failed.
    nudge            Send reminders to idle workers with old pending tasks.
    requeue          Release stale in-progress tasks back to the queue.
    close-bootstrap  Auto-close non-Task-Master bootstrap tasks.

Usage:
    python3 team_dispatch.py dispatch <team_name> <team_size> <items_jsonl>
        [--retry-task <taskmaster-id>]...
    python3 team_dispatch.py counts <team_name>
    python3 team_dispatch.py nudge <team_name> [--min-age-seconds N]
    python3 team_dispatch.py requeue <team_name> [--stale-minutes N]
    python3 team_dispatch.py close-bootstrap <team_name>
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from cli_runtime import run_cli


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _list_tasks(team_name: str) -> dict | None:
    """Call the team backend task-list API and return parsed JSON or None."""
    listed = subprocess.run(
        [
            "omx",
            "team",
            "api",
            "list-tasks",
            "--input",
            json.dumps({"team_name": team_name}),
            "--json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if listed.returncode != 0:
        return None
    try:
        return json.loads(listed.stdout)
    except json.JSONDecodeError:
        return None


def _tm_tasks(payload: dict) -> list[dict]:
    """Filter tasks to those with subject starting with ``Task Master ``."""
    tasks = payload.get("data", {}).get("tasks", []) or []
    return [t for t in tasks if str(t.get("subject") or "").startswith("Task Master ")]


def _taskmaster_id_from_subject(subject: str) -> str:
    """Extract the Taskmaster id from a ``Task Master <id> - ...`` subject."""
    prefix = "Task Master "
    if not subject.startswith(prefix):
        return ""
    rest = subject[len(prefix) :].strip()
    if not rest:
        return ""
    return rest.split(" - ", 1)[0].split(None, 1)[0].strip()


# ── dispatch ledger ────────────────────────────────────────────────────


SAFE_TEAM_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _runtime_dir() -> Path:
    """Return the Mainspring runtime root."""
    configured = os.environ.get("MAINSPRING_RUNTIME_DIR")
    if configured:
        return Path(configured)
    return Path(".mainspring")


def _runtime_state_dir() -> Path:
    """Return the resolved runtime state directory."""
    configured = os.environ.get("MAINSPRING_STATE_DIR")
    if configured:
        return Path(configured)
    return _runtime_dir() / "state"


def _dispatch_ledger_path(team_name: str) -> Path:
    """Return the path to the dispatch ledger for a team."""
    if team_name in {"", ".", ".."} or not SAFE_TEAM_NAME_RE.fullmatch(team_name):
        raise ValueError(f"unsafe team name: {team_name!r}")
    root_path = _runtime_state_dir() / "team"
    root = root_path.resolve()
    path = root_path / team_name
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"team ledger path escapes runtime state: {team_name!r}")
    return path / "dispatch-ledger.json"


def _read_dispatch_ledger(team_name: str) -> dict[str, dict]:
    """Read the dispatch ledger.  Returns ``{taskmaster_id: {status, ts, subject}}``."""
    path = _dispatch_ledger_path(team_name)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _write_dispatch_ledger(team_name: str, ledger: dict[str, dict]) -> None:
    """Persist the dispatch ledger atomically."""
    path = _dispatch_ledger_path(team_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(ledger, fh, indent=2)
    tmp.replace(path)


def _record_dispatch(
    team_name: str,
    tm_id: str,
    subject: str,
    status: str = "pending",
    team_task_id: str = "",
    owner: str = "",
) -> dict:
    """Record a dispatch event in the ledger."""
    ledger = _read_dispatch_ledger(team_name)
    ledger[tm_id] = {
        "status": status,
        "subject": subject,
        "team_task_id": team_task_id,
        "owner": owner,
        "ts": datetime.now(UTC).isoformat(),
    }
    _write_dispatch_ledger(team_name, ledger)
    return ledger[tm_id]


def _refresh_dispatch_ledger_from_team_tasks(
    team_name: str, payload: dict | None
) -> dict[str, dict]:
    """Merge current team backend task statuses into the persisted dispatch ledger."""
    ledger = _read_dispatch_ledger(team_name)
    if not payload:
        return ledger

    now = datetime.now(UTC).isoformat()
    changed = False
    for task in _tm_tasks(payload):
        subject = str(task.get("subject") or "")
        tm_id = _taskmaster_id_from_subject(subject)
        if not tm_id:
            continue
        previous = ledger.get(tm_id, {})
        next_entry = {
            "status": str(task.get("status") or "unknown"),
            "subject": subject,
            "team_task_id": str(task.get("id") or previous.get("team_task_id") or ""),
            "owner": str(task.get("owner") or previous.get("owner") or ""),
            "ts": str(previous.get("ts") or now),
            "observed_at": now,
        }
        if previous != next_entry:
            ledger[tm_id] = next_entry
            changed = True

    if changed:
        _write_dispatch_ledger(team_name, ledger)
    return ledger


def _duplicate_status_blocks_dispatch(status: str | None) -> bool:
    """Return true when a ledger status should block another automatic dispatch."""
    return str(status or "").strip() in {
        "pending",
        "in_progress",
        "completed",
        "failed",
        "dispatched",
    }


# ── dispatch ───────────────────────────────────────────────────────────


def cmd_dispatch(
    team_name: str,
    team_size: int,
    items_jsonl: str,
    retry_ids: frozenset[str] | None = None,
) -> None:
    """Parse items JSONL, create team tasks, and message assigned workers."""
    team_size = max(1, team_size)
    retry_ids = retry_ids or frozenset()
    items: list[dict] = []
    for raw in items_jsonl.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            items.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            print(f"[team-dispatch] skipped invalid item json: {exc}", file=sys.stderr)

    if not items:
        print("[team-dispatch] no items to dispatch")
        return

    # Deduplicate against existing active team tasks.
    existing_subjects: set[str] = set()
    payload = _list_tasks(team_name)
    ledger = _refresh_dispatch_ledger_from_team_tasks(team_name, payload)
    if payload:
        for task in _tm_tasks(payload):
            existing_subjects.add(str(task.get("subject") or ""))

    failures = 0
    for idx, item in enumerate(items, start=1):
        worker = f"worker-{((idx - 1) % team_size) + 1}"
        tm_id = str(item.get("id") or "").strip()
        title = str(item.get("title") or "").strip()
        description = str(item.get("description") or "").strip()
        scope = item.get("scope") or []
        if not isinstance(scope, list):
            scope = [str(scope)]
        scope_text = (
            ", ".join(str(part) for part in scope if str(part).strip())
            or "unknown; inspect Task Master details before editing"
        )
        subject = f"Task Master {tm_id} - {title}".strip()
        ledger_entry = ledger.get(tm_id) if tm_id else None
        if (
            tm_id
            and tm_id not in retry_ids
            and ledger_entry
            and _duplicate_status_blocks_dispatch(ledger_entry.get("status"))
        ):
            print(
                "[team-dispatch] skipped duplicate dispatch ledger entry: "
                f"Task Master {tm_id} is already "
                f"{ledger_entry.get('status', 'recorded')} in team {team_name}"
            )
            continue

        if subject in existing_subjects and tm_id not in retry_ids:
            print(
                f"[team-dispatch] skipped duplicate active team assignment: {subject}"
            )
            continue
        if tm_id in retry_ids:
            print(f"[team-dispatch] retry override enabled for Task Master {tm_id}")

        task_description = (
            f"Task Master id: {tm_id}\n"
            f"Title: {title}\n"
            f"Description: {description}\n\n"
            f"Expected file scope: {scope_text}\n\n"
            "Execution rules: read project guidance files (AGENTS.md / CLAUDE.md "
            "when present) and Taskmaster docs first; implement only this Task "
            "Master work item; keep write scope disjoint from other workers; "
            "run targeted verification plus typecheck/build when relevant; "
            "update Task Master with close-out evidence; leave the Task Master item "
            "in review unless reviewer PASS exists; never close the parent while any "
            "child remains pending, in-progress, review, or blocked.\n\n"
            "Report: files changed, tests/build/typecheck evidence, chapter delta, "
            "competitor delta, launch blocker reduced, gaps."
        )
        create_payload = {
            "team_name": team_name,
            "subject": subject,
            "description": task_description,
            "owner": worker,
            "requires_code_change": True,
        }
        created = subprocess.run(
            [
                "omx",
                "team",
                "api",
                "create-task",
                "--input",
                json.dumps(create_payload),
                "--json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        print(created.stdout, end="")
        if created.returncode != 0:
            print(f"[team-dispatch] create-task failed for {tm_id}", file=sys.stderr)
            if tm_id:
                ledger[tm_id] = _record_dispatch(
                    team_name, tm_id, subject, status="failed", owner=worker
                )
            failures += 1
            continue

        try:
            created_obj = json.loads(created.stdout)
            task_id = str(
                created_obj.get("data", {}).get("task", {}).get("id")
                or created_obj.get("data", {}).get("id")
                or ""
            )
        except Exception:
            task_id = ""
        if tm_id:
            ledger[tm_id] = _record_dispatch(
                team_name,
                tm_id,
                subject,
                status="pending",
                team_task_id=task_id,
                owner=worker,
            )

        body = (
            f"Task assigned: execute team task {task_id or '(created)'} = "
            f"Task Master {tm_id}. {title}. Stay in your worktree. Claim the "
            "task if needed, implement, verify, update Task Master, and report "
            "evidence."
        )
        msg_payload = {
            "team_name": team_name,
            "from_worker": "leader-fixed",
            "to_worker": worker,
            "body": body,
        }
        sent = subprocess.run(
            [
                "omx",
                "team",
                "api",
                "send-message",
                "--input",
                json.dumps(msg_payload),
                "--json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        print(sent.stdout, end="")
        if sent.returncode != 0:
            fallback = subprocess.run(
                [
                    "omx",
                    "team",
                    "api",
                    "write-worker-inbox",
                    "--input",
                    json.dumps(
                        {
                            "team_name": team_name,
                            "worker": worker,
                            "content": body + "\n",
                        }
                    ),
                    "--json",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            print(fallback.stdout, end="")
            if fallback.returncode != 0:
                print(
                    f"[team-dispatch] send-message and inbox fallback failed "
                    f"for {tm_id}",
                    file=sys.stderr,
                )
                failures += 1

    if failures:
        raise SystemExit(1)


# ── counts ─────────────────────────────────────────────────────────────


def cmd_counts(team_name: str) -> None:
    """Print ``pending in_progress completed failed`` counts."""
    listed = subprocess.run(
        [
            "omx",
            "team",
            "api",
            "list-tasks",
            "--input",
            json.dumps({"team_name": team_name}),
            "--json",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if listed.returncode != 0:
        print(
            f"team_task_counts:list-tasks failed: {listed.stdout.strip()}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    try:
        payload = json.loads(listed.stdout)
    except json.JSONDecodeError as exc:
        print(f"team_task_counts:invalid json: {exc}", file=sys.stderr)
        raise SystemExit(1)

    tasks = _tm_tasks(payload)
    pending = sum(1 for t in tasks if t.get("status") == "pending")
    in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
    completed = sum(1 for t in tasks if t.get("status") == "completed")
    failed = sum(1 for t in tasks if t.get("status") == "failed")
    print(pending, in_progress, completed, failed)


# ── nudge ──────────────────────────────────────────────────────────────


def cmd_nudge(team_name: str, min_age_seconds: int = 60) -> None:
    """Send reminders to idle workers with old pending tasks."""
    min_age = max(15, min_age_seconds)
    payload = _list_tasks(team_name)
    if not payload:
        return

    now = datetime.now(UTC)
    all_tasks = payload.get("data", {}).get("tasks", []) or []

    for task in all_tasks:
        subject = str(task.get("subject") or "")
        if not subject.startswith("Task Master ") or task.get("status") != "pending":
            continue
        worker = task.get("owner")
        if not worker:
            continue

        created = _parse_time(task.get("created_at"))
        if created and (now - created).total_seconds() < min_age:
            continue

        status_path = (
            _runtime_state_dir()
            / "team"
            / team_name
            / "workers"
            / worker
            / "status.json"
        )
        try:
            with open(status_path, encoding="utf-8") as fh:
                worker_status = json.load(fh)
        except Exception:
            worker_status = {}
        if worker_status.get("state") not in (None, "idle", "blocked"):
            continue

        worker_busy = any(
            other.get("status") == "in_progress"
            and ((other.get("claim") or {}).get("owner") or other.get("owner"))
            == worker
            for other in all_tasks
        )
        if worker_busy:
            continue

        body = (
            f"Pending assignment still waiting: execute team task {task.get('id')} "
            f"= {subject}. Read your inbox, claim it if unclaimed, work now, "
            "verify, update Task Master, and report evidence."
        )
        sent = subprocess.run(
            [
                "omx",
                "team",
                "api",
                "send-message",
                "--input",
                json.dumps(
                    {
                        "team_name": team_name,
                        "from_worker": "leader-fixed",
                        "to_worker": worker,
                        "body": body,
                    }
                ),
                "--json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        print(
            f"Nudged pending team task {task.get('id')} to {worker}; "
            f"send_exit={sent.returncode}"
        )
        if sent.stdout:
            print(sent.stdout, end="")


# ── requeue ────────────────────────────────────────────────────────────


def cmd_requeue(team_name: str, stale_minutes: int = 10) -> None:
    """Release stale in-progress tasks back to the queue."""
    stale_seconds = max(60, int(stale_minutes * 60))
    payload = _list_tasks(team_name)
    if not payload:
        return

    now = datetime.now(UTC)
    for task in payload.get("data", {}).get("tasks", []) or []:
        subject = str(task.get("subject") or "")
        if (
            not subject.startswith("Task Master ")
            or task.get("status") != "in_progress"
        ):
            continue
        claim = task.get("claim") or {}
        token = claim.get("token")
        worker = claim.get("owner") or task.get("owner")
        if not token or not worker:
            continue

        worker_status: dict = {}
        heartbeat: dict = {}
        status_path = (
            _runtime_state_dir()
            / "team"
            / team_name
            / "workers"
            / worker
            / "status.json"
        )
        heartbeat_path = (
            _runtime_state_dir()
            / "team"
            / team_name
            / "workers"
            / worker
            / "heartbeat.json"
        )
        try:
            with open(status_path, encoding="utf-8") as fh:
                worker_status = json.load(fh)
        except Exception:
            pass
        try:
            with open(heartbeat_path, encoding="utf-8") as fh:
                heartbeat = json.load(fh)
        except Exception:
            pass

        lease_until = _parse_time(claim.get("leased_until"))
        lease_expired = bool(lease_until and lease_until <= now)
        updated_at = _parse_time(worker_status.get("updated_at"))
        last_turn_at = _parse_time(heartbeat.get("last_turn_at"))
        worker_idle_stale = bool(
            worker_status.get("state") == "idle"
            and updated_at
            and (now - updated_at).total_seconds() >= stale_seconds
        )
        heartbeat_dead = bool(heartbeat.get("alive") is False)
        heartbeat_stale = bool(
            last_turn_at and (now - last_turn_at).total_seconds() >= stale_seconds
        )

        stale_reason: str | None = None
        if heartbeat_dead:
            stale_reason = "worker heartbeat reports dead"
        elif lease_expired and worker_idle_stale and heartbeat_stale:
            stale_reason = (
                f"expired lease {lease_until.isoformat()}, idle status, "  # type: ignore[union-attr]
                "and stale heartbeat"
            )

        if not stale_reason:
            continue

        release_payload = {
            "team_name": team_name,
            "task_id": str(task.get("id")),
            "claim_token": token,
            "worker": worker,
        }
        released = subprocess.run(
            [
                "omx",
                "team",
                "api",
                "release-task-claim",
                "--input",
                json.dumps(release_payload),
                "--json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        print(
            f"Requeue stale team task {task.get('id')} "
            f"({subject.splitlines()[0]}): {stale_reason}; "
            f"release_exit={released.returncode}"
        )
        if released.stdout:
            print(released.stdout, end="")


# ── close-bootstrap ───────────────────────────────────────────────────


def cmd_close_bootstrap(team_name: str) -> int:
    """Close non-Task-Master bootstrap tasks so they don't clutter the ledger.

    Bootstrap tasks are those whose subject does NOT start with ``Task Master ``.
    They are coordination scaffolding, not product work.  This function claims
    each one (to obtain a claim_token) and transitions it to ``completed``.

    Returns the number of tasks closed.
    """
    payload = _list_tasks(team_name)
    if not payload:
        return 0

    all_tasks = payload.get("data", {}).get("tasks", []) or []
    bootstrap = [
        t
        for t in all_tasks
        if not str(t.get("subject") or "").startswith("Task Master ")
        and t.get("status") in ("pending", "in_progress")
    ]
    if not bootstrap:
        return 0

    closed = 0
    for task in bootstrap:
        task_id = str(task.get("id") or "")
        subject = str(task.get("subject") or "")[:80]
        status = task.get("status") or "pending"

        # If already in_progress with a claim token, skip the claim step.
        claim = task.get("claim") or {}
        token = claim.get("token")

        if status == "pending":
            # Claim the task first to get a token.
            claim_result = subprocess.run(
                [
                    "omx",
                    "team",
                    "api",
                    "claim-task",
                    "--input",
                    json.dumps(
                        {
                            "team_name": team_name,
                            "task_id": task_id,
                            "worker": "leader-fixed",
                        }
                    ),
                    "--json",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if claim_result.returncode != 0:
                print(
                    f"[close-bootstrap] could not claim task {task_id} ({subject})",
                    file=sys.stderr,
                )
                continue
            try:
                claim_obj = json.loads(claim_result.stdout)
                token = claim_obj.get("data", {}).get("claim", {}).get(
                    "token"
                ) or claim_obj.get("data", {}).get("token")
            except (json.JSONDecodeError, AttributeError):
                print(
                    f"[close-bootstrap] invalid claim response for task {task_id}",
                    file=sys.stderr,
                )
                continue
            status = "in_progress"

        if not token:
            print(
                f"[close-bootstrap] no claim token for task {task_id} ({subject})",
                file=sys.stderr,
            )
            continue

        transition = subprocess.run(
            [
                "omx",
                "team",
                "api",
                "transition-task-status",
                "--input",
                json.dumps(
                    {
                        "team_name": team_name,
                        "task_id": task_id,
                        "from": status,
                        "to": "completed",
                        "claim_token": token,
                        "result": "Bootstrap task auto-closed by Mainspring.",
                    }
                ),
                "--json",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if transition.returncode == 0:
            closed += 1
            print(f"[close-bootstrap] closed bootstrap task {task_id}: {subject}")
        else:
            print(
                f"[close-bootstrap] transition failed for task {task_id} ({subject})",
                file=sys.stderr,
            )

    return closed


# ── CLI entry ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: team_dispatch.py <dispatch|counts|nudge|requeue|close-bootstrap> [args]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    subcmd = args[0]
    if subcmd == "dispatch":
        if len(args) < 4:
            print(
                "Usage: team_dispatch.py dispatch <team_name> <team_size> "
                "<items_jsonl> [--retry-task <taskmaster-id>]...",
                file=sys.stderr,
            )
            raise SystemExit(2)
        try:
            size = int(args[2])
        except ValueError:
            size = 1
        retry_ids: set[str] = set()
        idx = 4
        while idx < len(args):
            if args[idx] == "--retry-task" and idx + 1 < len(args):
                retry_ids.add(args[idx + 1])
                idx += 2
                continue
            print(
                "Usage: team_dispatch.py dispatch <team_name> <team_size> "
                "<items_jsonl> [--retry-task <taskmaster-id>]...",
                file=sys.stderr,
            )
            raise SystemExit(2)
        cmd_dispatch(args[1], size, args[3], frozenset(retry_ids))
    elif subcmd == "counts":
        if len(args) < 2:
            print("Usage: team_dispatch.py counts <team_name>", file=sys.stderr)
            raise SystemExit(2)
        cmd_counts(args[1])
    elif subcmd == "nudge":
        if len(args) < 2:
            print(
                "Usage: team_dispatch.py nudge <team_name> [--min-age-seconds N]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        min_age = 60
        if len(args) >= 4 and args[2] == "--min-age-seconds":
            try:
                min_age = int(args[3])
            except ValueError:
                pass
        cmd_nudge(args[1], min_age)
    elif subcmd == "requeue":
        if len(args) < 2:
            print(
                "Usage: team_dispatch.py requeue <team_name> [--stale-minutes N]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        stale_min = 10
        if len(args) >= 4 and args[2] == "--stale-minutes":
            try:
                stale_min = int(args[3])
            except ValueError:
                pass
        cmd_requeue(args[1], stale_min)
    elif subcmd == "close-bootstrap":
        if len(args) < 2:
            print(
                "Usage: team_dispatch.py close-bootstrap <team_name>",
                file=sys.stderr,
            )
            raise SystemExit(2)
        closed = cmd_close_bootstrap(args[1])
        if closed:
            print(f"[close-bootstrap] auto-closed {closed} bootstrap task(s)")
    else:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    run_cli(main)
