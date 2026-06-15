#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
# Mainspring CLI help text
# Globals read: SCRIPT_DIR, MAINSPRING_PACKAGE_VERSION
# Globals written: none

print_version() {
  local version="${MAINSPRING_PACKAGE_VERSION:-}"
  if [ -z "$version" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    version="$(awk -F '"' '/^version[[:space:]]*=/ { print $2; exit }' "$SCRIPT_DIR/pyproject.toml")"
  fi
  if [ -z "$version" ]; then
    version="unknown"
  fi
  printf 'mainspring %s\n' "$version"
}

print_help() {
  cat <<'EOF'
Mainspring

Product Requirements Document (PRD)-first AI coding agent orchestration for
production-grade software delivery with reviewer gates, HUD, Telegram alerts,
and auditable wave logs.

Start:
  cd /path/to/your-project
  mainspring

Daily use:
  start or continue        mainspring
  watch every run          mainspring hud
  check this project       mainspring status
  inspect saved setup      mainspring last-run
  resume saved setup       mainspring --last-run
  diagnose setup           mainspring doctor
  stop this project        mainspring stop --force

Focused run examples:
  one Taskmaster task      mainspring taskmaster --once
  one PRD-driven slice     mainspring night --prd docs/prd.md --once
  safe preview             mainspring --preset fast-smoke --dry-run

Telegram:
  send test message        mainspring notify-test
  check notifier health    mainspring notify-health
  restart notifier         mainspring notify-restart
  env: MAINSPRING_NOTIFY_ENABLED, MAINSPRING_TELEGRAM_BOT_TOKEN,
       MAINSPRING_TELEGRAM_CHAT_ID

Install:
  python3 -m pip install --user pipx
  python3 -m pipx ensurepath  # Homebrew: brew install pipx && pipx ensurepath
  git clone https://github.com/dlogvinenko/mainspring.git
  cd mainspring && make install-user

More:
  mainspring help --full
  mainspring hud --help           HUD options
  https://github.com/dlogvinenko/mainspring/blob/main/docs/guide.md
EOF
}

print_help_full() {
  cat <<'EOF'
Mainspring

Product Requirements Document (PRD)-first AI coding agent orchestration for
production-grade software delivery.

Start here:
  cd /path/to/your-project
  mainspring

That opens the guided start flow in an interactive terminal. Use
`mainspring doctor` for diagnostics, not as the normal first command.

Copy/paste commands:
  Copy the command exactly as shown after each dash.
  Every command line below is a complete runnable invocation.
  Flags are never shown as standalone workflows or separate columns.

  Start / resume:
    - mainspring => guided start or continue in this project
    - mainspring --last-run => rerun the saved setup for this project
    - mainspring last-run => inspect saved setup
    - mainspring last-run --format json => inspect saved setup as JSON

  Observe:
    - mainspring hud => live dashboard for every Mainspring run
    - mainspring hud --once => one-frame HUD snapshot
    - mainspring hud --json --once => machine-readable HUD snapshot
    - mainspring hud --all-runtimes => include stale recorded runs
    - mainspring hud --local => show only the current project
    - mainspring status => read-only status for this project
    - mainspring --metrics => pass rate, duration, and cost
    - mainspring --metrics --days 7 --routing => routing metrics for the last week
    - mainspring --metrics --format json => machine-readable metrics

  Run work:
    - mainspring taskmaster --once => one Taskmaster wave
    - mainspring taskmaster --once --pair codex+claude => one Taskmaster wave with a chosen pair
    - mainspring night --prd docs/prd.md --once => one Product Requirements Document (PRD) wave
    - mainspring night --prd docs/prd.md --once --pair codex+claude => one Product Requirements Document (PRD) wave with a chosen pair

  Preview / health:
    - mainspring --preset fast-smoke --dry-run => preview commands with zero API calls
    - mainspring --list-presets => show built-in run presets
    - mainspring doctor => diagnose local dependencies/setup

  Project planning:
    - mainspring init checkout-redesign => scaffold docs/checkout-redesign/prd.md
    - mainspring validate-prd docs/prd.md => validate a Product Requirements Document (PRD)
    - mainspring validate-prd docs/prd.md --format json => validate a Product Requirements Document (PRD) as JSON
    - mainspring decompose docs/prd.md --phase P1 => preview one Product Requirements Document (PRD) phase
    - mainspring decompose docs/prd.md --phase P1 --apply => write one Product Requirements Document (PRD) phase
    - mainspring next => Taskmaster backlog: print next ready item
    - mainspring scope-check => Taskmaster backlog: audit Method issues

  Stop / recover:
    - mainspring stop --force => stop this project
    - mainspring --repair-state --dry-run => preview reviewed stale-state repair
    - mainspring --repair-state --force => apply reviewed stale-state repair

  Telegram:
    - mainspring notify-test => send one Telegram test message
    - mainspring notify-health => inspect notifier daemon state
    - mainspring notify-health --format json => inspect notifier daemon state as JSON
    - mainspring notify-restart => restart only the recorded notifier daemon

  Advanced inspection:
    - mainspring --version => print installed version
    - mainspring engines => list engine adapters, local prerequisites, and setup gaps
    - mainspring engines --json => list engine adapters as JSON
    - mainspring limits => run-readiness, quota, and spend snapshot before a long run
    - mainspring limits --format json => run-readiness, quota, and spend snapshot as JSON
    - mainspring limits codex claude --format json => selected engine readiness/quota as JSON
    - mainspring limits --hours 72 => custom spend window
    - mainspring --self-test => live writer/reviewer handshake
    - mainspring --self-test-all => live pair matrix handshake
    - mainspring replay show last .mainspring/logs/waves.jsonl => inspect the latest recorded wave
    - mainspring replay run last .mainspring/logs/waves.jsonl --dry-run => preview a replay command

Install once:
  python3 -m pip install --user pipx
  python3 -m pipx ensurepath  # Homebrew: brew install pipx && pipx ensurepath
  git clone https://github.com/dlogvinenko/mainspring.git
  cd mainspring
  make install-user

Run anywhere:
  command -v mainspring
  mainspring --help
  cd /path/to/your-project
  mainspring
    If command -v prints nothing, ensure ~/.local/bin is on PATH and reopen
    the terminal.

Update this checkout:
  make install-user
    Refreshes the user-level pipx command after local Mainspring changes.

Optional provider/local-model deps:
  MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers
    Installs LiteLLM provider/local-model dependencies. Use Python 3.11-3.13;
    Python 3.14 provider deps are skipped until upstream packages support it.

Source-checkout fallback:
  ./mainspring.sh --project /path/to/project status
    Use this when you do not want a pipx command.

  Note: The v1 source install path is git clone plus make install-user.
    Source install stays the supported path until package-manager channels exist.

Modes:
  mainspring
    With no flags, open the guided start flow when run in an interactive
    terminal. If this project has saved settings, Mainspring shows them first
    and offers to continue with the same setup before asking new questions.
    This is the default entry point for new projects.

  taskmaster
    Use Taskmaster as the only task source.
    The worker will:
    - ask Taskmaster for the next actionable task
    - inspect task details
    - implement only that task
    - run verification
    - leave the task done / not-done based on outcome

  night
    Use the PRD as the planning source.
    The worker will:
    - read a compact PRD brief
    - identify the next highest-value autonomous slice
    - implement one coherent slice at a time
    - run verification
    - continue until a true blocker or no safe work remains

Options used by commands:
  --project <path>
    Source-checkout/global override for the project root Mainspring controls.
    Packaged pipx installs already target the directory where you run
    `mainspring`; direct ./mainspring.sh source-checkout runs target the checkout
    unless --project is provided.

  --topology team|solo
    solo: use one writer and one reviewer. Default and safest first-run path.
    team: launch parallel team workers in separate worktrees. Requires the
    external team backend plus tmux.
    Default: solo

  --pair <writer>+<reviewer>
    Set writer+reviewer pair in one flag. Default: claude+codex.
    Engines must be registered adapters; run `mainspring engines` to inspect
    the installed inventory. Runtime execution requires a supported adapter and
    a matching binary or provider bridge on PATH; preflight-only registrations
    fail closed before a wave.
    Default model mapping:
    - claude => opus
    - codex  => gpt-5.5
    - litellm => gpt-5.5 (generic provider bridge; pass provider model with --model)
    - gemini => gemini/gemini-2.5-pro (LiteLLM provider bridge)
    - grok => xai/grok-4.20-reasoning (LiteLLM provider bridge)
    - ollama => ollama/llama3.1 (local Ollama via LiteLLM)

  --engine <registered-engine>
    Choose the writer engine. Overrides the writer side of --pair.

  --model <model>
    Optional explicit model override for the chosen engine.

  --review-engine <registered-engine>
    Optional explicit reviewer engine. Overrides the reviewer side of --pair.

  --review-model <model>
    Optional explicit model override for the reviewer engine.

  --mode architect|code|debug|ask
    Writer role mode. code is the default implementation lane. debug adds
    root-cause discipline and targeted verification. architect and ask are
    no-edit advisory lanes; their reviewer PASS does not mark Taskmaster
    implementation work done.

  --speed-profile standard|fast|max
    Controls how aggressively the writer should parallelize and delegate.
    Default: max

  --max-agents <1-6>
    Maximum subagents/parallel lanes the writer should use when safe.
    Default: 6

  --auto-retry-ci <N>
    Opt-in retry budget for CI-detectable writer failures. Default: 0,
    preserving the current fail-stop behavior. When a writer exits non-zero
    and its output looks like a test, lint, or typecheck failure, Mainspring
    records the failed wave and injects the failure-output tail into the next
    writer prompt, capped at N retries to prevent runaway loops.

  --auto-retry-ci-log <path>
    Optional readable local CI log to include with --auto-retry-ci retry
    context. Mainspring tails this file into the next writer prompt only after
    a CI-detectable failure and fails closed before launch if the path is not
    readable. Use this for hosted/local CI logs captured outside writer stdout.

  --retry-task <id>
    Team topology only. Explicitly permit redispatching a Taskmaster id that
    is already recorded in the per-team dispatch ledger as pending,
    in-progress, completed, or failed. Repeat the flag for multiple ids.

  --once
    Run one wave only, then exit.

  --prd <path>
    PRD file for night mode. Optional if docs/prd.md or PRD.md exists.

  --help
    Show short operator help.

  help --full
    Show the full CLI contract.

  --version
    Print the installed Mainspring version and exit.

  --wizard
    Force interactive setup questions even if arguments are present.

  --last-run
    Reuse the last saved mode/pair/model/run-style settings instead of asking again.

  last-run [--format text|json]
    Show the saved settings for this project without launching work: settings
    file, saved timestamp, mode, topology, pair, writer/reviewer models,
    speed, agent count, PRD path, CI retry settings, and exact repeat/preview
    commands. Use `mainspring --last-run` to execute those saved settings.

  .mainspring.yaml
    Optional project-local config file loaded after --preset and before execution.
    YAML keys may use canonical names such as SPEED_PROFILE or lowercase aliases
    such as speed-profile. The file is validated against
    schema/config.schema.json. CLI flags win on conflict.
    Set MAINSPRING_CONFIG_FILE to point tests or alternate worktrees at another
    config path.

  --self-test
    Run a live writer/reviewer handshake in the runtime selftest dir and exit.
    This can call configured engines and consume provider quota.

  --self-test-all
    Run all live pair handshakes; can call engines and consume provider quota.

  status
    Print read-only runtime, git, model, team, and Taskmaster status. This
    never launches work, repairs state, mutates Taskmaster, or stages/commits
    files.

  doctor
    Print a non-mutating readiness report for git, locks, commands, logs,
    Taskmaster, tmux, node_modules, and active team backend state.

  --metrics
    Print 7-day rolling metrics from waves.jsonl: total waves, success rate,
    mean duration, top stuck tasks, chapter delta per pair, top expensive
    waves, and pass rate per pair. Combine with --days, --since, --pair,
    and --format for custom queries.

  --routing
    Used with --metrics. Print routing metrics: pass rate by pair/topology,
    mean duration by task class, repeated failure clusters, and cost per
    chapter delta by pair when ledger cost fields exist. The public
    `mainspring --metrics --routing` command is read-only; it does not change
    future wizard defaults.

  --days <N>
    Used with --metrics. Show metrics for the last N days (default: 7).

  --since <DATE>
    Used with --metrics. Show metrics since the given ISO date.

  --format json|text
    Used with --metrics. Output format (default: text).

  engines [--json]
    Print the registered engine inventory without launching an engine: binary
    availability, required modules, required environment variables, default
    model, execution support status, and quota support.
    Runtime command construction is adapter-backed for shell-dispatch engines.
    LiteLLM is an optional provider bridge. From the Mainspring source checkout,
    run `MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers`
    before provider waves; Python 3.14 provider deps are skipped until upstream
    packages support it. Gemini and Grok are provider-specific LiteLLM dispatch
    engines; missing modules or provider credentials fail closed instead of
    falling back.

  hud [--local] [--all-runtimes] [--once|--watch] [--rich] [--json] [--since 1h] [--width 80]
    Print a read-only operator HUD. Plain `mainspring hud` is global: it
    discovers live Mainspring work processes across the machine and shows
    folder, PID, Taskmaster tag, task, wave, pair, started/last stopped time,
    result, reason, consecutive failures, next action, Telegram state, and team
    state. State is operator health: Running, Waiting, Blocked, Failed,
    Not running, or Stopped cleanly. Use `mainspring hud --all-runtimes` to
    include past known runs, or --local for the current project-only HUD. --json emits the same data model.
    In an interactive terminal, plain `mainspring hud` opens the Rich live
    dashboard immediately. --once prints one frame.
    --watch refreshes dependency-free text output; --rich selects the Rich
    renderer explicitly for bounded smoke checks. Python rich is optional and
    reported by doctor when missing or unusable. --iterations bounds watch or
    rich smoke runs for automated checks.

  stop --force [--all]
    Stop recorded Mainspring processes for the current project. The --all flag is
    emergency-only and targets every matching Mainspring process owned by the
    current user.

  --repair-state
    Repair stale local runtime state when the active skill marker clearly
    disagrees with a completed/inactive mode state. Use --dry-run first; actual
    mutation requires --force.

  --dry-run
    When used standalone: print resolved settings, dependency checks, and the
    exact writer/reviewer commands that would execute, then exit. Zero API calls.
    When used with --repair-state: print the repair plan without changing files.

  --preset <name>
    Load a preset env file from presets/<name>.env before resolving settings.
    Project .mainspring.yaml then overrides preset values, and CLI flags
    override both. Available presets: nightly-max, conservative-docs, fast-smoke.

  --list-presets
    Print available presets with descriptions and exit.

  notify-test
    Send a sample Telegram notification to verify that
    MAINSPRING_TELEGRAM_BOT_TOKEN and MAINSPRING_TELEGRAM_CHAT_ID are
    correctly configured. Exits immediately after the test. Runtime event
    messages include Project, Folder, Taskmaster Tag, task, pair, result,
    reason, next action, and duration context where available so parallel
    project runs are distinguishable in one chat.

  notify-health [--format text|json]
    Print notification daemon health without starting or stopping the daemon
    and without calling the Telegram API. The command checks enabled/configured
    state, notify-state progress, notifier.log activity, notifier.pid process
    truth, pending ledger lines, and the configured stale threshold. JSON output
    includes next_step and next_step_message for automation and operator runbooks.

  notify-restart
    Restart only the recorded Mainspring Telegram notifier daemon. This uses
    notifier.pid plus process-command and current-ledger validation; a stale or
    foreign PID file is removed without killing unrelated processes. Requires
    notifications to be enabled and Telegram env vars to be configured, but does
    not call Telegram.

  replay <show|diff|build|run> ...
    Inspect, compare, reconstruct, or run a recorded wave from waves.jsonl.
    Use replay run <wave-ref> <ledger-path> --dry-run to preview the exact
    command and the same validation a real run would enforce. Use --save-as
    <id> to tag the real replay wave ledger row with a stable id and replay
    provenance. Prompt-backed replays fail closed when the prompt snapshot
    hash, recorded git HEAD, or recorded dirty-tree status no longer matches;
    pass --allow-worktree-drift only after intentionally checking out a
    different replay state. Older rows without prompt snapshots fail closed for
    real replay runs unless --allow-live-reconstruction is explicit.

  init <name> [--force]
    Scaffold docs/<name>/prd.md from the Method PRD template, create local
    .mainspring runtime directories, and initialize Taskmaster when
    .taskmaster is absent. Refuses to overwrite an existing PRD unless
    --force is given.

  decompose <prd-path> [--phase <id-or-title>] [--format text|json] [--apply]
    Validate a Method-shaped PRD, select one phase, and print deterministic
    task-master add-task prompt plans using the Method task template. With
    --apply, merge the generated tasks into .taskmaster/tasks/tasks.json with
    a backup under .mainspring/state/decompose and no duplicate generated
    tasks on repeat runs. Use --tasks-file and --backup-dir for isolated tests.

  validate-prd <path> [--format text|json]
    Validate a Method-shaped PRD before decomposition. Checks canonical
    sections, unresolved placeholders, truth-snapshot Source cells, ADR
    field coverage, and the explicit Won't backlog lane.

  limits [engine ...] [--engine <name>] [--format text|json] [--hours N]
    Print a one-shot readiness, quota, and spend view across registered engines.
    Status values: ready means runnable adapter plus local quota/readiness
    signal; adapter-only means adapter visible but credentials/quota are not
    proven; throttled means exhausted/rate-limited; not-configured means
    missing binary, module, credential, or execution requirement. Spend
    summarizes waves.jsonl for the last 24h by default; --hours changes the
    window. JSON is stable for HUD or jq consumers.

  scope-check [path/to/tasks.json]
    Audit active Taskmaster items against Method commandments. Flags vague
    titles, manual blockers outside the final phase, missing acceptance
    criteria, missing test plans, and effort estimates larger than half-day.
    Defaults to .taskmaster/tasks/tasks.json. If that backlog is missing,
    Mainspring prints setup guidance instead of Python internals.

  next [path/to/tasks.json]
    Print the next blocker-aware Taskmaster work item. Skips blocked tasks,
    skips unresolved dependencies, prefers the active PRD phase from
    .mainspring/state/active-prd.json when present, and returns a task or
    subtask id without mutating Taskmaster. If the backlog is missing,
    Mainspring prints setup guidance instead of Python internals.

  --force
    Safety confirmation used by commands that intentionally mutate runtime
    state, especially `mainspring stop --force` and
    `mainspring --repair-state --force`. Repair still refuses to kill live
    workers; force only permits reviewed stale-state mutations there.

  --restart-team
    Before starting team topology, preserve worker heads, shut down active team
    backend state, remove stale worktrees, and start a fresh team. Use this
    when you intentionally want a clean restart instead of resuming supervision.

Environment:
  MAINSPRING_* is the public configuration namespace for new projects.

  MAINSPRING_ENGINE
    Default engine when --engine is omitted.
  MAINSPRING_REVIEW_ENGINE
    Default reviewer engine when --review-engine is omitted.
  MAINSPRING_DEFAULT_CODEX_MODEL
    Default Codex model for writer/reviewer/team workers. Default: gpt-5.5
  MAINSPRING_DEFAULT_FAST_CODEX_MODEL
    Fast Codex model for future read-only lanes. Default: gpt-5.3-codex-spark
  MAINSPRING_DEFAULT_CLAUDE_MODEL
    Default Claude Code model. Default: opus
  MAINSPRING_CODEX_REASONING_EFFORT
    Codex reasoning effort for writer/reviewer/team workers. Default: xhigh
  MAINSPRING_SPEED_PROFILE
    Default speed profile when --speed-profile is omitted.
  MAINSPRING_MAX_AGENTS
    Default max subagent count when --max-agents is omitted.
  MAINSPRING_AUTO_RETRY_CI
    Default retry budget for CI-detectable writer failures. Default: 0.
  MAINSPRING_AUTO_RETRY_CI_LOG
    Optional readable local CI log tailed into opt-in auto-retry CI prompts.
  MAINSPRING_TOPOLOGY
    Default topology when --topology is omitted.
  MAINSPRING_AUTO_TMUX
    For team topology, auto-relaunch inside tmux when not already in tmux.
    Default: true
  MAINSPRING_TEAM_FALLBACK_TO_SOLO
    When team topology finds no parallel-safe pending/in-progress work, continue
    in solo topology to process review/status recovery lanes. Default: true
  MAINSPRING_TEAM_SUPERVISE
    Keep the team launcher alive after dispatch, poll worker completion, dispatch
    additional ready batches, and only then return/fallback. Default: true
  MAINSPRING_TEAM_POLL_SECONDS
    Poll interval for supervised team runs. Default: 30
  MAINSPRING_TEAM_EXCLUDE_PREFIXES
    Comma/colon-separated path prefixes to keep out of git-worktree team fanout.
    Default: .claude (local helper worktrees)
  MAINSPRING_AUTO_CHECKPOINT
    When true, commit safe dirty leader changes before team fanout so worker
    worktrees start from a reproducible clean checkout. Default: true
  MAINSPRING_RUNTIME_DIR
    Runtime root for logs, state, team worktrees, locks, and last-run settings.
    Fresh projects default to .mainspring.
  MAINSPRING_STATE_DIR
    Optional state-dir override for tests and unusual runtime layouts.
  MAINSPRING_NOTIFY_ENABLED
    Set to 1 to auto-launch the Telegram notification daemon when the wave
    loop starts. The daemon tails waves.jsonl and sends alerts on failures,
    retry loops, loop stops, quota warnings, team-stuck, milestones, and a
    daily digest with project, folder, tag, task, pair, result, reason, next
    action, and duration fields when the ledger has them.
    Default: 0 (disabled).
  MAINSPRING_TELEGRAM_BOT_TOKEN
    Telegram bot token for the notification daemon. Required when
    MAINSPRING_NOTIFY_ENABLED=1 or using notify-test.
  MAINSPRING_TELEGRAM_CHAT_ID
    Telegram chat ID for the notification daemon. Required when
    MAINSPRING_NOTIFY_ENABLED=1 or using notify-test.
  MAINSPRING_NOTIFY_STALE_SECONDS
    Pending-ledger-line age before a live notifier daemon is treated as stale
    and restarted at the next wave boundary. Default: 3600.

Logs:
  .mainspring/logs/taskmaster-loop-YYYYMMDD-HHMMSS.log
  .mainspring/logs/night-loop-YYYYMMDD-HHMMSS.log

Examples:
  Daily:
    mainspring
    mainspring hud
    mainspring status
    mainspring doctor
    mainspring stop --force

  One reviewed wave:
    mainspring taskmaster --topology solo --pair claude+codex --once
    mainspring night --prd docs/prd.md --topology solo --pair codex+claude --once

  Team run:
    mainspring taskmaster --topology team --pair codex+codex \
      --speed-profile max --max-agents 6

  Local writer preview:
    mainspring night --prd docs/prd.md --topology solo \
      --engine ollama --model 'ollama/qwen3:8b' \
      --review-engine codex --review-model gpt-5.5 \
      --dry-run --once

    OPENAI_API_BASE=http://127.0.0.1:18080/v1 OPENAI_API_KEY=local \
      mainspring night --prd docs/prd.md --topology solo \
      --engine litellm --model 'openai/qwen3.6-mtplx' \
      --review-engine codex --review-model gpt-5.5 \
      --dry-run --once

  Recovery / diagnostics:
    mainspring --repair-state --dry-run
    mainspring notify-health --format json
    mainspring replay build last .mainspring/logs/waves.jsonl
    mainspring validate-prd docs/prd.md

Practical guidance:
  - First run in a project: `mainspring`.
  - Command not found after install: ensure ~/.local/bin is on PATH, reopen the
    terminal, then run `command -v mainspring`.
  - Need a live dashboard: `mainspring hud`.
  - Need Telegram alerts: set MAINSPRING_TELEGRAM_BOT_TOKEN,
    MAINSPRING_TELEGRAM_CHAT_ID, MAINSPRING_NOTIFY_ENABLED=1, then run
    `mainspring notify-test`.
  - Run `mainspring` from the target project after pipx install.
  - Run `make install-user` in this checkout after local Mainspring changes.
  - Use --project when a source checkout or agent is controlling another repo.
  - Use taskmaster mode when the backlog is already curated in Taskmaster.
  - Use night mode when you want the worker to drive from a Product
    Requirements Document (PRD).
  - Prefer status for diagnosis; --last-run is an execution resume command.
  - Prefer --once for smoke checks before long unattended runs.
EOF
}
