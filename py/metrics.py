#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mainspring metrics reader — query waves.jsonl for operational insights.

Usage:
    python3 metrics.py <ledger-path> [--days N] [--since DATE] [--pair X+Y] [--routing] [--format json|text]

Answers the 7 standard questions:
  1. Total waves
  2. Success rate (exit_code==0 && verdict==PASS)
  3. Mean duration
  4. Top 5 stuck tasks (≥3 consecutive FAILs on same task)
  5. Mean chapter_delta per pair (when present)
  6. Top 10 most expensive waves (by duration)
  7. Pass rate per pair
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import median

from cli_runtime import run_cli
from failure_taxonomy import normalise_failure_reason_class

AUTO_DISABLE_WINDOW_DAYS = 14
AUTO_DISABLE_THRESHOLD_RATIO = 0.7
LOW_COST_MODEL_MARKERS = ("mini", "haiku", "spark", "fast", "cheap")


def read_ledger(path: Path) -> list[dict]:
    """Read wave objects, skipping malformed JSON and non-object rows."""
    entries: list[dict] = []
    if not path.is_file():
        return entries
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                entries.append(parsed)
        except Exception:
            continue
    return entries


def _parse_timestamp(entry: dict) -> datetime | None:
    ts = entry.get("timestamp") or entry.get("ts")
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except Exception:
        return None


def _get_pair(entry: dict) -> str:
    pair = str(entry.get("pair") or "").strip()
    if pair:
        return pair
    engines = entry.get("engines") or {}
    w = engines.get("writer") or entry.get("engine") or "?"
    r = engines.get("reviewer") or entry.get("review_engine") or "?"
    return f"{w}+{r}"


def _is_success(entry: dict) -> bool:
    verdict = str(entry.get("verdict") or "").upper()
    exit_code = entry.get("exit_code")
    return verdict == "PASS" and type(exit_code) is int and exit_code == 0


def _parse_float(value: object) -> float | None:
    try:
        return float(str(value).lstrip("+"))
    except (TypeError, ValueError):
        return None


def _duration_s(entry: dict) -> float:
    parsed = _parse_float(entry.get("duration_s") or entry.get("duration_seconds"))
    return parsed if parsed is not None else 0.0


def _wave_cost_usd(entry: dict) -> float | None:
    usage = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
    for value in (
        entry.get("cost_usd"),
        entry.get("total_cost_usd"),
        usage.get("cost_usd") if usage else None,
        usage.get("total_cost_usd") if usage else None,
    ):
        parsed = _parse_float(value)
        if parsed is not None and parsed >= 0:
            return parsed
    return None


def _entry_models(entry: dict) -> list[str]:
    models = entry.get("models")
    if isinstance(models, dict):
        return [str(value).strip() for value in models.values() if str(value).strip()]
    result = []
    for key in ("model", "review_model"):
        value = str(entry.get(key) or "").strip()
        if value:
            result.append(value)
    return result


def _is_auto_disable_eligible(pair: str, models: set[str]) -> bool:
    """Only fast/cheap lanes may be auto-disabled; premium lanes are protected."""
    haystack = " ".join([pair, *sorted(models)]).lower()
    return any(marker in haystack for marker in LOW_COST_MODEL_MARKERS)


def _failure_class(entry: dict) -> str:
    explicit = str(entry.get("failure_reason_class") or "").strip()
    reason = str(entry.get("failure_reason") or "").strip()
    normalised = normalise_failure_reason_class(reason, explicit)
    return normalised or reason or explicit or "unknown"


def _task_class(entry: dict) -> str:
    files = [
        str(item) for item in entry.get("changed_files", []) or [] if str(item).strip()
    ]
    lane = str(entry.get("selected_lane") or "").strip().lower()
    haystack = " ".join(files + [lane]).lower()
    if not haystack:
        return "unknown"
    if "migration" in haystack or "/migrations/" in haystack:
        return "migration"
    if any(part.startswith("tests/") for part in files) or ".test." in haystack:
        return "tests"
    if files and all(
        part.startswith("docs/")
        or part.endswith(".md")
        or part.startswith(".taskmaster/")
        for part in files
    ):
        return "docs"
    if any(part.startswith(("src/", "apps/", "server/", "scripts/")) for part in files):
        return "src"
    return lane or "unknown"


def filter_entries(
    entries: list[dict],
    *,
    days: int | None = None,
    since: str | None = None,
    pair: str | None = None,
) -> list[dict]:
    """Filter entries by time window and/or pair."""
    result = entries

    cutoff: datetime | None = None
    if days is not None:
        cutoff = datetime.now(UTC) - timedelta(days=days)
    elif since is not None:
        try:
            cutoff = datetime.fromisoformat(since).replace(tzinfo=UTC)
        except Exception:
            pass

    if cutoff is not None:
        filtered = []
        for e in result:
            ts = _parse_timestamp(e)
            if ts is not None and ts >= cutoff:
                filtered.append(e)
        result = filtered

    if pair is not None:
        result = [e for e in result if _get_pair(e) == pair]

    return result


def _pair_stats(entries: list[dict]) -> dict[str, dict[str, float]]:
    stats: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {"total": 0, "pass": 0}
    )
    for entry in entries:
        pair = _get_pair(entry)
        stats[pair]["total"] += 1
        if _is_success(entry):
            stats[pair]["pass"] += 1
    return {
        pair: {
            "total": int(values["total"]),
            "pass": int(values["pass"]),
            "pass_rate": round(values["pass"] / values["total"] * 100, 1)
            if values["total"]
            else 0.0,
        }
        for pair, values in sorted(stats.items())
    }


def compute_metrics(entries: list[dict]) -> dict:
    """Compute the 7 standard metrics from a list of wave entries."""
    total = len(entries)
    if total == 0:
        return {
            "total_waves": 0,
            "success_rate": 0.0,
            "mean_duration_s": 0.0,
            "top_stuck_tasks": [],
            "chapter_delta_per_pair": {},
            "top_expensive_waves": [],
            "pass_rate_per_pair": {},
        }

    # 1. Total waves
    # 2. Success rate
    successes = sum(1 for e in entries if _is_success(e))
    success_rate = round(successes / total * 100, 1)

    # 3. Mean duration
    durations = [_duration_s(e) for e in entries]
    mean_duration = round(sum(durations) / total, 1)

    # 4. Top 5 stuck tasks (consecutive FAILs on the same task_id)
    task_consec_fails: Counter[str] = Counter()
    last_task: str = ""
    consec: int = 0
    for e in entries:
        tid = e.get("task_id") or ""
        if not tid:
            last_task = ""
            consec = 0
            continue
        if tid == last_task and not _is_success(e):
            consec += 1
        elif not _is_success(e):
            consec = 1
        else:
            consec = 0
        last_task = tid
        if consec >= 3:
            task_consec_fails[tid] = max(task_consec_fails[tid], consec)

    top_stuck = [
        {"task_id": tid, "consecutive_fails": c}
        for tid, c in task_consec_fails.most_common(5)
    ]

    # 5. Mean chapter_delta per pair (when field is present)
    pair_deltas: defaultdict[str, list[float]] = defaultdict(list)
    for e in entries:
        cd = e.get("chapter_delta")
        if cd is None:
            continue
        try:
            val = float(str(cd).lstrip("+"))
        except (TypeError, ValueError):
            continue
        pair_deltas[_get_pair(e)].append(val)

    chapter_delta_per_pair = {
        p: round(sum(vs) / len(vs), 1) for p, vs in pair_deltas.items()
    }

    # 6. Top 10 most expensive waves (by duration)
    sorted_by_dur = sorted(entries, key=_duration_s, reverse=True)
    top_expensive = [
        {
            "wave_id": e.get("wave_id") or "?",
            "task_id": e.get("task_id") or "",
            "pair": _get_pair(e),
            "duration_s": _duration_s(e),
            "verdict": e.get("verdict") or "",
        }
        for e in sorted_by_dur[:10]
    ]

    # 7. Pass rate per pair
    pass_rate_per_pair = {
        pair: values["pass_rate"] for pair, values in _pair_stats(entries).items()
    }

    return {
        "total_waves": total,
        "success_rate": success_rate,
        "mean_duration_s": mean_duration,
        "top_stuck_tasks": top_stuck,
        "chapter_delta_per_pair": chapter_delta_per_pair,
        "top_expensive_waves": top_expensive,
        "pass_rate_per_pair": pass_rate_per_pair,
    }


def compute_routing_metrics(entries: list[dict]) -> dict:
    """Compute routing-focused metrics from a list of wave entries."""
    topology_stats: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {"total": 0, "pass": 0}
    )
    duration_by_class: defaultdict[str, list[float]] = defaultdict(list)
    failure_clusters: defaultdict[str, dict[str, object]] = defaultdict(
        lambda: {"count": 0, "task_ids": set()}
    )
    cost_delta_by_pair: defaultdict[str, dict[str, float]] = defaultdict(
        lambda: {"cost": 0.0, "delta": 0.0, "waves": 0}
    )
    value_by_pair: defaultdict[str, dict[str, object]] = defaultdict(
        lambda: {"cost": 0.0, "delta": 0.0, "waves": 0, "models": set()}
    )

    for entry in entries:
        topology = str(entry.get("topology") or "unknown")
        topology_stats[topology]["total"] += 1
        if _is_success(entry):
            topology_stats[topology]["pass"] += 1

        duration = _duration_s(entry)
        if duration is not None:
            duration_by_class[_task_class(entry)].append(duration)

        if not _is_success(entry):
            failure_class = _failure_class(entry)
            failure_clusters[failure_class]["count"] = (
                int(failure_clusters[failure_class]["count"]) + 1
            )
            task_id = str(entry.get("task_id") or "").strip()
            if task_id:
                task_ids = failure_clusters[failure_class]["task_ids"]
                assert isinstance(task_ids, set)
                task_ids.add(task_id)

        cost = _wave_cost_usd(entry)
        chapter_delta = _parse_float(entry.get("chapter_delta"))
        if cost is not None and chapter_delta is not None and chapter_delta > 0:
            pair = _get_pair(entry)
            cost_delta_by_pair[pair]["cost"] += cost
            cost_delta_by_pair[pair]["delta"] += chapter_delta
            cost_delta_by_pair[pair]["waves"] += 1
        if cost is not None and cost > 0:
            pair = _get_pair(entry)
            value_by_pair[pair]["cost"] = float(value_by_pair[pair]["cost"]) + cost
            value_by_pair[pair]["delta"] = float(value_by_pair[pair]["delta"]) + max(
                0.0, chapter_delta or 0.0
            )
            value_by_pair[pair]["waves"] = int(value_by_pair[pair]["waves"]) + 1
            models = value_by_pair[pair]["models"]
            assert isinstance(models, set)
            models.update(_entry_models(entry))

    pass_rate_by_topology = {
        topology: {
            "total": int(values["total"]),
            "pass": int(values["pass"]),
            "pass_rate": round(values["pass"] / values["total"] * 100, 1)
            if values["total"]
            else 0.0,
        }
        for topology, values in sorted(topology_stats.items())
    }

    mean_duration_by_task_class = {
        task_class: round(sum(values) / len(values), 1)
        for task_class, values in sorted(duration_by_class.items())
        if values
    }

    repeat_failure_clusters = [
        {
            "failure_reason_class": failure_class,
            "count": int(values["count"]),
            "task_ids": sorted(values["task_ids"]),  # type: ignore[arg-type]
        }
        for failure_class, values in failure_clusters.items()
        if int(values["count"]) >= 2
    ]
    repeat_failure_clusters.sort(
        key=lambda item: (-item["count"], item["failure_reason_class"])
    )

    cost_per_chapter_delta_per_pair = {
        pair: {
            "waves": int(values["waves"]),
            "cost_usd": round(values["cost"], 4),
            "chapter_delta": round(values["delta"], 2),
            "cost_per_chapter_delta": round(values["cost"] / values["delta"], 4),
        }
        for pair, values in sorted(cost_delta_by_pair.items())
        if values["delta"] > 0
    }
    chapter_delta_per_dollar_14d = _format_value_metrics(value_by_pair)
    auto_disable = compute_auto_disable_recommendation(chapter_delta_per_dollar_14d)

    return {
        "pass_rate_by_pair": _pair_stats(entries),
        "pass_rate_by_topology": pass_rate_by_topology,
        "mean_duration_by_task_class": mean_duration_by_task_class,
        "repeat_failure_clusters": repeat_failure_clusters,
        "cost_per_chapter_delta_per_pair": cost_per_chapter_delta_per_pair,
        "chapter_delta_per_dollar_14d": chapter_delta_per_dollar_14d,
        "auto_disable": auto_disable,
    }


def _format_value_metrics(value_by_pair: dict[str, dict[str, object]]) -> dict:
    result = {}
    for pair, values in sorted(value_by_pair.items()):
        cost = float(values["cost"])
        delta = float(values["delta"])
        models = values["models"]
        assert isinstance(models, set)
        result[pair] = {
            "waves": int(values["waves"]),
            "cost_usd": round(cost, 4),
            "positive_chapter_delta": round(delta, 2),
            "chapter_delta_per_dollar": round(delta / cost, 4) if cost > 0 else 0.0,
            "auto_disable_eligible": _is_auto_disable_eligible(pair, models),
            "models": sorted(models),
        }
    return result


def compute_auto_disable_recommendation(value_metrics: dict) -> dict:
    active_values = [
        float(values["chapter_delta_per_dollar"])
        for values in value_metrics.values()
        if float(values.get("cost_usd", 0.0)) > 0
    ]
    if not active_values:
        return {
            "window_days": AUTO_DISABLE_WINDOW_DAYS,
            "threshold_ratio": AUTO_DISABLE_THRESHOLD_RATIO,
            "median_chapter_delta_per_dollar": 0.0,
            "threshold_chapter_delta_per_dollar": 0.0,
            "pairs": [],
        }

    median_value = float(median(active_values))
    threshold = median_value * AUTO_DISABLE_THRESHOLD_RATIO
    pairs = []
    if median_value > 0:
        for pair, values in sorted(value_metrics.items()):
            value = float(values["chapter_delta_per_dollar"])
            eligible = bool(values["auto_disable_eligible"])
            if eligible and value < threshold:
                pairs.append(
                    {
                        "pair": pair,
                        "chapter_delta_per_dollar": round(value, 4),
                        "median_chapter_delta_per_dollar": round(median_value, 4),
                        "threshold_chapter_delta_per_dollar": round(threshold, 4),
                        "waves": int(values["waves"]),
                        "cost_usd": values["cost_usd"],
                        "positive_chapter_delta": values["positive_chapter_delta"],
                        "reason": "chapter_delta_per_dollar_14d_more_than_30pct_below_median",
                    }
                )
    return {
        "window_days": AUTO_DISABLE_WINDOW_DAYS,
        "threshold_ratio": AUTO_DISABLE_THRESHOLD_RATIO,
        "median_chapter_delta_per_dollar": round(median_value, 4),
        "threshold_chapter_delta_per_dollar": round(threshold, 4),
        "pairs": pairs,
    }


def _state_file_from_arg(path: Path) -> Path:
    return path if path.name == "disabled-pairs.json" else path / "disabled-pairs.json"


def read_disabled_pairs_state(path: Path) -> dict:
    try:
        data = json.loads(_state_file_from_arg(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {"disabled_pairs": data}


def load_disabled_pairs(path: Path) -> list[str]:
    data = read_disabled_pairs_state(path)
    pairs: list[str] = []
    if isinstance(data.get("disabled_pairs"), list):
        pairs.extend(str(item).strip() for item in data["disabled_pairs"])
    elif isinstance(data.get("pairs"), list):
        pairs.extend(str(item).strip() for item in data["pairs"])
    elif isinstance(data.get("pairs"), dict):
        for pair, payload in data["pairs"].items():
            if isinstance(payload, dict) and payload.get("status") == "auto_disabled":
                pairs.append(str(pair).strip())
    return sorted({pair for pair in pairs if pair})


def _manual_pair_list(data: dict, *keys: str) -> set[str]:
    pairs: set[str] = set()
    wants_reactivated = bool(
        {"manual_reactivated_pairs", "reactivated_pairs"} & set(keys)
    )
    wants_manual_disabled = "manual_disabled_pairs" in keys
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            pairs.update(str(item).strip() for item in value if str(item).strip())
    details = data.get("pairs")
    if isinstance(details, dict):
        for pair, payload in details.items():
            if not isinstance(payload, dict):
                continue
            status = str(payload.get("status") or "")
            if wants_reactivated and status == "manual_reactivated":
                pairs.add(str(pair).strip())
            if wants_manual_disabled and status == "manual_disabled":
                pairs.add(str(pair).strip())
    return pairs


def update_disabled_pairs_state(
    state_dir: Path,
    value_metrics: dict,
    auto_disable: dict,
    *,
    now: datetime | None = None,
) -> dict:
    state_file = _state_file_from_arg(state_dir)
    existing = read_disabled_pairs_state(state_file)
    reactivated = _manual_pair_list(
        existing, "manual_reactivated_pairs", "reactivated_pairs"
    )
    manual_disabled = _manual_pair_list(existing, "manual_disabled_pairs")
    previous_disabled = set(load_disabled_pairs(state_file))
    previous_auto_disabled = previous_disabled - manual_disabled - reactivated
    new_auto_disabled = {
        str(item["pair"])
        for item in auto_disable.get("pairs", [])
        if str(item.get("pair") or "").strip() and str(item["pair"]) not in reactivated
    }
    disabled_pairs = sorted(
        (previous_auto_disabled | new_auto_disabled | manual_disabled) - reactivated
    )

    timestamp = (now or datetime.now(UTC)).isoformat().replace("+00:00", "Z")
    pair_details = {}
    recommendation_by_pair = {
        str(item["pair"]): item for item in auto_disable.get("pairs", [])
    }
    for pair in sorted(set(value_metrics) | set(disabled_pairs) | reactivated):
        metric = value_metrics.get(pair, {})
        detail = {
            "status": "active",
            "updated_at": timestamp,
            "chapter_delta_per_dollar_14d": metric.get("chapter_delta_per_dollar"),
            "median_chapter_delta_per_dollar_14d": auto_disable.get(
                "median_chapter_delta_per_dollar"
            ),
            "cost_usd": metric.get("cost_usd"),
            "positive_chapter_delta": metric.get("positive_chapter_delta"),
            "waves": metric.get("waves", 0),
            "auto_disable_eligible": metric.get("auto_disable_eligible", False),
            "models": metric.get("models", []),
        }
        if pair in manual_disabled:
            detail["status"] = "manual_disabled"
            detail["reason"] = "manual_disabled"
        elif pair in reactivated:
            detail["status"] = "manual_reactivated"
            detail["reason"] = "manual_reactivated"
        elif pair in disabled_pairs:
            detail["status"] = "auto_disabled"
            detail["reason"] = recommendation_by_pair.get(pair, {}).get(
                "reason", "previously_auto_disabled_until_manual_reactivation"
            )
        pair_details[pair] = detail

    state = {
        "schema_version": 1,
        "updated_at": timestamp,
        "window_days": AUTO_DISABLE_WINDOW_DAYS,
        "threshold_ratio": AUTO_DISABLE_THRESHOLD_RATIO,
        "disabled_pairs": disabled_pairs,
        "manual_disabled_pairs": sorted(manual_disabled),
        "manual_reactivated_pairs": sorted(reactivated),
        "median_chapter_delta_per_dollar_14d": auto_disable.get(
            "median_chapter_delta_per_dollar", 0.0
        ),
        "threshold_chapter_delta_per_dollar_14d": auto_disable.get(
            "threshold_chapter_delta_per_dollar", 0.0
        ),
        "pairs": pair_details,
    }
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return state


def format_text(metrics: dict) -> str:
    """Format metrics as human-readable text."""
    lines = []
    lines.append(f"Total waves:    {metrics['total_waves']}")
    lines.append(f"Success rate:   {metrics['success_rate']}%")
    lines.append(f"Mean duration:  {metrics['mean_duration_s']}s")
    if metrics["total_waves"] == 0:
        lines.append("")
        lines.append("No wave data in the selected window.")
        lines.append(
            "Run Mainspring first, or widen the window with --days or --since."
        )

    lines.append("")
    lines.append("Pass rate per pair:")
    if metrics["pass_rate_per_pair"]:
        for pair, rate in metrics["pass_rate_per_pair"].items():
            lines.append(f"  {pair}: {rate}%")
    else:
        lines.append("  none yet")

    if metrics["top_stuck_tasks"]:
        lines.append("")
        lines.append("Top stuck tasks (≥3 consecutive fails):")
        for t in metrics["top_stuck_tasks"]:
            lines.append(
                f"  task {t['task_id']}: {t['consecutive_fails']} consecutive fails"
            )

    if metrics["chapter_delta_per_pair"]:
        lines.append("")
        lines.append("Mean chapter delta per pair:")
        for pair, delta in metrics["chapter_delta_per_pair"].items():
            lines.append(f"  {pair}: {delta:+.1f}")

    if metrics["top_expensive_waves"]:
        lines.append("")
        lines.append("Top 10 most expensive waves:")
        for w in metrics["top_expensive_waves"]:
            lines.append(
                f"  {w['wave_id']} task={w['task_id'] or 'none'} "
                f"pair={w['pair']} {w['duration_s']}s "
                f"verdict={w['verdict'] or 'unknown'}"
            )

    return "\n".join(lines)


def format_routing_text(metrics: dict) -> str:
    """Format routing metrics as human-readable text."""
    lines = ["Routing metrics"]
    has_any_routing_data = any(
        (
            metrics["pass_rate_by_pair"],
            metrics["pass_rate_by_topology"],
            metrics["mean_duration_by_task_class"],
            metrics["repeat_failure_clusters"],
            metrics["cost_per_chapter_delta_per_pair"],
            metrics["chapter_delta_per_dollar_14d"],
            metrics["auto_disable"]["pairs"],
        )
    )
    if not has_any_routing_data:
        lines.append("")
        lines.append("No routing data in the selected window.")
        lines.append(
            "Run Mainspring first, or widen the window with --days or --since."
        )
        return "\n".join(lines)

    lines.append("")
    lines.append("Pass rate by pair:")
    if metrics["pass_rate_by_pair"]:
        for pair, values in metrics["pass_rate_by_pair"].items():
            lines.append(
                f"  {pair}: {values['pass_rate']}% ({values['pass']}/{values['total']})"
            )
    else:
        lines.append("  none yet")

    lines.append("")
    lines.append("Pass rate by topology:")
    if metrics["pass_rate_by_topology"]:
        for topology, values in metrics["pass_rate_by_topology"].items():
            lines.append(
                f"  {topology}: {values['pass_rate']}% ({values['pass']}/{values['total']})"
            )
    else:
        lines.append("  none yet")

    if metrics["mean_duration_by_task_class"]:
        lines.append("")
        lines.append("Mean duration by task class:")
        for task_class, duration in metrics["mean_duration_by_task_class"].items():
            lines.append(f"  {task_class}: {duration}s")

    if metrics["repeat_failure_clusters"]:
        lines.append("")
        lines.append("Repeat failure clusters:")
        for cluster in metrics["repeat_failure_clusters"]:
            task_ids = ",".join(cluster["task_ids"]) or "none"
            lines.append(
                f"  {cluster['failure_reason_class']}: "
                f"{cluster['count']} waves tasks={task_ids}"
            )

    if metrics["cost_per_chapter_delta_per_pair"]:
        lines.append("")
        lines.append("Cost per chapter delta by pair:")
        for pair, values in metrics["cost_per_chapter_delta_per_pair"].items():
            lines.append(
                f"  {pair}: ${values['cost_per_chapter_delta']:.4f}/pt "
                f"({values['waves']} waves)"
            )
    if metrics["chapter_delta_per_dollar_14d"]:
        lines.append("")
        lines.append("Chapter delta per dollar (14d):")
        for pair, values in metrics["chapter_delta_per_dollar_14d"].items():
            marker = " eligible" if values["auto_disable_eligible"] else " protected"
            lines.append(
                f"  {pair}: {values['chapter_delta_per_dollar']:.4f}/$"
                f" ({values['waves']} waves,{marker})"
            )
    if metrics["auto_disable"]["pairs"]:
        lines.append("")
        lines.append("Auto-disabled pair candidates:")
        for item in metrics["auto_disable"]["pairs"]:
            lines.append(
                f"  {item['pair']}: {item['chapter_delta_per_dollar']:.4f}/$ "
                f"< {item['threshold_chapter_delta_per_dollar']:.4f}/$"
            )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print(
            "Usage: metrics.py <ledger-path> [--days N] [--since DATE] [--pair X+Y] [--routing] [--format json|text] [--update-disabled-pairs] [--state-dir DIR]",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if args[0] == "disabled-pairs":
        if len(args) < 2:
            print(
                "Usage: metrics.py disabled-pairs <state-dir-or-file>",
                file=sys.stderr,
            )
            raise SystemExit(2)
        for pair_name in load_disabled_pairs(Path(args[1])):
            print(pair_name)
        return

    ledger_path = args[0]
    days: int | None = None
    since: str | None = None
    pair: str | None = None
    fmt: str = "text"
    routing = False
    update_disabled_pairs = False
    state_dir: Path | None = None

    i = 1
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i] == "--since" and i + 1 < len(args):
            since = args[i + 1]
            i += 2
        elif args[i] == "--pair" and i + 1 < len(args):
            pair = args[i + 1]
            i += 2
        elif args[i] == "--routing":
            routing = True
            i += 1
        elif args[i] == "--format" and i + 1 < len(args):
            fmt = args[i + 1]
            i += 2
        elif args[i] == "--update-disabled-pairs":
            update_disabled_pairs = True
            i += 1
        elif args[i] == "--state-dir" and i + 1 < len(args):
            state_dir = Path(args[i + 1])
            i += 2
        else:
            print(f"Unknown flag: {args[i]}", file=sys.stderr)
            raise SystemExit(2)

    entries = read_ledger(Path(ledger_path))

    # Default to 7 days if no time filter specified
    if days is None and since is None:
        days = AUTO_DISABLE_WINDOW_DAYS if routing else 7

    filtered = filter_entries(entries, days=days, since=since, pair=pair)
    metrics = (
        compute_routing_metrics(filtered) if routing else compute_metrics(filtered)
    )
    if routing and update_disabled_pairs:
        if state_dir is None:
            state_dir = Path(ledger_path).parent.parent / "state"
        metrics["disabled_pairs_state"] = update_disabled_pairs_state(
            state_dir,
            metrics["chapter_delta_per_dollar_14d"],
            metrics["auto_disable"],
        )

    if fmt == "json":
        print(json.dumps(metrics, indent=2, ensure_ascii=False))
    else:
        print(format_routing_text(metrics) if routing else format_text(metrics))


if __name__ == "__main__":
    run_cli(main)
