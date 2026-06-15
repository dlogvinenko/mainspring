# Atomic Taskmaster Task Template

A task is **atomic** when an LLM agent can finish it end-to-end in <2 hours given only the task body, the codebase, and the project's PRD. If any of those conditions is missing, the task is too vague.

Use this template when adding tasks via `task-master add-task --prompt="..."` (read it back, refuse anything that doesn't satisfy all sections).

---

## Title

{{Imperative form, ≤ 70 chars. "Extract heredoc at mainspring.sh:2454 to py/stream_json_prettify.py" — not "Improve heredoc handling".}}

## Summary

{{1-3 sentences explaining WHAT changes and WHY. Cite the PRD phase this serves.}}

## Scope

**Touch these files:**

- `{{path/to/file:start_line-end_line}}` — {{what changes}}
- `{{path/to/new/file}}` — {{create with this content shape}}

**Do NOT touch:**

- {{anything explicitly out of scope, e.g. "anything in tests/ — separate task"}}

## Acceptance criteria

A reviewer should be able to verify each criterion mechanically.

- [ ] {{specific, measurable criterion 1, e.g. "mainspring.sh has 0 occurrences of `python3 - <<'PY'`"}}
- [ ] {{criterion 2 with command, e.g. "running `shellcheck mainspring.sh` shows 0 SC2259 errors"}}
- [ ] {{criterion 3 with file:line, e.g. "py/stream_json_prettify.py exists and accepts --mode writer|reviewer"}}

## Test plan

**Targeted tests** (must add or update):

- `{{tests/path/to/test_file.py}}` — {{which scenarios}}
- `{{tests/bats/test_xxx.bats}}` — {{which behaviors}}

**Manual verification** (if any):

- {{specific command + expected output, e.g. "run `mainspring --self-test-all` — Claude+Claude pair must produce non-empty display_file"}}

## Dependencies

- Depends on: {{taskmaster id list, or `none`}}
- Blocks: {{taskmaster id list of tasks that wait on this, or `none`}}

## Manual blocker check

**Does this task require any human action?** ({{`yes` | `no`}})

If **yes**, this is the wrong template. Split into:

1. A coding task that prepares everything an LLM can prepare (`pending`)
2. A manual task with `status: blocked` containing only the human action (e.g. "obtain production Stripe API key", "submit to Plugin Hub")

The manual task lives in the LAST phase of the PRD. The coding task can be done now.

If **no**, you're good. Continue.

## Priority

{{`high` | `medium` | `low`}}

**Reason:** {{why this priority — one sentence anchored in the PRD's phase ordering or a specific business outcome}}.

## Estimated effort

{{`< 30 min` | `30 min - 2 hrs` | `half-day` | `> half-day → split`}}

If `> half-day`, split now: `task-master expand --id=<id> --research --force` after creation, OR rewrite this task more narrowly.

## Notes for the LLM agent

{{Any non-obvious context the agent will need: known gotchas, files that look related but aren't, naming conventions specific to this codebase, gotchas from prior failed attempts. Keep brief.}}

---

## Self-check before saving

- [ ] Title is imperative and ≤ 70 chars
- [ ] Scope names file paths (and line ranges where applicable)
- [ ] Every acceptance criterion is mechanically verifiable
- [ ] Test plan names specific test files
- [ ] Manual blocker check is done — if `yes`, this task was split
- [ ] Effort estimate is `≤ half-day` — otherwise split
- [ ] No "improve X" / "clean up Y" / "make better" language
