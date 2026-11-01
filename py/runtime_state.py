#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mainspring runtime state operations.

Subcommands:
    team-status         Print summary of active team backend from status JSON.
    runtime-summary     Print runtime state summary (session, skill, mode, warnings).
    repair              Detect and fix stale Mainspring skill/mode/pid state.
    cleanup-stale       Kill stale Mainspring processes older than TTL.
    stop-processes      Stop recorded or global Mainspring processes.
    find-latest-team    Print the most recently modified team name.

Usage:
    python3 runtime_state.py team-status <team_name> <status_json>
    python3 runtime_state.py runtime-summary <state_dir>
    python3 runtime_state.py repair <state_dir> [--dry-run] [--force]
    python3 runtime_state.py cleanup-stale <current_pid> <ttl_minutes> [--force]
    python3 runtime_state.py stop-processes <state_dir> <current_pid> [--force] [--all]
    python3 runtime_state.py find-latest-team <team_state_dir>
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from cli_runtime import run_cli


def _usage_error(message: str, usage: str) -> None:
    print(message, file=sys.stderr)
    print(usage, file=sys.stderr)
    raise SystemExit(2)


def _parse_flag_set(values: list[str], *, allowed: set[str], usage: str) -> set[str]:
    flags: set[str] = set()
    for value in values:
        if value not in allowed:
            _usage_error(f"Unknown option: {value}", usage)
        flags.add(value)
    return flags


def _parse_int_arg(value: str, name: str, usage: str) -> int:
    try:
        return int(value)
    except ValueError:
        _usage_error(f"{name} must be an integer", usage)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pid_alive(value: object) -> bool:
    try:
        pid = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _runtime_pid_files(state_dir: Path) -> list[Path]:
    """Return Mainspring runtime lock/PID files."""
    candidates = [state_dir / "mainspring.lock"]
    return [path for path in candidates if path.exists()]


def _resolve_state_child_path(root: Path, value: str) -> Path:
    """Resolve a runtime-state child path without allowing directory escape."""
    root_resolved = root.resolve()
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [Path.cwd() / raw, root / raw]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_relative_to(root_resolved):
            return candidate
    raise ValueError(f"refusing state path outside runtime state dir: {value}")


# ── team-status ────────────────────────────────────────────────────────


def cmd_team_status(team_name: str, status_json: str) -> None:
    """Print team status summary from team backend JSON."""
    try:
        payload = json.loads(status_json)
    except Exception:
        print(f"{team_name}: status unreadable")
        return
    workers = payload.get("workers") or {}
    tasks = payload.get("tasks") or {}
    print(
        f"{team_name}: status={payload.get('status', 'unknown')} "
        f"phase={payload.get('phase', 'unknown')} "
        f"workers={workers.get('total', 'unknown')} "
        f"dead={workers.get('dead', 'unknown')} "
        f"tasks pending={tasks.get('pending', 'unknown')} "
        f"in_progress={tasks.get('in_progress', 'unknown')} "
        f"completed={tasks.get('completed', 'unknown')} "
        f"failed={tasks.get('failed', 'unknown')}"
    )


# ── runtime-summary ───────────────────────────────────────────────────


def cmd_runtime_summary(state_dir: str) -> None:
    """Print runtime state summary."""
    root = Path(state_dir)
    warnings: list[str] = []

    def mode_file_for(skill_state: dict) -> Path | None:
        initialized = skill_state.get("initialized_state_path")
        if initialized:
            try:
                return _resolve_state_child_path(root, str(initialized))
            except ValueError as exc:
                warnings.append(str(exc))
                return None
        skill = skill_state.get("skill") or skill_state.get("initialized_mode")
        if skill:
            candidate = root / f"{skill}-state.json"
            try:
                _resolve_state_child_path(root, str(candidate.absolute()))
            except ValueError as exc:
                warnings.append(str(exc))
                return None
            return candidate
        return None

    session = _read_json(root / "session.json") or {}
    skill_state = _read_json(root / "skill-active-state.json") or {}
    mode_path = mode_file_for(skill_state) if skill_state else None
    mode_state = _read_json(mode_path) if mode_path else None
    session_pid_alive = _pid_alive(session.get("pid"))
    has_team_state = any((root / "team").glob("*/config.json"))

    print(
        "session: "
        f"id={session.get('session_id', 'unknown')} "
        f"pid={session.get('pid', 'unknown')} "
        f"cwd={session.get('cwd', 'unknown')}"
    )
    if skill_state:
        print(
            "skill-active: "
            f"active={skill_state.get('active', 'unknown')} "
            f"skill={skill_state.get('skill', skill_state.get('initialized_mode', 'unknown'))} "
            f"phase={skill_state.get('phase', 'unknown')}"
        )
    else:
        print("skill-active: missing")

    if mode_path:
        cwd = Path.cwd()
        display = (
            mode_path.relative_to(cwd)
            if mode_path.is_absolute() and mode_path.is_relative_to(cwd)
            else mode_path
        )
        if mode_state:
            print(
                f"mode-state: path={display} "
                f"active={mode_state.get('active', 'unknown')} "
                f"phase={mode_state.get('current_phase', mode_state.get('phase', 'unknown'))} "
                f"completed_at={mode_state.get('completed_at', '')}"
            )
        else:
            print(f"mode-state: path={display} missing/unreadable")

    if skill_state.get("active") is True and mode_state:
        mode_active = mode_state.get("active")
        phase = str(mode_state.get("current_phase") or mode_state.get("phase") or "")
        if mode_active is False or phase in {
            "completed",
            "complete",
            "cancelled",
            "failed",
        }:
            warnings.append(
                "stale skill-active state: active=true while mode state is "
                "completed/inactive"
            )
        elif mode_active is True and not session_pid_alive and not has_team_state:
            warnings.append(
                "stale active mode state: active=true but session pid is not "
                "alive and no team state exists"
            )

    for pid_file in _runtime_pid_files(root):
        try:
            pid_text = pid_file.read_text(encoding="utf-8").strip()
            pid = int(pid_text)
        except Exception:
            warnings.append(f"stale pid file candidate: {pid_file.name} unreadable")
            continue
        if not Path(f"/proc/{pid}").exists() and os.name != "posix":
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            warnings.append(f"stale pid file: {pid_file.name} -> {pid}")

    if warnings:
        print("warnings:")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("warnings: none")


# ── repair ─────────────────────────────────────────────────────────────


def cmd_repair(state_dir: str, dry_run: bool = False, force: bool = False) -> None:
    """Detect and fix stale Mainspring skill/mode/pid state."""
    root = Path(state_dir)
    skill_path = root / "skill-active-state.json"

    skill = _read_json(skill_path)
    if not skill:
        print("No readable skill-active-state.json; nothing to repair.")
        return

    initialized = skill.get("initialized_state_path")
    try:
        mode_path = (
            _resolve_state_child_path(root, str(initialized))
            if initialized
            else root
            / f"{skill.get('skill') or skill.get('initialized_mode', 'unknown')}-state.json"
        )
        if not initialized:
            _resolve_state_child_path(root, str(mode_path.absolute()))
    except ValueError as exc:
        print(f"{exc}; refusing repair.")
        raise SystemExit(2) from exc
    mode = _read_json(mode_path)
    if not mode:
        print(
            f"Mode state is missing/unreadable at {mode_path}; "
            "refusing repair without --force."
        )
        raise SystemExit(0 if not force else 1)

    session = _read_json(root / "session.json") or {}
    session_pid_alive = _pid_alive(session.get("pid"))
    has_team_state = any((root / "team").glob("*/config.json"))

    stale_pid_files: list[tuple[Path, str]] = []
    for pid_file in _runtime_pid_files(root):
        try:
            pid = int(pid_file.read_text(encoding="utf-8").strip())
        except Exception:
            stale_pid_files.append((pid_file, "unreadable"))
            continue
        if not _pid_alive(pid):
            stale_pid_files.append((pid_file, str(pid)))

    phase = str(mode.get("current_phase") or mode.get("phase") or "")
    stale_completed_mismatch = skill.get("active") is True and (
        mode.get("active") is False
        or phase in {"completed", "complete", "cancelled", "failed"}
    )
    stale_dead_session = (
        skill.get("active") is True
        and mode.get("active") is True
        and not session_pid_alive
        and not has_team_state
    )
    stale = stale_completed_mismatch or stale_dead_session or bool(stale_pid_files)
    if not stale:
        print("No stale skill-active/mode-state/pid-file mismatch found.")
        return

    if stale_dead_session:
        print(
            "Repair candidate: active mode state has no live session pid "
            "and no team state."
        )
    elif stale_completed_mismatch:
        print(
            "Repair candidate: skill-active active=true while mode state is "
            "inactive/completed."
        )
    elif stale_pid_files:
        print("Repair candidate: stale Mainspring pid files.")
    print(f"  skill={skill.get('skill') or skill.get('initialized_mode')}")
    print(f"  mode_path={mode_path}")
    print(
        f"  mode_active={mode.get('active')} phase={phase} "
        f"session_pid={session.get('pid')} "
        f"session_pid_alive={session_pid_alive} "
        f"team_state={has_team_state}"
    )
    if stale_pid_files:
        print("  stale_pid_files:")
        for path, pid in stale_pid_files:
            print(f"    - {path} -> {pid}")

    if dry_run:
        if stale_completed_mismatch or stale_dead_session:
            print("DRY_RUN: would mark skill-active and mode state inactive/completed.")
        if stale_pid_files:
            print("DRY_RUN: would remove stale Mainspring pid files.")
        return

    if not force:
        print(
            "Refusing repair without --force. "
            "Review --repair-state --dry-run first, then rerun with --repair-state --force."
        )
        raise SystemExit(2)

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if stale_completed_mismatch or stale_dead_session:
        skill["active"] = False
        skill["phase"] = "completed"
        skill["updated_at"] = now
        skill["completed_at"] = skill.get("completed_at") or now
        for item in skill.get("active_skills") or []:
            if isinstance(item, dict):
                item["active"] = False
                item["phase"] = "completed"
                item["updated_at"] = now
                item["completed_at"] = item.get("completed_at") or now
        skill_path.write_text(json.dumps(skill, indent=2) + "\n", encoding="utf-8")
        mode["active"] = False
        mode["phase"] = "completed"
        mode["current_phase"] = "completed"
        mode["updated_at"] = now
        mode["completed_at"] = mode.get("completed_at") or now
        mode_path.write_text(json.dumps(mode, indent=2) + "\n", encoding="utf-8")
        print("Repaired skill-active-state.json and mode state.")

    for path, _ in stale_pid_files:
        try:
            path.unlink()
            print(f"Removed stale pid file: {path}")
        except Exception as exc:
            print(f"Could not remove stale pid file {path}: {exc}")


# ── cleanup-stale ──────────────────────────────────────────────────────


def cmd_cleanup_stale(current_pid: int, ttl_minutes: int, force: bool = False) -> None:
    """Kill stale Mainspring processes older than TTL."""
    if not force:
        print(
            "Refusing stale process cleanup without --force. "
            "Review --repair-state --dry-run before force cleanup."
        )
        return

    patterns = (
        "/bin/bash ./mainspring.sh --last-run",
        "bash ./mainspring.sh --last-run",
    )

    try:
        output = subprocess.check_output(
            ["ps", "-axo", "pid=,etime=,command="], text=True
        )
    except Exception:
        return

    def elapsed_minutes(value: str) -> int:
        value = value.strip()
        if "-" in value:
            days, rest = value.split("-", 1)
            return int(days) * 24 * 60 + elapsed_minutes(rest)
        parts = [int(part) for part in value.split(":")]
        if len(parts) == 3:
            h, m, _ = parts
            return h * 60 + m
        if len(parts) == 2:
            m, _ = parts
            return m
        return 0

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        first, _, rest = line.partition(" ")
        try:
            pid = int(first)
        except ValueError:
            continue
        if pid == current_pid:
            continue
        rest = rest.strip()
        elapsed, _, command = rest.partition(" ")
        if elapsed_minutes(elapsed) < ttl_minutes:
            continue
        if any(command.startswith(pattern) for pattern in patterns):
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"Stopped stale process {pid}: {command[:120]}")
            except ProcessLookupError:
                pass
            except PermissionError:
                print(f"Could not stop stale process {pid}: permission denied")


# ── find-latest-team ───────────────────────────────────────────────────


def cmd_find_latest_team(team_state_dir: str) -> None:
    """Print the most recently modified team name."""
    root = Path(team_state_dir)
    configs: list[tuple[float, Path]] = []
    if root.exists():
        for config in root.glob("*/config.json"):
            try:
                configs.append((config.stat().st_mtime, config))
            except OSError:
                pass
    if not configs:
        return
    configs.sort(reverse=True)
    for _, config in configs:
        try:
            data = json.loads(config.read_text())
        except Exception:
            continue
        name = data.get("name") or config.parent.name
        if name:
            print(name)
            break


# ── stop-processes ─────────────────────────────────────────────────────


def _pid_from_file(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        pid = int(text)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _pid_command(pid: int) -> str:
    try:
        return subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
        ).strip()
    except Exception:
        return ""


def _meaningful_command_token(parts: list[str]) -> str:
    idx = 0
    while idx < len(parts):
        token = parts[idx]
        name = Path(token).name
        if name in {"env", "nohup"}:
            idx += 1
            while (
                idx < len(parts)
                and "=" in parts[idx]
                and not parts[idx].startswith("-")
            ):
                idx += 1
            continue
        if name in {"bash", "sh", "zsh"} or name.startswith("python"):
            idx += 1
            while idx < len(parts) and parts[idx].startswith("-"):
                idx += 1
            continue
        return token
    return ""


def _is_mainspring_command(command: str) -> bool:
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    token = _meaningful_command_token(parts)
    name = Path(token).name
    if name in {"mainspring", "mainspring.sh"}:
        return True
    if name in {"notify_telegram.py", "hud.py"}:
        return "mainspring" in command or ".mainspring" in command
    return token.startswith("mainspring ") or token.startswith("./mainspring.sh ")


def _command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _is_notifier_for_state_dir(command: str, state_dir: Path) -> bool:
    tokens = _command_tokens(command)
    if not any(Path(token).name == "notify_telegram.py" for token in tokens):
        return False
    state_dir = state_dir.absolute()
    runtime_dir = state_dir.parent
    expected = {
        str(runtime_dir / "logs" / "waves.jsonl"),
        str(state_dir),
    }
    return any(token in expected for token in tokens)


def _stop_pid(
    pid: int,
    current_pid: int,
    label: str,
    *,
    require_mainspring_command: bool = True,
) -> bool:
    if pid == current_pid:
        return False
    if not _pid_alive(pid):
        return False
    if require_mainspring_command:
        command = _pid_command(pid)
        if not _is_mainspring_command(command):
            print(f"Refusing to stop non-Mainspring {label} pid {pid}")
            return False
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"Could not stop {label} pid {pid}: {exc}")
        return False
    print(f"Stopped {label} pid {pid}")
    return True


def _safe_team_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if not value or value in {".", ".."}:
        return None
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-")
    if any(char not in allowed for char in value):
        return None
    if ".." in value:
        return None
    return value


def _recorded_team_names(state_dir: Path) -> list[str]:
    names: list[str] = []
    for config_path in sorted((state_dir / "team").glob("*/config.json")):
        payload = _read_json(config_path) or {}
        name = _safe_team_name(payload.get("name")) or _safe_team_name(
            config_path.parent.name
        )
        if name is not None:
            names.append(name)
        else:
            print(f"Refusing unsafe team backend name from {config_path}")
    return names


def _stop_team_backend(team_name: str) -> bool:
    try:
        result = subprocess.run(
            ["omx", "team", "shutdown", team_name, "--force"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        print(f"Could not stop team backend {team_name}: omx command not found")
        return False
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        suffix = f": {detail}" if detail else ""
        print(f"Could not stop team backend {team_name}{suffix}")
        return False
    print(f"Stopped team backend {team_name}")
    return True


def cmd_stop_processes(
    state_dir: str,
    current_pid: int,
    *,
    force: bool = False,
    all_projects: bool = False,
) -> None:
    """Stop Mainspring processes explicitly requested by the operator."""
    if not force:
        print("Refusing to stop processes without --force.")
        return

    stopped = 0
    root = Path(state_dir)
    if not all_projects:
        for team_name in _recorded_team_names(root):
            if _stop_team_backend(team_name):
                stopped += 1
        pid_files = [*(_runtime_pid_files(root)), root / "notifier.pid"]
        for path in pid_files:
            pid = _pid_from_file(path)
            if pid is None:
                continue
            command = _pid_command(pid)
            is_notifier = (
                _is_mainspring_command(command)
                and Path(_meaningful_command_token(_command_tokens(command))).name
                == "notify_telegram.py"
            )
            if path.name == "notifier.pid" or is_notifier:
                if not _is_notifier_for_state_dir(command, root):
                    print(f"Refusing to stop notifier pid {pid} outside {root}")
                    continue
                if _stop_pid(
                    pid,
                    current_pid,
                    str(path),
                    require_mainspring_command=False,
                ):
                    stopped += 1
                continue
            if _stop_pid(pid, current_pid, str(path)):
                stopped += 1
        if stopped == 0:
            print("No recorded live Mainspring process found for this project.")
        return

    try:
        output = subprocess.check_output(["ps", "-axo", "pid=,command="], text=True)
    except Exception as exc:
        print(f"Could not inspect process list: {exc}")
        return

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        first, _, command = stripped.partition(" ")
        try:
            pid = int(first)
        except ValueError:
            continue
        if _is_mainspring_command(command) and _stop_pid(
            pid,
            current_pid,
            "mainspring",
            require_mainspring_command=False,
        ):
            stopped += 1
    if stopped == 0:
        print("No live Mainspring processes matched.")


# ── CLI entry ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    usage_root = (
        "Usage: runtime_state.py <team-status|runtime-summary|repair|"
        "cleanup-stale|stop-processes|find-latest-team> [args]"
    )
    if not args:
        print(usage_root, file=sys.stderr)
        raise SystemExit(2)

    subcmd = args[0]
    if subcmd == "team-status":
        usage = "Usage: runtime_state.py team-status <team_name> <status_json>"
        if len(args) != 3:
            _usage_error(
                "team-status requires exactly <team_name> and <status_json>",
                usage,
            )
        cmd_team_status(args[1], args[2])
    elif subcmd == "runtime-summary":
        usage = "Usage: runtime_state.py runtime-summary <state_dir>"
        if len(args) != 2:
            _usage_error(
                "runtime-summary requires exactly <state_dir>",
                usage,
            )
        cmd_runtime_summary(args[1])
    elif subcmd == "repair":
        usage = "Usage: runtime_state.py repair <state_dir> [--dry-run] [--force]"
        if len(args) < 2:
            _usage_error("repair requires <state_dir>", usage)
        flags = _parse_flag_set(
            args[2:],
            allowed={"--dry-run", "--force"},
            usage=usage,
        )
        cmd_repair(
            args[1],
            dry_run="--dry-run" in flags,
            force="--force" in flags,
        )
    elif subcmd == "cleanup-stale":
        usage = (
            "Usage: runtime_state.py cleanup-stale <current_pid> <ttl_minutes> "
            "[--force]"
        )
        if len(args) < 3:
            _usage_error(
                "cleanup-stale requires <current_pid> and <ttl_minutes>", usage
            )
        flags = _parse_flag_set(args[3:], allowed={"--force"}, usage=usage)
        current_pid = _parse_int_arg(args[1], "current_pid", usage)
        ttl_minutes = _parse_int_arg(args[2], "ttl_minutes", usage)
        cmd_cleanup_stale(current_pid, ttl_minutes, force="--force" in flags)
    elif subcmd == "stop-processes":
        usage = (
            "Usage: runtime_state.py stop-processes <state_dir> <current_pid> "
            "[--force] [--all]"
        )
        if len(args) < 3:
            _usage_error("stop-processes requires <state_dir> and <current_pid>", usage)
        flags = _parse_flag_set(args[3:], allowed={"--force", "--all"}, usage=usage)
        current_pid = _parse_int_arg(args[2], "current_pid", usage)
        cmd_stop_processes(
            args[1],
            current_pid,
            force="--force" in flags,
            all_projects="--all" in flags,
        )
    elif subcmd == "find-latest-team":
        usage = "Usage: runtime_state.py find-latest-team <team_state_dir>"
        if len(args) != 2:
            _usage_error(
                "find-latest-team requires exactly <team_state_dir>",
                usage,
            )
        cmd_find_latest_team(args[1])
    else:
        _usage_error(f"Unknown subcommand: {subcmd}", usage_root)


if __name__ == "__main__":
    run_cli(main)
