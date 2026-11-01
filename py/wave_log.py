#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Wave ledger JSONL operations for Mainspring.

Subcommands:
    append          Read wave metadata from env vars, emit one JSON line to stdout.
    last-summary    Read ledger file, print a one-line summary of the last wave.
    routing-hints   Read ledger file, print routing advice based on recent waves.

Usage:
    python3 wave_log.py append
    python3 wave_log.py last-summary <ledger-path>
    python3 wave_log.py routing-hints <ledger-path>

The ``append`` subcommand reads all wave fields from environment variables
(same contract as the inline heredoc it replaces) and prints exactly one
JSON line to stdout.  The caller is responsible for redirecting stdout into
the ledger file with append mode (``>> waves.jsonl``).
"""

from __future__ import annotations

from cli_runtime import run_cli

import fcntl
import json
import os
import sys
from pathlib import Path
from typing import Any

from failure_taxonomy import normalise_failure_reason_class


def _as_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _as_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().casefold()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _is_product_file_change(path: str) -> bool:
    normalized = path.strip()
    if normalized.startswith("./"):
        normalized = normalized.removeprefix("./")
    if not normalized:
        return False
    if normalized in {"README.md", "CLAUDE.md", "AGENTS.md"}:
        return False
    if normalized.endswith(".md"):
        return False
    if normalized.endswith(".pyc"):
        return False
    if normalized.endswith(
        (
            ".db-shm",
            ".db-wal",
            ".sqlite-shm",
            ".sqlite-wal",
            ".sqlite3-shm",
            ".sqlite3-wal",
        )
    ):
        return False
    if "/__pycache__/" in f"/{normalized}/":
        return False
    ignored_prefixes = (
        ".mainspring/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".taskmaster/",
        ".gradle/",
        ".next/",
        ".nuxt/",
        ".turbo/",
        ".vite/",
        "build/",
        "dist/",
        "target/",
        "docs/",
        "scripts/",
    )
    return not normalized.startswith(ignored_prefixes)


def _count_product_file_changes(paths: list[str]) -> int:
    return sum(1 for path in paths if _is_product_file_change(path))


def _as_float(value: object) -> float | None:
    try:
        parsed = float(str(value).lstrip("+"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _as_nonnegative_int(value: object) -> int | None:
    parsed = _as_float(value)
    if parsed is None:
        return None
    return int(parsed)


TOKEN_KEYS = (
    "input_tokens",
    "prompt_tokens",
    "output_tokens",
    "completion_tokens",
    "total_tokens",
    "cached_input_tokens",
    "cache_read_input_tokens",
)


def _normalise_usage(payload: dict[str, Any]) -> dict[str, int]:
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else payload
    result: dict[str, int] = {}
    for key in TOKEN_KEYS:
        parsed = _as_nonnegative_int(usage.get(key))
        if parsed is not None:
            result[key] = parsed
    input_tokens = result.get("input_tokens", result.get("prompt_tokens"))
    output_tokens = result.get("output_tokens", result.get("completion_tokens"))
    total_tokens = result.get("total_tokens")
    if input_tokens is not None:
        result["input_tokens"] = input_tokens
        result["prompt_tokens"] = input_tokens
    if output_tokens is not None:
        result["output_tokens"] = output_tokens
        result["completion_tokens"] = output_tokens
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        result["total_tokens"] = (input_tokens or 0) + (output_tokens or 0)
    return result


def _merge_usage(target: dict[str, Any], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = int(target.get(key, 0)) + value


def _read_usage_sidecar(path_value: str) -> dict[str, Any]:
    """Aggregate per-engine usage JSONL into one wave-ledger usage payload."""
    if not path_value:
        return {}
    path = Path(path_value)
    if not path.is_file():
        return {}

    usage: dict[str, Any] = {}
    total_cost = 0.0
    has_cost = False
    cost_sources: set[str] = set()
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        role = str(row.get("role") or "").strip()
        normalised = _normalise_usage(row)
        if normalised:
            _merge_usage(usage, normalised)
            if role:
                role_usage = usage.setdefault(role, {})
                if isinstance(role_usage, dict):
                    _merge_usage(role_usage, normalised)
        cost = _as_float(row.get("cost_usd") or row.get("total_cost_usd"))
        if cost is not None:
            total_cost += cost
            has_cost = True
            if role:
                role_usage = usage.setdefault(role, {})
                if isinstance(role_usage, dict):
                    role_usage["cost_usd"] = round(
                        float(role_usage.get("cost_usd", 0.0)) + cost,
                        10,
                    )
        source = str(row.get("cost_source") or "").strip()
        if source:
            cost_sources.add(source)

    if has_cost:
        usage["cost_usd"] = round(total_cost, 10)
        usage["total_cost_usd"] = round(total_cost, 10)
        if cost_sources:
            usage["cost_source"] = "+".join(sorted(cost_sources))
    return usage


# ── append ──────────────────────────────────────────────────────────────


def build_wave_entry() -> dict:
    """Build a wave ledger entry dict from environment variables."""
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    writer_engine = os.environ.get("ENGINE_VALUE") or ""
    reviewer_engine = os.environ.get("REVIEWER_VALUE") or ""
    writer_model = os.environ.get("MODEL_VALUE") or "default"
    reviewer_model = os.environ.get("REVIEW_MODEL_VALUE") or "default"
    duration_s = max(
        0,
        _as_int(os.environ.get("END_EPOCH")) - _as_int(os.environ.get("START_EPOCH")),
    )
    failure_reason = os.environ.get("FAILURE_REASON_VALUE") or ""
    failure_reason_class = normalise_failure_reason_class(
        failure_reason,
        os.environ.get("FAILURE_REASON_CLASS_VALUE") or "",
    )
    changed_files = [
        line.strip()
        for line in os.environ.get("CHANGED_FILES_VALUE", "").splitlines()
        if line.strip()
    ]
    pair = (
        f"{writer_engine}+{reviewer_engine}" if writer_engine or reviewer_engine else ""
    )
    entry = {
        "ts": timestamp,
        "timestamp": timestamp,  # legacy alias, kept for pre-schema consumers.
        "wave": _as_int(
            os.environ.get("WAVE_NUMBER_VALUE") or os.environ.get("WAVE_ID")
        ),
        "wave_id": os.environ.get("WAVE_ID") or "",
        "mode": os.environ.get("MODE_VALUE") or "",
        "topology": os.environ.get("TOPOLOGY_VALUE") or "",
        "team": os.environ.get("TEAM_VALUE") or "",
        "team_name": os.environ.get("TEAM_NAME_VALUE")
        or os.environ.get("TEAM_VALUE")
        or "",
        "task_id": os.environ.get("TASK_ID_VALUE") or "",
        "task_status_before": os.environ.get("TASK_STATUS_BEFORE_VALUE") or "",
        "task_status_after": os.environ.get("TASK_STATUS_AFTER_VALUE") or "",
        "selected_lane": os.environ.get("SELECTED_LANE") or "",
        "engine": writer_engine,
        "review_engine": reviewer_engine,
        "pair": pair,
        "engines": {
            "writer": writer_engine,
            "reviewer": reviewer_engine,
        },
        "model": writer_model,
        "review_model": reviewer_model,
        "models": {
            "writer": writer_model,
            "reviewer": reviewer_model,
            "reasoning": os.environ.get("REASONING_VALUE") or "",
        },
        "duration_s": duration_s,
        "duration_seconds": duration_s,  # legacy alias, kept for current readers.
        "product_files_changed": _count_product_file_changes(changed_files),
        "changed_files": changed_files,
        "tests": "",
        "verdict": os.environ.get("VERDICT_VALUE") or "",
        "exit_code": _as_int(os.environ.get("EXIT_CODE_VALUE"), 0),
        "failure_reason": failure_reason,
        "failure_reason_class": failure_reason_class,
        "fallback_engine_used": _as_bool(
            os.environ.get("FALLBACK_ENGINE_USED_VALUE"), default=False
        ),
        "retry_count": _as_int(os.environ.get("RETRY_COUNT_VALUE"), 0),
        "retry_used": _as_int(os.environ.get("RETRY_COUNT_VALUE"), 0) > 0,
        "blocked_reason": os.environ.get("BLOCKED_REASON_VALUE") or "",
        "next_action": os.environ.get("NEXT_ACTION_VALUE") or "",
    }
    optional_fields = {
        "prompt_path": os.environ.get("PROMPT_PATH_VALUE") or "",
        "prompt_sha256": os.environ.get("PROMPT_SHA256_VALUE") or "",
        "git_head": os.environ.get("GIT_HEAD_VALUE") or "",
        "git_status_before": os.environ.get("GIT_STATUS_BEFORE_VALUE") or "",
        "prd_path": os.environ.get("PRD_PATH_VALUE") or "",
    }
    for key, value in optional_fields.items():
        if value or (
            key == "git_status_before" and "GIT_STATUS_BEFORE_VALUE" in os.environ
        ):
            entry[key] = value
    usage = _read_usage_sidecar(os.environ.get("USAGE_PATH_VALUE") or "")
    if usage:
        entry["usage"] = usage
        cost = _as_float(usage.get("cost_usd") or usage.get("total_cost_usd"))
        if cost is not None:
            entry["cost_usd"] = round(cost, 10)
            entry["total_cost_usd"] = round(cost, 10)
    replayed_from = os.environ.get("REPLAYED_FROM_VALUE") or ""
    if replayed_from:
        entry["replayed_from"] = replayed_from
    replay_overrides = os.environ.get("REPLAY_OVERRIDES_VALUE") or ""
    if replay_overrides:
        try:
            entry["replay_overrides"] = json.loads(replay_overrides)
        except json.JSONDecodeError:
            entry["replay_overrides"] = replay_overrides
    return entry


def cmd_append(ledger_path: str | None = None) -> None:
    """Emit one JSON line.

    If *ledger_path* is given, atomically append to that file under an
    exclusive ``flock`` on ``<ledger_path>.lock``.  Otherwise fall back to
    printing to stdout (legacy mode, caller redirects).
    """
    line = json.dumps(build_wave_entry(), ensure_ascii=False, sort_keys=True)
    if ledger_path is None:
        print(line)
        return

    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with open(lock_path, "w") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        fcntl.flock(lock_fd, fcntl.LOCK_UN)


# ── last-summary ────────────────────────────────────────────────────────


def read_ledger(path: Path) -> list[dict]:
    """Parse object JSONL entries, ignoring malformed or non-object rows."""
    entries: list[dict] = []
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
            if isinstance(entry, dict):
                entries.append(entry)
        except Exception:
            continue
    return entries


def cmd_last_summary(ledger_path: str) -> None:
    """Print a one-line summary of the most recent wave."""
    path = Path(ledger_path)
    if not path.is_file() or path.stat().st_size == 0:
        print("last-wave: none")
        return

    entries = read_ledger(path)
    if not entries:
        print("last-wave: no valid ledger entries")
        return

    last = entries[-1]
    print(
        "last-wave: "
        f"id={last.get('wave_id', 'unknown')} "
        f"mode={last.get('mode', 'unknown')} "
        f"topology={last.get('topology', 'unknown')} "
        f"task={last.get('task_id', '') or 'none'} "
        f"lane={last.get('selected_lane', '') or 'unknown'} "
        f"verdict={last.get('verdict', '') or 'unknown'} "
        f"duration_seconds={last.get('duration_seconds', 'unknown')} "
        f"failure={last.get('failure_reason', '') or 'none'}"
    )
    next_action = last.get("next_action")
    if next_action:
        print(f"last-wave next-action: {next_action}")


# ── routing-hints ───────────────────────────────────────────────────────


def cmd_routing_hints(ledger_path: str) -> None:
    """Print routing advice based on the last 5 waves."""
    path = Path(ledger_path)
    if not path.is_file() or path.stat().st_size == 0:
        print(
            "routing: no wave metrics yet; start with --status and a safe solo "
            "--once after git gates are clean."
        )
        return

    entries = read_ledger(path)
    recent = entries[-5:]
    if not recent:
        print(
            "routing: no valid wave metrics yet; malformed ledger lines were ignored."
        )
        return

    failures = [
        item
        for item in recent
        if str(item.get("verdict") or "").upper() in {"FAIL", "ERROR"}
        or item.get("exit_code") not in (None, 0)
    ]
    review_fails = [
        item
        for item in recent
        if str(item.get("failure_reason") or "").startswith("review:")
    ]

    if len(failures) >= 3:
        print("routing: stop/review recommended; recent waves are failing repeatedly.")
    elif len(review_fails) >= 2:
        print(
            "routing: retry same item in solo mode with reviewer repair fields "
            "before adding new parallel work."
        )
    elif any(
        str(item.get("topology") or "") == "team"
        and item.get("failure_reason") == "team:no_parallel_safe_work"
        for item in recent
    ):
        print("routing: use solo mode; recent team run found no parallel-safe work.")
    else:
        print(
            "routing: no failure trend detected; team is acceptable only when "
            "git/plugin gates are clean and selected scopes are disjoint."
        )


# ── CLI entry ───────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: wave_log.py <append|last-summary|routing-hints> [args]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    subcmd = args[0]
    if subcmd == "append":
        ledger = None
        if len(args) >= 3 and args[1] == "--ledger":
            ledger = args[2]
        cmd_append(ledger)
    elif subcmd == "last-summary":
        if len(args) < 2:
            print("Usage: wave_log.py last-summary <ledger-path>", file=sys.stderr)
            raise SystemExit(2)
        cmd_last_summary(args[1])
    elif subcmd == "routing-hints":
        if len(args) < 2:
            print("Usage: wave_log.py routing-hints <ledger-path>", file=sys.stderr)
            raise SystemExit(2)
        cmd_routing_hints(args[1])
    else:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    run_cli(main)
