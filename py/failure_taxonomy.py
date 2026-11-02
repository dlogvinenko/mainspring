# SPDX-License-Identifier: Apache-2.0
"""Failure reason taxonomy for Mainspring.

Every ``failure_reason`` value written to ``waves.jsonl`` must use one of
the prefixed classes below.  The taxonomy is frozen at v1.0 — adding new
leaf values is non-breaking; adding a new prefix class requires a PRD
amendment.

Prefix classes:
    routing:*   — work-item selection / backlog / scheduling failures
    engine:*    — writer or reviewer engine failures (crash, quota, timeout)
    review:*    — review-gate failures (verdict FAIL, missing fields, invalid JSON)
    scope:*     — post-wave write-scope violations
    team:*      — team-topology orchestration failures

CLI:
    python3 failure_taxonomy.py list              → print all known reasons
    python3 failure_taxonomy.py validate <value>  → exit 0 if valid prefix, exit 1 otherwise
    python3 failure_taxonomy.py prefix <value>    → print the prefix class
    python3 failure_taxonomy.py normalize <value> → print the ledger class
    python3 failure_taxonomy.py action <value>    → print routing failure action
"""

from __future__ import annotations

import sys

from cli_runtime import run_cli

# ── Canonical failure reasons ────────────────────────────────────────────
# Each value below is a known, documented failure_reason that may appear
# in waves.jsonl.  Unknown values are tolerated (forward compat) but
# the validate subcommand will warn about them.

ROUTING_REASONS: frozenset[str] = frozenset(
    {
        "routing:no_actionable_task",
        "routing:empty_parent",
        "routing:missing_replay_prompt",
        "routing:missing_replay_target",
        "routing:plugin_invisible",
        "routing:replay_target_unavailable",
        "routing:scope_blocked",
    }
)

ROUTING_FAILURE_ACTIONS: dict[str, str] = {
    "routing:empty_parent": "block_taskmaster",
    "routing:scope_blocked": "block_taskmaster",
    "routing:plugin_invisible": "solo_fallback",
    "routing:no_actionable_task": "stop_no_task",
    "routing:missing_replay_prompt": "fail_no_task",
    "routing:missing_replay_target": "fail_no_task",
    "routing:replay_target_unavailable": "fail_no_task",
}

ENGINE_REASONS: frozenset[str] = frozenset(
    {
        "engine:exit_nonzero",
        "engine:no_file_changes",
        "engine:quota",
        "engine:timeout",
        "engine:crash",
        "engine:test_fail",
        "engine:lint_fail",
        "engine:typecheck_fail",
        "engine:auth",
        "engine:dependency_missing",
        "engine:quota_exhausted",
    }
)

REVIEW_REASONS: frozenset[str] = frozenset(
    {
        "review:gate_failed",
        "review:reviewer_unreachable",
        "review:missing_fields",
        "review:invalid_json",
        "review:verdict_not_pass",
    }
)

SCOPE_REASONS: frozenset[str] = frozenset(
    {
        "scope:violation",
        "scope:secret_detected",
    }
)

TEAM_REASONS: frozenset[str] = frozenset(
    {
        "team:no_parallel_safe_work",
        "team:run_failed",
        "team:stuck",
        "team:dispatch_duplicate",
    }
)

ALL_KNOWN_REASONS: frozenset[str] = (
    ROUTING_REASONS | ENGINE_REASONS | REVIEW_REASONS | SCOPE_REASONS | TEAM_REASONS
)

VALID_PREFIXES: frozenset[str] = frozenset(
    {"routing", "engine", "review", "scope", "team"}
)


def extract_prefix(reason: str) -> str | None:
    """Return the prefix class of a failure_reason, or None if unprefixed."""
    if ":" in reason:
        prefix = reason.split(":", 1)[0]
        if prefix in VALID_PREFIXES:
            return prefix
    return None


def is_valid_prefix(reason: str) -> bool:
    """Return True if the reason uses a known prefix class."""
    return extract_prefix(reason) is not None


def is_known_reason(reason: str) -> bool:
    """Return True if the reason is in the canonical list."""
    return reason in ALL_KNOWN_REASONS


def normalise_failure_reason_class(
    reason: str,
    explicit_class: str = "",
) -> str:
    """Return the canonical ``failure_reason_class`` ledger value.

    New rows store the machine-readable failure leaf, such as
    ``review:gate_failed``.  Bare prefix classes from older callers are upgraded
    when the full failure reason is available.
    """
    reason = reason.strip()
    explicit_class = explicit_class.strip()

    explicit_prefix = extract_prefix(explicit_class)
    reason_prefix = extract_prefix(reason)

    if explicit_prefix:
        if reason_prefix and reason_prefix != explicit_prefix:
            return reason
        return explicit_class

    if explicit_class in VALID_PREFIXES and reason and reason_prefix == explicit_class:
        return reason

    if reason_prefix:
        return reason

    return explicit_class if explicit_class in VALID_PREFIXES else ""


def routing_failure_action(reason: str, explicit_class: str = "") -> str:
    """Return the scheduler action for a routing failure class.

    ``routing:plugin_invisible`` is recoverable because ADR-02 deliberately
    routes nested-repo work to the leader's solo checkout.  Non-recoverable
    task-scoped routing failures are the only ones that should block the
    Taskmaster item automatically.
    """
    normalised = normalise_failure_reason_class(reason, explicit_class)
    if not normalised.startswith("routing:"):
        return ""
    return ROUTING_FAILURE_ACTIONS.get(normalised, "fail_no_task")


# ── CLI ──────────────────────────────────────────────────────────────────


def _cli_main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "Usage: failure_taxonomy.py <list|validate|prefix|normalize|action> [value]",
            file=sys.stderr,
        )
        return 2

    cmd = args[0]
    if cmd == "list":
        for reason in sorted(ALL_KNOWN_REASONS):
            print(reason)
        return 0

    if cmd == "validate":
        if len(args) < 2:
            print("Usage: failure_taxonomy.py validate <value>", file=sys.stderr)
            return 2
        value = args[1]
        if not value:
            return 0  # empty reason is valid (no failure)
        if is_valid_prefix(value):
            if not is_known_reason(value):
                print(
                    f"warning: unknown reason '{value}' (valid prefix)", file=sys.stderr
                )
            return 0
        print(f"invalid: '{value}' has no recognized prefix", file=sys.stderr)
        return 1

    if cmd == "prefix":
        if len(args) < 2:
            print("Usage: failure_taxonomy.py prefix <value>", file=sys.stderr)
            return 2
        prefix = extract_prefix(args[1])
        if prefix:
            print(prefix)
        return 0

    if cmd == "normalize":
        if len(args) < 2:
            print("Usage: failure_taxonomy.py normalize <value>", file=sys.stderr)
            return 2
        normalised = normalise_failure_reason_class(args[1])
        if normalised:
            print(normalised)
        return 0

    if cmd == "action":
        if len(args) < 2:
            print("Usage: failure_taxonomy.py action <value>", file=sys.stderr)
            return 2
        action = routing_failure_action(args[1])
        if action:
            print(action)
        return 0

    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    run_cli(_cli_main)
