# SPDX-License-Identifier: Apache-2.0
"""Engine usage/quota snapshots for Mainspring.

Subcommands:
    codex               Parse Codex session JSONL for rate-limit data.
    claude <probe-file> Parse Claude stream-json probe output for rate-limit data.
    --engine <name>     Emit a common JSON/text quota envelope for preflight.

Usage:
    python3 engine_quota.py codex
    python3 engine_quota.py claude /tmp/probe-output.jsonl
    python3 engine_quota.py --engine codex --format json

Both subcommands emit a single pipe-delimited status line to stdout,
matching the format the bash monolith already parses with ``sed``.
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

from cli_runtime import run_cli
from engines.registry import get_adapter, get_engine

# ── codex ───────────────────────────────────────────────────────────────


def codex_quota_line() -> str:
    """Scan ``~/.codex/sessions`` for the latest rate-limit payload."""
    root = Path.home() / ".codex" / "sessions"
    latest_payload: dict | None = None

    if root.exists():
        files = sorted(
            root.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for f in files:
            try:
                for line in reversed(f.read_text(errors="ignore").splitlines()):
                    if '"rate_limits"' in line and "used_percent" in line:
                        obj = json.loads(line)
                        latest_payload = obj.get("payload", {}).get("rate_limits", {})
                        raise _Found
            except _Found:
                break
            except Exception:
                continue

    if not isinstance(latest_payload, dict) or not latest_payload:
        return (
            "Codex|short_remaining=unknown|short_window=5h|short_reset=unknown"
            "|long_remaining=unknown|long_window=7d|long_reset=unknown|plan=unknown"
        )

    primary = latest_payload.get("primary", {})
    secondary = latest_payload.get("secondary", {})
    primary = primary if isinstance(primary, dict) else {}
    secondary = secondary if isinstance(secondary, dict) else {}
    plan = latest_payload.get("plan_type") or "unknown"
    short_used = _quota_number(primary.get("used_percent"))
    long_used = _quota_number(secondary.get("used_percent"))
    short_remaining = "unknown" if short_used is None else max(0.0, 100.0 - short_used)
    long_remaining = "unknown" if long_used is None else max(0.0, 100.0 - long_used)
    return (
        f"Codex|short_remaining={short_remaining}"
        f"|short_window={primary.get('window_minutes', 'unknown')}m"
        f"|short_reset={primary.get('resets_at', '')}"
        f"|long_remaining={long_remaining}"
        f"|long_window={secondary.get('window_minutes', 'unknown')}m"
        f"|long_reset={secondary.get('resets_at', '')}"
        f"|plan={plan}"
    )


def cmd_codex() -> None:
    """Print the legacy pipe-delimited Codex quota line."""
    print(codex_quota_line())


class _Found(Exception):
    """Sentinel to break out of nested loops."""


# ── claude ──────────────────────────────────────────────────────────────


def claude_quota_line(probe_path: str) -> str:
    """Parse a Claude stream-json probe file for rate-limit events."""
    path = Path(probe_path)
    status: str | None = None
    kind: str | None = None
    reset: str | None = None

    for line in path.read_text(errors="ignore").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if obj.get("type") == "rate_limit_event":
            info = obj.get("rate_limit_info", {}) or {}
            if not isinstance(info, dict):
                continue
            status = info.get("status") or status
            kind = info.get("rateLimitType") or kind
            reset = info.get("resetsAt") or reset

    if status or kind or reset:
        return (
            "Claude Code|"
            f"short_remaining=unknown|short_window={kind or 'unknown'}"
            f"|short_reset={reset or 'unknown'}"
            "|long_remaining=unknown|long_window=unknown|long_reset=unknown"
            f"|status={status or 'unknown'}"
        )
    return (
        "Claude Code|short_remaining=unknown|short_window=unknown"
        "|short_reset=unknown|long_remaining=unknown|long_window=unknown"
        "|long_reset=unknown|status=unknown"
    )


def cmd_claude(probe_path: str) -> None:
    """Print the legacy pipe-delimited Claude quota line."""
    print(claude_quota_line(probe_path))


# ── common envelope ─────────────────────────────────────────────────────


def _parse_pipe_line(line: str) -> tuple[str, dict[str, str]]:
    parts = line.strip().split("|")
    label = parts[0] if parts else "unknown"
    values = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        values[key] = value
    return label, values


def _quota_number(value: object) -> float | None:
    """Return finite nonnegative numeric evidence, never a Boolean measurement."""
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).strip())
    except (ValueError, TypeError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and parsed >= 0 else None


def _parse_percent(value: object) -> float | None:
    parsed = _quota_number(value)
    if parsed is None or parsed > 100:
        return None
    return round(parsed, 3)


def unknown_snapshot(engine_name: str) -> dict:
    """Return a common missing-quota shape for a registered or future engine."""
    info = get_engine(engine_name)
    return {
        "engine": engine_name,
        "display_name": info.display_name if info else engine_name,
        "binary": info.binary if info else engine_name,
        "binary_path": shutil.which(info.binary if info else engine_name),
        "available": shutil.which(info.binary if info else engine_name) is not None,
        "default_model": info.default_model if info else "",
        "execution_status": info.execution_status if info else "unknown",
        "quota": {
            "short": {
                "remaining_pct": None,
                "window": "unknown",
                "reset": "unknown",
            },
            "long": {
                "remaining_pct": None,
                "window": "unknown",
                "reset": "unknown",
            },
            "plan": "unknown",
            "status": "unknown",
            "source": "missing",
        },
    }


def _normalize_adapter_quota_snapshot(
    engine_name: str, adapter_snapshot: dict
) -> dict | None:
    if not adapter_snapshot:
        return None
    if isinstance(adapter_snapshot, dict) and "quota" in adapter_snapshot:
        snapshot = unknown_snapshot(engine_name)
        quota = adapter_snapshot.get("quota")
        if isinstance(quota, dict):
            short = quota.get("short", {})
            long = quota.get("long", {})
            short = short if isinstance(short, dict) else {}
            long = long if isinstance(long, dict) else {}
            snapshot.update(
                {
                    "quota": {
                        "short": {
                            "remaining_pct": _parse_percent(short.get("remaining_pct")),
                            "window": str(short.get("window") or "unknown"),
                            "reset": str(short.get("reset") or "unknown"),
                        },
                        "long": {
                            "remaining_pct": _parse_percent(long.get("remaining_pct")),
                            "window": str(long.get("window") or "unknown"),
                            "reset": str(long.get("reset") or "unknown"),
                        },
                        "plan": str(quota.get("plan") or "unknown"),
                        "status": str(quota.get("status") or "unknown"),
                        "source": str(quota.get("source") or "adapter"),
                    }
                }
            )
            return snapshot
    return None


def snapshot_from_line(engine_name: str, line: str, source: str) -> dict:
    """Convert a legacy pipe-delimited quota line into a common JSON shape."""
    label, values = _parse_pipe_line(line)
    snapshot = unknown_snapshot(engine_name)
    snapshot["display_name"] = label or snapshot["display_name"]
    snapshot["quota"] = {
        "short": {
            "remaining_pct": _parse_percent(values.get("short_remaining")),
            "window": values.get("short_window") or "unknown",
            "reset": values.get("short_reset") or "unknown",
        },
        "long": {
            "remaining_pct": _parse_percent(values.get("long_remaining")),
            "window": values.get("long_window") or "unknown",
            "reset": values.get("long_reset") or "unknown",
        },
        "plan": values.get("plan") or "unknown",
        "status": values.get("status") or "unknown",
        "source": source,
    }
    return snapshot


def engine_snapshot(engine_name: str, probe_path: str | None = None) -> dict:
    """Return a common quota snapshot without making network calls."""
    if get_engine(engine_name) is None:
        raise ValueError(f"unknown engine: {engine_name}")
    adapter = get_adapter(engine_name)
    if adapter is not None:
        adapter_snapshot = adapter.quota_snapshot()
        normalized = _normalize_adapter_quota_snapshot(engine_name, adapter_snapshot)
        if normalized is not None:
            return normalized
    if engine_name == "codex":
        return snapshot_from_line(engine_name, codex_quota_line(), "codex_sessions")
    if engine_name == "claude" and probe_path:
        return snapshot_from_line(
            engine_name, claude_quota_line(probe_path), "claude_probe"
        )
    return unknown_snapshot(engine_name)


def format_snapshot_text(snapshot: dict) -> str:
    """Render the common quota snapshot as a compact text line."""
    quota = snapshot["quota"]
    short = quota["short"]
    long = quota["long"]
    return (
        f"{snapshot['display_name']}|engine={snapshot['engine']}"
        f"|available={str(snapshot['available']).lower()}"
        f"|short_remaining={short['remaining_pct'] if short['remaining_pct'] is not None else 'unknown'}"
        f"|short_window={short['window']}"
        f"|short_reset={short['reset']}"
        f"|long_remaining={long['remaining_pct'] if long['remaining_pct'] is not None else 'unknown'}"
        f"|long_window={long['window']}"
        f"|long_reset={long['reset']}"
        f"|status={quota['status']}"
        f"|source={quota['source']}"
    )


def cmd_engine(args: list[str]) -> None:
    """Common engine quota preflight command."""
    engine_name = ""
    probe_path = None
    output_format = "text"
    i = 0
    while i < len(args):
        if args[i] == "--engine" and i + 1 < len(args):
            engine_name = args[i + 1]
            i += 2
        elif args[i] == "--probe-file" and i + 1 < len(args):
            probe_path = args[i + 1]
            i += 2
        elif args[i] == "--format" and i + 1 < len(args):
            output_format = args[i + 1]
            i += 2
        else:
            print(f"Unknown or incomplete flag: {args[i]}", file=sys.stderr)
            raise SystemExit(2)

    if not engine_name:
        print("engine_quota.py --engine requires a value", file=sys.stderr)
        raise SystemExit(2)
    if output_format not in {"json", "text"}:
        print("engine_quota.py --format must be json or text", file=sys.stderr)
        raise SystemExit(2)

    try:
        snapshot = engine_snapshot(engine_name, probe_path=probe_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from None

    if output_format == "json":
        print(json.dumps(snapshot, indent=2, sort_keys=True))
    else:
        print(format_snapshot_text(snapshot))


# ── CLI entry ───────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: engine_quota.py <codex|claude> [args] "
            "or --engine <name> [--format json|text]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args[0] == "--engine":
        cmd_engine(args)
        return

    subcmd = args[0]
    if subcmd == "codex":
        cmd_codex()
    elif subcmd == "claude":
        if len(args) < 2:
            print("Usage: engine_quota.py claude <probe-file>", file=sys.stderr)
            raise SystemExit(2)
        cmd_claude(args[1])
    else:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    run_cli(main)
