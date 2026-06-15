# Mainspring Competitive Positioning

**Snapshot date:** 2026-06-14
**Purpose:** explain where Mainspring fits among AI coding tools, why the
Product Requirements Document (PRD)-first approach matters, and what a public
v1 release is ready to claim.

This page intentionally avoids volatile star counts. It links to official
product pages, docs, or repositories so readers can verify the landscape for
themselves.

## Executive Summary

Mainspring is not another chat-style coding assistant. It is a local control
loop for production-grade autonomous coding work:

> Product Requirements Document (PRD)-first AI coding agent orchestration for
> production-grade software delivery.

That means Mainspring starts from intent, turns it into bounded writer/reviewer
waves, records JSONL evidence, shows operator state in a terminal HUD, and sends
Telegram alerts when work needs attention.

The wedge is operational trust. Tools like Aider, OpenCode, Cline, Goose,
OpenHands, and cloud coding agents are excellent at producing code. Mainspring
focuses on the surrounding system production work needs: requirements,
selection, scope control, independent review, evidence, replay, notifications,
and recovery.

## Market Map

| Segment | Examples | What users buy | Mainspring position |
| --- | --- | --- | --- |
| Terminal pair programmers | Aider, OpenCode, Goose | Fast local edits from a conversational loop. | Mainspring wraps work in PRD/task intent, reviewer gates, evidence, and operator state. |
| IDE approval agents | Cline, Roo Code, Cursor | Editor-native edits with per-action approval. | Mainspring favors unattended bounded waves instead of approval on every step. |
| Cloud coding agents | GitHub Copilot cloud agent / Agent HQ, Devin, Cursor agents | Assign work and receive branches or pull requests. | Mainspring is local, inspectable, model-flexible, and not tied to a hosted workflow. |
| Agent platforms and SDKs | OpenHands, Cline SDK, Goose API | Build custom coding-agent products. | Mainspring is a ready operator tool first, not a general agent SDK. |
| PRD/task decomposition | Claude Task Master / Taskmaster | Convert requirements into structured tasks. | Mainspring complements Taskmaster with execution, review, HUD, Telegram, replay, and wave evidence. |
| Orchestration | Agent Orchestrator, OpenAI Symphony, Claude Squad, Claude Code Agent Teams | Run many coding agents in isolated workspaces or coordinated sessions. | Mainspring adds PRD-first intent, cross-engine routing, fail-closed review, and local operator evidence. |
| AI quality gates | Continue | Source-controlled AI checks on pull requests. | Mainspring gates every autonomous wave before it claims progress. |
| Benchmark/research agents | SWE-agent | Reproducible SWE-bench-style issue solving. | Mainspring keeps source-only benchmark tooling and treats public benchmark evidence as follow-up credibility work. |

## Fresh Landscape

| Tool | Official surface | Main positioning | How Mainspring differs |
| --- | --- | --- | --- |
| OpenCode | [opencode.ai](https://opencode.ai/), [repo](https://github.com/anomalyco/opencode) | Open-source coding agent across terminal, desktop, IDE, providers, and local models. | Mainspring is narrower: PRD/task execution, reviewer evidence, HUD, Telegram, and replay. |
| OpenHands | [openhands.dev](https://openhands.dev/), [SDK docs](https://docs.openhands.dev/sdk), [repo](https://github.com/OpenHands/OpenHands) | Agent platform and SDK for software tasks. | Mainspring is a local operator workflow rather than a platform for building new agent products. |
| Cline | [cline.bot](https://cline.bot/), [docs](https://docs.cline.bot/cline-overview), [repo](https://github.com/cline/cline) | Coding agent runtime for editor, terminal, SDK, and explicit user approval. | Mainspring is better suited when the operator wants bounded unattended waves with evidence. |
| Goose | [goose-docs.ai](https://goose-docs.ai/), [repo](https://github.com/aaif-goose/goose) | Local general-purpose AI agent: desktop, CLI, API, MCP. | Mainspring is less general and more release/audit/process oriented. |
| Aider | [aider.chat](https://aider.chat/docs/), [repo](https://github.com/Aider-AI/aider) | AI pair programming in your terminal with deep git workflow. | Mainspring is not a chat editor; it is a supervisor around planned autonomous work. |
| Continue | [continue.dev](https://www.continue.dev/), [docs](https://docs.continue.dev/), [repo](https://github.com/continuedev/continue) | AI checks as pull-request status checks. | Mainspring runs implementation waves and gates the wave result before it moves on. |
| Claude Task Master | [tryhamster.com/product/taskmaster](https://tryhamster.com/product/taskmaster), [repo](https://github.com/eyaltoledano/claude-task-master) | PRD parsing, task dependencies, structured AI-agent work. | Mainspring pairs naturally with Taskmaster and adds execution/review/observability. |
| OpenAI Symphony | [OpenAI post](https://openai.com/index/open-source-codex-orchestration-symphony/), [repo](https://github.com/openai/symphony) | Manage work, not agents; isolated autonomous implementation runs. | Mainspring is local, multi-engine, Taskmaster-aware, and built around evidence-ledger operations. |
| Roo Code | [docs](https://roocodeinc.github.io/Roo-Code/), [repo](https://github.com/RooCodeInc/Roo-Code) | Editor-centered multi-mode coding agents. | Mainspring is terminal/operator-first and built for repeated autonomous runs. |
| SWE-agent | [swe-agent.com](https://swe-agent.com/), [repo](https://github.com/SWE-agent/SWE-agent) | Research-grade issue-solving agent with SWE-bench credibility. | Mainspring is product-operator workflow first; benchmarks are evidence, not the product surface. |
| Claude Squad | [repo](https://github.com/smtg-ai/claude-squad) | TUI for many terminal agents in separate workspaces. | Mainspring adds PRD/task selection, independent review, Telegram, and an evidence ledger. |
| Agent Orchestrator | [repo](https://github.com/AgentWrapper/agent-orchestrator), [site](https://ao-agents.com/) | Parallel coding agents, worktrees, CI fixes, merge conflicts, reviews. | Mainspring optimizes for Product Requirements Document (PRD)-first local operation rather than tracker/PR automation as the primary UX. |
| GitHub Copilot cloud agent / Agent HQ | [cloud-agent docs](https://docs.github.com/en/copilot/concepts/agents/cloud-agent/about-cloud-agent), [third-party agents](https://docs.github.com/copilot/concepts/agents/about-third-party-agents), [Agent HQ](https://github.com/features/copilot/agents) | GitHub-native background agents for issue-to-branch work, including Copilot, third-party agents, and custom agents. | Mainspring is useful when work must stay local, source-visible, cross-tool, model-flexible, and inspectable outside a hosted control plane. |
| Devin | [devin.ai](https://devin.ai/) | Parallel cloud agents for engineering teams. | Mainspring is a local open-source operator tool instead of a hosted SaaS agent. |
| Claude Code Agent Teams | [docs](https://code.claude.com/docs/en/agent-teams) | Experimental, disabled-by-default coordination for multiple Claude Code sessions. | Mainspring keeps cross-engine routing, Taskmaster/PRD workflow, and ledger-based evidence. |

## 1000-Point Release Readiness Method

This score measures whether Mainspring is ready for a public source release, not
whether it has more distribution than established competitors.

| Category | Points | What earns points |
| --- | ---: | --- |
| Product clarity | 120 | Clear buyer problem, PRD explanation, install path, examples, and SEO language. |
| Core workflow | 170 | PRD/Taskmaster selection, writer/reviewer loop, bounded waves, no self-grading. |
| Verification and evidence | 160 | Tests, coverage, reviewer validation, JSONL ledger, replay, fail-closed behavior. |
| Operator UX | 130 | Machine-wide HUD, status, last-run, stop/recovery, readable help, useful empty states. |
| Notifications | 90 | Telegram health, test/restart commands, project/folder/tag-aware event payloads. |
| Engine flexibility | 110 | Codex, Claude, LiteLLM providers, Ollama/local model path, no silent fallback. |
| Packaging and install | 100 | Source install, pipx console command, package smoke, global shell visibility. |
| Repository hygiene | 80 | No secrets, no private local paths, ignored runtime state, public security policy. |
| External growth | 40 | Hosted docs, package-manager distribution, public benchmark results, and provider matrix after source release. |
| **Total** | **1000** |  |

## Mainspring v1 Score

| Area | Score | Evidence |
| --- | ---: | --- |
| Product clarity | 112 / 120 | README opens with Product Requirements Document (PRD)-first positioning, install, start flow, HUD, Telegram, local models, and copy/paste commands. |
| Core workflow | 160 / 170 | Taskmaster and PRD modes run through writer/reviewer waves with scope checks and fail-closed review. |
| Verification and evidence | 150 / 160 | `make all`, package smoke, coverage, replay tests, golden runs, and reviewer validation are green locally. |
| Operator UX | 120 / 130 | `mainspring hud`, `status`, `last-run`, `doctor`, `stop`, and guided start are documented and tested. |
| Notifications | 84 / 90 | Telegram health/restart/test plus project/folder/tag-aware payloads are implemented. |
| Engine flexibility | 96 / 110 | Codex, Claude, LiteLLM provider routes, Ollama, and MTPLX-style local writer dry-runs are supported. |
| Packaging and install | 88 / 100 | `make install-user` installs the global command through pipx; PyPI/Homebrew are public-growth follow-ups. |
| Repository hygiene | 76 / 80 | Security policy, secret scans, ignore checks, and public string guards are in place. |
| External growth | 14 / 40 | Hosted docs are live; benchmark, public package channels, provider-matrix evidence, and comparison pages remain useful follow-up credibility work. |
| **Total** | **900 / 1000** | Public source release is live on a clean `main`, with hosted CI and Pages green. Signed tag and GitHub Release remain the publication steps for the `v1.0.0` announcement. |

## Fit Matrix

| If you need... | Use Mainspring when... | Use another tool when... |
| --- | --- | --- |
| Fast conversational edits | You want those edits wrapped in PRD/task intent, review, and evidence. | You only need an interactive chat editor for a tiny change. |
| Multi-agent parallelism | You need to see folder, PID, tag, task, result, and next action across runs. | You mainly want a visual terminal multiplexer for manual agent sessions. |
| PRD-to-work execution | You want requirements to drive implementation waves and audit evidence. | You only need to generate a task list and will execute manually. |
| Local/private operation | You need local state, local model writer options, and no hosted control plane. | You want managed cloud workers opening pull requests for you. |
| Review gates | You want every wave to stop if review JSON, tests, scope, or credentials are wrong. | You only need PR-level AI checks after humans already opened the PR. |

## Public Claims Mainspring Can Make

- Product Requirements Document (PRD)-first AI coding agent orchestration.
- Local AI coding agent orchestration for production-grade software delivery.
- Writer/reviewer AI coding workflow with fail-closed review.
- Taskmaster-aware execution loop.
- JSONL evidence ledger and replay.
- Terminal HUD for multiple coding-agent runs.
- Telegram alerts for autonomous coding runs.
- Local model writer with Codex or Claude reviewer.

## Claims To Avoid

- "Best coding agent." That is too broad and benchmark-dependent.
- "Fully autonomous software engineer." That overpromises and attracts the
  wrong buyer.
- "Replaces Taskmaster, Aider, OpenCode, Cline, or Goose." Mainspring is the
  execution/review/evidence layer around production-grade work, not a universal replacement.
- "No human action needed." Mainspring is explicit about when credentials,
  releases, repository visibility, or external services require the operator.

## Search And Discovery Plan

Use the full phrase **Product Requirements Document (PRD)** on first mention,
then use **PRD-first** after the acronym is defined. Pair it with broader
phrases such as **AI coding agent orchestration**, **autonomous coding workflow**,
and **production-grade software delivery** so developers who do not
search for PRD still understand the category.

| Priority | Action | Why |
| --- | --- | --- |
| P0 | Keep README first sentence keyword-rich: "Product Requirements Document (PRD)-first AI coding agent orchestration for production-grade software delivery." | GitHub previews and search need the category immediately. |
| P0 | Keep GitHub topics aligned: `ai-coding-agent`, `coding-agent`, `agent-orchestration`, `prd`, `taskmaster`, `llm-agents`, `codex`, `claude`, `ollama`, `litellm`, `developer-tools`. | GitHub discovery and related-repo placement. |
| P0 | Ship screenshots/demo assets for README and docs. | The value is operational; people need to see HUD, Telegram, and evidence. |
| P1 | Keep hosted docs live and add comparison pages. | Searchable durable docs beat README-only marketing, and high-intent pages convert better than generic docs. |
| P1 | Add comparison pages: "Mainspring vs Aider", "Mainspring vs OpenCode", "Mainspring vs Task Master", "Mainspring vs Agent Orchestrator". | High-intent search pages convert better than generic docs. |
| P1 | Publish a narrow honest benchmark or SWE-bench Verified result. | Unlocks stronger quality claims. |
| P2 | Add optional GitHub/Linear backlog adapters behind the existing BacklogSource boundary. | Helps teams that start from issue trackers without weakening PRD/Taskmaster defaults. |
| P2 | Add source-controlled review checks inspired by Continue. | Converts wave-level review discipline into repository policy. |

## Next Public Evidence

The source release uses normal public project actions. The next credibility
items are:

| Evidence | Why it matters |
| --- | --- |
| Signed `v1.0.0` tag + GitHub Release | Makes the v1.0.0 publication durable and referenceable. |
| Package-manager distribution | Reduces install friction after source install is proven. |
| Demo video or GIF | Shows PRD -> wave -> reviewer -> HUD -> Telegram -> ledger in under a minute. |
| Benchmark/provider matrix | Gives stronger public evidence for model-routing and quality claims. |

## Bottom Line

Mainspring exists because "vibe coding" and generic coding agents do not solve
the operator problem: knowing what the agent is trying to do, whether it
actually moved the product, what failed, how to resume, and what evidence exists.

Its public v1 strength is the combination of PRD discipline, bounded waves,
independent review, fail-closed evidence, HUD/Telegram visibility, local/private
model routing, and recovery commands.
