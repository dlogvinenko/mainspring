# Changelog

All notable Mainspring release changes are recorded here. The v1.0.0 GitHub
Release notes can be published from this file after the final release commit is
tagged and checked against `docs/prd.md`.

## v1.0.0 - Public Source Release

Mainspring is framed as Product Requirements Document (PRD)-first AI coding agent orchestration
for production-grade software delivery. It turns unstructured vibe coding into planned,
reviewed, observable, and auditable autonomous engineering work.

### Added

- Hard reviewer gate with structured JSON review parsing, fail-closed reviewer
  transport handling, and no silent pass when reviewer output is missing.
- Modular shell/Python runtime with extracted Python helpers, `mainspring
  --dry-run`, presets, and local CI gates for shell, Python, and Bats tests.
- Taskmaster-aware Method commands: `init`, `decompose`, `scope-check`, and
  blocker-aware `next`.
- Telegram notifications with dedup/rate limiting, daily cost digest,
  notifier health checks, and safe recorded-PID restart.
- Read-only terminal HUD with JSON, plain text, Rich, and bounded watch modes.
- LiteLLM-backed provider registry for Codex, Claude, Gemini, Grok, OpenAI,
  Anthropic, Azure, OpenRouter, Mistral, and Ollama routes.
- Metrics and routing reports, auto-disabled pair state, replayable wave ledger
  metadata, and deterministic golden-run fixtures.
- Source distribution groundwork: `pyproject.toml`, console entry point,
  package smoke, pipx smoke, generated Homebrew formula metadata, and
  fresh-clone smoke gate.
- Public release docs: README, guide, playbook, architecture notes, metrics
  schema, and generated GitHub Pages/Jekyll source.
- GitHub-facing README launch surface with a source-install-ready badge, a
  committed visual PRD-to-evidence hero, explicit GitHub source install
  instructions, generic PATH guidance, green/red decision tables,
  one-command start, HUD and Telegram sections, engine matrix, and honest
  publication checklist.

### Changed

- Runtime naming now prefers `MAINSPRING_*` and `.mainspring/`, with
  compatibility aliases for pre-v1 environment names where the current runtime
  still reads them.
- Public CLI help now stays focused on operator commands a normal user should
  run.
- GitHub repository metadata now uses the Product Requirements Document
  (PRD)-first description and discovery topics for public release.
  Release work is documented as normal maintainer actions: run local gates,
  create a signed tag, and publish a GitHub Release from this changelog.
- Pending benchmark result pages were removed from public docs; benchmark
  collateral should be published only after real SWE-bench evidence exists.
- GitHub Pages workflow now grants `pages: write` and `id-token: write` only
  to the gated deploy job; build and pull-request runs keep read-only contents
  permissions.
- Structured review validation now rejects non-numeric chapter, competitor, and
  launch deltas before a reviewer verdict can pass the wave.
- Provider execution fails closed on missing dependencies, missing credentials,
  malformed LiteLLM responses, or unknown engine names.
- Team routing records canonical failure classes and falls back to solo for
  recoverable worktree visibility issues instead of blocking ready work.
- `docs/prd.md` current-truth snapshot now reflects the standalone repo,
  resolved SC2259 state, implemented local CLI surfaces, and the remaining
  publication checklist items with release-only commands kept out of the
  public CLI.

### Publication Checklist

- Run the final local gates on the exact release commit.
- Push the release commit with GitHub auth that can update workflow files, then set
  repository visibility to public.
- Create a signed `v1.0.0` tag on the final clean release ref.
- Publish the GitHub Release with notes sourced from this changelog.
- Optional after public release: publish package-manager distribution, hosted
  docs, benchmark results, and real provider-matrix evidence.
