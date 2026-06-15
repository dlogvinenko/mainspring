#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mainspring wave replay — deterministic re-execution of recorded waves.

Subcommands:
    show <wave-id>                     Display full wave metadata.
    diff <wave-id-1> <wave-id-2>       Compare two wave entries side-by-side.
    build <wave-id> [overrides]        Reconstruct the mainspring CLI command.
    run <wave-id> [overrides]          Re-execute the wave (--dry-run to preview).

Overrides (apply to ``build`` and ``run``):
    --engine <name>          Swap writer engine
    --reviewer <name>        Swap reviewer engine
    --model <id>             Override writer model
    --review-model <id>      Override reviewer model
    --save-as <id>           Record the replayed wave under a new wave-id
    --allow-live-reconstruction
                             Permit non-deterministic reconstruction when a
                             historical row lacks a prompt snapshot

Usage:
    mainspring replay show <wave-id> <ledger-path>
    mainspring replay diff <id1> <id2> <ledger-path>
    mainspring replay build <wave-id> <ledger-path> [--engine X] [--reviewer Y] ...
    mainspring replay run <wave-id> <ledger-path> [--dry-run] [--save-as <id>] ...

Unique to Mainspring — no other autonomous-loop tool offers wave-level replay.
"""

from __future__ import annotations

from cli_runtime import run_cli

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# Ledger reader


def read_ledger(path: Path) -> list[dict]:
    """Parse all valid JSONL entries from *path*."""
    entries: list[dict] = []
    if not path.is_file():
        return entries
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            entries.append(json.loads(raw))
        except Exception:
            continue
    return entries


def _has_value(value: object) -> bool:
    return value is not None and str(value) != ""


def _first_value(entry: dict, *keys: str) -> object:
    for key in keys:
        if key in entry and _has_value(entry[key]):
            return entry[key]
    return ""


def get_wave_identifier(entry: dict) -> str:
    """Return the stable replay-visible wave id from canonical or legacy fields."""
    return str(_first_value(entry, "wave_id", "wave") or "unknown")


def get_timestamp(entry: dict) -> str:
    """Return the wave timestamp from canonical or legacy fields."""
    return str(_first_value(entry, "timestamp", "ts") or "unknown")


def get_duration_seconds(entry: dict) -> str:
    """Return the wave duration from canonical or legacy fields."""
    return str(_first_value(entry, "duration_seconds", "duration_s") or 0)


def get_exit_code_value(entry: dict) -> str:
    """Return the exit code exactly enough for display, across schema versions."""
    return str(_first_value(entry, "exit_code") or 0)


def parse_exit_code(value: object) -> int | None:
    """Normalize string/numeric exit-code values used by historical ledgers."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_wave(entries: list[dict], wave_id: str) -> dict | None:
    """Find a wave entry by its wave_id or canonical wave field."""
    for entry in entries:
        if get_wave_identifier(entry) == wave_id:
            return entry
    return None


def find_wave_by_index(entries: list[dict], index: int) -> dict | None:
    """Find a wave entry by its 0-based index in the ledger."""
    if 0 <= index < len(entries):
        return entries[index]
    return None


def resolve_wave(entries: list[dict], ref: str) -> dict | None:
    """Resolve a wave reference — either a wave_id string or a #N index.

    Supports:
        ``abc123``   → lookup by wave_id field
        ``#0``       → first wave in the ledger
        ``#-1``      -> last wave in the ledger
        ``last``     → alias for #-1
    """
    if ref == "last":
        return find_wave_by_index(entries, len(entries) - 1)
    if ref.startswith("#"):
        try:
            idx = int(ref[1:])
            if idx < 0:
                idx = len(entries) + idx
            return find_wave_by_index(entries, idx)
        except ValueError:
            return None
    return find_wave(entries, ref)


# ── wave metadata extraction ──────────────────────────────────────────


def get_engine(entry: dict) -> str:
    """Extract writer engine from a wave entry."""
    engines = entry.get("engines") or {}
    pair = str(entry.get("pair") or "")
    pair_writer = pair.split("+", 1)[0] if "+" in pair else ""
    return engines.get("writer") or entry.get("engine") or pair_writer


def get_reviewer(entry: dict) -> str:
    """Extract reviewer engine from a wave entry."""
    engines = entry.get("engines") or {}
    pair = str(entry.get("pair") or "")
    pair_reviewer = pair.split("+", 1)[1] if "+" in pair else ""
    return engines.get("reviewer") or entry.get("review_engine") or pair_reviewer


def get_pair(entry: dict) -> str:
    """Build the pair string ``writer+reviewer``."""
    writer = get_engine(entry)
    reviewer = get_reviewer(entry)
    if writer and reviewer:
        return f"{writer}+{reviewer}"
    return str(entry.get("pair") or "")


def get_model(entry: dict) -> str:
    """Extract writer model from a wave entry."""
    models = entry.get("models") or {}
    return models.get("writer") or entry.get("model") or "default"


def get_review_model(entry: dict) -> str:
    """Extract reviewer model from a wave entry."""
    models = entry.get("models") or {}
    return models.get("reviewer") or entry.get("review_model") or "default"


def is_success(entry: dict) -> bool:
    """Check if a wave entry represents a successful wave."""
    verdict = str(entry.get("verdict") or "").upper()
    exit_code = parse_exit_code(entry.get("exit_code", 0))
    return verdict == "PASS" and exit_code == 0


REPLAY_ACCEPTANCE_FIELDS = (
    ("chapter_delta", "Chapter delta"),
    ("competitor_delta", "Competitor delta"),
    ("launch_delta", "Launch delta"),
    ("product_score", "Product score"),
)


def _field_value(entry: dict, key: str) -> str:
    value = entry.get(key)
    if value is None:
        return ""
    return str(value)


def _missing_label(value: str) -> str:
    return value if value else "missing"


def _success_state(entry: dict) -> str:
    state = "PASS" if is_success(entry) else "FAIL"
    return f"{state} exit {get_exit_code_value(entry)}"


def get_prompt_path(entry: dict) -> str:
    """Extract the recorded writer-prompt snapshot path, if any."""
    return str(entry.get("prompt_path") or "")


def get_prd_path(entry: dict) -> str:
    """Extract the PRD path used for a night-mode wave, if any."""
    return str(entry.get("prd_path") or "")


def get_git_head(entry: dict) -> str:
    """Extract the git HEAD recorded before the writer ran, if any."""
    return str(entry.get("git_head") or "")


def has_git_status_before(entry: dict) -> bool:
    """Return whether the row recorded a pre-wave git status snapshot."""
    return "git_status_before" in entry


def get_git_status_before(entry: dict) -> str:
    """Extract the pre-wave git status snapshot, preserving clean as empty."""
    return str(entry.get("git_status_before") or "")


def get_prompt_sha256(entry: dict) -> str:
    """Extract the recorded prompt snapshot sha256, if any."""
    return str(entry.get("prompt_sha256") or "")


def replayability_summary(entry: dict) -> str:
    """Return operator-facing replayability from recorded metadata."""
    if get_prompt_path(entry):
        return "deterministic prompt snapshot"

    anchor = live_reconstruction_anchor(entry)
    if anchor:
        return f"live reconstruction only ({anchor})"

    return "not replayable (missing prompt snapshot and live anchor)"


def get_replay_target_id(entry: dict) -> str:
    """Return the recorded Taskmaster work target, if one exists."""
    return str(entry.get("work_id") or entry.get("task_id") or "").strip()


def live_reconstruction_anchor(entry: dict) -> str:
    """Return the current-state anchor for an explicit live reconstruction."""
    mode = str(entry.get("mode") or "").strip()
    target_id = get_replay_target_id(entry)
    if mode == "taskmaster" and target_id:
        return f"Taskmaster work item #{target_id}"
    prd_path = get_prd_path(entry)
    if mode == "night" and prd_path:
        return f"PRD {prd_path}"
    if target_id:
        return f"recorded work item #{target_id}"
    if prd_path:
        return f"PRD {prd_path}"
    return ""


def resolve_snapshot_path(path_value: str, root: Path | None = None) -> Path:
    """Resolve a recorded snapshot path relative to *root* when needed."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (root or Path.cwd()) / path


# Overrides


@dataclass
class ReplayOverrides:
    """Overrides for a replayed wave."""

    engine: str | None = None
    reviewer: str | None = None
    model: str | None = None
    review_model: str | None = None
    save_as: str | None = None
    dry_run: bool = False
    allow_worktree_drift: bool = False
    allow_live_reconstruction: bool = False


class ReplayArgumentError(ValueError):
    """Raised when replay override flags are malformed."""


def validate_replay_overrides(
    entry: dict,
    overrides: ReplayOverrides,
    entries: list[dict] | None = None,
) -> list[str]:
    """Return replay override validation errors that would corrupt provenance."""
    errors: list[str] = []
    if overrides.save_as is None:
        return errors

    save_as = overrides.save_as
    stripped = save_as.strip()
    if not stripped:
        errors.append("--save-as requires a non-empty wave id")
    elif stripped != save_as:
        errors.append("--save-as wave id must not have leading or trailing whitespace")
    elif stripped == "last" or stripped.startswith("#"):
        errors.append("--save-as wave id must not be a replay reference alias")

    existing_ids = {
        get_wave_identifier(candidate)
        for candidate in ([entry] if entries is None else entries)
    }
    if stripped and stripped in existing_ids:
        errors.append(f"--save-as wave id already exists in ledger: {stripped}")

    return errors


def apply_overrides(entry: dict, overrides: ReplayOverrides) -> dict:
    """Apply replay overrides to a wave entry, returning a new dict."""
    result = json.loads(json.dumps(entry))  # deep copy

    if overrides.engine is not None:
        engines = result.setdefault("engines", {})
        engines["writer"] = overrides.engine
    if overrides.reviewer is not None:
        engines = result.setdefault("engines", {})
        engines["reviewer"] = overrides.reviewer
    if overrides.model is not None:
        models = result.setdefault("models", {})
        models["writer"] = overrides.model
    if overrides.review_model is not None:
        models = result.setdefault("models", {})
        models["reviewer"] = overrides.review_model

    return result


# Show


def format_wave_detail(entry: dict) -> str:
    """Format a wave entry as a human-readable detail view."""
    lines = []
    lines.append(f"Wave ID:        {get_wave_identifier(entry)}")
    lines.append(f"Timestamp:      {get_timestamp(entry)}")
    lines.append(f"Mode:           {entry.get('mode', 'unknown')}")
    lines.append(f"Topology:       {entry.get('topology', 'unknown')}")
    lines.append(f"Team:           {entry.get('team', '') or 'none'}")
    lines.append(f"Task ID:        {entry.get('task_id', '') or 'none'}")
    lines.append(f"Work ID:        {entry.get('work_id', '') or 'none'}")
    lines.append(f"Lane:           {entry.get('selected_lane', '') or 'unknown'}")
    lines.append(f"Pair:           {get_pair(entry)}")
    lines.append(f"Writer model:   {get_model(entry)}")
    lines.append(f"Reviewer model: {get_review_model(entry)}")
    lines.append(f"Duration:       {get_duration_seconds(entry)}s")
    lines.append(f"Exit code:      {get_exit_code_value(entry)}")
    lines.append(f"Verdict:        {entry.get('verdict', '') or 'unknown'}")
    lines.append(f"Success:        {is_success(entry)}")
    for key, label in REPLAY_ACCEPTANCE_FIELDS:
        value = _field_value(entry, key)
        if value:
            lines.append(f"{label + ':':<16}{value}")
    if entry.get("replayed_from"):
        lines.append(f"Replayed from:  {entry.get('replayed_from')}")

    prompt_path = get_prompt_path(entry)
    if prompt_path:
        lines.append(f"Prompt path:    {prompt_path}")
    prompt_sha = get_prompt_sha256(entry)
    if prompt_sha:
        lines.append(f"Prompt sha256:  {prompt_sha}")
    git_head = get_git_head(entry)
    if git_head:
        lines.append(f"Git head:       {git_head}")
    if has_git_status_before(entry):
        lines.append(
            f"Git status:     {summarize_git_status(get_git_status_before(entry))}"
        )
    prd_path = get_prd_path(entry)
    if prd_path:
        lines.append(f"PRD path:       {prd_path}")
    lines.append(f"Replayability:  {replayability_summary(entry)}")

    failure = entry.get("failure_reason", "")
    if failure:
        lines.append(f"Failure reason: {failure}")
    blocked = entry.get("blocked_reason", "")
    if blocked:
        lines.append(f"Blocked reason: {blocked}")
    next_action = entry.get("next_action", "")
    if next_action:
        lines.append(f"Next action:    {next_action}")

    changed = entry.get("changed_files") or []
    if changed:
        lines.append(f"Changed files:  {len(changed)}")
        for f in changed[:20]:
            lines.append(f"  {f}")
        if len(changed) > 20:
            lines.append(f"  ... and {len(changed) - 20} more")

    # Show any additional fields not already displayed
    known_keys = {
        "wave_id",
        "wave",
        "timestamp",
        "ts",
        "mode",
        "topology",
        "team",
        "task_id",
        "work_id",
        "selected_lane",
        "engines",
        "models",
        "pair",
        "model",
        "review_model",
        "duration_seconds",
        "duration_s",
        "exit_code",
        "verdict",
        "failure_reason",
        "blocked_reason",
        "next_action",
        "changed_files",
        "chapter_delta",
        "competitor_delta",
        "launch_delta",
        "product_score",
        "tests",
        "retry_count",
        "replayed_from",
        "replay_overrides",
        "prompt_path",
        "prompt_sha256",
        "git_head",
        "git_status_before",
        "prd_path",
    }
    extras = {k: v for k, v in entry.items() if k not in known_keys and v}
    if extras:
        lines.append("")
        lines.append("Additional fields:")
        for k, v in extras.items():
            lines.append(f"  {k}: {v}")

    return "\n".join(lines)


# Diff


def has_replay_acceptance_context(a: dict, b: dict) -> bool:
    """Return whether a diff can show replay acceptance evidence."""
    wave_a = get_wave_identifier(a)
    wave_b = get_wave_identifier(b)
    return (
        bool(wave_a != "unknown" and b.get("replayed_from") == wave_a)
        or bool(wave_b != "unknown" and a.get("replayed_from") == wave_b)
        or any(
            _field_value(a, key) or _field_value(b, key)
            for key, _ in REPLAY_ACCEPTANCE_FIELDS
        )
    )


def format_replay_acceptance_summary(original: dict, replayed: dict) -> str:
    """Summarize whether a replay preserved acceptance-critical outcomes."""
    lines = ["Replay acceptance:"]
    recorded_fields = 0
    mismatches = 0

    for key, label in REPLAY_ACCEPTANCE_FIELDS:
        original_value = _field_value(original, key)
        replayed_value = _field_value(replayed, key)
        if not original_value and not replayed_value:
            continue
        recorded_fields += 1
        if original_value == replayed_value:
            status = "PASS"
        else:
            status = "MISMATCH"
            mismatches += 1
        lines.append(
            f"  {label} parity: {status} "
            f"({_missing_label(original_value)} vs {_missing_label(replayed_value)})"
        )

    if recorded_fields == 0:
        lines.append("  Delta/score parity: not recorded")

    original_verdict = str(original.get("verdict") or "unknown").upper()
    replayed_verdict = str(replayed.get("verdict") or "unknown").upper()
    verdict_mismatch = 0
    if original_verdict == replayed_verdict:
        lines.append(f"  Verdict drift: none ({original_verdict})")
    else:
        verdict_mismatch = 1
        lines.append(
            f"  Verdict drift: detected ({original_verdict} -> {replayed_verdict})"
        )

    success_mismatch = 0
    if is_success(original) == is_success(replayed):
        lines.append(f"  Success drift: none ({_success_state(original)})")
    else:
        success_mismatch = 1
        lines.append(
            "  Success drift: detected "
            f"({_success_state(original)} -> {_success_state(replayed)})"
        )

    exit_code_mismatch = 0
    original_exit_code = get_exit_code_value(original)
    replayed_exit_code = get_exit_code_value(replayed)
    if original_exit_code == replayed_exit_code:
        lines.append(f"  Exit-code drift: none ({original_exit_code})")
    else:
        exit_code_mismatch = 1
        lines.append(
            f"  Exit-code drift: detected ({original_exit_code} -> {replayed_exit_code})"
        )

    original_reviewer = get_reviewer(original) or "unknown"
    replayed_reviewer = get_reviewer(replayed) or "unknown"
    if original_reviewer != replayed_reviewer:
        lines.append(f"  Reviewer changed: {original_reviewer} -> {replayed_reviewer}")

    if (
        recorded_fields > 0
        and mismatches == 0
        and verdict_mismatch == 0
        and success_mismatch == 0
        and exit_code_mismatch == 0
    ):
        lines.append("  Determinism proof: PASS")
    elif recorded_fields > 0:
        lines.append("  Determinism proof: REVIEW")

    return "\n".join(lines)


def diff_waves(a: dict, b: dict) -> str:
    """Produce a side-by-side comparison of two wave entries."""
    lines = []
    id_a = get_wave_identifier(a)
    id_b = get_wave_identifier(b)
    lines.append(f"{'Field':<20} {'Wave ' + str(id_a):<30} {'Wave ' + str(id_b):<30}")
    lines.append("-" * 80)

    comparison_fields = [
        ("wave_id", "Wave ID"),
        ("timestamp", "Timestamp"),
        ("mode", "Mode"),
        ("topology", "Topology"),
        ("task_id", "Task ID"),
        ("selected_lane", "Lane"),
        ("duration_seconds", "Duration (s)"),
        ("exit_code", "Exit code"),
        ("verdict", "Verdict"),
        ("failure_reason", "Failure reason"),
        ("next_action", "Next action"),
        ("chapter_delta", "Chapter delta"),
        ("competitor_delta", "Competitor delta"),
        ("launch_delta", "Launch delta"),
        ("product_score", "Product score"),
        ("prompt_sha256", "Prompt sha256"),
        ("git_head", "Git head"),
        ("git_status_before", "Git status"),
    ]

    for key, label in comparison_fields:
        if key == "git_status_before":
            val_a = summarize_git_status(str(a.get(key, "") or ""))
            val_b = summarize_git_status(str(b.get(key, "") or ""))
        elif key == "wave_id":
            val_a = get_wave_identifier(a)
            val_b = get_wave_identifier(b)
        elif key == "timestamp":
            val_a = get_timestamp(a)
            val_b = get_timestamp(b)
        elif key == "duration_seconds":
            val_a = get_duration_seconds(a)
            val_b = get_duration_seconds(b)
        elif key == "exit_code":
            val_a = get_exit_code_value(a)
            val_b = get_exit_code_value(b)
        else:
            val_a = str(a.get(key, "") or "")
            val_b = str(b.get(key, "") or "")
        marker = " " if val_a == val_b else "≠"
        lines.append(f"{label:<20} {val_a:<30} {val_b:<30} {marker}")

    # Engines
    pair_a = get_pair(a)
    pair_b = get_pair(b)
    marker = " " if pair_a == pair_b else "≠"
    lines.append(f"{'Pair':<20} {pair_a:<30} {pair_b:<30} {marker}")

    # Models
    model_a = get_model(a)
    model_b = get_model(b)
    marker = " " if model_a == model_b else "≠"
    lines.append(f"{'Writer model':<20} {model_a:<30} {model_b:<30} {marker}")

    rmodel_a = get_review_model(a)
    rmodel_b = get_review_model(b)
    marker = " " if rmodel_a == rmodel_b else "≠"
    lines.append(f"{'Reviewer model':<20} {rmodel_a:<30} {rmodel_b:<30} {marker}")

    # Changed files summary
    files_a = a.get("changed_files") or []
    files_b = b.get("changed_files") or []
    lines.append(
        f"{'Changed files':<20} {len(files_a):<30} {len(files_b):<30}"
        f" {'≠' if len(files_a) != len(files_b) else ' '}"
    )

    # File overlap
    set_a = set(files_a)
    set_b = set(files_b)
    common = set_a & set_b
    only_a = set_a - set_b
    only_b = set_b - set_a
    if common or only_a or only_b:
        lines.append("")
        lines.append("File comparison:")
        if common:
            lines.append(f"  Common:        {len(common)} files")
        if only_a:
            lines.append(f"  Only in {id_a}: {len(only_a)} files")
            for f in sorted(only_a)[:5]:
                lines.append(f"    {f}")
        if only_b:
            lines.append(f"  Only in {id_b}: {len(only_b)} files")
            for f in sorted(only_b)[:5]:
                lines.append(f"    {f}")

    # Verdict drift analysis
    success_a = is_success(a)
    success_b = is_success(b)
    if success_a != success_b:
        lines.append("")
        lines.append("⚠ Verdict drift detected:")
        lines.append(f"  {id_a}: {'PASS' if success_a else 'FAIL'}")
        lines.append(f"  {id_b}: {'PASS' if success_b else 'FAIL'}")
        if pair_a != pair_b:
            lines.append(f"  Pair changed: {pair_a} → {pair_b}")

    if has_replay_acceptance_context(a, b):
        lines.append("")
        lines.append(format_replay_acceptance_summary(a, b))

    return "\n".join(lines)


# Build CLI command


def build_replay_command(
    entry: dict,
    overrides: ReplayOverrides | None = None,
    script_path: str = "./mainspring.sh",
) -> list[str]:
    """Build the mainspring CLI command that would replay this wave.

    Returns a list of command-line tokens.
    """
    effective = apply_overrides(entry, overrides) if overrides else entry

    prompt_path = get_prompt_path(effective)
    live_reconstruction = bool(
        overrides and overrides.allow_live_reconstruction and not prompt_path
    )
    mode = "night" if prompt_path else effective.get("mode") or "night"
    cmd = [script_path, mode]

    if mode == "night":
        prd_path = get_prd_path(effective)
        if not prd_path and prompt_path and Path("docs/prd.md").is_file():
            prd_path = "docs/prd.md"
        if prd_path:
            cmd.extend(["--prd", prd_path])

    # Topology
    topology = (
        "solo"
        if prompt_path or live_reconstruction
        else effective.get("topology") or "solo"
    )
    cmd.extend(["--topology", topology])

    # Pair
    writer = get_engine(effective)
    reviewer = get_reviewer(effective)
    if writer and reviewer:
        cmd.extend(["--pair", f"{writer}+{reviewer}"])

    # Models
    writer_model = get_model(effective)
    if writer_model and writer_model != "default":
        cmd.extend(["--model", writer_model])

    reviewer_model = get_review_model(effective)
    if reviewer_model and reviewer_model != "default":
        cmd.extend(["--review-model", reviewer_model])

    # Single wave
    cmd.append("--once")

    return cmd


def format_replay_command(cmd: list[str]) -> str:
    """Format command tokens as a shell-safe command string."""
    return " ".join(_quote_shell_token(token) for token in cmd)


def _quote_shell_token(token: str) -> str:
    """Return a POSIX-shell-safe representation of a single token."""
    safe_chars = (
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_@%=:,./-"
    )
    if token and all(char in safe_chars for char in token):
        return token
    return "'" + token.replace("'", "'\"'\"'") + "'"


def format_environment_overrides(env: dict[str, str]) -> str:
    """Format replay-specific env vars without dumping inherited process env."""
    if not env:
        return "(none)"
    return "\n".join(f"{key}={value}" for key, value in sorted(env.items()))


def format_validation_preview(errors: list[str]) -> str:
    """Format the validation result a real replay run would use."""
    if not errors:
        return "Real-run validation: OK"
    lines = ["Real-run validation: would fail"]
    lines.extend(f"  - {error}" for error in errors)
    return "\n".join(lines)


# Replay metadata


def build_replay_metadata(
    original: dict,
    overrides: ReplayOverrides | None = None,
) -> dict:
    """Build metadata dict describing the replay configuration."""
    meta: dict = {
        "original_wave_id": get_wave_identifier(original),
        "original_timestamp": get_timestamp(original),
        "original_verdict": original.get("verdict", ""),
        "original_pair": get_pair(original),
        "original_task_id": original.get("task_id", ""),
    }

    if overrides:
        changes: dict[str, str] = {}
        if overrides.engine:
            changes["engine"] = f"{get_engine(original)} → {overrides.engine}"
        if overrides.reviewer:
            changes["reviewer"] = f"{get_reviewer(original)} → {overrides.reviewer}"
        if overrides.model:
            changes["model"] = f"{get_model(original)} → {overrides.model}"
        if overrides.review_model:
            changes["review_model"] = (
                f"{get_review_model(original)} → {overrides.review_model}"
            )
        if overrides.save_as:
            meta["replay_wave_id"] = overrides.save_as
        meta["overrides"] = changes
    else:
        meta["overrides"] = {}

    return meta


def build_replay_environment_overrides(
    original: dict, overrides: ReplayOverrides
) -> dict[str, str]:
    """Build the replay-specific environment variables."""
    env: dict[str, str] = {}
    if overrides.save_as:
        env["MAINSPRING_WAVE_ID_OVERRIDE"] = overrides.save_as
    replayed_from = get_wave_identifier(original)
    env["MAINSPRING_REPLAYED_FROM"] = (
        "" if replayed_from == "unknown" else replayed_from
    )
    env["MAINSPRING_REPLAY_OVERRIDES"] = json.dumps(
        build_replay_metadata(original, overrides),
        ensure_ascii=False,
        sort_keys=True,
    )
    prompt_path = get_prompt_path(original)
    if prompt_path:
        env["MAINSPRING_REPLAY_PROMPT_FILE"] = prompt_path
        env["MAINSPRING_REPLAY_TARGET_ID"] = str(
            original.get("work_id") or original.get("task_id") or "replay"
        )
        env["MAINSPRING_REPLAY_ORIGINAL_MODE"] = str(original.get("mode") or "")
    elif overrides.allow_live_reconstruction:
        env["MAINSPRING_REPLAY_LIVE_RECONSTRUCTION"] = "1"
        target_id = get_replay_target_id(original)
        if target_id:
            env["MAINSPRING_REPLAY_TARGET_ID"] = target_id
        env["MAINSPRING_REPLAY_ORIGINAL_MODE"] = str(original.get("mode") or "")
    return env


def build_replay_environment(
    original: dict, overrides: ReplayOverrides
) -> dict[str, str]:
    """Build environment for a real replay run."""
    env = os.environ.copy()
    env.update(build_replay_environment_overrides(original, overrides))
    return env


def file_sha256(path: Path) -> str:
    """Return sha256 hex digest for *path*."""
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def current_git_head(root: Path | None = None) -> str:
    """Return current git HEAD, or an empty string outside git."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root or Path.cwd()),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def current_git_status(root: Path | None = None) -> str:
    """Return current git status using the same pathspec as Mainspring."""
    try:
        result = subprocess.run(
            [
                "git",
                "status",
                "--short",
                "--untracked-files=no",
                "--",
                ".",
                ":(exclude).mainspring",
                ":(exclude)node_modules",
                ":(exclude)dist",
                ":(exclude)coverage",
                ":(exclude)playwright-report",
                ":(exclude)test-results",
                ":(exclude)**/__pycache__/**",
                ":(exclude)**/*.pyc",
            ],
            cwd=str(root or Path.cwd()),
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip("\n")


def summarize_git_status(status: str) -> str:
    """Return a short status summary for validation errors."""
    lines = [line for line in status.splitlines() if line.strip()]
    if not lines:
        return "clean"
    suffix = "path" if len(lines) == 1 else "paths"
    return f"{len(lines)} changed {suffix}"


def validate_replay_inputs(
    wave: dict,
    overrides: ReplayOverrides,
    root: Path | None = None,
) -> list[str]:
    """Return fail-closed replay validation errors."""
    errors: list[str] = []
    root = root or Path.cwd()

    prompt_path = get_prompt_path(wave)
    if not prompt_path and not overrides.allow_live_reconstruction:
        errors.append(
            "recorded prompt snapshot is required for deterministic replay; "
            "use --allow-live-reconstruction to rebuild from current Taskmaster/PRD state"
        )
    elif not prompt_path and not live_reconstruction_anchor(wave):
        errors.append(
            "live reconstruction requires a recorded task_id/work_id or prd_path anchor"
        )
    elif prompt_path:
        resolved_prompt = resolve_snapshot_path(prompt_path, root)
        if not resolved_prompt.is_file():
            errors.append(f"prompt snapshot missing: {prompt_path}")
        else:
            expected_sha = get_prompt_sha256(wave)
            if expected_sha:
                actual_sha = file_sha256(resolved_prompt)
                if actual_sha != expected_sha:
                    errors.append(
                        "prompt snapshot sha256 mismatch: "
                        f"expected {expected_sha}, got {actual_sha}"
                    )

    recorded_head = get_git_head(wave)
    if recorded_head and not overrides.allow_worktree_drift:
        head = current_git_head(root)
        if not head:
            errors.append("cannot verify recorded git head in this worktree")
        elif head != recorded_head:
            errors.append(
                f"worktree git head drift: recorded {recorded_head}, current {head}"
            )

    if has_git_status_before(wave) and not overrides.allow_worktree_drift:
        recorded_status = get_git_status_before(wave)
        status = current_git_status(root)
        if status != recorded_status:
            errors.append(
                "worktree git status drift: "
                f"recorded {summarize_git_status(recorded_status)}, "
                f"current {summarize_git_status(status)}"
            )

    return errors


# CLI


USAGE = """\
Usage:
  mainspring replay show <wave-ref> <ledger-path>
  mainspring replay diff <wave-ref-1> <wave-ref-2> <ledger-path>
  mainspring replay build <wave-ref> <ledger-path> [--engine X] [--reviewer Y] ...
  mainspring replay run <wave-ref> <ledger-path> [--dry-run] [--save-as <id>] ...

Wave references:
  <wave-id>    Match by wave_id field
  #N           Match by 0-based index (#0 = first, #-1 = last)
  last         Alias for #-1

Override flags (build/run):
  --engine <name>        Swap writer engine
  --reviewer <name>      Swap reviewer engine
  --model <id>           Override writer model
  --review-model <id>    Override reviewer model
  --save-as <id>         Record replayed wave under a new id
  --dry-run              Print command without executing (run only)
  --allow-worktree-drift Run even when recorded git head differs
  --allow-live-reconstruction
                          Run an older non-snapshot row from current live state

Examples:
  mainspring replay show last .mainspring/logs/waves.jsonl
  mainspring replay diff "#-2" last .mainspring/logs/waves.jsonl
  mainspring replay build last .mainspring/logs/waves.jsonl --engine codex --reviewer claude
  mainspring replay run last .mainspring/logs/waves.jsonl --dry-run --save-as replay-smoke
"""


def _parse_overrides(args: list[str]) -> ReplayOverrides:
    """Parse override flags from remaining CLI args."""
    overrides = ReplayOverrides()
    i = 0
    while i < len(args):
        if args[i] in {
            "--engine",
            "--reviewer",
            "--model",
            "--review-model",
            "--save-as",
        } and (i + 1 >= len(args) or args[i + 1].startswith("--")):
            raise ReplayArgumentError(f"{args[i]} requires a value")

        if args[i] == "--engine":
            overrides.engine = args[i + 1]
            i += 2
        elif args[i] == "--reviewer":
            overrides.reviewer = args[i + 1]
            i += 2
        elif args[i] == "--model":
            overrides.model = args[i + 1]
            i += 2
        elif args[i] == "--review-model":
            overrides.review_model = args[i + 1]
            i += 2
        elif args[i] == "--save-as":
            overrides.save_as = args[i + 1]
            i += 2
        elif args[i] == "--dry-run":
            overrides.dry_run = True
            i += 1
        elif args[i] == "--allow-worktree-drift":
            overrides.allow_worktree_drift = True
            i += 1
        elif args[i] == "--allow-live-reconstruction":
            overrides.allow_live_reconstruction = True
            i += 1
        else:
            raise ReplayArgumentError(f"unknown replay override flag: {args[i]}")
    return overrides


def cmd_show(wave_ref: str, ledger_path: str) -> int:
    """Show detailed metadata for a wave."""
    entries = read_ledger(Path(ledger_path))
    if not entries:
        print(f"No waves found in {ledger_path}", file=sys.stderr)
        return 1

    wave = resolve_wave(entries, wave_ref)
    if wave is None:
        print(f"Wave '{wave_ref}' not found in {ledger_path}", file=sys.stderr)
        return 1

    print(format_wave_detail(wave))
    return 0


def cmd_diff(ref_a: str, ref_b: str, ledger_path: str) -> int:
    """Compare two waves side-by-side."""
    entries = read_ledger(Path(ledger_path))
    if not entries:
        print(f"No waves found in {ledger_path}", file=sys.stderr)
        return 1

    wave_a = resolve_wave(entries, ref_a)
    if wave_a is None:
        print(f"Wave '{ref_a}' not found in {ledger_path}", file=sys.stderr)
        return 1

    wave_b = resolve_wave(entries, ref_b)
    if wave_b is None:
        print(f"Wave '{ref_b}' not found in {ledger_path}", file=sys.stderr)
        return 1

    print(diff_waves(wave_a, wave_b))
    return 0


def cmd_build(wave_ref: str, ledger_path: str, override_args: list[str]) -> int:
    """Build the replay command for a wave."""
    entries = read_ledger(Path(ledger_path))
    if not entries:
        print(f"No waves found in {ledger_path}", file=sys.stderr)
        return 1

    wave = resolve_wave(entries, wave_ref)
    if wave is None:
        print(f"Wave '{wave_ref}' not found in {ledger_path}", file=sys.stderr)
        return 1

    try:
        overrides = _parse_overrides(override_args)
    except ReplayArgumentError as exc:
        print(f"replay: {exc}", file=sys.stderr)
        return 2
    override_errors = validate_replay_overrides(wave, overrides, entries)
    if override_errors:
        for error in override_errors:
            print(f"replay: {error}", file=sys.stderr)
        return 2
    cmd = build_replay_command(wave, overrides)
    meta = build_replay_metadata(wave, overrides)
    env_overrides = build_replay_environment_overrides(wave, overrides)
    validation_errors = validate_replay_inputs(wave, overrides)

    print("# Replay command")
    print(format_replay_command(cmd))
    print()
    print("# Replay environment")
    print(format_environment_overrides(env_overrides))
    print()
    print("# Replay metadata")
    print(json.dumps(meta, indent=2, ensure_ascii=False))
    print()
    print("# Replay validation")
    print(format_validation_preview(validation_errors))
    return 0


def cmd_run(wave_ref: str, ledger_path: str, override_args: list[str]) -> int:
    """Run a wave replay (or --dry-run to preview)."""
    entries = read_ledger(Path(ledger_path))
    if not entries:
        print(f"No waves found in {ledger_path}", file=sys.stderr)
        return 1

    wave = resolve_wave(entries, wave_ref)
    if wave is None:
        print(f"Wave '{wave_ref}' not found in {ledger_path}", file=sys.stderr)
        return 1

    try:
        overrides = _parse_overrides(override_args)
    except ReplayArgumentError as exc:
        print(f"replay: {exc}", file=sys.stderr)
        return 2
    override_errors = validate_replay_overrides(wave, overrides, entries)
    if override_errors:
        for error in override_errors:
            print(f"replay: {error}", file=sys.stderr)
        return 2
    cmd = build_replay_command(wave, overrides)
    meta = build_replay_metadata(wave, overrides)
    env_overrides = build_replay_environment_overrides(wave, overrides)
    validation_errors = validate_replay_inputs(wave, overrides)

    if overrides.dry_run:
        print("# Dry run — would execute:")
        print(format_replay_command(cmd))
        print()
        print("# Replay environment")
        print(format_environment_overrides(env_overrides))
        print()
        print("# Replay metadata")
        print(json.dumps(meta, indent=2, ensure_ascii=False))
        print()
        print("# Replay validation")
        print(format_validation_preview(validation_errors))
        print()
        print("# Original wave summary")
        print(
            f"  Verdict: {wave.get('verdict', 'unknown')} | "
            f"Duration: {wave.get('duration_seconds', 0)}s | "
            f"Files: {len(wave.get('changed_files') or [])}"
        )
        return 0

    if validation_errors:
        print("Replay input validation failed:", file=sys.stderr)
        for error in validation_errors:
            print(f"  - {error}", file=sys.stderr)
        print(
            "Use --allow-worktree-drift only after intentionally checking out "
            "the desired replay state.",
            file=sys.stderr,
        )
        return 1

    # Real execution — shell out to mainspring

    print(f"Replaying wave {get_wave_identifier(wave)}...")
    print(f"Command: {format_replay_command(cmd)}")
    print()

    try:
        result = subprocess.run(
            cmd,
            check=False,
            env=build_replay_environment(wave, overrides),
        )
        return result.returncode
    except FileNotFoundError:
        print(
            f"Could not find mainspring at '{cmd[0]}'. "
            "Ensure mainspring.sh is on PATH or use --dry-run.",
            file=sys.stderr,
        )
        return 127


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print(USAGE, file=sys.stderr)
        return 2
    if args[0] in ("-h", "--help"):
        print(USAGE)
        return 0

    subcmd = args[0]

    if subcmd == "show":
        if len(args) < 3:
            print(
                "Usage: mainspring replay show <wave-ref> <ledger-path>",
                file=sys.stderr,
            )
            return 2
        return cmd_show(args[1], args[2])

    elif subcmd == "diff":
        if len(args) < 4:
            print(
                "Usage: mainspring replay diff <wave-ref-1> <wave-ref-2> <ledger-path>",
                file=sys.stderr,
            )
            return 2
        return cmd_diff(args[1], args[2], args[3])

    elif subcmd == "build":
        if len(args) < 3:
            print(
                "Usage: mainspring replay build <wave-ref> <ledger-path> [overrides]",
                file=sys.stderr,
            )
            return 2
        return cmd_build(args[1], args[2], args[3:])

    elif subcmd == "run":
        if len(args) < 3:
            print(
                "Usage: mainspring replay run <wave-ref> <ledger-path> [--dry-run] [overrides]",
                file=sys.stderr,
            )
            return 2
        return cmd_run(args[1], args[2], args[3:])

    else:
        print(f"Unknown subcommand: {subcmd}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2


if __name__ == "__main__":
    run_cli(main)
