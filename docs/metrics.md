# Mainspring Metrics And Ledger

`waves.jsonl` is append-only JSONL. One row equals one completed wave.

## Emitted Fields

Current `wave_log.py` rows may include:

`ts`, `timestamp`, `wave`, `wave_id`, `mode`, `topology`, `team`, `team_name`,
`task_id`, `task_status_before`, `task_status_after`, `selected_lane`, `engine`,
`review_engine`, `pair`, `engines`, `model`, `review_model`, `models`,
`duration_s`, `duration_seconds`, `product_files_changed`, `changed_files`,
`tests`, `verdict`, `exit_code`, `failure_reason`, `failure_reason_class`,
`fallback_engine_used`, `retry_count`, `retry_used`, `blocked_reason`, `next_action`, `prompt_path`,
`prompt_sha256`, `git_head`, `git_status_before`, `prd_path`, `usage`,
`cost_usd`, `total_cost_usd`, `replayed_from`, and `replay_overrides`.

## Consumed Fields

Metrics, digest, routing, and replay readers also understand:

`chapter_delta`, `competitor_delta`, `launch_delta`, `product_score`,
`product_score_delta`, `score_delta`, `codex_short_delta_pct`,
`claude_short_delta`, `gemini_short_delta_pct`, `cost_usd`, `total_cost_usd`,
and `usage`.

## Operator Queries

```bash
mainspring --metrics --days 7
mainspring --metrics --format json
mainspring replay show <wave-id> .mainspring/logs/waves.jsonl
```

Fields may be added without a schema bump. Removing or renaming a field requires
a schema-version migration in the PRD.

`failure_reason_class` stores the canonical machine-readable reason, such as
`review:gate_failed`, `routing:plugin_invisible`, or `routing:scope_blocked`.
Older rows that contain only a bare prefix such as `review` are treated as
legacy data by readers.
