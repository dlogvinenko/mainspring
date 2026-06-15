# Mainspring Architecture

Mainspring is a Bash orchestrator with Python helpers.

## Boundaries

- `mainspring.sh` parses top-level commands and sources `lib/*.sh`.
- `lib/engines.sh` runs writer and reviewer turns through the engine registry.
- `py/*.py` owns structured parsing, JSONL writing, replay, metrics, and
  provider-engine helpers.
- `py/engines/*.py` registers engine adapters with one common protocol.
- `py/backlog_source.py` defines the backlog-source protocol. v1.0 ships the
  Taskmaster JSON adapter only; non-Taskmaster adapters must remain opt-in.

## Engine Adapter Contract

Each engine module exposes `ADAPTER.info`, `build_command`, `parse_usage`,
`quota_snapshot`, and `detect_failure`. Dispatch returns an argv plus a display
mode. Bash owns pipes and signal handling; Python owns command construction and
validation.

## Failure Policy

The reviewer is the only gate. Missing dependencies, missing credentials, empty
writer output, malformed LiteLLM provider responses, invalid review JSON, and
unknown engine names all fail closed.

## Backlog Source Contract

Backlog providers expose `list_ready_tasks`, `get_details`, `mark_done`, and
`mark_blocked`. The Taskmaster adapter reads `.taskmaster/tasks/tasks.json` for
scheduler decisions and uses the `task-master` CLI for status mutations. Failed
mutations raise an explicit error instead of silently treating the backlog as
updated.
