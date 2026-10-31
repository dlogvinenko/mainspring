#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Operator-glance quota and spend limits for Mainspring."""

from __future__ import annotations

from cli_runtime import run_cli

import json
import os
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import metrics
from engine_quota import engine_snapshot
from engines.registry import load_engines, readiness_errors
from notify_telegram import extract_wave_cost


BAR_WIDTH = 10
HELP_TEXT = """Usage: mainspring limits [engine ...] [--engine <name>] [--format text|json] [--hours N]

Show an operator snapshot of engine run readiness, quota windows, and recent
wave spend from the local Mainspring ledger. This is an offline local check:
adapter-only means Mainspring can see the adapter, but credentials/quota are not
proven here.

Examples:
  mainspring limits
  mainspring limits codex claude
  mainspring limits --engine codex --format json --hours 24
"""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_ts(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.replace(".", "", 1).isdigit():
        try:
            numeric = float(text)
        except ValueError:
            numeric = 0.0
        if numeric > 0:
            if numeric > 10_000_000_000:
                numeric = numeric / 1000.0
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _entry_ts(entry: dict) -> datetime | None:
    return _parse_ts(entry.get("ts") or entry.get("timestamp"))


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.1f}%"


def _bar(value: float | None) -> str:
    if value is None:
        return "unknown"
    clamped = max(0.0, min(100.0, float(value)))
    filled = round((clamped / 100.0) * BAR_WIDTH)
    return "[" + ("#" * filled) + ("-" * (BAR_WIDTH - filled)) + "]"


def _format_reset(value: object, now: datetime) -> str:
    reset = _parse_ts(value)
    if reset is None:
        return "unknown"
    local = reset.astimezone()
    delta = reset - now
    if delta.total_seconds() <= 0:
        prefix = "now"
    else:
        minutes = max(1, int(delta.total_seconds() // 60))
        hours, mins = divmod(minutes, 60)
        if hours:
            prefix = f"in {hours}h {mins:02d}m"
        else:
            prefix = f"in {mins}m"
    return f"{prefix}, {local.strftime('%a %H:%M %Z')}"


def _quota_has_signal(quota: dict) -> bool:
    # Provenance alone does not establish observed quota or readiness data.
    if str(quota.get("status") or "unknown") != "unknown":
        return True
    if str(quota.get("plan") or "unknown") != "unknown":
        return True
    for window_name in ("short", "long"):
        window = (
            quota.get(window_name) if isinstance(quota.get(window_name), dict) else {}
        )
        if window.get("remaining_pct") is not None:
            return True
        if str(window.get("reset") or "unknown") != "unknown":
            return True
    return False


def _operational_status(
    snapshot: dict, readiness_blockers: list[str]
) -> tuple[str, str]:
    if not snapshot.get("available"):
        return "not-configured", "engine adapter binary is not on PATH"
    if readiness_blockers:
        return "not-configured", "; ".join(readiness_blockers[:2])
    quota = snapshot.get("quota") if isinstance(snapshot.get("quota"), dict) else {}
    raw_status = str(quota.get("status") or "").strip().lower()
    short = quota.get("short") if isinstance(quota.get("short"), dict) else {}
    remaining = short.get("remaining_pct")
    try:
        remaining_value = float(remaining)
    except (TypeError, ValueError):
        remaining_value = None
    if remaining_value is not None and remaining_value <= 0:
        return "throttled", "short-window quota is exhausted"
    if any(marker in raw_status for marker in ("throttle", "rate", "limit")):
        return "throttled", f"quota status is {quota.get('status')}"
    if not _quota_has_signal(quota):
        return (
            "adapter-only",
            "adapter visible; credentials/quota not proven by this offline check",
        )
    return "ready", "adapter visible and a local quota/readiness signal is present"


def _engine_row(snapshot: dict, *, now: datetime) -> dict:
    quota = snapshot.get("quota") if isinstance(snapshot.get("quota"), dict) else {}
    short = quota.get("short") if isinstance(quota.get("short"), dict) else {}
    long = quota.get("long") if isinstance(quota.get("long"), dict) else {}
    short_remaining = short.get("remaining_pct")
    long_remaining = long.get("remaining_pct")
    short_pct = float(short_remaining) if short_remaining is not None else None
    long_pct = float(long_remaining) if long_remaining is not None else None
    engine_name = str(snapshot.get("engine") or "unknown")
    readiness_blockers = readiness_errors(
        engine_name,
        model=str(snapshot.get("default_model") or ""),
        require_executable=True,
        require_execution=True,
    )
    status, status_reason = _operational_status(snapshot, readiness_blockers)
    return {
        "engine": engine_name,
        "display_name": snapshot.get("display_name") or snapshot.get("engine") or "",
        "model": snapshot.get("default_model") or "",
        "status": status,
        "status_reason": status_reason,
        "readiness_blockers": readiness_blockers,
        "available": bool(snapshot.get("available")),
        "execution_status": snapshot.get("execution_status") or "unknown",
        "quota_status": quota.get("status") or "unknown",
        "quota_source": quota.get("source") or "missing",
        "plan": quota.get("plan") or "unknown",
        "short": {
            "remaining_pct": short_pct,
            "remaining_label": _fmt_pct(short_pct),
            "bar": _bar(short_pct),
            "window": short.get("window") or "unknown",
            "reset": short.get("reset") or "unknown",
            "reset_in": _format_reset(short.get("reset"), now),
        },
        "long": {
            "remaining_pct": long_pct,
            "remaining_label": _fmt_pct(long_pct),
            "bar": _bar(long_pct),
            "window": long.get("window") or "unknown",
            "reset": long.get("reset") or "unknown",
            "reset_in": _format_reset(long.get("reset"), now),
        },
    }


def _filter_recent(entries: list[dict], *, hours: int, now: datetime) -> list[dict]:
    cutoff = now - timedelta(hours=hours)
    recent = []
    for entry in entries:
        ts = _entry_ts(entry)
        if ts is not None and ts >= cutoff:
            recent.append(entry)
    return recent


def _spend_summary(entries: list[dict], *, hours: int, now: datetime) -> dict:
    recent = _filter_recent(entries, hours=hours, now=now)
    explicit = 0.0
    estimated = 0.0
    explicit_count = 0
    estimated_count = 0
    top_costs: list[dict] = []
    for entry in recent:
        cost_info = extract_wave_cost(entry)
        if cost_info is None:
            continue
        cost, source = cost_info
        if source == "estimated":
            estimated += cost
            estimated_count += 1
        else:
            explicit += cost
            explicit_count += 1
        top_costs.append(
            {
                "wave_id": entry.get("wave_id") or entry.get("wave") or "?",
                "task_id": entry.get("task_id") or "",
                "pair": entry.get("pair") or _legacy_pair(entry),
                "cost_usd": round(cost, 4),
                "source": source,
            }
        )
    total = explicit + estimated
    top_costs.sort(key=lambda row: row["cost_usd"], reverse=True)
    return {
        "period_hours": hours,
        "window_start": _iso_z(now - timedelta(hours=hours)),
        "window_end": _iso_z(now),
        "wave_count": len(recent),
        "costed_wave_count": explicit_count + estimated_count,
        "uncosted_wave_count": max(0, len(recent) - explicit_count - estimated_count),
        "total_usd": round(total, 4),
        "explicit_usd": round(explicit, 4),
        "estimated_usd": round(estimated, 4),
        "explicit_wave_count": explicit_count,
        "estimated_wave_count": estimated_count,
        "top_cost_waves": top_costs[:3],
    }


def _legacy_pair(entry: dict) -> str:
    engines = entry.get("engines") if isinstance(entry.get("engines"), dict) else {}
    writer = engines.get("writer") or entry.get("engine") or "?"
    reviewer = engines.get("reviewer") or entry.get("review_engine") or "?"
    return f"{writer}+{reviewer}"


def _resolve_engine_names(names: list[str]) -> list[str]:
    registered = load_engines()
    selected = names or list(registered.keys())
    deduped = []
    for name in selected:
        if name not in registered:
            raise ValueError(f"unknown engine: {name}")
        if name not in deduped:
            deduped.append(name)
    return deduped


def build_limits(
    *,
    engine_names: list[str] | None = None,
    ledger_path: Path,
    hours: int = 24,
    now: datetime | None = None,
) -> dict:
    """Build the machine-readable limits payload."""
    current_time = now or _utcnow()
    selected = _resolve_engine_names(engine_names or [])
    rows = [_engine_row(engine_snapshot(name), now=current_time) for name in selected]
    entries = metrics.read_ledger(ledger_path)
    return {
        "generated_at": _iso_z(current_time),
        "ledger": str(ledger_path),
        "engines": rows,
        "spend_24h": _spend_summary(entries, hours=hours, now=current_time),
    }


def format_text(payload: dict) -> str:
    """Render a compact operator-facing table."""
    lines = ["Mainspring limits", ""]
    lines.extend(
        [
            "Run status:",
            "  ready          adapter is runnable and a local quota/readiness signal exists",
            "  adapter-only   adapter is visible, but credentials/quota are not proven here",
            "  throttled      quota appears exhausted or rate-limited",
            "  not-configured missing binary, module, credential, or unsupported engine setup",
            "",
        ]
    )
    header = f"{'Engine':<10} {'Model':<24} {'Run status':<15} {'Short':<29} {'Long':<29} Source"
    lines.append(header)
    lines.append("-" * len(header))
    for row in payload["engines"]:
        short = _quota_cell(row["short"])
        long = _quota_cell(row["long"])
        lines.append(
            f"{row['engine']:<10} {_clip(row['model'], 24):<24} {row['status']:<15} "
            f"{short:<29} {long:<29} {row['quota_source']}"
        )
        lines.append(
            f"{'':<10} short reset: {row['short']['reset_in']} | "
            f"long reset: {row['long']['reset_in']}"
        )
        if row["status"] != "ready":
            _append_wrapped(
                lines,
                f"{'':<10} note: ",
                row["status_reason"],
                width=118,
            )

    spend = payload["spend_24h"]
    lines.extend(["", f"SPEND (last {spend['period_hours']}h, estimated)"])
    if spend["costed_wave_count"]:
        lines.append(
            f"Cost: ${spend['total_usd']:.2f} "
            f"({spend['costed_wave_count']}/{spend['wave_count']} waves with cost truth; "
            f"${spend['estimated_usd']:.2f} estimated)"
        )
    else:
        lines.append(
            "Cost: Waiting for usage data "
            f"(0/{spend['wave_count']} waves with cost truth)"
        )
    if spend["uncosted_wave_count"]:
        lines.append(f"Uncosted waves: {spend['uncosted_wave_count']}")
    if spend["top_cost_waves"]:
        lines.append("Top cost waves:")
        for wave in spend["top_cost_waves"]:
            source_label = " estimated" if wave["source"] == "estimated" else ""
            lines.append(
                f"  {wave['wave_id']} task={wave['task_id']} "
                f"{wave['pair']} ${wave['cost_usd']:.2f}{source_label}"
            )
    return "\n".join(lines)


def _quota_cell(window: dict) -> str:
    if window["bar"] == "unknown":
        return "unknown"
    return f"{window['bar']} {window['remaining_label']} {window['window']}"


def _clip(value: object, width: int) -> str:
    text = str(value or "")
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[: width - 3] + "..."


def _append_wrapped(
    lines: list[str],
    prefix: str,
    text: object,
    *,
    width: int,
) -> None:
    body = str(text or "")
    wrapped = textwrap.wrap(
        body,
        width=max(20, width - len(prefix)),
        break_long_words=False,
        break_on_hyphens=False,
    )
    if not wrapped:
        lines.append(prefix.rstrip())
        return
    lines.append(prefix + wrapped[0])
    continuation = " " * len(prefix)
    for line in wrapped[1:]:
        lines.append(continuation + line)


def _parse_args(args: list[str]) -> tuple[list[str], Path, str, int]:
    engine_names: list[str] = []
    runtime_dir = Path(os.environ.get("MAINSPRING_RUNTIME_DIR") or ".mainspring")
    ledger_path = runtime_dir / "logs" / "waves.jsonl"
    output_format = "text"
    hours = 24
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in {"--help", "-h"}:
            print(HELP_TEXT)
            raise SystemExit(0)
        if arg == "--engine" and i + 1 < len(args):
            engine_names.append(args[i + 1])
            i += 2
        elif arg == "--ledger" and i + 1 < len(args):
            ledger_path = Path(args[i + 1])
            i += 2
        elif arg == "--format" and i + 1 < len(args):
            output_format = args[i + 1]
            i += 2
        elif arg == "--hours" and i + 1 < len(args):
            try:
                hours = int(args[i + 1])
            except ValueError:
                print("mainspring limits --hours must be an integer", file=sys.stderr)
                raise SystemExit(2)
            i += 2
        elif arg.startswith("--"):
            print(f"Unknown or incomplete flag: {arg}", file=sys.stderr)
            raise SystemExit(2)
        else:
            engine_names.append(arg)
            i += 1
    if output_format not in {"text", "json"}:
        print("mainspring limits --format must be text or json", file=sys.stderr)
        raise SystemExit(2)
    if hours <= 0:
        print("mainspring limits --hours must be positive", file=sys.stderr)
        raise SystemExit(2)
    return engine_names, ledger_path, output_format, hours


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    engine_names, ledger_path, output_format, hours = _parse_args(args)
    try:
        payload = build_limits(
            engine_names=engine_names,
            ledger_path=ledger_path,
            hours=hours,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if output_format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_text(payload))
    return 0


if __name__ == "__main__":
    run_cli(main)
