# Mainspring Guide

`mainspring` is an autonomous execution driver. It turns a Product
Requirements Document (PRD) or Taskmaster backlog into reviewed, auditable
writer/reviewer waves.

The normal first command is just:

```bash
cd /path/to/your-project
mainspring
```

That opens the guided start flow in an interactive terminal. If stdin is not
interactive and no answers are piped in, Mainspring exits with setup guidance
instead of starting from incomplete setup. Use `doctor`
only when you want a dependency and environment diagnostic.

## Install Once, Run Anywhere

v1 installs use the GitHub repo plus the `mainspring` console command:

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath  # Homebrew: brew install pipx && pipx ensurepath
git clone https://github.com/dlogvinenko/mainspring.git
cd mainspring
make install-user
cd /path/to/your-project
mainspring
```

Check the command:

```bash
command -v mainspring
mainspring --version
mainspring --help
```

If `command -v mainspring` prints nothing, make sure the pipx app directory
`~/.local/bin` is on the shell PATH, then reopen the terminal.

Source checkouts should refresh the global editable command after local changes:

```bash
cd /path/to/mainspring
make install-user
cd /path/to/your-project
mainspring
```

That target runs `pipx ensurepath`, removes any old `mainspring` pipx
environment, and installs the current checkout. The reinstall step prevents
stale optional provider dependencies from lingering after an update. If you do
not want a pipx command, run the checkout script against any project explicitly:

```bash
./mainspring.sh --project /path/to/your-project status
```

Provider/local-model engines use optional LiteLLM dependencies. Install them
into the global command with Python 3.11-3.13, then check engine readiness:

```bash
cd /path/to/mainspring
MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers
mainspring engines
```

Both the providers extra and runtime requirements enforce `filelock>=4.2.1,<5`
within the existing Python <3.14 scope. This can select an earlier allowed
LiteLLM release while newer releases cap filelock below 4. Python 3.14 keeps
the Rich-only base runtime. Isolated install/import/mock checks do not verify
real provider credentials, inference or downloaded model assets.

Optional `fnm` bootstrap applies only allowlisted assignments from a successful
JSON helper. Helper failure discards its entire output and uses the existing
first-directory fallback. Successful-helper string cleanup, directory checks
and handling of the producer's exit status remain unchanged.

Release formula generation preserves accepted URL/homepage values as literal
Ruby data, including quotes, backslashes, controls and interpolation text.
Existing stripping, validators and CLI behavior remain unchanged.

## Coordinated runtime-lock updates

The runtime protocol locks the persistent `${LOCK_FILE}.guard` inode. The
`LOCK_FILE` contents are advisory PID metadata, not kernel ownership evidence.
Release removes only its own advisory PID while still holding the guard, then
unlocks and closes its descriptor without redirecting the caller's stderr.
Guard existence does not mean a process is running. Never remove or replace a
guard while an invocation or waiter may have it open.

This is a coordinated version change, not a zero-downtime or mixed-version
migration. Source edits can affect an active editable installation immediately.
Do not update one launch route while another can still run the old protocol.

1. Bound the affected domain: state paths, users/hosts sharing them, source trees,
   editable/package overrides, wrappers and automated/interactive launch owners.
   If that inventory cannot be bounded, defer activation.
2. Close all identified launch intake outside both locks, including restarters
   and pending interactive launches. The new guard does not exclude old code.
3. Let each old invocation finish or use its owning controller's scoped stop.
   Account for pending/preopened waiters and relevant children that can retain
   descriptors or relaunch. Require authoritative terminal outcomes; a PID-file
   check, process-name scan, signal acknowledgment or delay is insufficient.
4. Obtain the launch owners' explicit quiescent-domain confirmation. An unknown
   contender keeps intake closed; `status`, `doctor`, lock acquisition and PID
   absence cannot establish this confirmation.
5. With intake still closed, update all allowed routes to one reviewed build.
   Verify resolved source/payload hashes, not just package version. Keep old
   routes unavailable through their owners' existing controls; preserve guards.
6. After required isolated/CI validation, reopen one controlled new launcher,
   then the approved domain. Record its build and same-guard evidence.
7. Rollback repeats the cutover: close intake, obtain terminal/quiescent evidence
   for every new invocation and waiter, then switch all routes together. Never
   hot-revert one old launcher beside a new cohort; leave guard evidence intact.

The independent lock-protocol CI job runs outside `make all`, so unrelated lint
failure cannot hide backend evidence. Linux requests and logs a real `flock`
executable and version, then exercises the native branch; absence fails rather
than skips. macOS exercises the actual Python `fcntl` helper. Synthetic return
status controls are labeled as such and never substitute for native evidence.
No cross-backend, universal process/descriptor discovery or live install safety
claim follows from these tests. Any supported mixed-backend claim needs separate
actual evidence. This draft does not assert a Linux CI result before it exists.

## Everyday Commands

These are the commands most operators need day to day.

| Need | Run | Notes |
| --- | --- | --- |
| Start or continue work | `mainspring` | Guided setup, saved-run resume, or normal project launch from the current directory. |
| Watch all runs | `mainspring hud` | Live global dashboard for every Mainspring run on the machine. |
| Check this project | `mainspring status` | Read-only runtime/git/Taskmaster state without starting work. |
| Diagnose setup | `mainspring doctor` | Dependency, path, lock, notifier, and team-backend checks when something looks wrong. |
| Inspect saved setup | `mainspring last-run` | Show the last saved mode, topology, pair, models, and repeat commands. |
| Resume saved setup | `mainspring --last-run` | Launch the last saved setup for this project. |
| Preview safely | `mainspring --preset fast-smoke --dry-run` | Resolve commands and dependencies with zero API calls. |
| Run one Taskmaster item | `mainspring taskmaster --once` | One bounded writer/reviewer wave from the backlog. |
| Run one PRD slice | `mainspring night --prd docs/prd.md --once` | One Product Requirements Document (PRD)-driven wave. |
| Stop this project | `mainspring stop --force` | Stop the current project's recorded run. Run `mainspring stop --help` before emergency all-project cleanup. |
| Test Telegram | `mainspring notify-test` | Send one configured test notification. |
| Check notifier | `mainspring notify-health` | Read notifier health without calling Telegram. |

## Command Reference

These are supported public commands. The short help shows the daily path; this
table names the rest so humans and agents do not need to read shell code.

Every row below is a complete runnable command. Flags are shown only inside
copy/paste examples, never as separate columns.

| Need | Run | What it does |
| --- | --- | --- |
| Full help | `mainspring help --full` | Print the complete CLI contract. |
| Version | `mainspring --version` | Print the installed version. |
| Live HUD | `mainspring hud` | Watch live runs across the machine. |
| HUD snapshot | `mainspring hud --once` | Print one frame and exit. |
| HUD JSON | `mainspring hud --json --once` | Emit a machine-readable snapshot with run counts and `runs[]`. |
| Include old runs | `mainspring hud --all-runtimes` | Include stale recorded runs. |
| Current-project HUD | `mainspring hud --local` | Scope the dashboard to this checkout. |
| This project status | `mainspring status` | Read status for the current checkout. |
| Another project status | `mainspring --project /path/to/project status` | Read status for another checkout. |
| Inspect saved setup | `mainspring last-run` | Show saved launch settings. |
| Saved setup JSON | `mainspring last-run --format json` | Show saved launch settings as JSON. |
| Resume saved setup | `mainspring --last-run` | Run the saved setup again. |
| Safe preview | `mainspring --dry-run` | Resolve default settings before a real wave. |
| Preset preview | `mainspring --preset fast-smoke --dry-run` | Preview the fastest smoke preset with zero API calls. |
| List presets | `mainspring --list-presets` | Show built-in run presets. |
| Preview a pair | `mainspring --dry-run --pair codex+claude` | Preview writer/reviewer command construction. |
| Preview local writer | `mainspring --dry-run --engine ollama --model 'ollama/qwen3:8b'` | Check a local-model writer route before spending reviewer quota. |
| One Taskmaster wave | `mainspring taskmaster --once` | Run one bounded writer/reviewer wave. |
| Taskmaster with pair | `mainspring taskmaster --once --pair codex+claude` | Run one bounded wave with an explicit pair. |
| One PRD wave | `mainspring night --prd docs/prd.md --once` | Run one Product Requirements Document (PRD)-driven wave. |
| Continuous PRD mode | `mainspring night --prd docs/prd.md` | Keep selecting PRD-driven waves until stopped or blocked. |
| PRD wave with pair | `mainspring night --prd docs/prd.md --once --pair codex+claude` | Run one PRD-driven wave with an explicit pair. |
| Engines | `mainspring engines` | Inspect adapters, binaries, modules, credentials, and setup gaps. |
| Engines JSON | `mainspring engines --json` | Inspect adapters as JSON. |
| Limits | `mainspring limits` | Check run readiness, quota signal, and spend before long runs. |
| Limits JSON | `mainspring limits --format json` | Read run readiness, quota, and spend as JSON. |
| Selected limits | `mainspring limits codex claude` | Check selected engines only. |
| Custom limits window | `mainspring limits --hours 72` | Check spend over a custom window. |
| Metrics | `mainspring --metrics` | Read pass rate, duration, cost, and stuck-task signals. |
| Routing metrics | `mainspring --metrics --days 7 --routing` | Read routing metrics for the last week. |
| Metrics JSON | `mainspring --metrics --format json` | Emit metrics as JSON. |

## Project Planning Commands

These commands shape the backlog before autonomous work starts.

| Need | Command | What it does |
| --- | --- | --- |
| Initialize Method docs | `mainspring init checkout-redesign` | Create starter PRD docs under `docs/checkout-redesign/`. |
| Force Method docs overwrite | `mainspring init checkout-redesign --force` | Overwrite starter docs intentionally. |
| Validate a PRD | `mainspring validate-prd docs/prd.md` | Validate the Product Requirements Document before decomposition. |
| Validate a PRD as JSON | `mainspring validate-prd docs/prd.md --format json` | Emit validation details for scripts and agents. |
| Preview PRD decomposition | `mainspring decompose docs/prd.md --phase P1` | Preview one phase without writing Taskmaster tasks. |
| Apply PRD decomposition | `mainspring decompose docs/prd.md --phase P1 --apply` | Write validated Taskmaster tasks for one phase. |
| Pick next task | `mainspring next` | Requires a Taskmaster backlog; prints the next ready item. |
| Pick next task from a file | `mainspring next path/to/tasks.json` | Inspect a specific Taskmaster backlog. |
| Audit task shape | `mainspring scope-check` | Requires a Taskmaster backlog; checks the default backlog for Method issues. |
| Audit task file | `mainspring scope-check path/to/tasks.json` | Check a specific Taskmaster backlog. |

PRD validation checks live headings, Architecture Decision Records (ADRs), truth tables and lanes; fenced examples
do not supply that structure. Required ADR fields need nonblank value blocks,
including multiline prose or code. Short truth data rows without Source are
reported. A heading-only Won't lane remains allowed. Passing is a structural
check, not business or approval readiness.

`decompose --apply` matches structured generated records by exact source,
digest and `taskId`. Text-only legacy records require complete `GeneratedBy`,
`Source` and `Digest` marker lines. Malformed container shapes and ambiguous
legacy identity fail before a backup or task-file write. Valid merges keep
existing status, dependencies, subtasks and custom data. Digest/rendering and
edited-task behavior retain their existing rules.

Taskmaster dependency collections must be JSON arrays when present and non-null.
Malformed task or subtask collections do not establish readiness. Missing/null
fields and empty arrays keep their no-prerequisite behavior; existing `done`
checks and identifier matching are unchanged. Empty rollup/fallback/skip results
remain a single newline; task-path display retains the first complete
`.taskmaster/tasks/tasks.json` marker.

When no backlog exists, Mainspring does not guess: missing backlog prints
`mainspring init checkout-redesign` guidance so the operator can start from a
Product Requirements Document (PRD) with a concrete copy/paste example.

Saved settings retain tabs and ordinary single-line quoting; flat YAML comments
are recognized outside quoted scalars, preserving literal hashes. New saves
reject record separators before replacing the existing cache. Old complete
canonical `shlex.quote` single-quoted multiline records are skipped as a unit.
Hand-edited double-quoted multiline records remain unsupported: historical row
parsing can still read interior setting-like lines. Explicit user choices and
existing env/YAML validation rules retain their priority. Save staging does not
provide crash-atomic or concurrent-writer protection.

## Advanced and Recovery Commands

These are useful, but they are not the default start path.

| Need | Command | What it does |
| --- | --- | --- |
| Replay evidence | `mainspring replay show last .mainspring/logs/waves.jsonl` | Inspect a recorded wave without trusting memory. |
| State repair preview | `mainspring --repair-state --dry-run` | Preview stale-state cleanup; does not kill live processes. |
| State repair apply | `mainspring --repair-state --force` | Apply the reviewed stale-state repair intentionally. |
| Engine handshake | `mainspring --self-test` | Live writer/reviewer handshake; requires configured engines and may consume provider quota. |
| Pair matrix handshake | `mainspring --self-test-all` | Live built-in pair checks; requires configured engines and may consume provider quota. |

Each `replay run` child uses controls from the current source and invocation,
including `--save-as`. Inherited replay-owned leftovers are ignored; the calling
process and unrelated runtime environment are preserved.

`mainspring hud` is the global live dashboard in an interactive terminal. Plain
`mainspring hud` opens the Rich watch view immediately. It prints every live
Mainspring work process on the machine with folder, PID, Taskmaster tag, task,
lightweight project progress, wave, started/stopped times, newest activity first,
Telegram health, quota, and team state. Use `mainspring hud --all-runtimes` to
include past known runs, `mainspring hud --local` for the current
project-only HUD, and `mainspring hud --once` for a one-shot snapshot.

HUD `State` is operator health. `Running` means a run is currently working;
`Waiting` means the loop is alive after a clean wave and waiting for the next
result; `Blocked` means repeated failures need human action; `Failed` means the
latest wave failed but has not reached the blocked threshold; `Stopped cleanly`
means the loop found no work or ended without an active failure; `Not running`
means Mainspring found a past recorded run but no live process for it. The
`Reason`, `Fails`, and `Next` columns explain what to inspect or restart.

`Progress` is a lightweight read-only estimate for operator awareness. Mainspring
counts Taskmaster leaf tasks by active tag first, ignoring cancelled items; if
Taskmaster files are not present, it falls back to Product Requirements Document
(PRD) checkboxes. It is an operator signal, not a pass/fail release signal.

HUD JSON is intentionally small and stable for scripts and agents. The top-level
fields are `scope`, `generated_at`, `run_count`, `live_count`,
`needs_action_count`, `stale_count`, and `runs`. Each `runs[]` row carries the
same operator fields shown in the terminal HUD, including project, folder, PID,
tag, task, wave, pair, result, reason, progress, Telegram health, and next
action.

## What The Modes Do

- `mainspring` with no flags opens the guided start flow in an interactive
  terminal. If `.mainspring/state/last-run.env` exists, it shows the saved
  setup first and offers to continue with it before asking new questions.
  Non-interactive runs require piped answers or an explicit command:
  `mainspring last-run` to inspect saved settings if they exist,
  `mainspring --last-run` to resume saved settings if they exist,
  `mainspring --dry-run --once` to preview defaults with zero API calls, or
  `mainspring init checkout-redesign` to scaffold Product Requirements Document
  (PRD)-backed starter docs after replacing `checkout-redesign` with your
  feature name.
- `taskmaster` reads the Taskmaster backlog and picks ready work.
- `night` reads a PRD brief and lets the writer choose the next useful slice.
- `--project <path>` tells a source checkout to operate on another project
  root. The global `mainspring` command from pipx already targets the directory
  where you run it.
- `solo` runs one writer and one reviewer loop in the current shell. This is the default and safest first-run path.
- `team` starts up to six worker panes and dispatches Taskmaster-backed team
  work items with a per-task routing label. It requires the external team
  backend and tmux, so use it explicitly with `--topology team` after solo
  works.
- `status` prints a read-only report for root git, active tmux/processes,
  `.mainspring` runtime state, teams, Taskmaster counts, scheduler decision,
  selected-scope warnings, wave metrics, recommendations, and model defaults.
- `last-run` shows the saved project setup, timestamp, settings file, and exact repeat/preview commands.
- `--last-run` reuses `.mainspring/state/last-run.env` without executing it as shell code.
- `doctor` prints a non-mutating readiness report for commands, git state,
  locks, logs, dependencies, active team state, and provider-engine setup
  remediation.
- `--repair-state --dry-run` previews stale `.mainspring` runtime repairs without changing files.
- `--dry-run` (standalone) prints resolved settings, writer/reviewer command
  shapes, dependency checks, and exact remediation for missing provider modules
  or credentials. Zero API calls. Combine with `--preset` or `--last-run` to
  preview what a run would do.
- `--preset <name>` loads a preset env file from `presets/<name>.env`.
  CLI flags override preset values. Available: `nightly-max`,
  `conservative-docs`, `fast-smoke`.
- `--list-presets` prints available presets with descriptions.
- `--restart-team` intentionally resets active team state before launch.
  It preserves worker heads under backup refs before removing old worktrees.
- `notify-test` sends a sample Telegram notification to verify
  `MAINSPRING_TELEGRAM_BOT_TOKEN` and `MAINSPRING_TELEGRAM_CHAT_ID` are
  configured. Exits immediately after the test.

Fresh projects use `.mainspring/` for runtime state. Tests and unusual
automation setups can override runtime paths with `MAINSPRING_RUNTIME_DIR` or
`MAINSPRING_STATE_DIR`.

## Writer / Reviewer Pairs

Post-write scope checks use all discovered scope paths, while the progress
display keeps its 80-path limit. Checks run before idle or CI-retry routing and
after reviewer-feedback writer retries, including failed attempts. A violation
blocks further review and automatic checkpoints, preserving an initial failed
writer's exit status. Existing blacklist exemptions, task-state rules and mtime
discovery filters remain in place. This post-write guard provides no rollback
or read isolation.

Quota snapshots keep malformed numeric or nested evidence unknown. Remaining
percentages must be finite numbers from 0 to 100; booleans are not measurements.
Valid legacy used percentages above 100 still yield zero remaining. Binary
availability, status, source and reset metadata retain their existing meanings.

The limits report retains source labels as provenance. A label such as
`codex_sessions`, without other data, leaves a runnable adapter as
`adapter-only`. Existing status, plan, percentage and reset signals still
count; missing-setup and throttled-status precedence stay unchanged.

The hard review gate rejects a nonzero parser exit even when it produces no
message. JSON arrays, objects and booleans in known review text fields count as
missing evidence. Numeric score and delta rules, JSON priority, Markdown fallback
and duplicate-key handling are unchanged.

- `claude+codex`: Claude writes, Codex reviews.
- `codex+codex`: Codex writes, Codex reviews.
- `claude+claude`: Claude writes, Claude reviews.
- `codex+claude`: Codex writes, Claude reviews.

Default model choices are `gpt-5.5` for Codex and `opus` for Claude unless overridden. Codex reasoning defaults to `xhigh`.

The defaults are centralized through environment variables:

- `MAINSPRING_DEFAULT_CODEX_MODEL` (default `gpt-5.5`)
- `MAINSPRING_DEFAULT_FAST_CODEX_MODEL` (default `gpt-5.3-codex-spark`)
- `MAINSPRING_DEFAULT_CLAUDE_MODEL` (default `opus`)
- `MAINSPRING_CODEX_REASONING_EFFORT` (default `xhigh`)

Use the `MAINSPRING_*` names for new projects. They are the public
configuration surface for v1.

## Local Model Writer

Mainspring separates the writer from the reviewer. That means a local model can
do the first implementation pass, while Codex or Claude still performs the
independent review gate. This is the useful hybrid shape:

- local writer: lower-cost and private, good for draft implementation and docs work
- cloud reviewer: stronger gate, catches bad local output before the wave passes

Use `--engine` and `--model` for the writer. Use `--review-engine` and
`--review-model` for the reviewer. Prefer these explicit flags over `--pair`
when one side uses a custom local model id.

Before the first provider/local-model wave, run `mainspring engines`. It shows
whether the LiteLLM bridge is installed and which environment variables are
still missing. If it reports `module=litellm: missing`, run
`MAINSPRING_PROVIDERS_PYTHON=python3.13 make install-user-providers` from the
Mainspring source checkout. Missing modules or credentials fail closed before
any wave.

### Ollama

Use this when the model appears in `ollama list`.

```bash
ollama list
mainspring engines
mainspring night --prd docs/prd.md --topology solo \
  --engine ollama \
  --model 'ollama/qwen3:8b' \
  --review-engine codex \
  --review-model gpt-5.5 \
  --dry-run --once
```

`--dry-run` makes zero model calls. It only proves that Mainspring can resolve
the writer command, reviewer command, dependencies, runtime paths, and PRD path.
When the preview says `Status: READY`, remove `--dry-run` to launch the wave.

### MTPLX

Use this when MTPLX owns the local model and can expose an OpenAI-compatible
server.

Start MTPLX:

```bash
mtplx quickstart \
  --model Youssofal/Qwen3.6-27B-MTPLX-Optimized-Speed \
  --model-id qwen3.6-mtplx \
  --port 18080
```

Then run Mainspring from the project in another terminal:

```bash
OPENAI_API_BASE=http://127.0.0.1:18080/v1 \
OPENAI_API_KEY=local \
mainspring night --prd docs/prd.md --topology solo \
  --engine litellm \
  --model 'openai/qwen3.6-mtplx' \
  --review-engine codex \
  --review-model gpt-5.5 \
  --dry-run --once
```

`OPENAI_API_KEY=local` is just a non-empty placeholder for LiteLLM's
OpenAI-compatible route. MTPLX does not require a real key for localhost by
default. Change only the model id, port, and reviewer model for your own setup.

Useful verification ladder from the Mainspring source checkout:

```bash
cd /path/to/mainspring
mtplx status
mtplx models
curl -sS http://127.0.0.1:18080/health
OPENAI_API_BASE=http://127.0.0.1:18080/v1 OPENAI_API_KEY=local \
  python3 py/litellm_runner.py \
  --model 'openai/qwen3.6-mtplx' \
  --role writer \
  --prompt 'Reply with exactly OK.'
```

That low-level runner is a source-checkout diagnostic; the normal operator path
is still the `mainspring night ... --dry-run --once` command from your project.
If the runner returns `OK`, the local model path works. If the Mainspring dry-run
then says `Status: READY`, the writer/reviewer routing works. For multi-wave or
team runs, start with `--topology solo` first because many local servers are
tuned for one active request.

Direct Python callers of `build_brief(prd_path, max_chars=6000)` can set a
character limit. For a nonnegative limit below 32, an oversized summary becomes
the fitting prefix of the existing truncation marker (empty at zero).
Already-fitting summaries and normal/default output stay unchanged.
The CLI still uses 6000; this adds no CLI budget flag.

## Team Safety Rules

In team mode, Mainspring adds a routing label to each dispatched backlog item so
setup and supervision messages cannot be mistaken for product tasks. The label
is generated by Mainspring, not typed by the operator.

- The leader workspace must be clean to start new worktrees. If only
  `.taskmaster/*` is dirty, the script creates a Taskmaster checkpoint commit
  before fanout. If only `package-lock.json` is dirty, the script stashes that
  lockfile drift before fanout and tells you how to find the stash later. If
  source files are dirty, it falls back to solo instead of blocking forever.
- Auto-checkpoint uses a denylist for runtime state, logs, build outputs,
  secrets, local DBs, and screenshots/image dumps. Checkpoint commits
  use Lore trailers (`Constraint:`, `Rejected:`, `Confidence:`, `Scope-risk:`,
  `Directive:`, `Tested:`, `Not-tested:`).
- If a live team already exists, the script resumes supervision instead of launching a duplicate team.
- Bootstrap tasks are ignored for scheduling. Only Taskmaster-backed dispatch
  subjects count as product work.
- Pending assigned tasks are nudged if workers do not claim them after a short delay.
- Claimed work is requeued only with strong stale evidence: dead heartbeat, or expired lease plus stale idle status and stale heartbeat.
- Supervision requires usable worker evidence with nonnegative integer counts;
  the reported worker total determines whether all workers are dead.
- A completed backend receives no requeue, nudge or dispatch. Pending,
  in-progress or undispatched ready work, and unreadable counts, ready items or
  skip reasons, cause refusal with restart guidance. Successful no-more-work
  keeps the existing solo fallback choice. Active count-read failures retain retries.
- The selected Taskmaster tag's tasks must be an array. Other collection shapes
  are read errors; missing tag/tasks defaults and tag priority stay unchanged.
- If tmux cannot allocate panes for the requested worker count, the launcher automatically retries with fewer workers.
- Team dispatch skips duplicate Taskmaster-backed subjects already present in
  the active team ledger. Worker prompts include Taskmaster id, expected file
  scope, verification requirement, and the no-parent-closure rule.
- `MAINSPRING_TEAM_EXCLUDE_PREFIXES` is a colon/comma-separated list of path
  prefixes that team fanout should skip, which is useful for nested git repos
  or scopes that worker worktrees cannot see.
- `.claude/` helper worktrees are excluded by default; configured prefixes are
  additive.
- Parallel scope extraction recognizes supported roots at token starts:
  `packages/web/src/index.ts` no longer advertises `src/index.ts`.
  Existing `./` spellings, literal trailing periods and unknown-scope fallback
  remain unchanged. This is text matching, not filesystem validation.

## Wave Ledger

Every completed solo wave and team preflight/dispatch appends JSONL to `.mainspring/logs/waves.jsonl`.

Stable fields:

- `timestamp`
- `wave_id`
- `mode`
- `topology`
- `team`
- `task_id`
- `selected_lane`
- `engines`
- `models`
- `duration_seconds`
- `changed_files`
- `tests`
- `verdict`
- `exit_code`
- `failure_reason`
- `retry_count`
- `blocked_reason`
- `next_action`

`--status` reads this ledger, ignores malformed and non-object JSONL rows, prints
the last valid wave, and derives routing hints from recent failures. JSON object
rows retain their existing verdict and routing interpretation.

Metrics ignore malformed JSON and non-object JSONL rows. Included objects remain in totals when `exit_code` is missing or invalid; success requires `PASS` and an actual
integer `0` (not Boolean, string, null or float). Time filters require usable zoned timestamps; the ledger writer emits UTC/Z and readers accept explicit offsets. Without
a time filter, timestamp shape does not exclude rows. A date-only `--since YYYY-MM-DD` still starts the window at midnight UTC.

## Logs

Logs are written under `.mainspring/logs/`.

Claude stream display ignores malformed typed fields and keeps later valid events.
Valid writer/reviewer output is mirrored to stdout and the display file. The
formatter owns and closes its UTF-8 append display file on exit, including
interruptions, while borrowed stdout remains open. Eager creation, flush order
and I/O errors keep their behavior. Raw logs and text-source rules are unchanged;
no assistant/result text fallback is added.
Actual display/output I/O errors still fail.

- `.mainspring/logs/latest.log`: most recent run log.
- `.mainspring/logs/latest-taskmaster.log`: most recent Taskmaster run log.
- `.mainspring/logs/latest-summary.log`: latest summary output.
- `.mainspring/logs/latest-taskmaster-summary.log`: latest Taskmaster summary output.

## Recovery Commands

Start with read-only inspection. Do not resume saved work or launch a new wave
until the current state is understood. A persistent `.guard` is not stale PID
metadata and must not be removed/replaced by repair. Version cutover and rollback
require [all-invocation and waiter drain](#coordinated-runtime-lock-updates), not
only a successful `stop`, `status` or `doctor` check.

| Need | Run | Effect |
| --- | --- | --- |
| Global live view | `mainspring hud` | Read-only live dashboard for every discovered run. |
| Include old runs | `mainspring hud --all-runtimes` | Read-only history plus live rows. |
| Current project only | `mainspring hud --local` | Read-only dashboard scoped to the current project. |
| Project status | `mainspring status` | Read-only runtime, git, Taskmaster, and next-action status. |
| Environment check | `mainspring doctor` | Read-only dependency, lock, notifier, and engine diagnostics. |
| Saved setup | `mainspring last-run` | Read-only saved launch settings. |
| Repair preview | `mainspring --repair-state --dry-run` | Read-only stale-state repair plan. |
| Stop this project | `mainspring stop --force` | Terminates recorded current-project Mainspring processes. |
| Repair stale state | `mainspring --repair-state --force` | Applies only the reviewed repair preview. |

Ctrl-C exits the active run with status 130; SIGTERM, including
`mainspring stop --force`, exits with status 143. Shutdown stops only the
active engine pipeline and its descendants, gives them a short TERM grace
period, drops observed exited or zombie PIDs, and escalates only surviving
processes to KILL before releasing the runtime lock. No following wave starts.

`mainspring.lock` and `notifier.pid` use the same project check for recognized
notifier commands: the command must name this project's ledger or state path.
Relative-only notifier paths are insufficient attribution. The explicit
`--all` override, generic launcher handling and current-process protection
retain their existing behavior.

For structured Claude logs, quota classification uses engine error evidence
or a rate-limit event with status `rejected`. An `allowed_warning` event means
work is still permitted. Task prose about quotas and malformed rate-limit
metadata do not by themselves turn an unrelated process failure into quota
exhaustion.

Use `mainspring stop --help`, `mainspring --repair-state --dry-run`, and
`mainspring last-run` before any forceful recovery. `mainspring --last-run` and
`mainspring taskmaster ...` launch work; use them only after the recovery check
shows the project is safe to resume.

## No-Side-Effect Smoke Checklist

```bash
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git status --short --untracked-files=all > "$tmp/status-before.txt"
shasum .taskmaster/tasks/tasks.json .mainspring/state/skill-active-state.json 2>/dev/null > "$tmp/state-before.txt"
mainspring status > "$tmp/status-report.txt"
git status --short --untracked-files=all > "$tmp/status-after.txt"
shasum .taskmaster/tasks/tasks.json .mainspring/state/skill-active-state.json 2>/dev/null > "$tmp/state-after.txt"
diff -u "$tmp/status-before.txt" "$tmp/status-after.txt"
diff -u "$tmp/state-before.txt" "$tmp/state-after.txt"
mainspring --repair-state --dry-run
```

## Telegram Notifications

Mainspring can send Telegram notifications for key events during autonomous execution.

The internal `detach_exec.py` launch helper reports usage status 2 for a missing
or empty first command before session or exec operations. Valid commands retain
their argv. Operating-system exec errors retain status 127; session-creation
exceptions still propagate before execution. This adds no daemon-ready or recovery contract.

Use this when you run several long-lived projects at once. Runtime event
messages include `Project:`, `Folder:`, and `Tag:` so you can tell which run is
speaking.

**Setup:**

1. Create a Telegram bot via @BotFather and note the bot token.
2. Get your chat ID: send a message to the bot, then query Telegram's
   `getUpdates` endpoint for that bot token.
3. Set environment variables:
   ```bash
   export MAINSPRING_TELEGRAM_BOT_TOKEN="your-bot-token"
   export MAINSPRING_TELEGRAM_CHAT_ID="your-chat-id"
   ```
4. Test: `mainspring notify-test`
5. Enable auto-launch: `export MAINSPRING_NOTIFY_ENABLED=1`

**Event classes:**

| Event          | Trigger                                  | Rate limit   |
| -------------- | ---------------------------------------- | ------------ |
| `wave_failed`  | Wave verdict != PASS or exit_code != 0   | 1 per 5 min  |
| `retry_loop`   | 3+ consecutive fails on the same task_id | 1 per 5 min  |
| `loop_stopped` | Scheduler reaches terminal STOP          | 1 per 5 min  |
| `quota_warn`   | Engine usage delta > 90% of short window | 1 per 5 min  |
| `team_stuck`   | No new JSONL line in 30 minutes          | 1 per 5 min  |
| `milestone`    | chapter_delta > 50 or task marked done   | 1 per 5 min  |
| `daily_digest` | Once per day at 09:00 local              | Once per day |

**How it works:**

- Background daemon `notify_telegram.py watch` tails `.mainspring/logs/waves.jsonl`.
- Idle-threshold shutdowns write an explicit `STOP` ledger row, so the daemon
  sends `loop_stopped` instead of silently ignoring the final `IDLE` wave.
- On shutdown, Mainspring waits briefly for its own notifier daemon to process
  pending ledger lines before cleanup reaps the process.
- When a retry loop is detected, Mainspring sends one stronger `retry_loop`
  alert, suppresses duplicate `wave_failed` noise for that batch, and includes
  local `Open:` / `Stop:` commands for the affected project when context is
  known.
- Actionable event messages include `Project:`, `Folder:`, `Tag:`, `Task:`,
  `Pair:`, `Result:`, `Reason:`, `Next:`, and `Duration:` when the ledger has
  that context. `Project:` and `Folder:` come from the watched project root;
  `Tag:` comes from `MAINSPRING_TASKMASTER_TAG` or `.taskmaster/state.json`
  when Taskmaster context is present. This keeps parallel Mainspring runs
  distinguishable in one Telegram chat.
- Auto-launched when `MAINSPRING_NOTIFY_ENABLED=1` before the wave loop starts.
- Auto-reaped on exit (cleanup trap).
- Daemon failure never blocks a wave.
- Dedup state persisted in `.mainspring/state/notify-state.json`.
- Daemon log at `.mainspring/logs/notifier.log`.

**Recovery:**

If the daemon stops responding:

```bash
mainspring notify-health --format json
mainspring notify-restart
mainspring notify-test
```

`notify-restart` only stops the notifier recorded in `.mainspring/state/notifier.pid`
after validating that the process belongs to this runtime's ledger. Avoid broad
process-name kills; they can kill another project's notifier.

## Development Verification

`make coverage` is the dependency-free helper-line gate with the existing 80%
threshold. Supported first-party Python CLI interception restores the caller's
working directory and normalizes UTF-8 text newlines; byte output stays exact.
Non-None deadlines, explicit decoding/error options and conflicting text flags
use genuine subprocess execution. Those child lines can remain unobserved while
eligible source still stays in the denominator.

This is a bounded tracing measure, not a full subprocess emulator or proof of
live account/provider integration. Keep native behavior and observability
separate when interpreting the result; passing the threshold does not erase
unobserved source or establish native-locale/Windows parity.

## Docs Site Maintenance

The docs-site generator checks canonical document inputs before output writes
or cleanup. Incremental writes reject symbolic or hard-link aliases to those
inputs. Marked generated output can still be rebuilt, including removing output
symlinks without changing source targets. Unmarked incremental output keeps
unrelated custom assets.

## Known Non-Product Inputs

Manual credentials, production keys, live deployment, legal copy, and store
submission steps must stay isolated as separate Taskmaster work. They should
not block implementation work that can be completed locally.
