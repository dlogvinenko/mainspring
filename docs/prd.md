# Mainspring — Product Requirements Document (PRD)

**Status:** canonical plan for Mainspring (autonomous execution loop). Lives at `docs/prd.md`. The Method that produced this document is at [`docs/method.md`](method.md); Mainspring was built with the same Product Requirements Document (PRD)-first discipline it now ships.
**Owner:** Mainspring maintainers.
**Companion docs:** [`docs/guide.md`](guide.md) — operator commands and recovery shortcuts.

This is the document that drives Mainspring as a clean modular Apache-2.0 OSS
tool prepared for the `mainspring v1.0.0` GitHub source release. Nothing else
in the repo speaks for Mainspring's plan; if it disagrees with this file, this
file wins.

---

## Contents

1. [Mission](#mission)
2. [Durability principles](#durability-principles)
3. [Current truth snapshot (verified)](#current-truth-snapshot-verified)
4. [Naming and brand boundary](#naming-and-brand-boundary)
5. [Target architecture](#target-architecture)
6. [Phase map](#phase-map)
7. [Architecture decisions (ADRs)](#architecture-decisions-adrs)
8. [Operational doctrine](#operational-doctrine)
9. [Health rituals](#health-rituals)
10. [Disaster recovery](#disaster-recovery)
11. [Versioning and migration](#versioning-and-migration)
12. [v1.0 GitHub release checklist](#v10-github-release-checklist)
13. [Explicit non-goals](#explicit-non-goals)
14. [Backlog (Must / Should / Could / Won't)](#backlog-must-should-could-wont)
15. [Appendix A — Source-of-knowledge recipes](#appendix-a-source-of-knowledge-recipes)
16. [Appendix B — Verification commands](#appendix-b-verification-commands)
17. [Appendix C — Competitor landscape / competitive positioning](#appendix-c-competitor-landscape-competitive-positioning-june-2026-refresh)

---

## Mission

Mainspring is a single-operator, single-host **autonomous execution instrument**: it picks work from a Product Requirements Document (PRD) or backlog, runs a writer model or CLI against it, runs an independent reviewer as a hard gate, captures verifiable outcomes as JSONL, and stops or continues based on what actually shipped — not what the agent claims.

Mainspring is positioned as **Product Requirements Document (PRD)-first AI coding agent orchestration for production-grade software delivery**, not as another generic autonomous coding chat wrapper. The public surface must explain the practical buyer problem first: vibe coding is useful for exploration, but production work needs intent, review, evidence, visibility, and recovery.

**Three verbs**: pick, ship, record. Anything that doesn't serve one of these is decoration.

**Audience**:

1. Operators shipping production-grade local projects with AI agents. Primary.
2. Developers who want a local Product Requirements Document (PRD)-first AI coding loop with review, evidence, HUD, and Telegram. Secondary.
3. Contributors extending engines, backlog sources, docs, or release tooling. Tertiary.

**Non-audience**: enterprise teams, compliance auditors, cloud SaaS users. Mainspring is a local operator tool, not a hosted platform.

---

## Durability principles

The ten commandments. Anything below this line bows to them. If a phase plan, a feature, or an ADR conflicts with one of these, the plan loses.

1. **The wave is the unit.** One pass of `pick → write → review → log → decide` is one wave. Mainspring's correctness, observability, and metrics all hinge on the wave being a clean atomic concept. Never blur it.
2. **Truth before autonomy.** A wrong autonomous loop is worse than a slow one. Mainspring never marks a Taskmaster item done unless the reviewer hard-gate passed _and_ the changed-file check confirmed product code moved.
3. **The reviewer is the only gate.** No silent fallback that bypasses the review verdict. If the reviewer is unreachable, the wave fails closed (logs + Telegram, no auto-pass).
4. **Writer output must be visible to the reviewer.** The SC2259 silent-failure bug (heredoc-overrides-stdin) is the canonical anti-example. Every writer→reviewer handoff must be byte-verifiable. **Never** rebuild that bug.
5. **JSONL is the contract.** `.mainspring/logs/waves.jsonl` schema (defined below) is frozen. Adding fields is non-breaking; removing or renaming a field requires a `schema_version` bump and a 90-day deprecation window.
6. **The CLI is the contract.** Every flag in `--help` is a public API. Adding flags is non-breaking; removing a flag requires deprecation + stderr warning for one minor version.
7. **No embedded heredocs.** Bash dispatches; Python scripts compute. No `python3 - <<'PY'`, no `python3 -c '...'` longer than 80 chars in critical paths. Pretty-printing is a real `.py` file with tests.
8. **Fail closed, fail loud.** If we can't reach the LLM, the writer's output, the review verdict, the JSONL writer, or the lock file — we stop the wave with a stderr message. Never paper over.
9. **No fictional features.** The doctrine, the guide, and `--help` may only describe behavior present in the current commit. If a phase claims a feature, the test for it must already be green.
10. **Reversible by default.** Auto-checkpoint commits are OK; destructive cleanup, force shutdown, force push, rm -rf of worktrees, git reset --hard — all need an explicit user gate (`--restart-team`, `--repair-state`, `--force`). Mainspring should never destroy the user's in-progress work to make its own bookkeeping cleaner.

---

## Current truth snapshot (verified)

Refreshed 2026-10-30 for signal shutdown, Claude failures and provider dependencies
against public base `4d365cc`. Current checks below are local draft evidence;
the baseline lint findings still block a clean gate.
Publication, global installation and coverage rows remain historical evidence;
they were not revalidated as current results in this draft.

| Metric                                  | Value                                              | Source                                                   |
| --------------------------------------- | -------------------------------------------------- | -------------------------------------------------------- |
| `mainspring.sh` LOC                     | 442                                                | `wc -l mainspring.sh` on 2026-10-30                      |
| Bash functions across entrypoint + lib  | 172                                                | function-pattern scan on `mainspring.sh lib/*.sh` on 2026-10-30 |
| Source shell syntax                     | passes                                             | `bash -n mainspring.sh lib/*.sh`                         |
| Source shell lint                       | passes                                             | `shellcheck -S warning mainspring.sh lib/*.sh`           |
| Python lint                             | 410 baseline findings, zero additions                | Ruff 0.17.3 comparison with public `4d365cc` on 2026-10-30 |
| Python format                           | passes, 97 files already formatted                 | `ruff format --check py`                                 |
| Active embedded Python in shell paths   | 0 heredoc / inline-parser hits                     | `rg` scan for `python3 - <<` and `python3 -c` in shell    |
| Pytest suite files                      | 47                                                 | `find py/tests -name 'test_*.py'` plus count             |
| Bats suite files                        | 12                                                 | `find tests/bats -name '*.bats'` plus count              |
| Python line coverage                    | 90.6% (coverage gate pass)                         | `make coverage` on 2026-06-16                           |
| Full local gate                         | blocked: 1149 Python tests passed, 1 skipped; 223 Bats passed (doctor fixtures isolate inherited interpreter overrides); HUD/docs-site and package smoke pass; 410 baseline Ruff findings; known filelock findings resolved in the validated public dependency graphs | separate local gates on 2026-10-30; `make all` stops at baseline lint |
| Provider dependency floor               | filelock >=4.2.1,<5 on Python <3.14; actual 3.11 requirements and 3.13 providers-extra installs/mock checks pass; public graphs have 0 known findings; 3.14 remains Rich-only | isolated validation on 2026-10-30; local unpublished source and real providers are outside registry/mock proof |
| Global editable CLI                     | passes: `make install-user`; `command -v mainspring` resolves `~/.local/bin/mainspring`; installed HUD captured output exits one-shot; unsupported release-management probes fail with `Unknown command` | local pipx smoke on 2026-06-15 |
| Taskmaster runtime state                | not tracked in source release                      | `py/tests/test_no_hardcoded_paths.py`                    |
| Public release checklist                | clean `main` is public; hosted CI and GitHub Pages are green; remaining external action is signing `v1.0.0` and publishing the GitHub Release | GitHub repository state, hosted Actions runs, Pages deployment, signing key |
| PRD readiness score                     | 900 / 1000                                        | source-install product path is green; remaining points are publication checklist items |
| Telegram notifier health in clean env   | disabled until `MAINSPRING_NOTIFY_ENABLED=1`       | `./mainspring.sh notify-health --format json`            |

Signal shutdown ends the run with exit status 130 for SIGINT or 143 for
SIGTERM. It terminates only the active engine pipeline and its descendants,
with bounded TERM/KILL cleanup before releasing the runtime lock, and starts
no further wave. Regressions cover both Codex and Claude pipelines, including an engine
and subprocess that ignore TERM, without making model calls.

Structured Claude failure classification accepts engine error evidence and
`rejected` rate-limit events. An `allowed_warning` event is not exhaustion;
task prose mentioning quota and malformed rate-limit metadata do not cause a
quota classification or crash the failure-reporting path.

**Resolved historical critical bug:** the former SC2259 path
`"${cmd[@]}" | tee "$raw_file" | python3 - <<'PY' ... PY` let the heredoc
override piped writer output, so the reviewer could see an empty
`display_file`. P1 extracted stream prettification into
`py/stream_json_prettify.py`, added the non-empty display-file regression, and
removed active embedded Python from source shell paths.

**What works in v1 today** (confirmed):

- `status`, `doctor`, `--dry-run`, `--last-run`, `--repair-state`,
  `--metrics`, `hud`, `engines`, `limits`,
  `replay`, `notify-health`, `notify-restart`, `init`, `decompose`,
  `scope-check`, `next`, and `validate-prd` are implemented as local CLI
  surfaces.
- Pre-v1 compatibility commands are not part of the public v1 source surface;
  fresh projects start directly in `.mainspring/`.
- Solo + team topologies for `taskmaster` and `night` modes remain the runtime
  shape; team mode now has visibility routing, bootstrap cleanup, and duplicate
  dispatch prevention.
- Auto-checkpoint keeps Lore trailers and denylist protections; final public
  history review remains normal git work outside Mainspring's public CLI.
- `.mainspring/logs/waves.jsonl` is the primary runtime ledger in fresh
  projects; older pre-v1 runtime state is read only as a compatibility input
  when already present.
- `MAINSPRING_*` env vars are primary; older pre-v1 env aliases remain
  compatibility inputs and emit deprecation warnings when used.

**What remains for publication**:

- The source-install path is public on `main`. The published history is short,
  readable, and free of local development artifacts; it is not from
  checkpoint-heavy working history.
- Completed external publication work: the final ref is pushed, the repository
  is public, GitHub metadata is set, hosted CI is green, GitHub Pages is live,
  and the draft GitHub Release uses notes from `CHANGELOG.md`.
- The remaining external step is ordinary maintainer signing work: create the
  signed `v1.0.0` tag on the clean commit and publish the GitHub Release.
- Homebrew, benchmark numbers, and real provider-matrix evidence are valuable
  follow-up credibility work. They are not normal operator commands and do not
  block the source-install repository.

**1000-point PRD score rule:** 900 points are reserved for product readiness:
implementation, tests, documentation, packaging smoke, installed CLI behavior,
HUD/Telegram usability, and security/public-repo hygiene. The remaining 100
points are reserved for publication checklist items. The current score
**900/1000** holds until the signed `v1.0.0` release is created from the final
clean commit.

---

## Naming and brand boundary

Three names that must never blur:

| Name           | What it is                                                                                                                                                  | Where it lives                                                                                  |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| **Mainspring** | This tool — the autonomous execution loop. The CLI binary, the runtime, the brand.                                                                          | Standalone `mainspring` repository; `mainspring.sh` plus packaged `mainspring` console entry point. Apache-2.0. |
| **Team backend** | External dependency — a separate team-orchestration CLI that Mainspring uses only for explicit `--topology team` runs. Not part of the normal solo path. | Wherever the backend CLI is installed on PATH. Mainspring depends on it for team topology only. |
| **Taskmaster** | External dependency — backlog source. Mainspring picks work from it.                                                                                        | `task-master` CLI + `.taskmaster/` directory.                                                   |

**The user-facing bag**:

- CLI binary: `mainspring` from `make install-user` / pipx, with `./mainspring.sh --project <path>` as the source-checkout fallback.
- Runtime state: `.mainspring/` for fresh projects.
- Env vars: `MAINSPRING_*` for runtime defaults.
- Config dir on user system: reserved for future global presets / quota cache. Runtime state stays project-local by default.
- Logs: `.mainspring/logs/`, JSONL feed `waves.jsonl`, latest-symlinks `latest.log` / `latest-summary.log`.

**Compatibility boundary:** `MAINSPRING_*` and `.mainspring/` are the public names. Older pre-v1 runtime names are not part of the public configuration contract; historical ledger/replay readers may still parse old recorded fields, but new launches use the Mainspring namespace.

---

## Target architecture

The v1 source tree is intentionally boring: one Bash entrypoint, small Bash modules,
tested Python helpers, committed docs, and gitignored project-local runtime
state.

### File layout

```
mainspring.sh                      # Bash entrypoint and CLI dispatch
lib/                               # Bash modules: lock, log, help, status,
                                   # doctor, notify, team, wave, wizard
py/                                # tested Python helpers and CLIs
  engines/                         # EngineAdapter implementations
  bench/                           # source-only SWE-bench helpers; not installed runtime
  tests/                           # pytest suite
tests/bats/                        # shell integration tests
docs/                              # README-linked operator, method, metrics,
                                   # architecture, PRD, and operator docs
method/                            # reusable Mainspring Method templates/skill
presets/                           # built-in run profiles
schema/                            # project config JSON Schema
packaging/homebrew/                # source-only Homebrew tap publishing runbook
.mainspring/                       # gitignored project-local runtime state
  logs/waves.jsonl                 # append-only wave ledger
  state/last-run.env               # safe saved setup, parsed without source
  state/notify-state.json          # Telegram dedup/rate-limit state
```

### CLI contract (frozen at v1.0)

```
mainspring [taskmaster|night] [flags]
  Modes:
    taskmaster                     read .taskmaster/ backlog, pick ready work
    night                          read PRD brief, writer chooses next slice

  Topology:
    --topology solo|team
    --pair <writer>+<reviewer>     e.g. claude+codex, gemini+claude
    --engine <name>                writer engine (when --pair not used)
    --review-engine <name>         reviewer engine
    --model <id>                   override writer model
    --review-model <id>            override reviewer model
    --speed-profile standard|fast|max
    --max-agents 1-6
    --once                         single wave then exit
    --prd <path>                   night mode PRD path

  Observe / inspect:
    hud [--once|--json|--local]    global live operator dashboard
    status                         runtime + git + scheduler + waves snapshot
    last-run [--format json]       show saved setup + repeat commands
    --metrics [--days N]           query waves.jsonl
    engines [--json]               registered engine inventory
    limits [engine ...] [--hours N] run-readiness, quota, and spend snapshot

  Setup / planning:
    init <name>                    scaffold Method PRD docs
    validate-prd <path>            validate Product Requirements Document shape
    decompose <prd-path>           turn one PRD phase into Taskmaster tasks
    next [tasks.json]              print next blocker-aware task id
    scope-check [tasks.json]       audit Taskmaster task shape

  Recovery / verification:
    doctor                         env + dependency sanity check
    stop --force [--all]           stop recorded Mainspring processes
    --repair-state --dry-run       preview stale runtime cleanup
    --repair-state --force         apply reviewed stale runtime cleanup
    --self-test                    one self-test wave on a synthetic task
    --self-test-all                full pair-mode matrix
    notify-test                    send sample Telegram notification
    notify-health [--format json]  inspect notifier daemon state
    notify-restart                 restart only the recorded notifier daemon

  Evidence / local maintenance:
    replay <show|diff|build|run>   inspect or reconstruct recorded waves
    --list-presets                 print available presets

  Run modifiers:
    --wizard                       interactive setup
    --last-run                     reuse .mainspring/state/last-run.env
    --restart-team                 destructive: reset active team backend state
    --preset <name>                load preset env
    --dry-run                      print resolved settings, no API calls
```

### JSONL wave schema (frozen at v1.0, schema_version=1)

`.mainspring/logs/waves.jsonl` — one JSON line per completed wave. Append-only via `flock` on `waves.jsonl.lock`.

**Required fields** (frozen — adding new ones is the only allowed change without a schema_version bump):

| Field       | Type                       | Description                                           |
| ----------- | -------------------------- | ----------------------------------------------------- |
| `ts`        | string (ISO-8601 UTC, `Z`) | wave completion timestamp                             |
| `mode`      | enum                       | `taskmaster` \| `night`                               |
| `engine`    | enum                       | writer engine: `codex` \| `claude` \| `gemini` \| ... |
| `wave`      | integer                    | 1-indexed wave counter within the run                 |
| `exit_code` | integer                    | writer exit code                                      |

**Standard optional fields** (always emitted, may be `null`):

| Field                    | Type           | Description                                                            |
| ------------------------ | -------------- | ---------------------------------------------------------------------- |
| `review_engine`          | enum           | reviewer engine                                                        |
| `model`, `review_model`  | string         | model ids                                                              |
| `pair`                   | string         | `<engine>+<review_engine>` for easy `jq` grouping                      |
| `task_id`                | string \| null | Taskmaster id                                                          |
| `work_id`                | string \| null | subtask id when applicable                                             |
| `topology`               | enum           | `solo` \| `team`                                                       |
| `team_name`              | string \| null | active team name when topology=team                                    |
| `duration_s`             | number         | wall-clock seconds                                                     |
| `product_files_changed`  | integer        | count from `count_product_file_changes`                                |
| `verdict`                | enum           | `PASS` \| `FAIL` \| `null` (review crashed)                            |
| `chapter_delta`          | string         | `+50` / `-3` / `0` style, signed                                       |
| `competitor_delta`       | string         | same                                                                   |
| `launch_delta`           | string         | same                                                                   |
| `product_score`          | integer        | 0–1000 rubric                                                          |
| `retry_used`             | boolean        | one-shot reviewer retry was triggered                                  |
| `failure_reason_class`   | string \| null | `routing:plugin_invisible`, `engine:quota`, `review:invalid_json`, ... |
| `codex_short_delta_pct`  | number \| null | usage delta as % of short window                                       |
| `claude_short_delta`     | number \| null | Claude usage delta                                                     |
| `gemini_short_delta_pct` | number \| null | future engines extend the same shape                                   |

**Schema versioning**: required fields are frozen. Removing or renaming one bumps `schema_version` and triggers a 90-day deprecation window where `wave_log.py` writes both old and new shapes.

### Concrete code shapes (load-bearing)

These are the current public contracts that anchor the architecture. The live
source tree is the root-level `mainspring.sh`, `lib/`, and `py/` layout.

#### `run_ai_turn(role, prompt, log, display)` — the engine dispatcher

```bash
# lib/engines.sh delegates command construction to py/engines/registry.py.
# Direct CLI engines (claude/codex) and provider engines (gemini, openai,
# anthropic, azure, openrouter, mistral, grok, ollama, litellm) all fail closed
# through the same registry readiness checks before a wave launches.
```

Adding a new engine means adding one adapter under `py/engines/`, registering
the default model/readiness contract, and covering it with registry tests.
Provider engines must never silently fall back to another provider, model, or
reviewer.

#### `acquire_lock` / `release_lock` — flock on fd 9

```bash
# lib/lock.sh
acquire_lock() {
  mkdir -p "$(dirname "$LOCK_FILE")"
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    local existing_pid
    existing_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
    echo "Mainspring already running (pid ${existing_pid:-unknown}); stop it or wait." >&2
    exit 1
  fi
  echo "$$" >&9
}
release_lock() {
  exec 9>&- 2>/dev/null || true
  if [ -f "$LOCK_FILE" ] && [ "$(cat "$LOCK_FILE" 2>/dev/null || true)" = "$$" ]; then
    rm -f "$LOCK_FILE"
  fi
}
```

The kernel auto-releases fd 9 on any exit (including SIGKILL), so the script can never leave a stale lock. The PID file content is purely advisory for human inspection.

#### `check_write_scope` — post-wave path guard

```bash
# lib/write_scope.sh
# Reads newline-separated changed file paths on stdin.
# Returns 0 if all paths are inside the allowed product scope.
# Returns 1 and prints offenders on stderr otherwise.
check_write_scope() {
  local offenders=()
  local path
  while IFS= read -r path; do
    [ -z "${path// }" ] && continue
    case "$path" in
      .env|.env.*|.secret|.secret.*|*/.env|*/.env.*|*/.secret|*/.secret.*)
        offenders+=("$path"); continue ;;
      node_modules/*|*/node_modules/*) offenders+=("$path"); continue ;;
      .git/*|*/.git/*)                  offenders+=("$path"); continue ;;
      dist/*|coverage/*|playwright-report/*|test-results/*)
        offenders+=("$path"); continue ;;
      src/*|apps/*|tests/*|e2e/*|docs/*|.taskmaster/*|scripts/*|shared/*|server/*|public/*|plugins/*)
        continue ;;
      *) continue ;;  # top-level dotfile-clean path tolerated
    esac
  done
  if [ "${#offenders[@]}" -gt 0 ]; then
    printf 'write_scope violation: %s\n' "${offenders[@]}" >&2
    return 1
  fi
  return 0
}
```

Invoked after the writer finishes, before review prompt build. Failure here forces a review-fail with reason `scope:violation`.

#### `parse_review.py` — required review JSON fields

```python
REQUIRED_FIELDS = (
    "verdict", "chapters", "chapter_delta", "competitor_delta", "launch_delta",
    "product_score", "strengths", "gaps", "next_actions", "verification_evidence", "rationale",
)
```

The reviewer is prompted to emit a fenced `json ... ` block. If absent, fall back to a Markdown `KEY: VALUE` parser (legacy v1 shape). If still missing required fields → review FAIL with reason `review:missing_fields:<key>` written to JSONL.

---

## Phase map

This is the historical implementation map that produced the current source
release. Completed items remain as audit trail; current release truth lives in
the verified snapshot above and the v1.0 checklist below. Each future phase must
end green: `make all`, targeted tests, docs updates, and fresh evidence.

### P-Audit — Release audit remediation (DONE 2026-05-03)

**Goal:** keep external release-audit findings executable through the Method
tooling without moving them out of Taskmaster.

- [x] **P-Audit-1f + P4.5-5 Make canonical PRD validate clean.** Preserve the
  ADR required subsection headings in `docs/prd.md`, keep the canonical PRD as
  the validator fixture, and verify `./mainspring.sh decompose docs/prd.md
  --phase P-Audit` completes without PRD validation errors.
  - 2026-05-03 completion status: Taskmaster task 1 is done; PRD validation and
    full local gates pass. Remaining PRD gaps are publication checklist items, not
    P-Audit validator cleanup.

### P0 — Reality reset (DONE 2026-04-26)

**Goal:** docs and disk match reality, no parallel planning artifacts.

- [x] Delete the unproven legacy prototype directory.
- [x] Delete the obsolete loop refactor scratch plan (Codex-authored).
- [x] Extract the old in-project loop script into the standalone root-level `mainspring.sh`.
- [x] Move the operator guide into the standalone repo as `docs/guide.md`.
- [x] Rename the old loop-script test file to the Mainspring naming convention and update legacy path references (42 occurrences).
- [x] Update CLAUDE.md, README.md, docs/execution/README.md, current-scope-program-update-plan.md, BIG-BACKLOG-ALGORITHM.md.
- [x] Add `.mainspring/` to `.gitignore`.
- [x] Write this PRD (now `docs/prd.md` after OSS extraction).
- [x] Formalize the Mainspring Method (now `docs/method.md` plus `method/` templates after OSS extraction).
- [x] Write the operational Playbook (now `docs/playbook.md`).
- [x] Renumber phases to insert P4.5 (Method tooling) for `mainspring init` / `decompose` / `scope-check` / `next` / `validate-prd` CLI commands.

### P1 — Critical bugs + portability (1-2 days, in place on `mainspring.sh`) — **🟢 ACTIVE since 2026-04-26**

**Goal:** stop the silent failures. The Claude→Claude review gate must demonstrably see writer output.

- [x] **P1-1 🔥 Fix SC2259 heredoc-overrides-pipe at lines 2454, 2641.** ✅ DONE 2026-04-26. Extracted Python pretty-print to [`py/stream_json_prettify.py`](../py/stream_json_prettify.py) (`--mode writer|reviewer`, SPDX Apache-2.0, ruff clean). Replaced both heredocs with `| CLAUDE_DISPLAY_FILE="$display_file" python3 "$MAINSPRING_PY_DIR/stream_json_prettify.py" --mode <role>` (env var inline, fixes SC2031 too). Also fixed root path resolution after standalone repo extraction. Verified: `bash -n` clean, `shellcheck -S error` returned 0 SC2259, heredoc count dropped, and smoke tests cover the canonical `CLAUDE_DISPLAY_FILE`-not-empty regression for the silent-failure bug.
- [x] **P1-2 Remove hardcoded `$HOME` path at line 84.** ✅ DONE 2026-04-26, hardened 2026-06-13. Replaced raw `$HOME` glob with allowlisted `fnm env --json` parsing when `fnm` is on PATH, keeping the glob as a fallback for systems without `fnm` binary. The launcher no longer evaluates generated shell code during PATH bootstrap. Added `fnm` to `doctor` as WARN (not FAIL). No hardcoded user paths remain.
- [x] **P1-3 Fix SC2155 / SC2034.** ✅ DONE 2026-04-26. Split all 5 `local x="$(date ...)"` into separate declare + assign (SC2155). Removed 5 dead variables: `status`, `phase`, `dead`, `total` from `active_team_status_summary`; `dispatched_any`, `idle_rounds` from `supervise_team_run` (SC2034). Result: `shellcheck -S warning` now returns **0 warnings** (was 11).
- [x] **P1-4 Verify gate works.** ✅ DONE 2026-04-26. Mainspring Wave 1 (`night --topology solo --pair claude+claude --once=false`) ran end-to-end against this PRD: writer streamed visible output via `stream_json_prettify.py`, reviewer hard-gate ratified with **exit code 0 (PASS)**, and the display file was non-empty. The current release evidence is the v1.0 verification snapshot above; pre-release loop paths are not part of the public contract.

**Acceptance:**

- `shellcheck -S error mainspring.sh lib/*.sh` = 0
- `shellcheck -S warning mainspring.sh lib/*.sh` = 0 or every warning is intentional and documented
- One real wave produces non-empty display file + meaningful reviewer rationale on **all 4 pair modes**

**Rubric impact:** correctness 95→140, portability 90→105.

### P2 — De-monolith (~2 weeks, incremental commits to feature branch)

**Goal:** main entry ≤ 500 LOC, no embedded Python, no duplication between writer/reviewer paths.

- [x] **P2-1 Extract all 9 heredocs** to `py/`. _(Complete — all strict `python3 - <<'PY'` heredocs extracted; the later broader heredoc cleanup is also complete.)_
  - [x] `wave_ledger` → `wave_log.py` (3 subcommands: append, last-summary, routing-hints)
  - [x] `usage_snapshot` → `engine_quota.py` (2 subcommands: codex, claude)
  - [x] `settings_persister` → `last_run.py` (2 subcommands: save, load)
  - [x] `dispatch_parallel_team_tasks` → `team_dispatch.py dispatch`
  - [x] `team_task_counts` → `team_dispatch.py counts`
  - [x] `nudge_pending_team_tasks` → `team_dispatch.py nudge`
  - [x] `requeue_stale_team_tasks` → `team_dispatch.py requeue`
  - [x] `engine_stream_handler` — confirmed both paths already use `stream_json_prettify.py` (P1-1)
- [x] **P2-2 Consolidate 8 `python3 -c` invocations** into one CLI: `py/team_status.py --field status|phase|dead-workers|usable-check`. All 8 callsites replaced.
- [x] **P2-1b Extract remaining 13 broader heredocs** (`python3 - <args> <<'PY'`). All 13 extracted:
  - [x] `taskmaster.py` (11 subcommands: status-summary, scope-summary, task-metadata, task-status, pick-work-item, parent-rollup, next, fallback-next, collect-parallel, team-skip-reason, scope-check)
  - [x] `prd_brief.py` (1 subcommand: build brief from PRD markdown)
  - [x] `runtime_state.py` (5 subcommands: team-status, runtime-summary, repair, cleanup-stale, find-latest-team)
- [x] **P2-3 Merge `run_engine` + `run_reviewer`.** Implement `run_ai_turn(role)` per the contract above. Extract `spawn_codex`, `spawn_claude` per-engine helpers. Extract `run_with_heartbeat(pid, label)` for the heartbeat loop. Delete `run_engine` and `run_reviewer`. _(Complete — `run_ai_turn`, `spawn_codex`, `spawn_claude`, `run_with_heartbeat` implemented in `lib/engines.sh`.)_
- [x] **P2-4 Split into bash modules** under `lib` per the layout above. Use `source` in `mainspring.sh`. Each module ≤ 600 LOC. Module-private helpers may not be called across module boundaries. _(Complete — 24 modules extracted to `lib`, `mainspring.sh` at 391 LOC, largest module `lib/help.sh` at 598 LOC, tied with `lib/team.sh`. Full local gate on 2026-06-16: pytest suite green, 1 skipped; 223 Bats; HUD/docs-site smoke and dependency audit OK.)_
- [x] **P2-5 Make hidden coupling explicit.** ✅ DONE 2026-04-26. The 5 audit offenders resolved: removed obsolete `STATUS_FILE`; documented the intentional trap globals; kept the settings persister encapsulated; converted `append_wave_ledger` and `auto_checkpoint_dirty_tree` from hidden global reads to explicit parameters; and documented the globals contract in `lib/common.sh`. Current v1.0 gates cover shell lint, Python tests, Bats, and packaging smoke.

**Acceptance:**

- `mainspring.sh` ≤ 500 LOC
- `shellcheck` clean on all `lib/*.sh`
- `bash -n` clean on every shell file
- `doctor`, `--self-test-all`, `--last-run` all still work
- Real wave succeeds end-to-end on all 4 pair modes
- No `python3 - <<'PY'` anywhere in the tree _(achieved — 0 heredocs of any form remain)_
- `python3 -c` only in calls under 80 chars and not in critical paths _(achieved — 0 `python3 -c` calls remain)_

**Rubric impact:** architecture 60→155.

### P3 — Tests + observability (~1 week)

**Goal:** safety net for aggressive P4–P7 refactors. Failing test fails the wave.

- [x] **P3-1 bats-core suite.** ✅ DONE 2026-04-26. 33 bats tests across 5 files (`test_common.bats`, `test_wizard.bats`, `test_wave.bats`, `test_review.bats`, `test_lock.bats`, `test_log.bats`). Covers: `apply_pair_mode`, `apply_default_models_for_current_pair`, `count_product_file_changes`, `count_nonempty_lines`, `print_limited_lines`, `format_epoch_local`, `review_output_hard_validate`, `extract_review_field`, `acquire_lock`, `build_review_prompt`, `append_review_ledgers`, `append_wave_summary`. `# Scenario:` + `# Expected:` convention. Tests skip cleanly on missing modules. `bash tests/bats/run.sh` all green.
- [x] **P3-2 pytest suite.** ✅ DONE 2026-04-26. 130 tests across 10 test files covering all 10 `.py` modules. Happy paths, edge cases, regression tests (SC2259 display_file non-empty regression, concurrent flock safety). Target was ≥35; achieved 130.
- [x] **P3-3 JSONL wave log.** ✅ DONE 2026-04-26. `wave_log.py append --ledger <path>` now atomically appends under an exclusive `flock` on `<path>.lock`. `log.sh` updated to use `--ledger` instead of shell `>>` redirection. Backward-compatible stdout fallback when no `--ledger` arg. 4 new pytest tests including concurrent-safety test (5 parallel writers, all 5 entries survive). `metrics.py` reader implemented (see P3-4). Current public metrics documentation lives at `docs/metrics.md`.
- [x] **P3-4 `--metrics` command.** ✅ DONE 2026-04-26. `py/metrics.py` implements all 7 standard questions: total waves, success rate, mean duration, top stuck tasks, mean chapter delta per pair, expensive waves, and pass rate per pair. Flags: `--days N`, `--since DATE`, `--format json|text`, `--pair X+Y`. Integrated into `mainspring.sh` as `--metrics [--days N] [--since DATE] [--pair X+Y] [--format json|text]`. Help text and pytest coverage lock compute, filter, format, and CLI paths.
- [x] **P3-5 Makefile + local CI.** ✅ DONE 2026-04-26. The root `Makefile` owns `shell-lint`, `ruff`, `pytest`, `bats`, `lint`, `test`, `all`, and `clean`. Verified by the current v1.0 gates: shellcheck OK, ruff OK, pytest green, Bats green, HUD smoke OK, and docs-site smoke OK.

**Acceptance:**

- `make all` from the repository root green
- ≥ 25 bats + ≥ 35 pytest passing _(current v1.0 evidence: 223 Bats and pytest suite green)_
- coverage ≥ 80% on `py/` _(achieved: `make coverage` reports 90.6%, above the 80% gate)_
- `waves.jsonl` populated by every wave _(achieved: flock-guarded append via `--ledger`)_
- `--metrics` answers all 7 questions above _(achieved: all 7 standard questions answered)_
- failing test in suite fails `--self-test-all`

**Rubric impact:** testability 55→135, observability 130→160.

### P4 — UX polish (~1 week)

**Goal:** "production ready" → "delightful to operate".

- [x] **P4-1 Structured review JSON.** ✅ DONE 2026-04-26. Created `py/parse_review.py` (JSON-strict parser with markdown `FIELD: VALUE` fallback, canonical fields, CLI with `parse`/`validate`/`field`/`shell-vars` subcommands). Updated `build_review_prompt()` in `lib/review.sh` to request fenced `json` as primary format, keeping legacy `FIELD: VALUE` as documented fallback. Replaced regex-scraping calls across review ledger append, hard validation, repair instructions, and field extraction with `parse_review.py` calls. Validation now produces specific error messages such as `missing FILES_TO_TOUCH` and `review:missing_fields:CHAPTERS`. Current v1.0 local gates cover this path.
  - 2026-05-03 hardening: `parse_review.py validate` now fails closed on malformed `PRODUCT_SCORE` values (`invalid_type:PRODUCT_SCORE`) and out-of-range rubric scores (`invalid_range:PRODUCT_SCORE`) instead of accepting any non-empty string. Verified by focused parse-review tests, review Bats, PRD validation, and the local gate at the time.
  - 2026-05-03 delta validation hardening: the same gate now rejects malformed `CHAPTER_SCORE_DELTA`, `COMPETITOR_DELTA`, and `LAUNCH_DELTA` values with `invalid_type:*` reasons instead of allowing non-numeric review-score evidence through. Verified by focused parse-review tests, review Bats, PRD validation, and the local gate at the time.
- [x] **P4-2 `--dry-run` mode.** ✅ DONE 2026-04-26. Standalone `--dry-run` prints resolved settings (mode, pair, engines, models, topology, speed, agents, paths), writer/reviewer command shapes, and dependency checks — zero API calls. Works with `--preset`, `--last-run`, and `--repair-state`. Integrated into `lib/wizard.sh` as `run_dry_run()` and covered by Bats plus Python tests.
  - 2026-05-04 last-run discoverability follow-up: `mainspring last-run` now shows the saved per-project setup without launching work, including `.mainspring/state/last-run.env`, saved timestamp, mode/topology/pair/models, speed/agents, PRD, CI retry settings, and exact repeat/preview commands. `mainspring --last-run` remains the execution resume path.
  - 2026-05-04 wizard resume follow-up: plain interactive `mainspring` now checks the saved per-project setup first, prints the same readable last-run summary, and offers `Continue with saved setup` before falling through to the normal manual wizard. Explicit `mainspring --last-run` remains the non-interactive resume command.
  - 2026-06-13 first-run hardening, polished 2026-06-14: plain `mainspring` now enters the guided setup surface even when stdin is not a TTY. Empty non-interactive stdin fails closed with explicit commands (`last-run` to inspect saved setup, `--last-run` to resume saved setup, `--dry-run --once` to preview defaults, and `init checkout-redesign` to scaffold PRD-backed starter docs with a replace-the-name hint) instead of falling through to `.taskmaster directory not found`. Verified by top-level Bats regressions and a fresh temp-project smoke.
  - 2026-06-09 command-alias hardening: user-facing noun commands `mainspring status`, `mainspring doctor`, and `mainspring notify-test` dispatch to the existing read-only/test paths. Compatibility flag spellings remain parser-only for old scripts and stay out of public help/docs. Verified by Bats dispatch regressions and help/README tests.
- [x] **P4-3 Presets.** ✅ DONE 2026-04-26. Created root-level `presets/` with `nightly-max.env`, `conservative-docs.env`, and `fast-smoke.env`. Loaded via `last_run.py` safe parsing (no `source`). `--list-presets` shows descriptions, and `--preset <name>` loads before CLI flag resolution so flags still win.
- [x] **P4-4 Public history review kept outside the CLI.** ✅ UPDATED 2026-06-15. Earlier pre-public builds included a publication-only history tool. It was removed from the runtime, package manifest, tests, and public docs before v1 because it was not product behavior and made the CLI look larger than the real operator workflow. Public history review now stays in normal git release-owner practice.
- [x] **P4-5 Failure reason taxonomy.** ✅ DONE 2026-05-03. `failure_taxonomy.py` standardises `failure_reason_class` values on `routing:*`, `engine:*`, `review:*`, `scope:*`, and `team:*`, upgrades legacy bare classes, and owns the routing-failure action policy. Recoverable team visibility failures fall back to solo; non-recoverable task-scoped routing failures block Taskmaster with the same machine-readable code. Team preflight consults this policy before applying a Taskmaster block, and `metrics.py` uses the same normalisation helper for repeat-failure clusters. Current v1.0 gates cover taxonomy, ledger, metrics, Taskmaster, team, and full local CI.
- [x] **P4-6 Worktree visibility routing rule.** ✅ DONE 2026-05-03. Team mode skips Taskmaster items whose declared scope matches `MAINSPRING_TEAM_EXCLUDE_PREFIXES` or the pre-v1 compatibility alias, emits `routing:plugin_invisible` as the recoverable team skip reason, and falls back to solo per ADR-02. `doctor` now scans for nested `.git` roots and warns when a nested repo path is not covered by the exclude prefixes, while reporting OK for covered paths and the compatibility alias. Verified by `python3 -m pytest py/tests/test_taskmaster.py -q` (39 passed), `bats tests/bats/test_doctor.bats` (4 passed), `bash -n lib/doctor.sh`, and `shellcheck -S warning lib/doctor.sh tests/bats/test_doctor.bats`.
  - 2026-05-03 local helper worktree hardening: `.claude/` is now a built-in team exclude prefix, so local Claude/Codex helper worktrees do not trigger doctor visibility warnings and cannot be selected for git-worktree fanout. Operator-configured exclude prefixes remain additive. Current v1.0 gates cover Taskmaster, doctor, and full local CI.
- [x] **P4-7 Bootstrap auto-close.** ✅ DONE 2026-05-03. `team_dispatch.py close-bootstrap` closes active non-`Task Master ...` bootstrap tasks by claiming pending tasks when needed and transitioning them to completed; Taskmaster work and already-completed bootstrap tasks are ignored. Verified by `py/tests/test_team_dispatch.py`.
- [x] **P4-8 Duplicate dispatch prevention.** ✅ DONE 2026-05-03. `team_dispatch.py dispatch` persists a per-team dispatch ledger keyed by Taskmaster id, refreshes from active team tasks, blocks automatic redispatch for pending/in-progress/completed/failed ids, records failed create attempts, and allows explicit `--retry-task <id>` overrides. Verified by `py/tests/test_team_dispatch.py`.

**Acceptance:**

- review parser fails specifically (`missing_field:CHAPTERS`, `invalid_type:PRODUCT_SCORE`) — no silent passes _(achieved: 39 pytest tests)_
- `--dry-run` makes zero external API calls (verified via `strace`/test fixture) _(achieved: 3 bats tests confirm output + zero API calls)_
- presets cover 3 flag combos (`nightly-max`, `conservative-docs`, `fast-smoke`), loaded via safe parsing _(achieved: 4 bats tests)_
- public history review remains outside the public CLI surface
- a wave that violates team worktree visibility records `failure_reason_class=routing:plugin_invisible` and falls back to solo
- a non-recoverable task-scoped routing failure records `failure_reason_class=routing:scope_blocked` and blocks the Taskmaster item
- two team tasks for the same id can't both be `pending`

**Rubric impact:** safety 110→132, UX 70→95.

### P4.5 — Mainspring Method tooling (~1 week)

**Goal:** make the Mainspring Method (the doctrine-first dev flow at [`docs/method.md`](method.md)) executable as Mainspring CLI subcommands. Today the Method is documented plus CLI-assisted; this phase made its key steps callable from the CLI so operators (and future Mainspring waves themselves) can invoke them programmatically.

The Method package source lives under `method/` and ships as part of the Mainspring OSS release. CLI commands in this phase wrap those templates and validators.

- [x] **P4.5-1 `mainspring init <name>`.** ✅ DONE 2026-05-03. `py/method_init.py` scaffolds `docs/<slug>/prd.md` from the Method PRD template, creates `.mainspring/state` and `.mainspring/logs`, records `active-prd.json`, initializes Taskmaster when available, and fails closed when the template or Taskmaster bootstrap is missing. Verified by `py/tests/test_method_init.py` and top-level Bats dispatch coverage.
  - Create `docs/<name>/prd.md` from `method/templates/prd.md` with `{{Project}} = <name>` substituted.
  - Run `task-master init` if `.taskmaster/` doesn't exist.
  - Create `.mainspring/` runtime state dir.
  - Print next-step hints (`run mainspring doctor`, `apply the Method to write the PRD`, etc.).
- [x] **P4.5-2 `mainspring decompose <prd-path>`.** ✅ DONE 2026-05-03. `py/decompose.py` validates PRDs, parses the Phase Map, selects requested or active phases, emits deterministic Taskmaster prompt plans, classifies manual blockers, and can idempotently apply generated tasks to a Taskmaster tasks file with backups and digests. Verified by `py/tests/test_decompose.py` and Bats top-level dispatch/apply coverage.
- [x] **P4.5-3 `mainspring scope-check`.** ✅ DONE 2026-05-03. `taskmaster.py scope-check` audits active backlog items for vague titles, missing acceptance criteria, missing test plans, manual blockers in the wrong place, and oversized work. It exits non-zero for high-severity violations and reports clean backlogs as zero violations. Verified by `py/tests/test_taskmaster.py` and Bats top-level dispatch coverage.
  - Flag tasks with vague titles ("improve X", "clean up Y").
  - Flag manual-blocker tasks NOT in the last phase.
  - Flag tasks without acceptance criteria.
  - Flag tasks without test plans.
  - Flag tasks > half-day estimated effort (must split).
  - Print a violations report; exit non-zero if any high-severity violations.
- [x] **P4.5-4 `mainspring next` (blocker-aware).** ✅ DONE 2026-05-03. `taskmaster.py next` skips blocked tasks and unmet dependencies, returns ready subtasks, and prefers tasks in the active PRD phase from `.mainspring/state/active-prd.json`. Verified by `py/tests/test_taskmaster.py` and Bats top-level dispatch coverage.
- [x] **P4.5-5 PRD-shape validator.** ✅ DONE 2026-05-03. `py/prd_validate.py` validates the 17-section PRD shape, unresolved placeholders, Current Truth Snapshot source commands, ADR required subfields, and Backlog Won't coverage. `mainspring validate-prd docs/prd.md` passes and `decompose` uses it as preflight. Verified by `py/tests/test_prd_validate.py`.
- [x] **P4.5-6 Method package shipped with Mainspring OSS release.** ✅ DONE 2026-05-03. The extracted repo includes `method/` with the Method skill, templates, install script, and README. Public README frames the Method as a first-class feature and links `docs/method.md`. Verified by `py/tests/test_public_readme.py` and Method template presence.
  - 2026-05-03 release-doc reconciliation: `docs/method.md`, the Method skill, Method README, Method PRD templates, and the Playbook now reflect the shipped P4.5 CLI reality (`mainspring init`, `decompose`, `scope-check`, `next`, `validate-prd`) instead of describing those commands as unshipped roadmap work. Verified by `py/tests/test_method_docs.py` plus the focused docs gate.

**Acceptance:**

- `mainspring init demo-feature` produces a valid `docs/demo-feature/prd.md` skeleton, `.taskmaster/` initialised, `.mainspring/` state dir present.
- `mainspring decompose docs/prd.md` produces a Taskmaster backlog matching the PRD's current phase structure (idempotent — second run produces no new tasks).
- `mainspring scope-check` on a backlog containing one "improve dashboard" task flags it; on a clean backlog reports "0 violations".
- `mainspring validate-prd docs/prd.md` exits 0 (the Mainspring PRD is the canonical example and must validate clean against its own validator).
- `mainspring next` skips tasks marked `blocked` and tasks with unresolved dependencies.
- Method package documented in Mainspring's public README at extraction time.

**Rubric impact:** Method productization +30, UX 95→110.

### P5 — Observability and engine support (~1.5 weeks)

**Goal:** the three big features the operator wants for the OSS release.

- [x] **P5-1 Telegram notifications.** ✅ DONE 2026-04-27. Created `py/notify_telegram.py` (watch/send/test subcommands, SPDX Apache-2.0, ruff clean). Event classes: `wave_failed`, `retry_loop`, `loop_stopped`, `quota_warn`, `team_stuck`, `milestone`, and `daily_digest`. Per-event rate limiting and persistent dedup state live in `.mainspring/state/notify-state.json`. Daemon failure never blocks a wave. `lib/notify.sh` owns daemon start/stop/reap and `run_notify_test`; `mainspring.sh` integrates `notify-test`, `notify-health`, auto-launch, and cleanup. Env: `MAINSPRING_TELEGRAM_BOT_TOKEN`, `MAINSPRING_TELEGRAM_CHAT_ID`, `MAINSPRING_NOTIFY_ENABLED`.
  - 2026-05-03 recovery hardening: `mainspring notify-health [--format text|json]` now reports disabled, unconfigured, healthy, starting, stale, and config-error states with canonical `next_step` guidance; `mainspring notify-restart` replaces only the recorded notifier PID after validating that the process command belongs to the current runtime ledger. The stuck-daemon playbook now routes operators through `notify-health` → `notify-restart` → `notify-test` instead of broad process-name kills. Verified by `python3 -m pytest py/tests/test_notify_telegram.py py/tests/test_hud.py -q` (173 passed), `bats tests/bats/test_notify.bats tests/bats/test_wizard.bats` (74 passed), `bash -n mainspring.sh lib/notify.sh lib/help.sh`, `shellcheck -S error mainspring.sh lib/notify.sh lib/help.sh tests/bats/test_notify.bats tests/bats/test_wizard.bats`, `ruff check py/notify_telegram.py py/tests/test_notify_telegram.py py/tests/test_hud.py`, and `python3 py/prd_validate.py docs/prd.md`.
  - 2026-05-03 acceptance evidence: the watcher has direct regressions for burst failure batches: unrelated failed waves send one `wave_failed` alert with suppressed duplicates, while repeated failures for the same task promote to one stronger `retry_loop` alert. In both paths the watcher advances `last_line_count` through the whole batch and does not block the wave path. The killed-daemon acceptance remains covered by `tests/bats/test_notify.bats::start_notify_daemon recovers from killed daemon pid`, which removes a dead recorded PID, starts a replacement, and returns success. Verified by `python3 -m pytest py/tests/test_notify_telegram.py::TestWatchLoop::test_watch_fifty_failures_do_not_flood_wave_failed -q` and the notify Bats gate.
  - 2026-05-04 project-context hardening: Telegram event messages now include `Project:` from the watched runtime ledger root and `Tag:` from `MAINSPRING_TASKMASTER_TAG` or `.taskmaster/state.json` when Taskmaster context is present. This makes simultaneous Mainspring runs distinguishable in one Telegram chat. Current v1.0 gates cover notifier regressions and full local CI.
  - 2026-05-04 idle-stop alerting: the wave loop now appends an explicit `STOP` ledger row when it exits after the idle streak threshold, and the Telegram watcher emits `loop_stopped` with project/tag/task/reason context. This fixes the prior blind spot where the daemon processed final `IDLE` rows but sent no terminal notification. Verified by notifier pytest and notify Bats coverage.
  - 2026-06-09 operator payload hardening: actionable Telegram events now include `Folder:` plus task, pair, result, reason, next action, and duration fields where the wave ledger has them. `retry_loop` and `team_stuck` alerts now point at the latest affected task/pair instead of only saying that something is stuck. This fixes the multi-project operator gap where one Telegram chat could not reliably tell which checkout, tag, and run needed attention.
  - 2026-05-04 shutdown drain hardening: cleanup now waits briefly for an owned notifier daemon to drain pending ledger lines before reaping it. This closes the race where the idle-threshold `STOP` row was written but the watcher was killed before its next poll. Verified by Bats coverage plus local log/state diagnosis from a live project runtime.
  - 2026-05-04 actionable retry-loop alerting: when the latest ledger state is already a retry loop, the watcher sends one `retry_loop` message before per-wave events and suppresses duplicate `wave_failed` noise for that batch. Retry-loop messages now include the reason plus project-local `Open:` and `Stop:` commands when the watched ledger root is known. Verified by notifier pytest coverage.
- [x] **P5-2 HUD / dashboard.** ✅ DONE 2026-05-03. `mainspring hud` dispatches to `py/hud.py`, a read-only terminal HUD with text, JSON, watch, and Rich Live render modes. Snapshot panels cover current wave, recent waves, today-style metrics, quota gauges for Codex / Claude / Gemini, Telegram notifier health, ledger health, and active team state. Flags include `--once`, `--watch`, `--rich`, `--json`, `--since`, `--width`, `--interval`, and bounded `--iterations`; there is no web port or mutation control. Runtime dependency `rich>=13.7,<15` is declared in `requirements.txt`. Verified by `python3 py/hud.py --json --once --ledger .mainspring/logs/waves.jsonl --state-dir .mainspring/state | python3 -m json.tool`, Rich renders at widths 80 and 200, `py/tests/test_hud.py` coverage in `make all`, and the `hud-rich-smoke` Makefile gate.
  - 2026-05-04 operator HUD polish: `mainspring hud --rich --watch` now renders the live Rich dashboard instead of rejecting the documented flag combination. HUD snapshots include the watched project folder, current/recent wave started and stopped times, and recent waves sorted newest stopped first. Verified by `python3 -m pytest py/tests/test_hud.py -q`, `./mainspring.sh hud --rich --watch --iterations 1 --interval 0 --width 120`, installed global `mainspring hud --rich --watch --iterations 1 --interval 0 --width 120`, and full `make all`.
  - 2026-05-04 usability follow-up, refreshed 2026-06-13: plain `mainspring hud` now opens the live dashboard in an interactive terminal, captured/scripted output remains one-shot, stale `session.json` cwd no longer overrides the watched runtime folder, long wave IDs are compacted in the Rich table, and normal recovery surfaces now point at current-project `mainspring stop --force` instead of promoting cross-project process cleanup. Verified by focused HUD/state/README tests plus full `make all`.
  - 2026-05-04 global operator follow-up: plain `mainspring hud` is now a machine-level operator dashboard, not a current-folder-only view. It discovers live Mainspring work processes from process commands/cwd plus runtime roots; rows show live status, folder, PID, Taskmaster tag, task, wave, pair, started/last stopped time, verdict, Telegram state, and team state. Stale known runtimes are opt-in via `mainspring hud --all-runtimes`; the old single-project dashboard remains available as `mainspring hud --local` or explicit `--ledger` / `--state-dir`. Verified by focused global HUD tests plus full `make all`.
  - 2026-05-04 default-live follow-up: interactive plain `mainspring hud` now promotes to the Rich watch dashboard even though the shell wrapper injects global seed paths; captured output remains a finite one-shot for pipes, tests, and scripts. Verified by focused HUD CLI tests, Bats dispatch coverage, installed CLI smoke, and full `make all`.
  - 2026-05-04 operator-state follow-up, refreshed 2026-06-09: global HUD rows now distinguish process liveness from operator health with human labels (`Running`, `Waiting`, `Blocked`, `Failed`, `Stopped cleanly`) while preserving stable machine state values in JSON. Rows surface failure reason, consecutive failed waves, and next action. The wave scope filters also ignore generated build caches and runtime SQLite sidecars (`build/`, `.gradle/`, `target/`, frontend caches, `*.db-wal`, `*.db-shm`) so successful Gradle/Vitest verification no longer fails the reviewer gate only because test/build tools touched generated output.
  - 2026-05-04 progress follow-up: HUD snapshots now include a lightweight read-only project progress signal. Taskmaster leaf tasks for the active tag are counted first, ignoring cancelled items; if Taskmaster files are absent, the HUD falls back to Product Requirements Document (PRD) checkbox completion. Global and local HUD views surface the resulting `Progress` value so the operator can see broad movement without reading logs. Verified by focused HUD tests and CLI smoke.
  - 2026-06-12 interrupt hygiene follow-up: `Ctrl-C` / `KeyboardInterrupt` in live HUD modes now exits cleanly with status 130 instead of printing a Python traceback after the Rich panel. Regression coverage exercises both plain `--watch` and Rich live modes, and the installed CLI was verified with a real `SIGINT` smoke.
  - 2026-06-14 public snapshot polish: captured global HUD output now uses the same operator language as the Rich dashboard: `View: all projects on this machine`, `needs action` counts, multiline run cards, `Folder`, `Tag`, `Task`, `Progress`, `Result`, `Reason`, `Telegram`, and `Next` fields. Stale global-scope wording, vague attention labels, and dense key/value debug-line styling are removed from public snapshots and the committed HUD demo/preview assets. Verified by focused HUD/README/hygiene tests and source CLI snapshot smoke.
  - 2026-06-12 process-boundary follow-up: every Python CLI entrypoint now routes through shared interrupt handling, with direct subpackage entrypoints covered by local `KeyboardInterrupt` guards. Operator interrupts now consistently exit 130 instead of leaking Python tracebacks; notifier watch persists state before exiting 130. A repo-wide static test prevents new naked `__main__` entrypoints from bypassing this contract, and packaging metadata ships `cli_runtime.py` both as an installed module and as a `share/mainspring/py` runtime helper.
- [ ] **P5-3 Multi-engine provider support.** Superseded by P-Comp-1's LiteLLM-backed engine registry rather than a bespoke plugin protocol. Code-side support now routes Gemini, Grok, OpenAI, Anthropic, Azure, OpenRouter, Mistral, and Ollama through provider adapters, with missing modules or credentials failing closed instead of silently falling back. Remaining market follow-up: run at least one real non-author provider wave, preferably Gemini, against a docs-only task with explicit credentials.

**Acceptance:**

- Telegram daemon survives 50 consecutive wave failures without flood; sends 1 message + 1 dedup-suppressed log line per remaining failure
- Telegram daemon kill -9 → wave loop unaffected
- `mainspring hud` runs cleanly on a populated `waves.jsonl`; `--json` output round-trips through `jq`
- adding `engines/grok.py` requires zero changes to `engines.sh` or `wizard.sh`
- `mainspring --pair gemini+claude --once` runs end-to-end against a docs-only task

**Rubric impact:** observability 160→185, ergonomics 95→120, extensibility +20 (new axis).

### P6 — Metrics-driven routing (~1 week)

**Goal:** the routing default (which pair, which topology) gets chosen by data, not preference.

- [x] **P6-1 Extend JSONL fields.** ✅ DONE 2026-05-03. `wave_log.py` emits the additive v1 fields `topology`, `team`, `team_name`, `failure_reason_class`, `task_status_before`, and `task_status_after` without a schema bump. `failure_reason_class` is derived from explicit values or failure prefixes for routing readers. Verified by `py/tests/test_wave_log.py` coverage in the focused routing gate.
- [x] **P6-2 Routing report.** ✅ DONE 2026-05-03. `mainspring --metrics --routing` now reports pass rate by pair, pass rate by topology, mean duration by task class, repeat-failure clusters, cost per chapter delta per pair, 14-day chapter-delta-per-dollar values, and auto-disable candidates. Verified by `python3 -m pytest py/tests/test_metrics.py -q` (22 passed), `mainspring --metrics --routing --format json --days 365 | python3 -m json.tool`, and the focused 127-test routing/LiteLLM/ledger gate.
- [x] **P6-3 Auto-disable rule.** ✅ DONE 2026-05-03. `metrics.py --routing --update-disabled-pairs` writes `.mainspring/state/disabled-pairs.json`, preserves manual reactivation, and only recommends lower-cost/fast lanes below 70% of the 14-day median chapter-delta-per-dollar value. `run_wizard()` hides auto-disabled default pairs and offers manual override. Verified by `py/tests/test_metrics.py` and `tests/bats/test_wizard.bats` coverage; live production disablement remains data-dependent.
- [x] **P6-4 Daily digest content.** ✅ DONE 2026-05-03. `build_daily_digest()` now emits data-derived digest lines for total waves, pass rate, mean duration, total cost, current quota status, disabled pairs, top 3 stuck task ids, tokens by pair, role tokens by pair, top 3 cost waves, and cost-per-positive-movement metrics. Cost truth prefers ledger `cost_usd` / `total_cost_usd`; if absent, it estimates only from known model prices + token counts and labels estimated rows. Verified by `python3 -m pytest py/tests/test_notify_telegram.py py/tests/test_notifier_recovery_docs.py -q` (140 passed), including P-Comp-5 calendar-day acceptance coverage.

**Acceptance:**

- `--metrics --routing` answers "which pair is best for tests today" with a number + sample size
- a deliberately bad pair (e.g. `claude-haiku+claude-haiku`) auto-disables after 14 days of underperformance
- the daily digest contains zero hand-written prose

**Rubric impact:** observability 185→210, decision quality +30.

### P7 — Repo extraction + GitHub release (1-2 days)

**Goal:** Mainspring ships as its own Apache-2.0 OSS repo on GitHub as a
clean source-install v1.0 release. The current public release procedure is the
single checklist in [v1.0 GitHub release checklist](#v10-github-release-checklist);
older scratch bootstrap commands are not part of the public contract.

- [x] **P7-1 Internal renames.** ✅ DONE 2026-05-03. One-pass mechanical cleanup across the now-modular tree:
  - pre-v1 env aliases → `MAINSPRING_*` (with backwards-compat: read both, log deprecation for one minor version, drop in v1.1.0)
  - pre-v1 runtime paths → `.mainspring/` (fresh public projects start directly in `.mainspring/`; no public compatibility helper ships)
  - All prose mentions of the legacy product name → "Mainspring"
  - Internal log labels (`[claude]` → unchanged because those are engine names, NOT the tool name)
  - 2026-05-03 completion status, reconciled 2026-06-13 for public v1: operator-facing runtime defaults read `MAINSPRING_*` first with compatibility fallback. Runtime-root resolution is centralized: fresh projects use `.mainspring/` for logs/state/team/lock/last-run paths. Historical extraction shims are not part of the public source surface. Helper fallbacks in status/team/doctor/self-test default to `.mainspring` when sourced without top-level launcher globals. Current v1.0 gates cover status/team/wizard regressions, PRD validation, and packaging/SPDX checks.
  - 2026-05-03 prose cleanup closure: literal legacy product-name search now returns no matches outside ignored runtime/build directories. Focused verification passed with `bats tests/bats/test_common.bats` (8 passed), `python3 -m pytest py/tests/test_mainspring_bootstrap.py py/tests/test_public_readme.py py/tests/test_prd_validate.py -q` (27 passed, 1 skipped), `bash -n lib/common.sh mainspring.sh`, `shellcheck -S warning lib/common.sh mainspring.sh`, and `python3 py/prd_validate.py docs/prd.md`.
  - 2026-05-03 standalone command cleanup: operator-facing generated commands now target the extracted repo contract (`./mainspring.sh`, `mainspring`, and root-level `make all`). Covered surfaces: Method init next steps, PRD decomposition writer prompts, replay command reconstruction, stale-process cleanup matching, Method task templates, and the operator playbook. Legacy process patterns remain only where needed for migration or safe cleanup.
- [x] **P7-2 Source tree.**
  ```
  mainspring/                        # repo root
  |-- mainspring.sh                  # entry script
  |-- lib/                           # bash modules
  |-- py/                            # python helpers and pytest suite
  |-- presets/                       # env presets
  |-- schema/                        # project config schema
  |-- tests/bats/                    # bash test suite
  |-- tests/golden-runs/             # replay regression fixtures
  |-- docs/
  |   |-- architecture.md
  |   |-- competitive-analysis.md
  |   |-- method.md
  |   |-- metrics.md
  |   |-- guide.md
  |   |-- playbook.md
  |   |-- prd.md
  |   `-- assets/
  |-- Makefile
  |-- README.md                      # quickstart + screenshots + GitHub flair
  |-- LICENSE                        # Apache-2.0 boilerplate
  |-- NOTICE                         # mandatory under Apache-2.0
  |-- SECURITY.md                    # vulnerability reporting policy
  |-- CONTRIBUTING.md                # how to add an engine adapter, run tests
  |-- CHANGELOG.md                   # starts at v1.0.0
  |-- .github/workflows/ci.yml       # shellcheck + ruff + bats + pytest matrix
  `-- .gitignore
  ```
- [x] **P7-3 Apache-2.0 hygiene.** `LICENSE` + `NOTICE` files. SPDX header on every source file: `# SPDX-License-Identifier: Apache-2.0`. Third-party deps (`rich`, `pytest`, `ruff`, `shellcheck`, `bats-core`) listed in `NOTICE`. No copyright on the author personally — copyright "Mainspring contributors" so future PR authors don't need a CLA.
- [x] **P7-4 Public README.** ✅ DONE 2026-05-04, refreshed 2026-06-14. `README.md` is a GitHub-facing landing page with release badges, a committed visual hero (`docs/assets/readme-hero.svg`), explicit current GitHub source install instructions, generic PATH guidance for `~/.local/bin`, plain-language positioning, green/red badge decision tables, one-command start (`mainspring`), concise default `mainspring --help` plus full `mainspring help --full` contract, Product Requirements Document (PRD) explanation, vibe-coding tradeoff framing, key-feature table, HUD and Telegram sections, copy/paste commands, engine support matrix, canonical docs links, and no unsupported release-management CLI commands. The committed HUD preview and asciinema demo now use the same public snapshot vocabulary as the actual CLI and avoid stale table/debug output. Verified by `python3 -m pytest py/tests/test_public_readme.py py/tests/test_hud.py py/tests/test_no_hardcoded_paths.py -q`, `make release-check`, `make install-user`, source/global CLI smoke, SVG render smoke, and JSONL parsing of the asciinema cast.
- [x] **P7-5 GitHub publication procedure.** The source tree is already a
  standalone repository. Publication uses the maintained checklist below:
  run local gates, publish only the reviewed final release commit, make the repository
  public, set the Product Requirements Document (PRD)-first description and
  topics, ensure a signed `v1.0.0` tag exists on the final clean commit, and
  publish a GitHub Release from `CHANGELOG.md`. Keep publication as ordinary
  GitHub work; do not add release-only Mainspring commands.

**Acceptance:**

- The GitHub repository is public, Apache-2.0, and has the production-grade
  PRD-first description plus discovery topics.
- `git clone <repo> <fresh-dir> && cd <fresh-dir> && make all` green from a
  fresh clone.
- `mainspring --help` works on a fresh box with only `bash`, `python3`, `git` installed (other deps reported by `mainspring doctor`)

**Rubric impact:** packaging +50 (new axis), distributability +30.

---

## Architecture decisions (ADRs)

Six load-bearing decisions. Each is reversible only at high cost; each is documented here so future maintainers can read them and either re-confirm or override.

### ADR-01: License = Apache-2.0

**Context:** Mainspring will become public OSS. License choice is permanent (changing later requires CLA from every contributor).

**Options considered:** MIT (simplest), Apache-2.0 (explicit patent grant), BSD-2-Clause.

**Decision:** Apache-2.0.

**Rationale:** Mainspring is infrastructure tooling (runs for life), not a 200-LOC library. The patent grant matters because: (a) the engine-adapter pattern is novel-ish; (b) someone could fork Mainspring, patent the adapter approach, and try to enforce against the original. Apache-2.0 blocks that. Mature dev tools (Terraform, Kubernetes, k6, Bun, Vite) default to Apache-2.0; matching that signals enterprise readiness and lets teams adopt without legal review. MIT is simpler but loses the patent grant for no practical gain.

**Consequences:** every source file gets an SPDX header; `NOTICE` file required; copyright held by "Mainspring contributors" (no CLA, future contributors implicitly accept under §5).

**Reversal cost:** very high (relicensing public OSS requires every contributor's consent). Get this right now.

### ADR-02: Nested-repo strategy = configurable team-exclude

**Context:** Operators sometimes have nested git repos (submodule-style, ignored nested checkouts) inside their workspace. Team workers operate in worktrees that don't see those nested repos; team-mode dispatch of nested-repo-scoped tasks would silently fail.

**Options considered:** ignore nested repos and let reviewer failure catch it; force all nested-repo work to solo manually; auto-detect nested git roots on every dispatch; expose an explicit exclude-prefix knob.

**Decision:** Mainspring exposes `MAINSPRING_TEAM_EXCLUDE_PREFIXES` plus a pre-v1 compatibility alias as a colon/comma-separated list of path prefixes that team mode skips. `.claude/` local helper worktrees are excluded by default, and operator-configured prefixes are additive. Team mode skips matching Taskmaster items with `failure_reason_class=routing:plugin_invisible`. Such work routes to the solo lane, which sees the nested repo because it runs in the leader workspace.

**Rationale:** generic exclusion is a one-line, fully-tested guard; the operator decides which paths are nested-repo or team-invisible per project.

**Consequences:** team mode may leave some ready tasks untouched when their scope matches an exclude prefix; operators must keep the prefix list honest per project. Doctor and routing reports must make skipped scopes visible so the skip is never silent.

**Reversal cost:** low — change the env var.

### ADR-04: Model policy = always premium

**Context:** routing decision — keep fast/mini lanes for low-risk docs-only work, or force every wave through the most capable model?

**Options considered:** always premium; low-risk docs-only lanes; dynamic pair selection by recent metrics; manual per-wave model choice.

**Decision:** always premium. Default models: Codex `gpt-5.5` with `reasoning_effort=xhigh`; Claude `opus`; Gemini `gemini-2.5-pro`. No "fast" lane is shipped as a default preset.

**Rationale:** Mainspring's mission is high-quality autonomous execution. Cheaping out on a docs task that the reviewer then has to re-do costs more cycles than running premium once. The user explicitly chose this. Future engines must default to their flagship model.

**Consequences:** the P6 metrics-driven auto-disable rule is restricted to _non-default_ lanes that an operator explicitly enabled. Premium pairs are never auto-disabled.

**Reversal cost:** low — change defaults in `wizard.sh`.

### ADR-05: Team failure semantics = both `failed` + `blocked`

**Context:** when a team task fails for a non-recoverable routing reason attached to a Taskmaster item (for example an explicit scope block or stale empty parent), what state goes where? Recoverable preflight visibility skips are covered by ADR-02 and route to solo instead of blocking the backlog.

**Options considered:** mark only the team backend task failed; mark only the Taskmaster item blocked; retry indefinitely with the same routing; dual-mark both systems with the same machine-readable reason.

**Decision:** for non-recoverable task-scoped routing failures, mark the team backend task `failed` (with `failure_reason_class` recorded in the team ledger and `waves.jsonl`), AND mark the Taskmaster item `blocked` (with the same machine-readable reason in the task body). Supervision must not re-dispatch a known-blocked item until the operator clears the block manually. Recoverable reasons such as `routing:plugin_invisible` are logged as failed team-preflight rows and then processed by the solo lane.

**Rationale:** dual-marking gives the operator two views of the same fact: the team metrics show "this team had N routing failures of class X" (useful for triage), and Taskmaster shows "task #42 is blocked because Y" (useful when picking next work). Single-marking either way loses one of those views.

**Consequences:** blockers become explicit operator work instead of hidden scheduler state; clearing a false-positive block requires manual Taskmaster action. Metrics can group by `failure_reason_class` across both ledgers because the same code is written to both places.

**Reversal cost:** medium — would require unwinding the dispatch ledger schema.

### ADR-06: Auto-checkpoint policy = keep recovery commits out of public history

**Context:** Mainspring's auto-checkpoint commits operational state during fanout (using Lore trailers + denylist). Final history quality depends on the operator reviewing checkpoints and publishing semantic commits.

**Options considered:** disable auto-checkpoint entirely; keep operational checkpoint commits as final history; auto-squash without asking; keep checkpointing and document public-history review.

**Decision:** keep auto-checkpoint as-is, but keep public-history preparation outside the Mainspring CLI. The operator uses normal git review and semantic commits before publication.

**Rationale:** auto-checkpoint preserves work without operator intervention, which is the whole point of autonomous execution. Manual finalization preserves history quality, which is the point of OSS publication. Doing both means the worst-case path still has an auditable trail of what happened, while the happy path ships clean semantic commits.

**Consequences:** operators get durable recovery points during autonomous fanout, but PR branches still require final history review. Mainspring does not expose a public history-rewrite command.

**Reversal cost:** low — this keeps history tooling outside the product surface.

### ADR-07: Implementation language strategy = Bash for orchestration, Python for structured data

**Context:** Mainspring orchestrates AI agents through subprocesses (Codex, Claude, Gemini CLIs), parses their structured outputs (stream-json events, review verdicts), manages tmux + worktree fanout, and reads/writes JSONL state files. The natural shape spans two very different concerns: **shell glue** (process spawning, pipes, signal handling, fanout) and **structured data** (JSON parsing, schema validation, formatted reporting). Choosing one language for both means losing the other's strengths.

**Options considered:**

1. **Bash only.** Verified painful in v1: 4644 LOC monolith, 9 embedded `python3 - <<'PY'` heredocs that produced the canonical SC2259 silent-failure bug, 8 inline `python3 -c '...'` parsers, JSON munging through a sed/awk underbelly. The whole P0+P1+P2 effort exists _because_ this approach was untenable.
2. **Python only.** Clean tests, single language, async streaming via Anthropic/OpenAI SDKs, idiomatic for AI-agent tools (Aider, GPT Engineer, Mentat, Claude Engineer all chose Python). But: subprocess+pipe plumbing is verbose (`Popen` with stdin/stdout PIPE + signal handling = ~3× the bash-equivalent LOC); tmux + worktree fanout is awkward through `subprocess`; loses Bash's "pipe is a first-class verb" feel.
3. **Go.** Single binary, no runtime dependency, fast startup, strong concurrency primitives. But: build pipeline required (cross-compile per platform), every release becomes a binary distribution problem, maintainers would have to own CI for releases; raises the adoption barrier from "git clone, run" to "download binary or set up Go toolchain".
4. **Rust.** Same upside as Go but more packaging and contributor friction than this local operator tool needs.
5. **Node/TypeScript.** Awkward as shell-glue (everything goes through `child_process.spawn`); npm dependencies in an OSS CLI tool is an anti-pattern; would clash with the planned `pip install` distribution path.
6. **Bash + Python (current).** Bash for what it's good at; Python for what it's good at; explicit CLI boundary between them; both pre-installed on every macOS/Linux developer workstation; zero build step. The split that organically emerged from the v1 → v2 refactor.

**Decision:** **Bash + Python, with a strict CLI boundary.**

- **Bash** owns: orchestration (`mainspring.sh` + 23 modules in `lib/`), CLI flag parsing, process spawning, pipes, signals, tmux + worktree fanout, lockfile management, log directories.
- **Python** owns (`py/*.py`): JSON parsing (stream-json prettify, review verdict parsing, runtime-state queries), JSONL emission (`wave_log.py`), schema validation, taskmaster query helpers, team-dispatch JSON mangling, engine quota snapshots, safe env-file loading.
- **Boundary:** Bash invokes Python via real CLIs (`python3 py/<name>.py --flag value`), never via embedded heredocs. Python modules accept all input via argv/stdin/explicit env vars; no ambient config. Each Python CLI is independently testable with pytest.

**Rationale:**

- Bash is the right shape for orchestration. Spawning two processes, piping their outputs through `tee` and a transformer, backgrounding with `&`, waiting on PIDs — these are bash one-liners. The same logic in Python is `subprocess.Popen(stdin=PIPE, stdout=PIPE, ...)` plus thread/select juggling. P2-3's `run_ai_turn` is 30 lines of bash; the equivalent Python would be 80–120 lines and a class.
- Python is the right shape for structured data. Every `.py` module does one thing: parse, validate, format. The current pytest suite gives broad parser, formatter, runtime-state, package, docs, and release-surface coverage with zero ceremony. Equivalent bash would be 3× the LOC and far weaker assertions.
- The CLI boundary kills the v1 anti-pattern. The SC2259 bug existed because Python was embedded as a heredoc _inside_ bash; the heredoc clobbered stdin and the writer's stream silently dropped. With real `.py` files invoked through subprocess, the boundary is explicit, contract-bound, and unit-testable. The bug is structurally impossible to recreate.
- Zero build step matters for adoption. The current honest public path is `git clone https://github.com/dlogvinenko/mainspring.git`, `cd mainspring`, `make install-user`, then `cd <project>` and `mainspring`; direct PyPI and Homebrew installs are future distribution work. Source checkouts still work with `./mainspring.sh --project <path>`. Adding Go/Rust would require either a cross-platform release pipeline or `go install`/`cargo install` as install instructions, both of which add friction before the source-install path has public usage. Bash + Python is what `direnv`, `asdf`, `nvm` ship as, and they have lived for a decade.
- The current maintenance stack already includes Bash and Python, and both are common on developer workstations. A Go/Rust rewrite would force another primary language onto the maintenance surface before the source-install path has public adoption.
- **2026-05-03 trigger note:** P-Comp-1 has activated re-evaluation trigger #1. Engine command construction and provider dispatch are now Python-owned through the registry + LiteLLM runner; Bash still owns pipes, process supervision, and log capture. The live provider evidence remains credential-gated and must not be faked.

**Consequences:**

- Two languages to lint and test (`shellcheck` + `bash -n` for shell, `ruff` + `pytest` for Python). The Makefile (P3-5) absorbs this — one `make lint test` runs everything.
- Distribution is source-first: `git clone`, `make install-user`, then run the global `mainspring` command from any project. `method/install.sh` installs only the optional Method skill. Direct PyPI and Homebrew channels remain follow-up distribution work after the source release.
- AI-agent ecosystem norms (Aider, GPT Engineer, etc. → Python) are noted but not followed. Mainspring's identity is "shell-orchestrator that calls Python helpers", not "Python AI agent".
- Provider adapters now live in Python behind the registry + LiteLLM runner; bash side stays minimal.

**Reversal cost:** **medium-to-high** for a full rewrite to pure Python; **trivial** for incremental Python expansion (e.g. moving more bash logic into Python on a per-module basis). The boundary is designed to allow incremental migration if we ever decide to go pure Python — bash would shrink module by module while CLI calls stay stable.

**Re-evaluate when:**

1. We need async streaming directly through Anthropic/OpenAI SDKs (skipping the `claude -p` / `codex exec` CLIs). At that point a pure-Python rewrite becomes attractive because the SDKs are Python-first.
2. We want `pip install mainspring` as a distribution channel after the v1.0 OSS source release.
3. We want a real plugin system for engines (Python entry_points beats bash sourcing).

Until any of those three triggers, the current split is the right shape. **Bash for shell, Python for data.** Each language gets the work it was designed for.

---

## Operational doctrine

How to actually use Mainspring in daily work. This is the lived contract; see `guide.md` for the full command reference.

### When to use solo vs team

Default to **solo** unless the explicit reason for team is satisfied:

- > 4 ready Taskmaster items with non-overlapping scope, AND
- leader workspace is clean (or only `.taskmaster/` dirty), AND
- no scope-blocked items in the head of the queue, AND
- no plugin/nested-repo items in the head of the queue.

Otherwise solo. Solo is faster to debug, doesn't require tmux capacity, and produces the same quality output for single-item work.

**Rule of thumb:** if solo would finish the queue faster than team would even _start_ (because of fanout overhead), pick solo.

### Pair selection (until P6 metrics override)

| Goal                                      | Pair                                  | Why                                                                                  |
| ----------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------ |
| Maximum quality, no speed concern         | `claude+codex` (opus + gpt-5.5 xhigh) | best writer + best reviewer; differing model families catch each other's blind spots |
| Same family double-check                  | `claude+claude` or `codex+codex`      | useful when one provider is rate-limited                                             |
| Most reasoning needed (complex refactors) | `codex+codex` xhigh                   | Codex with xhigh effort and Codex review is the highest-effort lane                  |
| Fastest decision (only when single-step)  | `claude+claude`                       | Claude's tool-calling is faster than Codex round-trips                               |

After P6 lands, consult `mainspring --metrics --routing` and use the data, not the table.

### Reading `--metrics`

Metrics ignore malformed JSON and non-object JSONL rows. Included objects remain in totals when `exit_code` is missing or invalid; success requires `PASS` and an actual integer `0` (not Boolean, string, null or float). Time filters require usable zoned timestamps; the ledger writer emits UTC/Z and readers accept explicit offsets. Without a time filter, timestamp shape does not exclude rows. A date-only `--since YYYY-MM-DD` still starts the window at midnight UTC. Three signals matter most:

1. **Pass rate per pair, last 14 days.** If a pair drops below 70%, investigate before another wave on it. Below 50% → auto-disable should have kicked in (P6).
2. **Top 5 stuck task ids.** A stuck task = ≥3 consecutive FAIL waves. Promote stuck tasks out of the queue: either manual review, switch pair, or mark `blocked` with a reason.
3. **Mean duration trend.** Sudden 2x increase = engine quality degrading or task complexity drifting.

### When to `--restart-team`

Only when the team is provably stuck and `--repair-state --dry-run` doesn't reveal a recoverable cause. `--restart-team` preserves worker heads under `refs/mainspring-preserve/...` before resetting, so it's not destructive — but it does reset team backend state. Use it as a last resort.

### Auto-checkpoint discipline

Auto-checkpoint commits during fanout are operational; review and squash them before publication. **Never** push those checkpoints directly to a PR branch — they are short-lived recovery checkpoints, not release history.

### Cost awareness without cost guardrails

Per ADR-04, no cost guardrail. The operator's daily-digest Telegram message (P5-1) shows total spend; the operator decides when to pause. The combination of premium-only lanes + visible daily spend + manual stop is sufficient for a single-operator tool.

---

## Health rituals

Two recurring checks. The intent is small enough to actually do; the consequences of skipping are large enough to make the discipline worthwhile.

### Weekly (≤ 10 min)

1. `mainspring --metrics --days 7` — check pass rate per pair, top stuck tasks.
2. `mainspring doctor` — confirm dependencies + git state clean.
3. `wc -l .mainspring/logs/waves.jsonl` — sanity that the JSONL is growing.
4. Review local git history before pushing public work.
5. If the daily digest noted any disabled pairs, either re-enable manually with reason or accept and move on.

### Monthly (≤ 30 min)

1. Run the weekly ritual.
2. Read the last 4 weeks of `.mainspring/logs/notifier.log` — look for retry-loop events; investigate any task that retry-looped 3+ times.
3. Run `make all` from the repository root — must be green.
4. Audit `.mainspring/state/disabled-pairs.json` — pairs that have been auto-disabled for > 30 days should be either re-enabled or removed from the registry entirely.
5. Skim the last 30 days of `waves.jsonl` for any `failure_reason_class` value that's new — every value should map to a known taxonomy entry in P4-5.

---

## Disaster recovery

Six failure modes that have happened or are likely to happen, with concrete recovery steps.

### `.mainspring/` corrupted (e.g. partial write of `waves.jsonl`)

**Detect:** `mainspring --metrics` errors with `Invalid JSON at line N`.

**Recover:**

```bash
mv .mainspring/logs/waves.jsonl .mainspring/logs/waves.jsonl.corrupt
jq -c '.' .mainspring/logs/waves.jsonl.corrupt > .mainspring/logs/waves.jsonl 2>/dev/null
# or, more aggressive — keep only well-formed lines:
grep -v '^$' .mainspring/logs/waves.jsonl.corrupt | while IFS= read -r line; do
  echo "$line" | jq -e . >/dev/null 2>&1 && echo "$line"
done > .mainspring/logs/waves.jsonl
```

### Dead host mid-wave

**Detect:** lock file shows pid that no longer exists; `mainspring status` shows in-progress wave with timestamp > 30 min old.

**Recover:** run `mainspring --repair-state --dry-run` first. If the preview
only touches stale runtime bookkeeping, run `mainspring --repair-state --force`,
then resume normal flow. Because flock is fd-based, the OS already released the
lock when the host died.

### Runaway loop (wave count climbing without progress)

**Detect:** `--metrics` shows ≥10 consecutive FAIL waves on the same task, or `mainspring hud` shows `STUCK` / repeated `RETRY` with the same task. Telegram should have already surfaced one actionable `retry_loop` event.

**Recover:** use the retry-loop notification's `Open:` command to inspect the local HUD/log. If it is genuinely stuck, use the notification's `Stop:` command or `mainspring stop --force`; mark the offending task `blocked` in Taskmaster with `failure_reason_class=manual:runaway`; investigate offline. Resume after the block clears.

### Stale worktrees / zombie tmux panes

**Detect:** `mainspring doctor` warns; `git worktree list` shows worktrees pointing to non-existent paths.

**Recover:** start with `mainspring --repair-state --dry-run`. If git itself
reports stale worktrees, run `git worktree prune`. For team backend state, use
`mainspring --last-run --restart-team` only after checking the preserved worker
heads that Mainspring reports. Avoid broad tmux cleanup; kill only a specific
session after manually confirming it is unrelated to active work.

### Lock without owner (rare; only happens if `flock` is unavailable on the platform)

**Detect:** `mainspring` exits immediately with "already running" but no process matches the recorded pid.

**Recover:** run `mainspring --repair-state --dry-run`, then
`mainspring --repair-state --force` only if the preview identifies the lock as
stale. Mainspring will re-acquire on next launch. If this happens repeatedly,
`mainspring doctor` should be flagging missing flock support; install
`util-linux` or the platform equivalent.

### Telegram daemon stuck

**Detect:** `.mainspring/logs/notifier.log` has not appended in > 1 hour despite waves continuing.

**Recover:** run `mainspring notify-health --format json`. If it reports `next_step=restart-notifier-daemon`, run `mainspring notify-restart`, then `mainspring notify-test` to confirm Telegram delivery. `notify-restart` only stops the PID recorded for this runtime's notifier after validating the process command and current ledger path; do not use broad process-name kills because they can kill another project's notifier.

---

## Versioning and migration

### SemVer policy

Mainspring follows strict SemVer from v1.0.0 onward:

- **MAJOR**: removing/renaming a CLI flag, removing a JSONL required field, removing an env var, breaking the `EngineAdapter` Protocol.
- **MINOR**: adding a CLI flag, adding a JSONL field, adding an engine adapter, adding an env var.
- **PATCH**: bug fixes, doc updates, internal refactors with no public surface change.

### Schema versioning (JSONL)

`schema_version=1` for v1.0.0–v1.x. To bump to `schema_version=2`:

1. Add the new shape to `wave_log.py append`. Emit both shapes for 90 days (overlap window).
2. Update `metrics.py` to read both versions.
3. Document the new shape in `docs/metrics.md` with a compatibility note.
4. After 90 days, drop emission of the old shape; readers continue to support it for one more major version.

### Env var deprecation

Renaming an env var into the `MAINSPRING_*` namespace in P7:

1. Read both for one minor version.
2. If the old one is set and the new one isn't, log a stderr deprecation notice once per process.
3. After one minor version, drop reading the old one.

### Runtime state note

Public v1 writes `.mainspring/` directly. Pre-v1 private runtime trees are outside the public operator path.

---

## v1.0 GitHub release checklist

Mainspring's source-install product gate is the local gate below. Public
publication is ordinary GitHub repository work, not a hidden CLI workflow and not
a Mainspring subcommand. There is no public release subcommand for this on
purpose: after the verified source tree is ready, publish the reviewed final
release commit, make the repository public, sign the tag, and create the GitHub
Release. The public `main` branch, hosted CI, and hosted docs are already live;
Homebrew, benchmarks, and provider-matrix evidence are follow-up credibility
steps.

Before the maintainer publishes or republishes a release commit:

```bash
make release-check
```

`make release-check` is intentionally boring: it runs `make all`, package
smoke, Python coverage, Product Requirements Document (PRD) validation, and
`git diff --check`. It performs no GitHub mutations, no tag creation, no
provider calls, and no hidden release-state updates.

Then the owner publishes from a reviewed release commit:

- Confirm the repository history intended for public release is clean. Public source
  history must not contain local paths, private project names, memory artifacts, tokens,
  screenshots, or runtime ledgers.
- Push the final release ref with a GitHub credential that has `workflow` scope
  when workflow files are present. Done for the clean public `main` commit.
- Confirm the GitHub repository description and topics match the public
  positioning, then set repository visibility to public. Done on 2026-06-15.
- Create a signed `v1.0.0` tag on the exact release commit.
- Publish the GitHub Release using `CHANGELOG.md` as the release-note source.
  The draft release is already retargeted to the clean commit.

Package-manager distribution, benchmark numbers, and live provider matrix
evidence are follow-up credibility work, not requirements for the first
source-install release. Hosted docs are already published at
`https://dlogvinenko.github.io/mainspring/`.

### Correctness

- [x] `shellcheck -S warning` clean on all `*.sh` (zero errors, zero warnings; no exceptions) _(`make all`: shellcheck OK)_
- [x] `bash -n` clean on all `*.sh` _(`make all`: bash -n OK)_
- [ ] `ruff check` + `ruff format --check` clean on all `*.py` _(Ruff 0.17.3 reports 410 findings already present on public baseline `4d365cc`; all 93 Python files are formatted)_
- [x] Built-in writer/reviewer pair modes resolve through the public CLI and self-test surfaces _(Bats pair parsing, engine command construction, `--self-test`, and `--self-test-all` coverage; real provider-matrix evidence is follow-up credibility work)_
- [x] Review gate demonstrably receives writer output (no SC2259 regression) _(P1-4 real wave evidence + `make all` stream/review regression tests)_

### Architecture

- [x] Main entrypoint ≤ 500 LOC _(442 LOC including bounded signal cleanup; verified by `wc -l mainspring.sh` on 2026-10-30)_
- [x] Zero `python3 - <<'PY'` heredocs _(all extracted in P2)_
- [x] No `python3 -c` invocations longer than 80 chars _(all consolidated in P2-2)_
- [x] No duplicated writer/reviewer engine paths _(unified `run_ai_turn` in `lib/engines.sh`)_
- [x] All bash modules ≤ 600 LOC _(largest: `lib/help.sh` at 598 LOC; tied with `lib/team.sh`; verified by `wc -l lib/*.sh`)_

### Tests

- [x] ≥ 25 bats tests passing in < 30s _(223 Bats pass in `make all` on 2026-06-14)_
- [x] ≥ 35 pytest tests passing in < 30s _(pytest suite green, 1 skipped, in `make all` on 2026-06-14)_
- [x] ≥ 80% line coverage on Python modules _(`make coverage`: 90.6%, gate pass on 2026-06-16)_
- [x] CI matrix green on Linux + macOS _(local `.github/workflows/ci.yml` runs `make all` on `ubuntu-latest` and `macos-latest`; v1 release evidence is the hosted GitHub Actions run on the clean public `main` commit)_

### Observability

- [x] Every wave emits one valid `waves.jsonl` line _(flock-guarded `append --ledger`)_
- [x] `--metrics` answers all 7 standard questions _(130-test metrics module)_
- [x] `--metrics --routing` answers pair-effectiveness questions _(verified by `py/tests/test_metrics.py` and JSON CLI smoke)_

### Safety

- [x] No hardcoded user paths _(verified by `py/tests/test_no_hardcoded_paths.py`)_
  - 2026-05-03 portability hardening: the guard now scans the current standalone release tree (`mainspring.sh`, `lib/`, `py/`, `tests/`, `docs/`, `method/`, packaging metadata, and generated docs assets) instead of stale pre-extraction roots, and `docs/assets/hud-demo.cast` no longer embeds an absolute local user-home PRD path.
- [x] `flock`-based concurrency _(verified by `py/tests/test_fd_lock.py` + `tests/bats/test_lock.bats`)_
- [x] Write-scope whitelist enforced; `.env*` / `node_modules` / `.git` always rejected _(verified by `tests/bats/test_write_scope.bats`)_
- [x] Destructive ops require explicit `--restart-team` / `--repair-state --force` _(automatic team preflight now refuses worktree/state cleanup without `--restart-team`; stale process cleanup and state repair require `--force`; verified by `tests/bats/test_team.bats`, `py/tests/test_runtime_state.py`, shellcheck, and `bash -n`)_

### UX

- [x] `doctor` covers every external dependency _(`./mainspring.sh doctor` reports command deps, fd-lock fallback, Python `rich`/`pytest`, engine registry module/env requirements, notifier, Taskmaster, logs, and current WARN gaps)_
  - 2026-05-03 dependency hygiene: `doctor` treats `node_modules` as relevant only when `package.json` exists, and provider-engine module probes use the active virtualenv, repo `.venv`, or `MAINSPRING_PY` before falling back to `python3`. Credential setup rows no longer masquerade as missing Python modules when `litellm` is installed.
- [x] `--dry-run` makes zero API calls _(standalone mode prints resolved settings + commands, exits with no API calls)_
- [x] Presets cover the 3 common flag combos _(nightly-max, conservative-docs, fast-smoke in presets/)_
- [x] Telegram notifications work on all 7 event classes _(wave_failed, retry_loop, loop_stopped, quota_warn, team_stuck, milestone, daily_digest; actionable event payloads include project, folder, Taskmaster tag, task, pair, result, reason, next action, and duration context when available)_
- [x] `mainspring hud` renders cleanly on 80x24 and 200x60 terminals _(verified by `py/tests/test_hud.py` + `hud-rich-smoke`)_

### Portability

- [x] Fresh box: `git clone && make all` green without editing files
  - 2026-06-14 status refresh: the current worktree-local `make all` is green
    (pytest suite green, 1 skipped; 223 Bats; HUD/docs-site smoke and dependency
    audit OK). `make package-smoke`, `make coverage`, PRD validation, and
    `git diff --check` are also green on the current source line.
    Before tagging, rerun the same gates on the exact commit being released.
  - 2026-05-18 status refresh: the current worktree-local `make all` was green
    at the time; the current v1.0 snapshot above is the release-facing evidence.
  - 2026-05-04 clean-clone smoke: `make fresh-clone-smoke` ran from a clean published checkout, cloned the source into a disposable checkout, and ran `make all`.
  - 2026-05-03 local gate status: `make fresh-clone-smoke` now refuses dirty worktrees, clones clean `HEAD` into a temporary directory, and runs `make all` from the clone so local uncommitted state cannot masquerade as fresh-box evidence. Verified by `python3 -m pytest py/tests/test_fresh_clone_smoke.py -q` plus a direct fail-closed run against a dirty worktree.
  - 2026-05-03 standalone repo hygiene: the root `Makefile` now treats the checkout root as `ROOT`, so `make all` and HUD smoke targets do not read runtime state from outside a fresh clone. Regression coverage lives in `py/tests/test_fresh_clone_smoke.py`.
  - 2026-05-03 local agent worktree hygiene: `shell-lint` discovery now prunes `.claude/`, and team visibility defaults exclude `.claude/`, so local Claude/Codex helper checkouts cannot make `make all` lint unrelated worktree files or trigger team fanout warnings. Verified by the fresh-clone smoke regression, focused doctor/Taskmaster regressions, `./mainspring.sh doctor`, and the local gate at the time.
  - 2026-05-03 coverage-gate hygiene: `py/fresh_clone_smoke.py` now captures and replays child `make` output through Python streams so the stdlib trace coverage harness sees the same stdout/stderr shape as a real subprocess. Verified by `python3 -m pytest py/tests/test_fresh_clone_smoke.py -q`, `make coverage`, and `make all`.
  - 2026-05-03 evidence-artifact hardening: successful `make fresh-clone-smoke` runs now write `.mainspring/state/fresh-clone-smoke-evidence.json` with the clean source HEAD, source repo, target, command, and result so the eventual release evidence is auditable without trusting scrollback. The artifact is written only after the cloned `make all` passes; dirty-worktree and failed-clone paths still fail closed without producing an evidence file.
- [x] Local wheel + isolated pipx smoke passes from source checkout _(`make package-smoke`: sdist+wheel build, bootstrap tests green with 1 skipped, and 23 Homebrew formula tests passed; `make pipx-smoke`: 1 passed)_
- [x] Homebrew formula metadata is generated from explicit release inputs _(`py/tests/test_homebrew_formula.py`: validates URL/sha/version guards, pyproject-derived `python@X.Y`, Homebrew desc length, dependency shape, and Ruby syntax when `ruby` is installed)_
- [x] `mainspring doctor` runs on a box with only `bash`, `python3`, `git` installed _(minimal-PATH Bats fixture verifies missing `task-master` / team backend command stays WARN-only even with active team state; `doctor_active_team_report` no longer leaks command-not-found output)_
- [x] Provider adapters fail closed on missing modules, credentials, malformed responses, or unknown engine names _(real non-author provider evidence is follow-up market evidence after the source release)_

### Documentation

- [x] `README.md` answers how to install Mainspring, how users verify PATH visibility, why Mainspring exists, when to use it, how to start with `mainspring`, what HUD/Telegram/Product Requirements Document (PRD)-first execution provide, and where to go next
- [x] `docs/prd.md` is the canonical plan _(this file; see opening status and Mission source-of-truth language)_
- [x] `guide.md` is the operator reference
- [x] `metrics.md` documents the JSONL schema in full
- [x] `architecture.md` documents `EngineAdapter` Protocol + extension points
- [x] `CONTRIBUTING.md` walks through "add an engine adapter" as the canonical contribution
- [x] GitHub Pages docs source is generated from canonical docs and covered by a local smoke gate _(Pages is enabled and deployed at `https://dlogvinenko.github.io/mainspring/`; hosted Docs Site run `27561122958` passed on the clean public commit)_

### Legal

- [x] `LICENSE` = Apache-2.0 boilerplate, unmodified
- [x] `NOTICE` lists third-party deps with their licenses
- [x] SPDX header on every source file _(verified by `py/tests/test_source_license_headers.py`)_
- [x] Copyright = "Mainspring contributors", no individual

### Release

- [x] GitHub repository description and discovery topics are set
  - 2026-06-13 owner metadata evidence: the repository description is "Product
    Requirements Document (PRD)-first AI coding agent orchestration for
    production-grade software delivery." Discovery topics include
    `ai-coding-agent`, `coding-agent`, `agent-orchestration`, `prd`,
    `taskmaster`, `llm-agents`, `codex`, `claude`, `ollama`, `litellm`, and
    `developer-tools`. Repository visibility is public as of 2026-06-15.
- [ ] Signed annotated `v1.0.0` tag exists on the final clean release commit
  - 2026-06-15 owner action: import or unlock the maintainer GPG key, sign
    the clean public `main` commit, push the tag, then publish the prepared
    draft GitHub Release.
- [x] GitHub release notes pulled from `CHANGELOG.md`
  - 2026-06-15 release-note source status: `CHANGELOG.md` contains the v1.0.0
    release narrative, and the draft GitHub Release is retargeted to the clean
    commit with those notes.
- [x] GitHub repository page shows public Apache-2.0 status
  - 2026-06-15 evidence: `dlogvinenko/mainspring` is public, defaults to
    `main`, and exposes the Apache-2.0 source tree at the clean release commit.

---

## Explicit non-goals

These are things Mainspring will **never** become. Reject any change that moves toward them.

- **Not a multi-machine system.** Single host, single operator, single tmux. If you need fleet management, you need a different tool.
- **Not an OpenTelemetry citizen.** No distributed tracing. Single-host JSONL is the observability surface. Future export to Prometheus / OTel is a non-goal because Mainspring is not part of an SRE fleet.
- **Not Sentry-instrumented.** No exception aggregation service. Telegram notifications + `notifier.log` are the alerting surface.
- **Not a cost-governed tool.** No automatic spend caps, no budget enforcement. Per ADR-04 the operator runs premium models and watches the daily digest. Cost discipline is human, not automated.
- **Not a read-scope sandbox.** Mainspring trusts its own writer/reviewer agents to not leak secrets in summary logs. If that trust ever breaks, the response is a `secret-scan` post-wave hook, not a chroot/namespace sandbox.
- **Not a cross-machine resume tool.** If a host dies mid-wave, the wave is lost. The next host start re-picks the task from Taskmaster. No state replication.
- **Not a Linear / Jira / GitHub Issues integration.** Mainspring reads Taskmaster only. Wrapping a different backlog source is a fork, not a feature request.
- **Not a UI for managing waves.** HUD is read-only. No "kill wave" buttons, no "retry" buttons, no drag-and-drop. Operations are CLI-driven.
- **Not a public-server-exposed dashboard.** HUD is localhost only, no port, no auth. Anyone wanting remote access uses `ssh`.
- **Not a parallel writer-multiplexer.** One writer per wave. No fan-out across writers within a single wave. (Team mode runs _separate_ waves in parallel; that's not the same as one wave with N writers.)
- **Not a per-action approval tool.** Cline-style approve-every-command UX breaks the autonomous-loop ethos. Operators choose scope and gates up front; the reviewer and tests stop unsafe outcomes.
- **Not a demo-video generator.** Walkthrough videos are valuable in some agent platforms, but Mainspring's evidence surface is JSONL, review verdicts, tests, logs, and replay.
- **Not a second memory layer.** Taskmaster, PRDs, ledgers, and git history own durable state. Adding Mem0/Hermes-style session memory duplicates those contracts.
- **Not a community-growth product.** Discord or similar community operations are outside the personal-tool-to-OSS scope until real adoption creates a maintainer need.
- **Not a backwards-compatibility museum.** v0.x → v1.0 wipes history. From v1.0 onwards, deprecation windows are 90 days for schema changes, 1 minor version for env vars. After that, gone.

---

## Backlog (Must / Should / Could / Won't)

Ranked by value-per-effort. **Must** items block the source-install v1.0 code release; **Should** items ship in v1.x; **Could** are later candidates; **Won't** are explicit dead ends.

### Must (blocks source-install v1.0.0 code release)

1. P1-1 SC2259 fix (heredoc → real `.py`) — single highest-impact bug fix.
2. P1-2 Remove hardcoded `$HOME` path.
3. P2-1, P2-3, P2-4 Heredoc extraction + run_ai_turn merge + bash modularization.
4. P2-2 `python3 -c` consolidation into `team_status.py`.
5. P3-1 / P3-2 / P3-3 / P3-5 Tests + JSONL + Makefile.
6. P3-4 `--metrics` command at the standard-questions level.
7. P4-1 Structured review JSON (kills regex parsing in critical path).
8. P4-2 `--dry-run` mode.
9. P4-3 Presets.
10. P5-1 Telegram notifications.
11. P-Comp-1 LiteLLM multi-provider registry and fail-closed provider routing.
12. P7-1 → P7-6 Repo extraction, public README, and source-install release hygiene.

### Should (v1.x post-release)

1. P4-5 Failure reason taxonomy.
2. P4-6 / P4-7 / P4-8 Worktree visibility routing + bootstrap auto-close + dispatch ledger.
3. P5-2 HUD (rich-based TUI).
4. P6 Metrics-driven routing + auto-disable + daily digest.

### Could (v2 candidates, only if data justifies)

1. Web HUD (separate from TUI; only if multiple users ask).
2. Additional engines: Ollama (local), OpenRouter (multi-provider), Grok.
3. Property/fuzz testing on JSONL emitter.
4. Golden-file testing for review-prompt drift.

### Won't (explicit non-goals — do not propose)

- See [Explicit non-goals](#explicit-non-goals).
- Linear/Jira/GH Issues backlog adapter.
- Cost guardrails / hard spend caps.
- OpenTelemetry / Sentry integration.
- Read-scope sandbox.
- Multi-machine state sync.
- Cross-machine resume.
- Public web exposure.
- "Fast" model lanes as defaults.

---

## Phase P-Comp — Post-competitor-analysis amendments (2026-04-27)

**Goal:** apply the recommendations from [Appendix C — Competitor landscape](#appendix-c-competitor-landscape-competitive-positioning-june-2026-refresh) and [`docs/competitive-analysis.md`](competitive-analysis.md). Ratified 2026-04-27; 8 strong-recommend items + 5 considered items + 4 explicit skips.

**Strategic reframe (item 0 — applies to all subsequent work):** Mainspring is positioned as **Product Requirements Document (PRD)-first AI coding agent orchestration for production-grade software delivery**, NOT as "yet another autonomous coding agent". The Method remains the durable asset, but the public entry point must be understandable to people who do not already know the Method: one command to start, clear explanation of PRD vs. vibe coding, visible HUD, Telegram operations, hard reviewer gate, and evidence ledger. Direct competitors (Composio AO, OpenAI Symphony, Taskmaster autopilot) own the orchestrator-only niche; Mainspring's differentiator is making doctrine executable and auditable across any project.

### Strongly recommend (market evidence after the source-install release)

- [ ] **P-Comp-1 LiteLLM adoption (replaces P5-3 bespoke adapters).** Drop the hand-rolled provider branching in favor of the shared engine registry and LiteLLM provider adapter. Get Gemini, Ollama, OpenRouter, Mistral, Groq, Azure, OpenAI, and Anthropic via one abstraction. `py/engines/_base.py` and `py/engines/litellm_adapter.py` own the provider boundary; P5-3 task body rewrites point at LiteLLM instead of a bespoke shell plugin protocol.
  - 2026-05-03 code-side status: registry-routed LiteLLM and provider adapters exist for Gemini, Grok, OpenAI, Anthropic, Azure, OpenRouter, Mistral, and Ollama. `litellm_runner.py` writes usage/cost sidecars and now fails closed on malformed response shape before treating provider output as writer/reviewer text. Remaining market follow-up: install `litellm` in the runtime environment and run a real provider wave with explicit credentials. Missing dependencies or API keys affect that provider run only, not the source-install release.
  - 2026-05-03 dry-run remediation status: provider readiness preflight now aggregates missing setup and prints exact operator guidance such as `python3 -m pip install -r requirements.txt` and setting `GOOGLE_API_KEY` to the provider credential during `mainspring night --pair gemini+claude --dry-run`. This does not run the provider; it makes setup actionable before a real wave.
  - 2026-05-03 doctor remediation status: the shared engine inventory now emits `setup:` lines for missing LiteLLM modules and provider env vars, so `mainspring doctor` shows the same exact remediation without running a provider. Verified by focused engine-registry tests, doctor Bats, PRD validation, and the local gate at the time. This improves readiness visibility; it does not replace a real provider run.
  - 2026-05-03 interpreter consistency hardening: provider dry-run readiness and runtime LiteLLM command construction now use the same Mainspring Python resolver as doctor (`VIRTUAL_ENV`, repo `.venv`, `MAINSPRING_PY`, then `python3`). This prevents false `litellm` missing-module reports when dependencies are installed in the repo virtualenv, while still failing closed on missing provider credentials.
  - 2026-05-03 runtime remediation consistency: the live LiteLLM runner now uses the same missing-module remediation as doctor and dry-run (`python3 -m pip install -r requirements.txt`) before exiting closed. This still does not close the live provider evidence gap; it prevents the runtime failure path from giving weaker setup guidance than the preflight paths.
  - 2026-05-03 live credential preflight hardening: the live LiteLLM runner now checks known provider-model env vars before calling the provider, so a Gemini run without `GOOGLE_API_KEY` exits closed with the same actionable credential guidance used by doctor and dry-run. The shared LiteLLM provider mapping now feeds registry validation and runtime checks. Verified by `python3 -m pytest py/tests/test_litellm_runner.py py/tests/test_engine_registry.py -q`, `ruff check py/litellm_runner.py py/engines/litellm_adapter.py py/engines/registry.py py/tests/test_litellm_runner.py py/tests/test_engine_registry.py`, and `ruff format --check py/litellm_runner.py py/engines/litellm_adapter.py py/engines/registry.py py/tests/test_litellm_runner.py py/tests/test_engine_registry.py`. This keeps provider runs fail-closed; credentials and a real docs-only provider wave remain market-evidence work.
- [x] **P-Comp-2 `mainspring replay <wave-id>`.** ✅ DONE 2026-05-03. Implemented `py/replay.py` plus top-level `mainspring replay <show|diff|build|run>` dispatch. Replay reads wave rows from `waves.jsonl`, resolves canonical or legacy wave ids, reconstructs the CLI command, supports `--engine`, `--reviewer`, `--model`, `--review-model`, and `--save-as`, and records replay provenance through `wave_log.py` (`replayed_from`, `replay_overrides`, optional wave-id override). Deterministic prompt-backed replays fail closed on missing prompt snapshots, prompt hash drift, git HEAD drift, or dirty-tree drift unless the operator explicitly allows worktree drift; older rows require explicit `--allow-live-reconstruction`. Golden-run replay evidence preserves `chapter_delta`, `competitor_delta`, `launch_delta`, `product_score`, verdict, success state, and exit code; reviewer swaps surface drift in `replay diff`; the committed golden source row includes a prompt snapshot whose dry-run replay validates with `Real-run validation: OK` without launching a provider. Verified by `python3 -m pytest py/tests/test_replay.py py/tests/test_golden_run.py py/tests/test_wave_log.py -q` (123 passed), `bats tests/bats/test_wizard.bats tests/bats/test_log.bats` (42 passed), `python3 py/golden_run.py check-all tests/golden-runs` (OK), `python3 py/replay.py run golden-002-slice-impl tests/golden-runs/mainspring-prd-to-pr/waves.jsonl --dry-run --save-as golden-002-replay-smoke` (validation OK), `python3 py/replay.py diff golden-002-slice-impl golden-003-replay-evidence tests/golden-runs/mainspring-prd-to-pr/waves.jsonl`, and `ruff check` / `ruff format --check` on replay-related files.
- [ ] **P-Comp-3 SWE-bench-Verified score.** Run Mainspring on the SWE-bench-Verified benchmark, then publish the `%-solved` number in public docs only after a real result exists. The source tree keeps the validated runner script `py/bench/swe_bench.py`, but v1 no longer ships a public placeholder result page.
  - 2026-06-13 public-release cleanup: the empty benchmark result page was removed from the public docs site because benchmark collateral should appear only after real evidence exists. `py/bench/swe_bench.py` remains source-only benchmark tooling with focused tests and is not part of the installed `mainspring` runtime payload. Remaining benchmark work: generate real Mainspring predictions, run SWE-bench Verified in an explicit benchmark environment, then publish the actual `% resolved` number.
- [ ] **P-Comp-4 pipx + Homebrew distribution (extends P7).** Post-source distribution work: publish package-manager paths so users can install without cloning the repository. Ship `pyproject.toml` + entry point so `pipx install mainspring` works. Publish a Homebrew tap (`brew install <tap>/mainspring`). Bash entry script becomes a thin shim that the Python entry point invokes. The source-install release remains valid before these channels exist.
  - 2026-05-03 local packaging status: `pyproject.toml` declares the `mainspring` console entry point, runtime dependencies, and packaged data files for `mainspring.sh`, `lib/`, `py/`, `presets/`, `schema/`, and `method/`. `Makefile` now exposes `package-smoke` and `pipx-smoke` verification. Verified by package and pipx smoke tests. Remaining distribution work: publish package-manager metadata and capture an external fresh-box install.
  - 2026-05-03 Homebrew formula metadata status: `py/homebrew_formula.py` now generates `Formula/mainspring.rb` from explicit release version, tarball URL, homepage, sha256 inputs, and the `pyproject.toml` `requires-python` floor so formula `python@X.Y` cannot drift silently from package metadata. The formula keeps only runtime dependencies (`bash`, `git`, Python) and no longer declares unused `:test` dependencies; tests lock the Homebrew desc length, dependency shape, pyproject-derived Python version, and Ruby syntax. `packaging/homebrew/README.md` documents the tap publish sequence, including the required `brew update-python-resources mainspring` step for vendoring `rich`/`litellm` resources. Verified by focused formula tests, generated-formula Ruby syntax, ruff checks on formula files, and package smoke. Remaining distribution work: publish the tap and capture external `brew install <tap>/mainspring` output.
  - 2026-05-04 global editable CLI hardening, refreshed 2026-06-13: `Makefile` now exposes `install-user` / `dev-install`, runs `pipx ensurepath`, removes any old Mainspring pipx environment, and installs the current checkout as the user-level `mainspring` command. The Python console bootstrap marks pipx invocations with `MAINSPRING_CONSOLE_ENTRYPOINT=1`, so editable installs target the caller's project directory while direct `./mainspring.sh` source-checkout runs still require `--project` to control another repo. README, guide, and `--help` now document install-once/run-anywhere usage and the source-checkout `--project` fallback. Current v1.0 gates include global install smoke and bootstrap coverage.
- [x] **P-Comp-5 Daily cost digest in Telegram (extends P5-1).** ✅ DONE 2026-05-03. P5-1's daily 09:00 digest now uses the previous local calendar day and includes total spend, top-3 most expensive waves, tokens per pair, role-token breakdowns, cost per positive `chapter_delta`, cost per explicit or inferred `product_score` movement, uncosted movement callouts, quota status, and disabled pairs. Sources are ledger cost fields first, then a local explicit price table only when token counts and model ids are known; unknown models stay uncosted instead of fabricating spend. Verified by `test_comp5_daily_cost_digest_acceptance` plus the focused notifier suite (`140 passed`).

### Recommend (v1.x growth work after source release)

- [x] **P-Comp-6 YAML config + JSON Schema** (`.mainspring.yaml`). ✅ DONE 2026-05-03. Project-local config loads after presets and before execution, CLI flags win on conflict, lowercase aliases are accepted, and schema validation fails closed via `schema/config.schema.json`. The schema is included in the packaged data files. Verified by `py/tests/test_last_run.py`, `py/tests/test_mainspring_bootstrap.py`, and `tests/bats/test_wizard.bats`.
- [x] **P-Comp-7 GitHub Pages docs-site source and workflow.** ✅ DONE 2026-05-04, refreshed 2026-06-15. `py/docs_site.py` generates a Jekyll source tree from the committed canonical docs (`docs/prd.md`, `docs/method.md`, `docs/playbook.md`, `docs/guide.md`, `docs/competitive-analysis.md`, plus architecture and metrics pages) without duplicating a second planning source or publishing empty benchmark result pages. `.github/workflows/pages.yml` builds that generated source with `actions/jekyll-build-pages`, uploads the Pages artifact, and deploys only on `main` pushes after the repo owner enables GitHub Pages and sets `MAINSPRING_ENABLE_PAGES_DEPLOY=1`. Workflow permissions are least-privilege: build and pull-request runs keep read-only contents permissions, while `pages: write` and `id-token: write` exist only on the gated deploy job. `make docs-site-smoke` validates the generator output locally. Hosted Pages is live at `https://dlogvinenko.github.io/mainspring/` and returns HTTP 200 with SEO, Open Graph, and Twitter metadata. Verified by `python3 -m pytest py/tests/test_docs_site.py py/tests/test_ci_workflow.py py/tests/test_prd_validate.py -q`, `make docs-site-smoke`, hosted Docs Site run `27561122958`, and an HTTP smoke check against the published URL.
- [x] **P-Comp-8 Golden-run regression fixture.** ✅ DONE 2026-05-03. Created `tests/golden-runs/mainspring-prd-to-pr/` with a 3-wave PRD-to-PR ledger and deterministic `expected.txt`; `golden_run.py check-all` now has a committed scenario to diff in pytest. This gives replay/ledger behavior an end-to-end fixture without launching model CLIs.

**v1.x roadmap ownership:** P-Comp-6, P-Comp-7 local implementation and hosted publication, and P-Comp-8 are complete. Future hosted-docs work is limited to optional custom-domain polish; the default GitHub Pages site is already published.

### Considered (Could — v1.x or later, not blocking v1.0)

- [x] **P-Comp-9 `BacklogSource` plugin interface (Taskmaster + GH Issues + Linear).** ✅ DONE 2026-05-03. `py/backlog_source.py` defines the Python protocol (`list_ready_tasks`, `get_details(id)`, `mark_done(id)`, `mark_blocked(id, reason)`) and ships the Taskmaster JSON adapter only for v1.0. The existing `taskmaster.py next`/metadata/status read paths now exercise the adapter, while status mutations call the `task-master` CLI and fail closed on command errors instead of pretending the backlog changed. Packaged runtime metadata includes the new module. Non-Taskmaster adapters remain opt-in roadmap work, not v1.0 behavior. Verified by `python3 -m pytest py/tests/test_backlog_source.py py/tests/test_taskmaster.py py/tests/test_mainspring_bootstrap.py::test_pyproject_declares_pipx_console_entry_and_runtime_payload -q`.
- [x] **P-Comp-10 `--auto-retry-ci <N>` opt-in retry loop.** ✅ DONE 2026-05-03. Default remains `0` (current stop-on-fail behavior). When enabled, writer failures classified as `typecheck_fail`, `lint_fail`, or `test_fail` record `engine:<reason>` in the ledger, increment `retry_count`, keep the same Taskmaster item, and inject the captured failure-output tail plus optional `--auto-retry-ci-log` tail into the next writer prompt. The retry cap is enforced before each retry so the loop cannot run away. Verified by Bats coverage in `test_wave.bats` and CLI/dry-run coverage in `test_wizard.bats`; full `make all` includes both.
- [x] **P-Comp-11 Role-based agent modes (`--mode architect|code|debug|ask`).** ✅ DONE 2026-05-03. `--mode` is parsed by the CLI, saved/loaded through presets and `.mainspring.yaml`, shown in dry-run output, appended to the writer prompt, and passed into the reviewer lens. `architect` and `ask` are advisory no-edit modes: review hard validation rejects user file edits and keeps Taskmaster items in `review` instead of closing them. `debug` adds root-cause and targeted-verification discipline while `code` remains the default implementation lane. Verified by focused Bats coverage in `test_log.bats`, `test_review.bats`, and `test_wizard.bats`; full `make all` includes these paths.
- [ ] **P-Comp-12 Plugin entry-points via Python (replace bash `source`).** When LiteLLM (P-Comp-1) lands and proves the Python expansion path, revisit ADR-07: move engine + backlog adapters to `pyproject.toml` `[project.entry-points]` mechanism. v2 conversation; not v1.x. Triggers ADR-07 re-evaluation per the "trigger #3 plugin system" note.
- [ ] **P-Comp-13 Plausible-style anonymous opt-in telemetry.** Track only: wave count, pass-rate, version, OS. Default OFF. Aider and OpenHands do this. Lower priority because Mainspring has private-first ethos; revisit only after v1.0 OSS release if adoption signal demands it.

**Could-lane re-evaluation triggers:** P-Comp-9's core interface is complete; non-Taskmaster adapters become eligible when at least two alternate backlog sources are requested by real operators. P-Comp-12 becomes eligible only after P-Comp-1 proves Python provider dispatch in real waves. P-Comp-13 becomes eligible after public adoption creates a concrete maintainer question that anonymous counts would answer. P-Comp-9, P-Comp-10, and P-Comp-11 are already closed.

### Explicit skips (Won't — confirmed non-goals)

- **Per-action approval mode (Cline-style).** Breaks autonomous-loop ethos. Cline + Aider already serve that niche.
- **Walkthrough video artifact (Symphony-style).** Useful later, but heavy ops cost. Not v1.
- **Memory / context persistence between sessions (Mem0, Hermes).** Taskmaster owns state. Adding our own memory layer = duplication.
- **Discord community channel.** Personal-tool ethos. Per current PRD anti-goals. Revisit only if OSS adoption growth demands it.

### Acceptance for closing P-Comp

- [x] All source-release Must items complete and locally verified; remaining provider/benchmark/package evidence is tracked as follow-up growth work after the source release.
- [x] Should items (P-Comp-6 through P-Comp-8) on the v1.x roadmap with explicit owners + estimates.
- [x] Could items documented in Backlog with re-evaluation triggers.
- [x] Skips added to "Explicit non-goals" section above.
- [x] Mission section in this PRD updated with the Method-first reframe quoted in item 0.
- [x] README and docs-site entry explain Product Requirements Document (PRD)-first AI coding, vibe-coding tradeoffs, install path, one-command start, HUD, Telegram, and evidence-ledger value in plain language.

---

## Appendix A — Source-of-knowledge recipes

This appendix points future maintainers and AI agents at the current source of
truth. It is intentionally a map, not a second implementation plan.

### CLI truth

- `lib/help.sh` is the public help contract. Any new command or flag needs help text plus Bats coverage before it is documented elsewhere.
- PRD validation uses live headings, ADRs, truth tables and lanes, not fenced examples. Required ADR fields need nonblank value blocks, including multiline prose or code; short truth data rows without Source are reported. A heading-only Won't lane remains allowed. Passing is structural validation, not business or approval readiness.
- `lib/cli.sh` is the argument parser. Public command spelling lives there.
- `docs/guide.md` is the human-facing command reference. Its command tables group command families with complete runnable variants, not detached flags.
- Taskmaster dependency collections must be arrays when present and non-null. Malformed collections do not establish readiness; missing/null fields and empty arrays remain no prerequisites. Existing `done` checks and identifier matching stay unchanged in `py/backlog_source.py` and `py/taskmaster.py`.

### Runtime and logs

- `.mainspring/logs/waves.jsonl` is the wave ledger. Additive fields are OK;
  removal or rename needs a schema-version migration.
- `py/wave_log.py` owns ledger rows and failure context. Its readers skip malformed and non-object JSONL rows while preserving the existing verdict and routing interpretation of JSON objects.
- `py/replay.py` is the source of truth for reconstructing recorded waves. Each replay child derives its controls from the current source and invocation, including `--save-as`, ignores inherited replay-owned leftovers, and preserves the caller and unrelated runtime environment.
- `py/runtime_state.py` discovers live runtimes for HUD, status, and notifier recovery. It must not trust stale session cwd over a verified process cwd.
- `py/stream_json_prettify.py` ignores malformed typed event shapes without hiding later valid events. Valid writer/reviewer output is mirrored to stdout and display files; real I/O errors propagate. Raw logs, text-source rules and provider routing are unchanged; no assistant/result text fallback is added.

### Operator visibility

- `py/hud.py` owns global/local HUD rendering, progress estimation, and clean interrupt behavior.
- `py/engine_quota.py` keeps malformed numeric/nested evidence unknown; remaining percentages must be finite 0..100, and booleans are not measurements. Binary availability, status, source/reset metadata, legacy used-over-100 saturation at zero and numeric precision are unchanged.
- `py/notify_telegram.py` owns Telegram event selection, deduplication,
  project/folder/tag context, and loop-stopped alerts.
- `lib/notify.sh` owns only daemon lifecycle and recorded-PID validation.
  Broad process-name kills are not an acceptable recovery path.

### Review and safety gates

- `lib/review.sh` applies the hard gate; a nonzero parser exit rejects even without output.
- `py/parse_review.py` treats JSON containers and booleans in known text fields as missing evidence.
  Numeric score/delta rules, JSON priority, Markdown fallback and duplicate-key policy are unchanged.
- `lib/write_scope.sh` protects the operator's checkout from forbidden path
  changes and generated-output noise.

### Package payload

- `pyproject.toml` declares the installed console script and runtime payload.
- `MANIFEST.in` declares source distribution collateral.
- `py/mainspring_bootstrap.py` launches the packaged runtime without inheriting
  a project virtualenv that could hide dependencies.

### Verification map

- Shell syntax and lint: `bash -n mainspring.sh lib/*.sh` and
  `shellcheck -S warning mainspring.sh lib/*.sh`.
- Python lint and format: `ruff check py` and `ruff format --check py`.
- Unit/integration behavior: `python3 -m pytest py/tests -q` and
  `bash tests/bats/run.sh`.
- Public docs and payload checks: `make release-check` (which expands to
  `make all`, `make package-smoke`, coverage, PRD validation, and
  `git diff --check`).

---

## Appendix B — Verification commands

Use these from the repository root when validating a release candidate. These
commands are intentionally boring: they prove the source tree, package payload,
PRD, and diff hygiene without calling live AI providers.

```bash
set -e
make release-check
./mainspring.sh doctor
./mainspring.sh --dry-run --once
```

Optional live engine smoke, only when credentials/quota are intentionally
available:

```bash
./mainspring.sh --self-test
./mainspring.sh --self-test-all
```

Optional portability smoke, only when Docker is available:

```bash
docker run --rm -v "$(pwd):/m" -w /m alpine:3.19 sh -c 'apk add bash python3 git shellcheck && bash mainspring.sh doctor || true'
```

---

## Appendix C — Competitor landscape / competitive positioning (June 2026 refresh)

The detailed current market analysis lives in
[`docs/competitive-analysis.md`](competitive-analysis.md). It supersedes the
April 2026 snapshot that previously lived inline here.

**Snapshot date:** 2026-06-14. Product claims were checked against official
docs and public repository surfaces. Exact popularity metrics are intentionally
omitted because popularity signals drift quickly.

### Current strategic finding

Mainspring should not compete as "another coding agent." OpenCode, Cline,
Goose, Aider, OpenHands, Roo Code, GitHub Copilot cloud agent, and Devin already
own the broad coding-agent mindshare.

Mainspring should compete as:

> Product Requirements Document (PRD)-first AI coding agent orchestration for
> production-grade software delivery.

That means Mainspring exists to solve the operator problem that generic agents
leave behind: intent, bounded work, independent review, evidence, global status,
notifications, local/private model routing, and recovery.

### June 2026 release score

The refreshed 1000-point release-readiness score in
[`docs/competitive-analysis.md`](competitive-analysis.md) rates Mainspring's v1 source release readiness at 900/1000. This is a source-release readiness score, not a claim that Mainspring has more distribution than established competitors.

Mainspring scores high on:

- Product Requirements Document (PRD)-first production-grade workflow.
- Taskmaster-aware work selection.
- Independent writer/reviewer wave model.
- Fail-closed JSONL evidence, replay, and failure taxonomy.
- Global dashboard and Telegram operator visibility.
- Local/private writer model routing through Ollama or MTPLX plus Codex/Claude
  reviewer.

Next public credibility evidence after the source release:

- Signed `v1.0.0` tag and GitHub Release.
- Package-manager install path.
- Demo video or GIF showing PRD -> wave -> reviewer -> HUD -> Telegram -> ledger.
- Published SWE-bench Verified or equivalent benchmark result.
- Optional GitHub Issues, Linear, and Jira backlog adapters.

### Closest threats

| Threat | Why it matters | Mainspring response |
| --- | --- | --- |
| Agent Orchestrator | Worktrees, PR automation, CI fixes, review comment loops, tracker integrations. | Stay Product Requirements Document (PRD)-first and evidence-first; add optional GitHub/Linear backlog adapters later. |
| OpenAI Symphony | Strong "manage work, not agents" positioning plus OpenAI brand. | Stay local/private, multi-engine, and operator-owned. |
| Claude Task Master | Owns PRD-to-task decomposition and overlaps with autopilot. | Be explicit: Mainspring complements Taskmaster by adding execution, review, HUD, Telegram, and evidence. |
| OpenCode / Goose / Aider | Broader coding-agent mindshare and provider/local-model support. | Do not fight on chat UX; own autonomous execution control. |
| Cline / Roo Code | Strong editor-native trust and approval UX. | Own unattended CLI waves where per-action approval is the wrong workflow. |
| GitHub Copilot cloud agent / Devin | Hosted issue-to-PR convenience and enterprise reach. | Own local/private, inspectable, non-SaaS workflows. |

### Search and positioning requirements

Public copy should repeatedly use these phrases where natural:

- Product Requirements Document (PRD)-first AI coding agent orchestration.
- Local AI coding agent orchestration for production-grade software delivery.
- Writer/reviewer AI coding workflow.
- Taskmaster execution loop.
- Fail-closed AI code review gate.
- JSONL evidence ledger and replay.
- Terminal HUD for multiple coding agents.
- Telegram alerts for autonomous coding runs.
- Local model writer with Codex or Claude reviewer.

The next market-facing gates are: signed release announcement, package install
path, comparison pages, 60-second demo, and benchmark evidence.

---

_Last edited: 2026-10-30. This file is the canonical plan; if any other file in the repo disagrees, update it._
