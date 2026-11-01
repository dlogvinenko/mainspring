# SPDX-License-Identifier: Apache-2.0
"""Mainspring Telegram notification daemon.

Subcommands:
    watch           Tail waves.jsonl, emit Telegram notifications on events.
    health          Check whether the watcher state is caught up with the ledger.
    send            Send a single message (used by bash notify.sh wrapper).
    test            Send a sample notification to verify config.

Events emitted:
    wave_failed     A wave completed with verdict != PASS.
    retry_loop      3+ consecutive FAILs on the same task_id.
    quota_warn      engine quota cumulative delta > 90%.
    team_stuck      No new JSONL line in 30 minutes.
    milestone       chapter_delta > 50 OR task status → done.
    loop_stopped    Scheduler reached a terminal STOP condition.
    daily_digest    Sent once per day at 09:00 local.

Per-event rate limit: max 1 message per 5 minutes per event class.
Dedup state persisted in .mainspring/state/notify-state.json.

Usage:
    python3 notify_telegram.py watch <ledger-path> [--state-dir <dir>]
    python3 notify_telegram.py health <ledger-path> [--state-dir <dir>] [--log-file <path>] [--pid-file <path>] [--stale-seconds <n>] [--format text|json]
    python3 notify_telegram.py operator-health <ledger-path> [--state-dir <dir>] [--log-file <path>] [--pid-file <path>] [--stale-seconds <n>] [--format text|json]
    python3 notify_telegram.py send <message> [--parse-mode html|markdown]
    python3 notify_telegram.py test
"""

from __future__ import annotations

import json
import math
import os
import shlex
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cli_runtime import run_cli

# Configuration


def _get_bot_token() -> str | None:
    return os.environ.get("MAINSPRING_TELEGRAM_BOT_TOKEN")


def _get_chat_id() -> str | None:
    return os.environ.get("MAINSPRING_TELEGRAM_CHAT_ID")


# ── Telegram send primitive ──────────────────────────────────────────────


def send_message(
    text: str,
    bot_token: str | None = None,
    chat_id: str | None = None,
    parse_mode: str | None = None,
    timeout: int = 10,
) -> dict | None:
    """Send a Telegram message. Returns the API response dict or None on error."""
    token = bot_token or _get_bot_token()
    cid = chat_id or _get_chat_id()
    if not token or not cid:
        print(
            "notify: MAINSPRING_TELEGRAM_BOT_TOKEN and MAINSPRING_TELEGRAM_CHAT_ID required",
            file=sys.stderr,
        )
        return None

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict = {"chat_id": cid, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        if not isinstance(payload, dict):
            print("notify: Telegram API response is not a JSON object", file=sys.stderr)
            return None
        if payload.get("ok") is not True:
            description = payload.get("description") or "missing ok=true"
            print(f"notify: Telegram API error: {description}", file=sys.stderr)
            return None
        return payload
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        print(f"notify: Telegram send failed: {exc}", file=sys.stderr)
        return None


# ── Event detection ──────────────────────────────────────────────────────

EVENT_CLASSES = (
    "wave_failed",
    "retry_loop",
    "quota_warn",
    "team_stuck",
    "milestone",
    "loop_stopped",
    "daily_digest",
)

RATE_LIMIT_SECONDS = 300  # 5 minutes per event class
STALE_DAEMON_SECONDS = 3600  # 1 hour with pending ledger lines is operator-visible.
QUOTA_USAGE_FIELDS = (
    ("codex", "codex_short_delta_pct"),
    ("claude", "claude_short_delta"),
    ("gemini", "gemini_short_delta_pct"),
)
MODEL_PRICES_USD_PER_MTOK = {
    # OpenAI API pricing, standard processing, April 2026.
    "gpt-5.5": {"input": 5.0, "cached_input": 0.50, "output": 30.0},
    "gpt-5.4": {"input": 2.50, "cached_input": 0.25, "output": 15.0},
    "gpt-5.4-mini": {"input": 0.75, "cached_input": 0.075, "output": 4.50},
    # Anthropic Claude API 1P pricing, standard/global routing, April 2026.
    "claude-opus-4.7": {"input": 5.0, "cached_input": 0.50, "output": 25.0},
    "claude-opus-4.6": {"input": 5.0, "cached_input": 0.50, "output": 25.0},
    "claude-opus-4.5": {"input": 5.0, "cached_input": 0.50, "output": 25.0},
    "claude-opus-4.1": {"input": 15.0, "cached_input": 1.50, "output": 75.0},
    "claude-opus-4": {"input": 15.0, "cached_input": 1.50, "output": 75.0},
    "claude-sonnet-4.6": {"input": 3.0, "cached_input": 0.30, "output": 15.0},
    "claude-sonnet-4.5": {"input": 3.0, "cached_input": 0.30, "output": 15.0},
    "claude-sonnet-4": {"input": 3.0, "cached_input": 0.30, "output": 15.0},
    "claude-haiku-4.5": {"input": 1.0, "cached_input": 0.10, "output": 5.0},
    "claude-haiku-3.5": {"input": 0.80, "cached_input": 0.08, "output": 4.0},
    "claude-haiku-3": {"input": 0.25, "cached_input": 0.03, "output": 1.25},
    # Mainspring CLI aliases.
    "opus": {"input": 5.0, "cached_input": 0.50, "output": 25.0},
    "sonnet": {"input": 3.0, "cached_input": 0.30, "output": 15.0},
    "haiku": {"input": 1.0, "cached_input": 0.10, "output": 5.0},
}


def log_status(message: str, now: float | None = None) -> None:
    """Write an operator-visible daemon status line."""
    ts = (
        datetime.fromtimestamp(now or time.time(), UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )
    print(f"notify: {ts} {message}", file=sys.stderr, flush=True)


FAILURE_CONTEXT_FIELDS = (
    ("chapter_delta", "Chapter delta"),
    ("competitor_delta", "Competitor delta"),
    ("launch_delta", "Launch delta"),
    ("product_score", "Product score"),
)


def _clean_context_value(value: object) -> str:
    return str(value or "").strip()


def _first_context_value(
    entry: dict | None,
    context: dict[str, str] | None,
    keys: tuple[str, ...],
) -> str:
    sources: list[dict] = []
    if entry is not None:
        sources.append(entry)
    if context is not None:
        sources.append(context)
    for source in sources:
        for key in keys:
            value = _clean_context_value(source.get(key))
            if value:
                return value
    return ""


def _entry_uses_taskmaster(entry: dict | None) -> bool:
    if not entry:
        return False
    mode = _clean_context_value(entry.get("mode")).lower()
    return mode == "taskmaster" or bool(_clean_context_value(entry.get("task_id")))


def format_event_context(
    entry: dict | None = None,
    context: dict[str, str] | None = None,
) -> list[str]:
    """Return project/folder/tag context lines for operator notifications."""
    project = _first_context_value(
        entry,
        context,
        ("project_name", "project", "repo", "repository"),
    )
    folder = _first_context_value(
        entry,
        context,
        ("project_root", "folder", "workspace_root", "workspace", "cwd", "root"),
    )
    tag = _first_context_value(
        entry,
        context,
        ("taskmaster_tag", "task_tag", "tag", "current_tag"),
    )
    if not tag and _entry_uses_taskmaster(entry):
        tag = "master"

    lines: list[str] = []
    if project:
        lines.append(f"Project: {project}")
    if folder:
        lines.append(f"Folder: {folder}")
    if tag:
        lines.append(f"Tag: {tag}")
    return lines


def project_root_from_ledger_path(ledger_path: Path) -> Path | None:
    """Infer the operator project root from .mainspring ledger paths."""
    try:
        path = ledger_path.resolve(strict=False)
    except OSError:
        path = ledger_path
    for parent in path.parents:
        if parent.name == ".mainspring":
            return parent.parent
    env_root = _clean_context_value(os.environ.get("MAINSPRING_PROJECT_ROOT"))
    return Path(env_root) if env_root else None


def read_taskmaster_tag(project_root: Path | None) -> str:
    """Return the active Taskmaster tag for notification context."""
    env_tag = _clean_context_value(os.environ.get("MAINSPRING_TASKMASTER_TAG"))
    if env_tag:
        return env_tag
    if project_root is None:
        return ""

    taskmaster_dir = project_root / ".taskmaster"
    state_path = taskmaster_dir / "state.json"
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            tag = _clean_context_value(state.get("currentTag"))
            if tag:
                return tag
        except Exception:
            pass
    return "master" if taskmaster_dir.exists() else ""


def build_notify_context(ledger_path: Path) -> dict[str, str]:
    """Build stable project context for a watcher process."""
    project_root = project_root_from_ledger_path(ledger_path)
    project_name = _clean_context_value(os.environ.get("MAINSPRING_PROJECT_NAME"))
    if not project_name and project_root is not None:
        project_name = project_root.name

    context: dict[str, str] = {}
    if project_root is not None:
        context["project_root"] = str(project_root)
    if project_name:
        context["project_name"] = project_name
    tag = read_taskmaster_tag(project_root)
    if tag:
        context["taskmaster_tag"] = tag
    return context


def format_failure_context(entry: dict) -> list[str]:
    """Return review/score context lines for failed-wave notifications."""
    lines: list[str] = []
    for key, label in FAILURE_CONTEXT_FIELDS:
        value = entry.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            lines.append(f"{label}: {text}")
    return lines


def format_failure_next_action(entry: dict, reason: str) -> list[str]:
    """Return operator recovery guidance for failed-wave notifications."""
    next_action = str(entry.get("next_action") or "").strip()
    if not next_action and reason == "review:reviewer_unreachable":
        next_action = (
            "Restore the reviewer engine and rerun the review gate for this same "
            "item; no writer retry or auto-pass is trusted until the reviewer "
            "returns exit code 0."
        )
    if not next_action:
        next_action = (
            "Inspect the latest HUD/log, fix the blocker, and only rerun after "
            "the reason is understood."
        )
    return [f"Next: {next_action}"] if next_action else []


def format_project_action_lines(context: dict[str, str] | None = None) -> list[str]:
    """Return local operator commands for the project that emitted the event."""
    if not context:
        return []
    root = _clean_context_value(context.get("project_root"))
    if not root:
        return []
    quoted = shlex.quote(root)
    return [
        f"Open: cd {quoted} && mainspring hud --local",
        f"Stop: cd {quoted} && mainspring stop --force",
    ]


def _project_action_block(context: dict[str, str] | None = None) -> str:
    lines = format_project_action_lines(context)
    return "" if not lines else "\n" + "\n".join(lines)


def detect_wave_failed(
    entry: dict, context: dict[str, str] | None = None
) -> str | None:
    """Detect a wave failure event."""
    if _entry_failed(entry):
        task = entry.get("task_id") or "unknown"
        reason = _entry_failure_reason(entry) or "no reason"
        pair = _get_pair(entry)
        lines = [
            "🔴 Wave failed",
            *format_event_context(entry, context),
            f"Task: {task}",
            f"Pair: {pair}",
            f"Result: {_entry_result(entry)}",
            f"Reason: {reason}",
            *format_failure_context(entry),
            *format_failure_next_action(entry, reason),
            f"Duration: {_format_duration(entry)}",
        ]
        return "\n".join(lines)
    return None


def detect_retry_loop(
    entries: list[dict], context: dict[str, str] | None = None
) -> str | None:
    """Detect 3+ consecutive failures on the same task."""
    if len(entries) < 3:
        return None
    recent = entries[-3:]
    task_ids = [e.get("task_id") for e in recent]
    if not task_ids[0] or len(set(task_ids)) != 1:
        return None
    if all(_entry_failed(e) for e in recent):
        failure_reasons = [_entry_failure_reason(e) for e in recent]
        latest = recent[-1]
        context_lines = "\n".join(format_event_context(recent[-1], context))
        context_prefix = f"{context_lines}\n" if context_lines else ""
        if failure_reasons and set(failure_reasons) == {"review:reviewer_unreachable"}:
            return (
                f"🔁 Reviewer outage loop detected\n"
                f"{context_prefix}"
                f"Task: {task_ids[0]}\n"
                f"Pair: {_get_pair(latest)}\n"
                f"Result: RETRY_LOOP\n"
                f"Reason: review:reviewer_unreachable\n"
                f"Fails: {len(recent)}+ consecutive waves\n"
                "Next: Restore the reviewer engine before retrying writer work; "
                "do not mark the task blocked for product reasons.\n"
                f"Duration: {_format_duration(latest)}"
                f"{_project_action_block(context)}"
            )
        return (
            f"🔁 Mainspring is stuck\n"
            f"{context_prefix}"
            f"Task: {task_ids[0]}\n"
            f"Pair: {_get_pair(latest)}\n"
            f"Result: RETRY_LOOP\n"
            f"Fails: {len(recent)}+ consecutive waves\n"
            f"Reason: {_entry_failure_reason(latest) or 'unknown'}\n"
            "Next: stop the loop, inspect the latest HUD/log, then fix the "
            "blocker or mark the task blocked before rerunning.\n"
            f"Duration: {_format_duration(latest)}"
            f"{_project_action_block(context)}"
        )
    return None


def detect_quota_warn(entry: dict, context: dict[str, str] | None = None) -> str | None:
    """Detect engine quota approaching limit (>90%)."""
    for engine, field in QUOTA_USAGE_FIELDS:
        val = entry.get(field)
        if val is not None:
            try:
                if float(val) > 90:
                    context_lines = "\n".join(format_event_context(entry, context))
                    context_prefix = f"{context_lines}\n" if context_lines else ""
                    task = entry.get("task_id") or "none"
                    return (
                        f"⚠️ Quota warning\n"
                        f"{context_prefix}"
                        f"Task: {task}\n"
                        f"Pair: {_get_pair(entry)}\n"
                        f"Result: WARN\n"
                        f"Reason: quota:{engine}_short_window_{val}%\n"
                        "Next: consider pausing or switching engine.\n"
                        f"Duration: {_format_duration(entry)}"
                    )
            except (TypeError, ValueError):
                continue
    return None


def detect_milestone(entry: dict, context: dict[str, str] | None = None) -> str | None:
    """Detect chapter_delta > 50 or task marked done."""
    context_lines = "\n".join(format_event_context(entry, context))
    context_prefix = f"{context_lines}\n" if context_lines else ""
    chapter_delta = entry.get("chapter_delta")
    if chapter_delta is not None:
        try:
            delta_val = int(str(chapter_delta).lstrip("+"))
            if delta_val > 50:
                task = entry.get("task_id") or "unknown"
                return (
                    f"🏆 Milestone reached\n"
                    f"{context_prefix}"
                    f"Task: {task}\n"
                    f"Pair: {_get_pair(entry)}\n"
                    f"Result: MILESTONE\n"
                    f"Reason: chapter_delta:+{delta_val}\n"
                    "Next: keep the current route and continue with the next "
                    "ready item.\n"
                    f"Duration: {_format_duration(entry)}"
                )
        except (TypeError, ValueError):
            pass

    if _entry_passed(entry) and entry_marks_task_done(entry):
        task = entry.get("task_id") or "unknown"
        return (
            f"✅ Task completed\n"
            f"{context_prefix}"
            f"Task: {task}\n"
            f"Pair: {_get_pair(entry)}\n"
            f"Result: PASS\n"
            "Reason: task_marked_done\n"
            "Next: continue with the next ready item.\n"
            f"Duration: {_format_duration(entry)}"
        )
    return None


def detect_loop_stopped(
    entry: dict, context: dict[str, str] | None = None
) -> str | None:
    """Detect a scheduler stop event."""
    if str(entry.get("verdict") or "").upper() != "STOP":
        return None

    task = entry.get("task_id") or "none"
    reason = _entry_failure_reason(entry) or str(entry.get("blocked_reason") or "")
    if not reason:
        reason = "scheduler stopped"
    pair = _get_pair(entry)
    duration = _entry_duration(entry)
    dur = f"{duration:g}" if duration is not None else "unknown"
    next_action = str(entry.get("next_action") or "").strip()
    lines = [
        "⏹️ Mainspring stopped",
        *format_event_context(entry, context),
        f"Task: {task}",
        f"Pair: {pair}",
        f"Result: {_entry_result(entry)}",
        f"Reason: {reason}",
    ]
    if next_action:
        lines.append(f"Next: {next_action}")
    lines.append(f"Duration: {dur}s")
    return "\n".join(lines)


def _compact_text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def entry_marks_task_done(entry: dict) -> bool:
    """Return whether a wave entry proves the Taskmaster item is done."""
    for key in ("task_status_after", "taskmaster_status_after", "task_status"):
        status = _compact_text(entry.get(key))
        if status in {"done", "completed"}:
            return True
        if status:
            return False

    # Legacy rows predate task_status_after. Keep a narrow fallback, but never
    # turn reviewer repair guidance such as "do not mark done" into a milestone.
    next_action = _compact_text(entry.get("next_action"))
    if not next_action:
        return False
    negated_done = (
        "do not mark",
        "don't mark",
        "not mark",
        "not done",
        "not yet done",
        "keep work item in review",
        "keep task in review",
        "leave work item in review",
        "leave task in review",
    )
    if any(phrase in next_action for phrase in negated_done):
        return False
    done_markers = (
        "mark task done",
        "mark the task done",
        "marked done",
        "marked as done",
        "task marked done",
        "task completed",
        "--status=done",
        "status=done",
    )
    return any(marker in next_action for marker in done_markers)


def _parse_float(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return result


def _parse_delta(value: object) -> float:
    parsed = _parse_float(str(value).lstrip("+")) if value is not None else None
    return parsed if parsed is not None else 0.0


def _parse_ts(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _entry_timestamp(entry: dict) -> datetime | None:
    """Return a wave timestamp from canonical or legacy ledger fields."""
    return _parse_ts(entry.get("ts") or entry.get("timestamp"))


def _entry_duration(entry: dict) -> float | None:
    """Return wave duration from canonical or legacy ledger fields."""
    return _parse_float(entry.get("duration_s") or entry.get("duration_seconds"))


def _entry_exit_code(entry: dict) -> int | None:
    """Return wave exit code from canonical or legacy ledger fields."""
    value = entry.get("exit_code")
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _entry_failed(entry: dict) -> bool:
    """Return whether a wave row represents failure."""
    verdict = str(entry.get("verdict") or "").upper()
    exit_code = _entry_exit_code(entry)
    return verdict in ("FAIL", "ERROR") or (exit_code is not None and exit_code != 0)


def _entry_passed(entry: dict) -> bool:
    """Return whether a wave row represents a clean pass."""
    verdict = str(entry.get("verdict") or "").upper()
    return verdict == "PASS" and not _entry_failed(entry)


def _entry_failure_reason(entry: dict) -> str:
    """Return the most specific failure reason available on a wave row."""
    reason = str(entry.get("failure_reason") or "").strip()
    if reason:
        return reason
    return str(entry.get("failure_reason_class") or "").strip()


def _entry_result(entry: dict) -> str:
    """Return the operator-visible result for a wave row."""
    verdict = str(entry.get("verdict") or "").strip().upper()
    if verdict:
        return verdict
    exit_code = _entry_exit_code(entry)
    if exit_code is None:
        return "unknown"
    return "PASS" if exit_code == 0 else f"EXIT {exit_code}"


def _format_duration(entry: dict | None) -> str:
    """Return the operator-visible duration field."""
    if entry is None:
        return "unknown"
    duration = _entry_duration(entry)
    return f"{duration:g}s" if duration is not None else "unknown"


def _normalize_model_name(model: object) -> str:
    return str(model or "").strip().lower().replace("_", "-")


def _model_price(model: object) -> dict[str, float] | None:
    normalized = _normalize_model_name(model)
    if not normalized or normalized in {"auto", "default", "?"}:
        return None
    if normalized in MODEL_PRICES_USD_PER_MTOK:
        return MODEL_PRICES_USD_PER_MTOK[normalized]
    if "gpt-5.4-mini" in normalized or "gpt-5.4 mini" in normalized:
        return MODEL_PRICES_USD_PER_MTOK["gpt-5.4-mini"]
    for key in ("gpt-5.5", "gpt-5.4"):
        if key in normalized:
            return MODEL_PRICES_USD_PER_MTOK[key]
    for key in (
        "claude-opus-4.7",
        "claude-opus-4.6",
        "claude-opus-4.5",
        "claude-opus-4.1",
        "claude-opus-4",
        "claude-sonnet-4.6",
        "claude-sonnet-4.5",
        "claude-sonnet-4",
        "claude-haiku-4.5",
        "claude-haiku-3.5",
        "claude-haiku-3",
    ):
        if key in normalized:
            return MODEL_PRICES_USD_PER_MTOK[key]
    if "opus" in normalized:
        return MODEL_PRICES_USD_PER_MTOK["opus"]
    if "sonnet" in normalized:
        return MODEL_PRICES_USD_PER_MTOK["sonnet"]
    if "haiku" in normalized:
        return MODEL_PRICES_USD_PER_MTOK["haiku"]
    return None


def _get_pair(entry: dict) -> str:
    pair = str(entry.get("pair") or "").strip()
    if pair:
        return pair
    engines = entry.get("engines") or {}
    writer = engines.get("writer") or entry.get("engine") or "?"
    reviewer = engines.get("reviewer") or entry.get("review_engine") or "?"
    return f"{writer}+{reviewer}"


def _get_model(entry: dict, role: str = "writer") -> object:
    models = entry.get("models") if isinstance(entry.get("models"), dict) else {}
    role_model = models.get(role) if models else None
    if role_model:
        return role_model
    if role == "reviewer":
        return entry.get("reviewer_model") or entry.get("review_model")
    return entry.get("writer_model") or entry.get("model")


def _token_breakdown(usage: dict) -> dict[str, float] | None:
    input_tokens = _parse_float(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_tokens = _parse_float(
        usage.get("output_tokens") or usage.get("completion_tokens")
    )
    cached_tokens = _parse_float(
        usage.get("cached_input_tokens")
        or usage.get("cache_read_input_tokens")
        or usage.get("cached_tokens")
    )
    if input_tokens is None and output_tokens is None and cached_tokens is None:
        return None
    return {
        "input": input_tokens or 0.0,
        "cached_input": cached_tokens or 0.0,
        "output": output_tokens or 0.0,
    }


def _estimate_usage_cost_usd(model: object, usage: dict) -> float | None:
    prices = _model_price(model)
    tokens = _token_breakdown(usage)
    if prices is None or tokens is None:
        return None
    cached_input = min(tokens["cached_input"], tokens["input"])
    billable_input = max(0.0, tokens["input"] - cached_input)
    return (
        (billable_input / 1_000_000) * prices["input"]
        + (cached_input / 1_000_000) * prices["cached_input"]
        + (tokens["output"] / 1_000_000) * prices["output"]
    )


def extract_wave_cost(entry: dict) -> tuple[float, str] | None:
    """Return explicit or safely estimated wave cost.

    Cost is explicit when the ledger provides a cost field. Otherwise it is
    estimated only from token counts and a known model price table.
    """
    usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
    candidates = (
        entry.get("cost_usd"),
        entry.get("total_cost_usd"),
        usage.get("cost_usd") if usage else None,
        usage.get("total_cost_usd") if usage else None,
    )
    for value in candidates:
        parsed = _parse_float(value)
        if parsed is not None and parsed >= 0:
            return parsed, "ledger"

    if not usage:
        return None

    role_usages = [
        role for role in ("writer", "reviewer") if isinstance(usage.get(role), dict)
    ]
    if role_usages:
        total = 0.0
        for role in role_usages:
            estimated = _estimate_usage_cost_usd(_get_model(entry, role), usage[role])
            if estimated is None:
                return None
            total += estimated
        return total, "estimated"

    estimated = _estimate_usage_cost_usd(_get_model(entry), usage)
    if estimated is None:
        return None
    return estimated, "estimated"


def extract_wave_cost_usd(entry: dict) -> float | None:
    """Return explicit or safely estimated per-wave USD cost."""
    cost = extract_wave_cost(entry)
    return cost[0] if cost is not None else None


def extract_token_count(entry: dict) -> int | None:
    """Return real token usage if the ledger entry contains supported fields."""
    usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
    for value in (
        entry.get("tokens"),
        entry.get("total_tokens"),
        usage.get("tokens") if usage else None,
        usage.get("total_tokens") if usage else None,
    ):
        parsed = _parse_float(value)
        if parsed is not None and parsed >= 0:
            return int(parsed)

    input_tokens = _parse_float(usage.get("input_tokens") or usage.get("prompt_tokens"))
    output_tokens = _parse_float(
        usage.get("output_tokens") or usage.get("completion_tokens")
    )
    if input_tokens is not None or output_tokens is not None:
        return int((input_tokens or 0) + (output_tokens or 0))

    role_total = 0
    role_found = False
    for role in ("writer", "reviewer"):
        role_usage = usage.get(role) if isinstance(usage.get(role), dict) else None
        if not role_usage:
            continue
        tokens = _token_breakdown(role_usage)
        if tokens is None:
            continue
        role_found = True
        role_total += int(tokens["input"] + tokens["output"])
    if role_found:
        return role_total
    return None


def extract_role_token_counts(entry: dict) -> dict[str, int]:
    """Return per-role token usage when the ledger records role-specific usage."""
    usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
    role_counts: dict[str, int] = {}
    for role in ("writer", "reviewer"):
        role_usage = usage.get(role) if isinstance(usage.get(role), dict) else None
        if not role_usage:
            continue
        tokens = _token_breakdown(role_usage)
        if tokens is None:
            continue
        role_counts[role] = int(tokens["input"] + tokens["output"])
    return role_counts


def extract_product_score_delta(entry: dict) -> float:
    """Return a product-score movement only when explicitly logged."""
    for field in ("product_score_delta", "score_delta"):
        if field in entry:
            return _parse_delta(entry.get(field))
    return 0.0


def _positive_product_score_movement_totals(
    entries: list[dict], costed_entry_ids: set[int]
) -> tuple[float, float, str]:
    """Return costed and total positive score movement."""
    explicit_seen = False
    total_explicit = 0.0
    explicit_total = 0.0
    for entry in entries:
        if "product_score_delta" not in entry and "score_delta" not in entry:
            continue
        explicit_seen = True
        delta = max(0.0, extract_product_score_delta(entry))
        total_explicit += delta
        if id(entry) in costed_entry_ids:
            explicit_total += delta
    if explicit_seen:
        return explicit_total, total_explicit, "explicit"

    previous: float | None = None
    total_inferred = 0.0
    inferred_total = 0.0
    for entry in entries:
        score = _parse_float(entry.get("product_score"))
        if score is None:
            continue
        if previous is not None:
            movement = max(0.0, score - previous)
            total_inferred += movement
            if id(entry) in costed_entry_ids:
                inferred_total += movement
        previous = score
    return inferred_total, total_inferred, "inferred" if total_inferred > 0 else "none"


def _format_delta_points(value: float) -> str:
    """Format positive score/chapter movement for compact digest lines."""
    if value <= 0:
        return "0"
    if value.is_integer():
        return f"+{int(value)}"
    return f"+{value:.1f}".rstrip("0").rstrip(".")


def _format_pct(value: float) -> str:
    if value.is_integer():
        return f"{int(value)}%"
    return f"{value:.1f}%"


def extract_quota_status(entries: list[dict]) -> str:
    """Return the latest quota status represented in ledger data."""
    latest: dict[str, float] = {}
    explicit_status = ""
    for entry in entries:
        if isinstance(entry.get("quota_status"), str):
            explicit_status = str(entry["quota_status"]).strip()
        for engine, field in QUOTA_USAGE_FIELDS:
            parsed = _parse_float(entry.get(field))
            if parsed is not None and parsed >= 0:
                latest[engine] = parsed
        quota = entry.get("quota") if isinstance(entry.get("quota"), dict) else {}
        for engine, payload in quota.items():
            if not isinstance(payload, dict):
                continue
            used = _parse_float(
                payload.get("short_used_pct")
                or payload.get("short_usage_pct")
                or payload.get("used_percent")
            )
            remaining = _parse_float(
                payload.get("short_remaining_pct")
                or payload.get("short_remaining")
                or payload.get("remaining_percent")
            )
            if used is None and remaining is not None:
                used = max(0.0, 100.0 - remaining)
            if used is not None and used >= 0:
                latest[str(engine).strip().lower()] = used

    if latest:
        preferred = ["codex", "claude", "gemini"]
        ordered = [engine for engine in preferred if engine in latest]
        ordered.extend(sorted(engine for engine in latest if engine not in preferred))
        return ", ".join(
            f"{engine} {_format_pct(latest[engine])} short used" for engine in ordered
        )
    return explicit_status or "Waiting for quota data"


def load_disabled_pairs(state_dir: Path | None) -> list[str]:
    """Read disabled pair names from state, tolerating future schema shapes."""
    if state_dir is None:
        return []
    path = state_dir / "disabled-pairs.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    pairs: list[str] = []
    if isinstance(data, list):
        pairs = [str(item).strip() for item in data]
    elif isinstance(data, dict):
        for key in ("disabled_pairs", "pairs"):
            if isinstance(data.get(key), list):
                pairs.extend(str(item).strip() for item in data[key])
        details = data.get("pairs")
        if isinstance(details, dict):
            for pair, payload in details.items():
                if not isinstance(payload, dict):
                    continue
                status = str(payload.get("status") or "").strip()
                if status in {"auto_disabled", "manual_disabled"}:
                    pairs.append(str(pair).strip())
        if not pairs:
            metadata_keys = {
                "disabled_pairs",
                "generated_at",
                "manual_disabled_pairs",
                "manual_reactivated_pairs",
                "median_chapter_delta_per_dollar_14d",
                "pairs",
                "reactivated_pairs",
                "schema_version",
                "threshold_chapter_delta_per_dollar_14d",
                "threshold_ratio",
                "updated_at",
                "window_days",
            }
            for key, value in data.items():
                if key in metadata_keys:
                    continue
                if value and "+" in key:
                    pairs.append(str(key).strip())
    return sorted({pair for pair in pairs if pair})


def build_daily_digest(
    entries: list[dict],
    days: int = 1,
    state_dir: Path | None = None,
    *,
    mode: str = "rolling",
    now: datetime | None = None,
    context: dict[str, str] | None = None,
) -> str | None:
    """Build a daily digest message from recent entries."""
    if not entries:
        return None

    if days <= 0:
        return None

    now = now if now is not None else datetime.now().astimezone()
    now_local = now if now.tzinfo is not None else now.astimezone()
    now = now_local.astimezone(UTC)
    if mode == "calendar":
        digest_date = (now_local - timedelta(days=days)).date()
    else:
        digest_date = now_local.date()

    recent = []
    for e in entries:
        ts = _entry_timestamp(e)
        if ts is None:
            continue
        ts_utc = ts.astimezone(UTC)
        if mode == "calendar":
            if ts_utc.astimezone(now_local.tzinfo).date() != digest_date:
                continue
        else:
            cutoff_s = days * 86400
            if (now - ts_utc).total_seconds() > cutoff_s:
                continue
        recent.append(e)

    if not recent:
        return None

    total = len(recent)
    passed = sum(1 for e in recent if _entry_passed(e))
    failed = sum(1 for e in recent if _entry_failed(e))
    other = max(0, total - passed - failed)
    pass_rate = (passed / total * 100) if total else 0
    durations = [
        duration
        for e in recent
        for duration in [_entry_duration(e)]
        if duration is not None
    ]
    mean_dur = sum(durations) / len(durations) if durations else 0
    wave_costs = [
        (e, cost, source)
        for e in recent
        for cost_info in [extract_wave_cost(e)]
        if cost_info is not None
        for cost, source in [cost_info]
    ]
    total_cost = sum(cost for _, cost, _ in wave_costs)
    estimated_cost_count = sum(
        1 for _, _, source in wave_costs if source == "estimated"
    )
    costed_entries = [entry for entry, _, _ in wave_costs]
    costed_entry_ids = {id(entry) for entry in costed_entries}

    tokens_by_pair: dict[str, int] = {}
    role_tokens_by_pair: dict[str, dict[str, int]] = {}
    for e in recent:
        tokens = extract_token_count(e)
        pair = _get_pair(e)
        if tokens is not None:
            tokens_by_pair[pair] = tokens_by_pair.get(pair, 0) + tokens
        role_counts = extract_role_token_counts(e)
        if role_counts:
            pair_roles = role_tokens_by_pair.setdefault(pair, {})
            for role, count in role_counts.items():
                pair_roles[role] = pair_roles.get(role, 0) + count

    total_positive_chapter_delta = sum(
        max(0.0, _parse_delta(e.get("chapter_delta"))) for e in recent
    )
    costed_positive_chapter_delta = sum(
        max(0.0, _parse_delta(e.get("chapter_delta"))) for e in costed_entries
    )
    uncosted_positive_chapter_delta = max(
        0.0, total_positive_chapter_delta - costed_positive_chapter_delta
    )
    (
        costed_positive_score_delta,
        total_positive_score_delta,
        score_delta_source,
    ) = _positive_product_score_movement_totals(recent, costed_entry_ids)
    uncosted_positive_score_delta = max(
        0.0, total_positive_score_delta - costed_positive_score_delta
    )

    # Top stuck tasks (3+ fails)
    task_fails: dict[str, int] = {}
    for e in recent:
        tid = e.get("task_id")
        if tid and _entry_failed(e):
            task_fails[tid] = task_fails.get(tid, 0) + 1
    stuck = sorted(
        ((tid, c) for tid, c in task_fails.items() if c >= 3),
        key=lambda x: -x[1],
    )[:3]
    quota_status = extract_quota_status(recent)
    disabled_pairs = load_disabled_pairs(state_dir)

    lines = [
        f"📊 Daily Digest ({digest_date.strftime('%Y-%m-%d')})",
        *format_event_context(context=context),
        "Waves: "
        f"{total} ({passed} pass, {failed} fail"
        f"{f', {other} other' if other else ''})",
        f"Pass rate: {pass_rate:.0f}%",
        f"Mean duration: {mean_dur:.0f}s",
        f"Quota: {quota_status}",
    ]
    if state_dir is None:
        lines.append("Disabled pairs: Waiting for state data")
    elif disabled_pairs:
        lines.append(f"Disabled pairs: {', '.join(disabled_pairs)}")
    else:
        lines.append("Disabled pairs: none")

    if wave_costs:
        lines.append(
            f"Cost: ${total_cost:.2f} ({len(wave_costs)}/{total} waves with cost truth)"
        )
        if estimated_cost_count:
            lines.append(f"Estimated cost waves: {estimated_cost_count}")
        if costed_positive_chapter_delta > 0:
            lines.append(
                f"Cost / chapter delta: "
                f"${total_cost / costed_positive_chapter_delta:.2f}/pt"
            )
        else:
            lines.append(
                "Cost / chapter delta: Waiting for costed positive chapter_delta"
            )
        if uncosted_positive_chapter_delta > 0:
            lines.append(
                "Uncosted chapter delta: "
                f"{_format_delta_points(uncosted_positive_chapter_delta)} "
                "(excluded from unit costs)"
            )
        if costed_positive_score_delta > 0:
            source_label = (
                " (from product_score movement)"
                if score_delta_source == "inferred"
                else ""
            )
            lines.append(
                f"Cost / score delta: "
                f"${total_cost / costed_positive_score_delta:.2f}/pt"
                f"{source_label}"
            )
        else:
            lines.append("Cost / score delta: Waiting for score-delta data")
        if uncosted_positive_score_delta > 0:
            lines.append(
                "Uncosted score delta: "
                f"{_format_delta_points(uncosted_positive_score_delta)} "
                "(excluded from unit costs)"
            )

        top_costs = sorted(wave_costs, key=lambda item: -item[1])[:3]
        lines.append("Top cost waves:")
        for e, cost, source in top_costs:
            wave_id = e.get("wave_id") or "unknown"
            task = e.get("task_id") or "none"
            source_label = " estimated" if source == "estimated" else ""
            lines.append(
                f"  • {wave_id} task={task} {_get_pair(e)} ${cost:.2f}{source_label}"
            )
    else:
        lines.append("Cost: Waiting for usage data")

    if tokens_by_pair:
        lines.append("Tokens by pair:")
        for pair, tokens in sorted(tokens_by_pair.items()):
            lines.append(f"  • {pair}: {tokens}")
    if role_tokens_by_pair:
        lines.append("Role tokens by pair:")
        for pair, role_counts in sorted(role_tokens_by_pair.items()):
            parts = [
                f"{role}={role_counts[role]}"
                for role in ("writer", "reviewer")
                if role in role_counts
            ]
            lines.append(f"  • {pair}: {', '.join(parts)}")
    if stuck:
        lines.append("Stuck tasks:")
        for tid, count in stuck:
            lines.append(f"  • {tid} ({count} fails)")
    return "\n".join(lines)


# ── Rate limiting + dedup state ──────────────────────────────────────────


def _nonnegative_int(value: object, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if parsed >= 0 else default


def _nonnegative_float(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed) or parsed < 0:
        return default
    return parsed


def _fsync_directory(path: Path) -> None:
    """Best-effort fsync for the directory entry after an atomic replace."""
    flags = getattr(os, "O_RDONLY", 0)
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class NotifyState:
    """Persistent dedup + rate-limit state."""

    def __init__(self, state_path: Path) -> None:
        self.path = state_path
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self.path.is_file():
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
            return payload if isinstance(payload, dict) else {}
        return {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(
            f".{self.path.name}.{os.getpid()}.{time.time_ns()}.tmp"
        )
        try:
            with tmp_path.open("w", encoding="utf-8") as stream:
                stream.write(json.dumps(self._data, indent=2, ensure_ascii=False))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_path, self.path)
            _fsync_directory(self.path.parent)
        finally:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass

    def _last_sent_ts(self, event_class: str) -> float:
        last_sent = self._data.get("last_sent")
        if not isinstance(last_sent, dict):
            return 0.0
        return _nonnegative_float(last_sent.get(event_class), 0.0)

    def _last_attempt_ts(self, event_class: str) -> float:
        last_attempt = self._data.get("last_attempt")
        if not isinstance(last_attempt, dict):
            return 0.0
        return _nonnegative_float(last_attempt.get(event_class), 0.0)

    def is_rate_limited(self, event_class: str, now: float | None = None) -> bool:
        """Check if event_class is within the rate limit window."""
        ts = now if now is not None else time.time()
        last = self._last_sent_ts(event_class)
        return (ts - last) < RATE_LIMIT_SECONDS

    def is_attempt_limited(self, event_class: str, now: float | None = None) -> bool:
        """Check if an event class already attempted delivery recently."""
        ts = now if now is not None else time.time()
        last = max(self._last_sent_ts(event_class), self._last_attempt_ts(event_class))
        return (ts - last) < RATE_LIMIT_SECONDS

    def record_attempt(self, event_class: str, now: float | None = None) -> None:
        """Record a delivery attempt without claiming the message was delivered."""
        ts = now if now is not None else time.time()
        if not isinstance(self._data.get("last_attempt"), dict):
            self._data["last_attempt"] = {}
        self._data["last_attempt"][event_class] = _nonnegative_float(ts, 0.0)

    def record_sent(self, event_class: str, now: float | None = None) -> None:
        """Record that an event of this class was sent."""
        ts = now if now is not None else time.time()
        if not isinstance(self._data.get("last_sent"), dict):
            self._data["last_sent"] = {}
        self._data["last_sent"][event_class] = _nonnegative_float(ts, 0.0)

    @property
    def last_line_count(self) -> int:
        return _nonnegative_int(self._data.get("last_line_count"), 0)

    @last_line_count.setter
    def last_line_count(self, value: int) -> None:
        self._data["last_line_count"] = _nonnegative_int(value, 0)

    @property
    def last_activity_ts(self) -> float:
        return _nonnegative_float(self._data.get("last_activity_ts"), 0.0)

    @last_activity_ts.setter
    def last_activity_ts(self, value: float) -> None:
        self._data["last_activity_ts"] = _nonnegative_float(value, 0.0)

    @property
    def last_digest_date(self) -> str:
        return self._data.get("last_digest_date", "")

    @last_digest_date.setter
    def last_digest_date(self, value: str) -> None:
        self._data["last_digest_date"] = value


# ── Watch loop ───────────────────────────────────────────────────────────


def _read_ledger_lines(path: Path) -> list[str]:
    """Read all non-empty lines from the ledger."""
    if not path.is_file():
        return []
    try:
        return [
            line
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        ]
    except OSError:
        return []


def _parse_entries(lines: list[str]) -> list[dict]:
    """Parse JSONL lines into dicts, skipping invalid."""
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue
    return entries


def _latest_processed_log_ts(log_path: Path) -> float | None:
    """Return the latest notifier.log processed-line timestamp."""
    try:
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if " processed " not in line:
            continue
        parts = line.split(maxsplit=3)
        if len(parts) < 3 or parts[0] != "notify:" or parts[2] != "processed":
            continue
        parsed = _parse_ts(parts[1])
        if parsed is not None:
            return parsed.timestamp()
    return None


def _read_pid(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        pid = int(raw)
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


def _try_notify_status(
    state: NotifyState,
    event_class: str,
    message: str,
    now: float | None = None,
) -> str:
    """Send notification if not rate-limited."""
    if state.is_attempt_limited(event_class, now=now):
        return "rate_limited"
    state.record_attempt(event_class, now=now)
    result = send_message(message)
    if result is not None:
        state.record_sent(event_class, now=now)
        return "sent"
    return "failed"


def _format_statuses(statuses: list[tuple[str, str]], wanted: str) -> str:
    values = [event for event, status in statuses if status == wanted]
    if not values:
        return "none"
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return ",".join(
        f"{event}x{count}" if count > 1 else event
        for event, count in sorted(counts.items())
    )


def process_new_entries(
    new_entries: list[dict],
    all_entries: list[dict],
    state: NotifyState,
    now: float | None = None,
    status_log: list[tuple[str, str]] | None = None,
    context: dict[str, str] | None = None,
) -> list[str]:
    """Process new entries and send applicable notifications.

    Returns list of event classes that were sent.
    """
    sent: list[str] = []
    retry_loop_msg = detect_retry_loop(all_entries, context=context)
    suppress_wave_failed = retry_loop_msg is not None

    if retry_loop_msg:
        status = _try_notify_status(state, "retry_loop", retry_loop_msg, now=now)
        if status_log is not None:
            status_log.append(("retry_loop", status))
        if status == "sent":
            sent.append("retry_loop")

    for entry in new_entries:
        # wave_failed
        msg = (
            None if suppress_wave_failed else detect_wave_failed(entry, context=context)
        )
        if msg:
            status = _try_notify_status(state, "wave_failed", msg, now=now)
            if status_log is not None:
                status_log.append(("wave_failed", status))
            if status == "sent":
                sent.append("wave_failed")

        # quota_warn
        msg = detect_quota_warn(entry, context=context)
        if msg:
            status = _try_notify_status(state, "quota_warn", msg, now=now)
            if status_log is not None:
                status_log.append(("quota_warn", status))
            if status == "sent":
                sent.append("quota_warn")

        # milestone
        msg = detect_milestone(entry, context=context)
        if msg:
            status = _try_notify_status(state, "milestone", msg, now=now)
            if status_log is not None:
                status_log.append(("milestone", status))
            if status == "sent":
                sent.append("milestone")

        # loop_stopped
        msg = detect_loop_stopped(entry, context=context)
        if msg:
            status = _try_notify_status(state, "loop_stopped", msg, now=now)
            if status_log is not None:
                status_log.append(("loop_stopped", status))
            if status == "sent":
                sent.append("loop_stopped")

    return sent


def watch_loop(
    ledger_path: Path,
    state: NotifyState,
    poll_interval: float = 5.0,
    max_iterations: int | None = None,
) -> None:
    """Main watch loop — tail the ledger and emit notifications.

    Args:
        ledger_path: Path to waves.jsonl.
        state: Persistent notification state.
        poll_interval: Seconds between polls.
        max_iterations: If set, exit after this many iterations (for testing).
    """
    state.save()
    iteration = 0
    while True:
        if max_iterations is not None and iteration >= max_iterations:
            break
        iteration += 1
        now = time.time()
        context = build_notify_context(ledger_path)

        lines = _read_ledger_lines(ledger_path)
        current_count = len(lines)
        prev_count = state.last_line_count

        if current_count < prev_count:
            log_status(
                f"ledger line count reset from {prev_count} to {current_count}; "
                "re-reading current ledger",
                now=now,
            )
            prev_count = 0
            state.last_line_count = 0

        if current_count > prev_count:
            new_lines = lines[prev_count:]
            all_entries = _parse_entries(lines)
            new_entries = _parse_entries(new_lines)
            statuses: list[tuple[str, str]] = []

            if new_entries:
                process_new_entries(
                    new_entries,
                    all_entries,
                    state,
                    now=now,
                    status_log=statuses,
                    context=context,
                )

            state.last_line_count = current_count
            state.last_activity_ts = now
            log_status(
                f"processed {len(new_lines)} new ledger line(s), "
                f"{len(new_entries)} valid; "
                f"sent={_format_statuses(statuses, 'sent')} "
                f"suppressed={_format_statuses(statuses, 'rate_limited')} "
                f"failed={_format_statuses(statuses, 'failed')}",
                now=now,
            )
        elif current_count == prev_count and state.last_activity_ts > 0:
            # team_stuck: no new line in 30 minutes
            elapsed = now - state.last_activity_ts
            if elapsed > 1800:
                parsed_entries = _parse_entries(lines)
                latest_entry = parsed_entries[-1] if parsed_entries else None
                context_lines = "\n".join(format_event_context(context=context))
                context_prefix = f"{context_lines}\n" if context_lines else ""
                task = (
                    latest_entry.get("task_id") or "unknown"
                    if latest_entry is not None
                    else "unknown"
                )
                pair = (
                    _get_pair(latest_entry) if latest_entry is not None else "unknown"
                )
                msg = (
                    f"⏰ Team stuck\n"
                    f"{context_prefix}"
                    f"Task: {task}\n"
                    f"Pair: {pair}\n"
                    f"Result: STUCK\n"
                    f"Reason: no_new_wave_{elapsed / 60:.0f}m\n"
                    "Next: run mainspring status or mainspring doctor.\n"
                    f"Duration: {_format_duration(latest_entry)}"
                )
                status = _try_notify_status(state, "team_stuck", msg, now=now)
                if status != "rate_limited":
                    log_status(
                        f"team_stuck notification {status}; "
                        f"elapsed_minutes={elapsed / 60:.0f}",
                        now=now,
                    )

        # daily_digest at 09:00 local
        local_now = datetime.now()
        today_str = local_now.strftime("%Y-%m-%d")
        if (
            local_now.hour >= 9
            and state.last_digest_date != today_str
            and current_count > 0
        ):
            digest_now = local_now.astimezone()
            all_entries = _parse_entries(lines)
            digest = build_daily_digest(
                all_entries,
                days=1,
                state_dir=state.path.parent,
                mode="calendar",
                now=digest_now,
                context=context,
            )
            if digest:
                status = _try_notify_status(state, "daily_digest", digest, now=now)
                if status == "sent":
                    state.last_digest_date = today_str
                if status != "rate_limited":
                    log_status(f"daily_digest notification {status}", now=now)

        state.save()

        time.sleep(poll_interval)


# ── Health check ─────────────────────────────────────────────────────────


def check_watch_health(
    ledger_path: Path,
    state: NotifyState,
    now: float | None = None,
    stale_seconds: int = STALE_DAEMON_SECONDS,
    log_path: Path | None = None,
    pid_path: Path | None = None,
) -> dict:
    """Return watcher health based on ledger progress and persisted state."""
    ts = now if now is not None else time.time()
    current_count = len(_read_ledger_lines(ledger_path))
    last_count = state.last_line_count
    pending_lines = max(0, current_count - last_count)
    last_activity_ts = state.last_activity_ts
    seconds_since_activity = ts - last_activity_ts if last_activity_ts > 0 else None
    try:
        state_mtime_ts = state.path.stat().st_mtime
    except OSError:
        state_mtime_ts = None
    try:
        ledger_mtime_ts = ledger_path.stat().st_mtime
    except OSError:
        ledger_mtime_ts = None
    seconds_since_state_write = (
        ts - state_mtime_ts if state_mtime_ts is not None else None
    )
    seconds_since_ledger_write = (
        ts - ledger_mtime_ts if ledger_mtime_ts is not None else None
    )
    log_exists = log_path.is_file() if log_path is not None else None
    last_processed_log_ts = (
        _latest_processed_log_ts(log_path) if log_path is not None else None
    )
    seconds_since_log_activity = (
        ts - last_processed_log_ts if last_processed_log_ts is not None else None
    )
    pid_exists = pid_path.is_file() if pid_path is not None else None
    daemon_pid = _read_pid(pid_path) if pid_path is not None else None
    daemon_pid_running = _pid_is_running(daemon_pid) if pid_path is not None else None

    status = "healthy"
    reason = "caught_up"
    if current_count < last_count:
        status = "stale"
        reason = "ledger_line_count_reset"
    elif pending_lines > 0 and last_activity_ts <= 0:
        stale_age = seconds_since_state_write
        if stale_age is None:
            stale_age = seconds_since_ledger_write
        if stale_age is not None and stale_age > stale_seconds:
            status = "stale"
            reason = "pending_without_activity_stale"
        else:
            status = "starting"
            reason = "pending_without_activity"
    elif (
        pending_lines > 0
        and seconds_since_activity is not None
        and seconds_since_activity > stale_seconds
    ):
        status = "stale"
        reason = "pending_lines_stale"

    if log_path is not None and status == "healthy" and current_count > 0:
        if not log_exists or last_processed_log_ts is None:
            warmup_age = seconds_since_activity
            if warmup_age is None:
                warmup_age = seconds_since_state_write
            if warmup_age is None:
                warmup_age = seconds_since_ledger_write
            if warmup_age is not None and warmup_age > stale_seconds:
                status = "stale"
                reason = (
                    "notifier_log_missing"
                    if not log_exists
                    else "notifier_log_no_processed_activity"
                )
            else:
                status = "starting"
                reason = "notifier_log_warming_up"
        elif (
            seconds_since_log_activity is not None
            and seconds_since_log_activity > stale_seconds
            and ledger_mtime_ts is not None
            and ledger_mtime_ts > last_processed_log_ts
        ):
            status = "stale"
            reason = "notifier_log_stale"

    if pid_path is not None and status != "stale":
        if not pid_exists:
            status = "stale"
            reason = "daemon_pid_missing"
        elif daemon_pid is None:
            status = "stale"
            reason = "daemon_pid_invalid"
        elif not daemon_pid_running:
            status = "stale"
            reason = "daemon_pid_not_running"

    next_step = health_next_step(status, reason)
    return {
        "status": status,
        "reason": reason,
        **next_step,
        "ledger_lines": current_count,
        "last_line_count": last_count,
        "pending_lines": pending_lines,
        "last_activity_ts": last_activity_ts,
        "seconds_since_activity": seconds_since_activity,
        "state_mtime_ts": state_mtime_ts,
        "seconds_since_state_write": seconds_since_state_write,
        "ledger_mtime_ts": ledger_mtime_ts,
        "seconds_since_ledger_write": seconds_since_ledger_write,
        "stale_seconds": stale_seconds,
        "log_path": str(log_path) if log_path is not None else None,
        "log_exists": log_exists,
        "last_processed_log_ts": last_processed_log_ts,
        "seconds_since_log_activity": seconds_since_log_activity,
        "pid_path": str(pid_path) if pid_path is not None else None,
        "pid_exists": pid_exists,
        "daemon_pid": daemon_pid,
        "daemon_pid_running": daemon_pid_running,
    }


def _env_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def notify_enabled_from_env() -> bool:
    """Return whether Telegram notification monitoring is enabled."""
    return _env_enabled(os.environ.get("MAINSPRING_NOTIFY_ENABLED"))


def notify_configured_from_env() -> bool:
    """Return whether Telegram delivery credentials are configured."""
    return bool(_get_bot_token() and _get_chat_id())


def operator_health(
    ledger_path: Path,
    *,
    state_dir: Path,
    stale_seconds: int = STALE_DAEMON_SECONDS,
    log_path: Path | None = None,
    pid_path: Path | None = None,
    now: float | None = None,
) -> dict:
    """Return operator-facing notification health, including env readiness."""
    state_path = state_dir / "notify-state.json"
    enabled = notify_enabled_from_env()
    configured = notify_configured_from_env()
    base = {
        "enabled": enabled,
        "configured": configured,
        "ledger_path": str(ledger_path),
        "state_path": str(state_path),
        "log_path": str(log_path) if log_path is not None else None,
        "pid_path": str(pid_path) if pid_path is not None else None,
        "stale_seconds": stale_seconds,
    }
    if not enabled:
        guidance = health_next_step(
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
        }
    if not configured:
        guidance = health_next_step(
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
        }

    health = check_watch_health(
        ledger_path,
        NotifyState(state_path),
        now=now,
        stale_seconds=stale_seconds,
        log_path=log_path,
        pid_path=pid_path,
    )
    return {**base, **health}


def format_operator_health_text(health: dict) -> str:
    """Render one-line operator health for shell users."""
    return (
        "notify: health "
        f"status={health['status']} "
        f"reason={health['reason']} "
        f"pending={health['pending_lines']} "
        f"ledger_lines={health['ledger_lines']} "
        f"last_line_count={health['last_line_count']} "
        f"next_step={health['next_step']} "
        f"next_step_message={health['next_step_message']}"
    )


def health_next_step(status: str, reason: str) -> dict[str, str]:
    """Return operator-facing recovery guidance for a health state."""
    if status == "healthy":
        return {
            "next_step": "none",
            "next_step_message": "No action needed.",
        }
    if status == "disabled":
        return {
            "next_step": "enable-notifications",
            "next_step_message": (
                "Set MAINSPRING_NOTIFY_ENABLED=1 to monitor Telegram delivery."
            ),
        }
    if status == "unconfigured":
        return {
            "next_step": "configure-telegram",
            "next_step_message": (
                "Set MAINSPRING_TELEGRAM_BOT_TOKEN and MAINSPRING_TELEGRAM_CHAT_ID, "
                "then run mainspring notify-test."
            ),
        }
    if reason == "invalid_stale_seconds":
        return {
            "next_step": "fix-notify-stale-threshold",
            "next_step_message": (
                "Set MAINSPRING_NOTIFY_STALE_SECONDS to a non-negative integer "
                "number of seconds, or unset it to use the default."
            ),
        }
    if status == "starting":
        return {
            "next_step": "wait-for-heartbeat",
            "next_step_message": "Wait for the notifier heartbeat; rerun HUD if pending lines keep aging.",
        }
    if reason == "ledger_line_count_reset":
        return {
            "next_step": "review-ledger-rotation",
            "next_step_message": (
                "Review ledger rotation/truncation, then let the next enabled wave "
                "restart the notifier."
            ),
        }
    if reason in {
        "daemon_pid_missing",
        "daemon_pid_invalid",
        "daemon_pid_not_running",
        "notifier_log_missing",
        "notifier_log_no_processed_activity",
        "notifier_log_stale",
        "pending_without_activity_stale",
        "pending_lines_stale",
    }:
        return {
            "next_step": "restart-notifier-daemon",
            "next_step_message": (
                "Run mainspring notify-restart to replace the recorded notifier "
                "daemon, then run mainspring notify-test. Keep "
                "MAINSPRING_NOTIFY_ENABLED=1 for future wave-boundary auto-recovery."
            ),
        }
    return {
        "next_step": "inspect-notifier-health",
        "next_step_message": (
            "Inspect notifier.log and waves.jsonl before trusting notification delivery."
        ),
    }


# ── CLI entry ────────────────────────────────────────────────────────────


def _usage_top(stream=sys.stderr) -> None:
    print(
        "Usage: notify_telegram.py <watch|health|operator-health|send|test> [args]",
        file=stream,
    )


def _usage_watch(stream=sys.stderr) -> None:
    print(
        "Usage: notify_telegram.py watch <ledger-path> [--state-dir <dir>]",
        file=stream,
    )


def _usage_health(stream=sys.stderr) -> None:
    print(
        "Usage: notify_telegram.py health <ledger-path> "
        "[--state-dir <dir>] [--log-file <path>] [--pid-file <path>] "
        "[--stale-seconds <n>] [--format text|json]",
        file=stream,
    )


def _usage_operator_health(stream=sys.stderr) -> None:
    print(
        "Usage: notify_telegram.py operator-health <ledger-path> "
        "[--state-dir <dir>] [--log-file <path>] [--pid-file <path>] "
        "[--stale-seconds <n>] [--format text|json]",
        file=stream,
    )


def _usage_send(stream=sys.stderr) -> None:
    print(
        "Usage: notify_telegram.py send <message> [--parse-mode html|markdown]",
        file=stream,
    )


def _usage_test(stream=sys.stderr) -> None:
    print("Usage: notify_telegram.py test", file=stream)


def _parse_watch_args(args: list[str]) -> tuple[Path, Path]:
    if len(args) < 1:
        _usage_watch()
        raise SystemExit(2)
    if args[0].startswith("-"):
        print("notify: watch requires a ledger path before flags", file=sys.stderr)
        raise SystemExit(2)

    ledger_path = Path(args[0])
    state_dir = None
    i = 1
    while i < len(args):
        if args[i] == "--state-dir" and i + 1 < len(args):
            state_dir = Path(args[i + 1])
            i += 2
        elif args[i] == "--state-dir":
            print("notify: --state-dir requires a value", file=sys.stderr)
            raise SystemExit(2)
        else:
            print(f"notify: unknown watch flag: {args[i]}", file=sys.stderr)
            raise SystemExit(2)

    if state_dir is None:
        state_dir = ledger_path.parent.parent / "state"

    return ledger_path, state_dir


def cmd_watch(args: list[str]) -> None:
    """Watch subcommand."""
    if args and args[0] in {"--help", "-h"}:
        _usage_watch(sys.stdout)
        return

    ledger_path, state_dir = _parse_watch_args(args)
    state = NotifyState(state_dir / "notify-state.json")
    print(f"notify: watching {ledger_path}", file=sys.stderr)
    print(f"notify: state dir {state_dir}", file=sys.stderr)

    try:
        watch_loop(ledger_path, state)
    except KeyboardInterrupt:
        state.save()
        print("\nnotify: stopped", file=sys.stderr)
        raise SystemExit(130) from None


def _parse_health_args(
    args: list[str], ledger_path: Path
) -> tuple[Path, int, str, Path | None, Path | None]:
    state_dir = ledger_path.parent.parent / "state"
    stale_seconds = STALE_DAEMON_SECONDS
    output_format = "text"
    log_path = None
    pid_path = None
    i = 0
    while i < len(args):
        if args[i] == "--state-dir" and i + 1 < len(args):
            state_dir = Path(args[i + 1])
            i += 2
        elif args[i] == "--state-dir":
            print("notify: --state-dir requires a value", file=sys.stderr)
            raise SystemExit(2)
        elif args[i] == "--log-file" and i + 1 < len(args):
            log_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--log-file":
            print("notify: --log-file requires a value", file=sys.stderr)
            raise SystemExit(2)
        elif args[i] == "--pid-file" and i + 1 < len(args):
            pid_path = Path(args[i + 1])
            i += 2
        elif args[i] == "--pid-file":
            print("notify: --pid-file requires a value", file=sys.stderr)
            raise SystemExit(2)
        elif args[i] == "--stale-seconds" and i + 1 < len(args):
            try:
                stale_seconds = int(args[i + 1])
            except ValueError:
                print("notify: --stale-seconds must be an integer", file=sys.stderr)
                raise SystemExit(2) from None
            if stale_seconds < 0:
                print("notify: --stale-seconds must not be negative", file=sys.stderr)
                raise SystemExit(2)
            i += 2
        elif args[i] == "--stale-seconds":
            print("notify: --stale-seconds requires a value", file=sys.stderr)
            raise SystemExit(2)
        elif args[i] == "--format" and i + 1 < len(args):
            output_format = args[i + 1]
            if output_format not in ("text", "json"):
                print("notify: --format must be text or json", file=sys.stderr)
                raise SystemExit(2)
            i += 2
        elif args[i] == "--format":
            print("notify: --format requires a value", file=sys.stderr)
            raise SystemExit(2)
        else:
            print(f"notify: unknown health flag: {args[i]}", file=sys.stderr)
            raise SystemExit(2)
    return state_dir, stale_seconds, output_format, log_path, pid_path


def cmd_health(args: list[str]) -> None:
    """Health subcommand."""
    if args and args[0] in {"--help", "-h"}:
        _usage_health(sys.stdout)
        return

    if len(args) < 1:
        _usage_health()
        raise SystemExit(2)
    if args[0].startswith("-"):
        print("notify: health requires a ledger path before flags", file=sys.stderr)
        raise SystemExit(2)

    ledger_path = Path(args[0])
    state_dir, stale_seconds, output_format, log_path, pid_path = _parse_health_args(
        args[1:], ledger_path
    )
    state = NotifyState(state_dir / "notify-state.json")
    health = check_watch_health(
        ledger_path,
        state,
        stale_seconds=stale_seconds,
        log_path=log_path,
        pid_path=pid_path,
    )

    if output_format == "json":
        print(json.dumps(health, sort_keys=True))
    else:
        print(
            "notify: health "
            f"status={health['status']} "
            f"reason={health['reason']} "
            f"pending={health['pending_lines']} "
            f"ledger_lines={health['ledger_lines']} "
            f"last_line_count={health['last_line_count']} "
            f"next_step={health['next_step']}"
        )

    if health["status"] == "stale":
        raise SystemExit(2)
    raise SystemExit(0)


def cmd_operator_health(args: list[str]) -> None:
    """Operator-facing health subcommand."""
    if args and args[0] in {"--help", "-h"}:
        _usage_operator_health(sys.stdout)
        return

    if len(args) < 1:
        _usage_operator_health()
        raise SystemExit(2)
    if args[0].startswith("-"):
        print(
            "notify: operator-health requires a ledger path before flags",
            file=sys.stderr,
        )
        raise SystemExit(2)

    ledger_path = Path(args[0])
    state_dir, stale_seconds, output_format, log_path, pid_path = _parse_health_args(
        args[1:], ledger_path
    )
    health = operator_health(
        ledger_path,
        state_dir=state_dir,
        stale_seconds=stale_seconds,
        log_path=log_path,
        pid_path=pid_path,
    )

    if output_format == "json":
        print(json.dumps(health, sort_keys=True))
    else:
        print(format_operator_health_text(health))

    if health["status"] in {"stale", "config_error"}:
        raise SystemExit(2)
    if health["status"] == "unconfigured":
        raise SystemExit(1)
    raise SystemExit(0)


def cmd_send(args: list[str]) -> None:
    """Send a single message."""
    if args and args[0] in {"--help", "-h"}:
        _usage_send(sys.stdout)
        return

    if len(args) < 1:
        _usage_send()
        raise SystemExit(2)

    message = args[0]
    parse_mode = None
    extra = args[1:]
    if extra:
        if len(extra) == 2 and extra[0] == "--parse-mode":
            parse_mode = extra[1]
            if parse_mode not in ("html", "markdown"):
                print("notify: --parse-mode must be html or markdown", file=sys.stderr)
                raise SystemExit(2)
        elif len(extra) == 1 and extra[0] == "--parse-mode":
            print("notify: --parse-mode requires a value", file=sys.stderr)
            raise SystemExit(2)
        else:
            print(f"notify: unknown send flag: {extra[0]}", file=sys.stderr)
            raise SystemExit(2)

    result = send_message(message, parse_mode=parse_mode)
    if result is None:
        raise SystemExit(1)
    print("notify: message sent", file=sys.stderr)


def cmd_test(args: list[str] | None = None) -> None:
    """Send a test notification."""
    args = args or []
    if args and args[0] in {"--help", "-h"}:
        _usage_test(sys.stdout)
        return
    if args:
        print(f"notify: unknown test flag: {args[0]}", file=sys.stderr)
        raise SystemExit(2)

    msg = (
        "🧪 Mainspring notification test\n"
        f"Time: {datetime.now(UTC).isoformat().replace('+00:00', 'Z')}\n"
        "If you see this, Telegram notifications are working."
    )
    result = send_message(msg)
    if result is None:
        print("notify: test FAILED — check token and chat_id", file=sys.stderr)
        raise SystemExit(1)
    print("notify: test OK", file=sys.stderr)


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        _usage_top()
        raise SystemExit(2)

    subcmd = args[0]
    if subcmd in {"--help", "-h"}:
        _usage_top(sys.stdout)
    elif subcmd == "watch":
        cmd_watch(args[1:])
    elif subcmd == "health":
        cmd_health(args[1:])
    elif subcmd == "operator-health":
        cmd_operator_health(args[1:])
    elif subcmd == "send":
        cmd_send(args[1:])
    elif subcmd == "test":
        cmd_test(args[1:])
    else:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    run_cli(main)
