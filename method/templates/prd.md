# {{Project / Scope name}} — Product Requirements Document (PRD)

> **What is a PRD?** A single canonical document that defines a project, feature, or scope end-to-end — from mission and principles through architecture, phase plan, ADRs, and release criteria. It's the ONE place a future agent (human or AI) reads to understand the project, decide what to do next, and verify what "done" means.
>
> **Why a PRD?** Without it, work is improvised: AI agents hallucinate features that don't exist, stakeholders work toward different mental models, scope creeps, manual blockers smuggle into coding tasks, "done" means different things to different people. A PRD makes all of these structurally impossible by being explicit and canonical.
>
> **How to write one** (60-90 min for a medium scope, 2-3 hours for a major refactor):
>
> 1. Audit reality first (Step 2 of the Method) — verified numbers, not estimates.
> 2. Reality-reset old planning artifacts before writing this PRD (Step 3) — one canonical document per scope.
> 3. Ratify ADRs with the user explicitly (Step 4) — don't guess load-bearing decisions.
> 4. Fill in every section below in order. The 17 sections are mandatory; if a section doesn't apply, write "N/A — <one-line reason>" rather than deleting it.
> 5. Save at `docs/<scope>/prd.md`. Delete this template note before saving.
>
> Replace every `{{...}}` placeholder. The placeholders are guidance; the prose around them is canonical and must be preserved.

**Status:** {{`canonical plan, supersedes <list of prior docs>` | `draft for review` | `living document, last verified <date>`}}.
**Owner:** {{author / role}}.
**Companion docs:** {{links to operator guide, metrics doc, architecture doc, etc., or `none yet`}}.

{{One-paragraph elevator pitch: what this document drives, from what current state to what end state, by when. Concrete enough that a future agent reading only this paragraph + the contents below can act without other context.}}

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
12. [Definition of Done (release checklist)](#definition-of-done-release-checklist)
13. [Explicit non-goals](#explicit-non-goals)
14. [Backlog (Must / Should / Could / Won't)](#backlog-must-should-could-wont)
15. [Appendix A — Source-of-knowledge recipes](#appendix-a-source-of-knowledge-recipes)
16. [Appendix B — Verification commands](#appendix-b-verification-commands)
17. [Acknowledgments / Lineage](#acknowledgments-lineage)

---

## Mission

{{One paragraph: what this thing is, who it's for, what three verbs it lives by. End with the explicit non-audience.}}

**Three verbs**: {{e.g. pick, ship, prove}}.
**Audience**: {{ranked list — primary / secondary / tertiary}}.
**Non-audience**: {{who this is explicitly NOT for, so scope creep can be rejected}}.

---

## Durability principles

The N commandments. Anything below this line bows to them. If a phase plan, a feature, or an ADR conflicts with one of these, the plan loses.

1. **{{principle 1 title}}.** {{1-3 sentences explaining + a negative example of what violating it looks like}}
2. **{{principle 2 title}}.** {{...}}

{{Aim for 6-12 principles. Each must be falsifiable: you can point at a code change and say "this violates principle N". Vague principles like "be good" are forbidden.}}

---

## Current truth snapshot (verified)

Captured {{YYYY-MM-DD}} via {{audit method, e.g. "static audit, zero side effects" / "live --doctor run"}}.

| Metric                    | Value     | Source                             |
| ------------------------- | --------- | ---------------------------------- |
| {{e.g. LOC of main file}} | {{value}} | {{`wc -l <path>`}}                 |
| {{lint status}}           | {{value}} | {{`shellcheck -S warning <path>`}} |
| {{count of N pattern}}    | {{value}} | {{`grep -c <pattern> <path>`}}     |

{{Every row must have a Source command that the user could re-run. No row is "estimated" — if you don't know, run the command.}}

**What works today** (confirmed via {{method}}):

- {{specific working capability with command/path proof}}
- {{...}}

**What is broken / dangerous**:

- {{specific bug with file:line + impact, e.g. "scripts/foo.sh:2454 SC2259 silently passes empty content to reviewer"}}
- {{...}}

**What was never proven**: {{things in prior docs that the audit could NOT verify, OR `nothing — every claim above has a source command`}}.

---

## Naming and brand boundary

Three names that must never blur:

| Name                          | What it is                                    | Where it lives              |
| ----------------------------- | --------------------------------------------- | --------------------------- |
| **{{This thing}}**            | {{the system being defined here}}             | {{paths / repos / domains}} |
| **{{Adjacent dependency 1}}** | {{external thing this depends on but is NOT}} | {{where it lives}}          |
| **{{Adjacent dependency 2}}** | {{...}}                                       | {{...}}                     |

**The user-facing bag**:

- CLI binary / entry point: {{name + path}}
- Runtime state: {{path on disk}}
- Env vars: {{prefix pattern, e.g. `MAINSPRING_*`}}
- Config dir: {{`~/.<name>/` if applicable}}
- Logs: {{paths}}

{{If naming requires migration from old names, explain when and why the rename happens (which phase) and why we wait until then.}}

---

## Target architecture

The shape this thing must reach to be called v1.0 ready.

### File layout

```
{{tree showing target directory structure}}
```

### Public contract (frozen at v1.0)

{{Whatever interface this thing exposes — CLI, HTTP API, library API, file format. Frozen means: adding is non-breaking, renaming/removing requires a major bump + deprecation window. Be exhaustive.}}

### Core data shapes (frozen)

{{JSON schemas, DB tables, file formats. Required vs optional fields, types, examples.}}

### Concrete code shapes (load-bearing)

{{The 2-5 functions/files that anchor the architecture. Show the exact signature, not paraphrased. These are the contracts modules speak through.}}

---

## Phase map

{{N}} phases. Each phase ends green: {{the verification gate, usually `bash -n`/`shellcheck`/tests/build/docs}}. No phase commits unless verification is clean.

> **Phase-by-phase decomposition**: only the currently-active phase gets decomposed into Taskmaster (Method Step 6). Future phases stay as outlines below. The Mainspring Playbook (`docs/playbook.md` in this repository) drives the activation/completion lifecycle for each phase.

> **Commit policy**: {{e.g. "no intermediate commits between phases — single v1.0.0 release commit at the end" or "feature-branch per phase, squash-merge to main"}}

### Phase {{0}} — {{Reality reset}} ({{DONE | TBD time estimate}})

**Goal:** {{one sentence}}.

- [{{x|}}] {{atomic task with file:line where applicable}}
- [{{x|}}] {{...}}

**Acceptance:**

- {{verification step that proves the phase is done}}
- {{...}}

{{Repeat for each phase. Phases should be sized so each is 1-3 weeks of work or 1-2 days for small projects. If a phase is bigger, split it.}}

---

## Architecture decisions (ADRs)

{{N}} load-bearing decisions. Each is reversible only at high cost; each is documented here so future maintainers can read them and either re-confirm or override.

### ADR-01: {{decision title}}

**Context:** {{what situation forces a decision}}.

**Options considered:** {{the alternatives, with one-line trade-off each}}.

**Decision:** {{the chosen option}}.

**Rationale:** {{why this option won — concrete reasons, not "feels right"}}.

**Consequences:** {{what changes / what we now have to do because of this}}.

**Reversal cost:** {{`trivial` | `low` | `medium` | `high` | `very high — get this right now`}}.

{{Repeat for each ADR. Common ADRs to consider: license, naming, versioning policy, primary tech stack, deprecation window, monetization model (if applicable), data retention.}}

---

## Operational doctrine

{{How to actually USE this thing in daily work. The lived contract. Reference the operator guide for full command syntax; this section is the WHEN-TO-USE-WHAT decision tree.}}

### When to {{use mode A vs mode B}}

{{Decision criteria, e.g. "Default to solo unless N+ items in queue and leader workspace is clean"}}.

### {{Other operational rules}}

{{...}}

---

## Health rituals

Two recurring checks. The intent is small enough to actually do; the consequences of skipping are large enough to make the discipline worthwhile.

### Weekly (≤ 10 min)

1. {{specific command + what to look for}}
2. {{...}}

### Monthly (≤ 30 min)

1. {{run weekly first}}
2. {{...}}

---

## Disaster recovery

{{N}} failure modes that have happened or are likely to happen, with concrete recovery steps.

### {{Failure mode title, e.g. "Corrupted runtime state"}}

**Detect:** {{symptom}}.

**Recover:**

```bash
{{exact recovery commands}}
```

{{Repeat for each failure mode. Aim for 4-8 modes covering: data corruption, crashed mid-operation, runaway loop, stuck dependency, lock without owner, network partition, etc.}}

---

## Versioning and migration

### SemVer policy

{{What's MAJOR / MINOR / PATCH for this thing. Be specific: list public-surface changes that bump major.}}

### Schema versioning ({{if applicable, e.g. JSONL / DB / API}})

{{Version field, deprecation window, both-shape emission strategy.}}

### Env var / config deprecation

{{Renaming workflow: read both for one minor version, log deprecation notice, drop old.}}

### Migration script

{{runtime-state compatibility, if this project needs one.}}

---

## Definition of Done (release checklist)

This thing is v1.0-ready when **all** of the following are true.

### Correctness

- [ ] {{specific gate}}
- [ ] {{...}}

### Architecture

- [ ] {{...}}

### Tests

- [ ] {{coverage threshold}}
- [ ] {{test count threshold}}
- [ ] {{CI matrix}}

### Observability

- [ ] {{...}}

### Safety

- [ ] {{...}}

### UX

- [ ] {{...}}

### Portability

- [ ] {{fresh-box install works}}

### Documentation

- [ ] {{README, API docs, migration guide, etc.}}

### Legal (if OSS)

- [ ] LICENSE file
- [ ] NOTICE file (if Apache-2.0)
- [ ] SPDX headers on every source file
- [ ] Copyright = "{{Project}} contributors", no individual

### Release

- [ ] {{tagging, release notes, public availability}}

---

## Explicit non-goals

These are things this project will **never** become. Reject any change that moves toward them.

- **Not {{anti-feature 1}}.** {{one-line reason}}.
- **Not {{anti-feature 2}}.** {{...}}

{{Aim for 6-12. The point is to make scope-creep rejection easy: "that's a non-goal, see PRD".}}

---

## Backlog (Must / Should / Could / Won't)

Ranked by value-per-effort.

### Must (blocks this release or scope)

1. {{phase reference + one-line goal}}
2. {{...}}

### Should (v1.x post-release)

1. {{...}}

### Could (v2 candidates, only if data justifies)

1. {{...}}

### Won't (explicit non-goals — do not propose)

- See [Explicit non-goals](#explicit-non-goals).
- {{specific items the team has been asked for and rejected, with the date asked}}

---

## Appendix A — Source-of-knowledge recipes

{{Reference snippets, code excerpts, schemas, and patterns that anchor the architecture. Useful when the canonical implementation lives elsewhere or is inherited from a deleted prior plan. Future agents should be able to reconstruct the contract from this appendix without external dependencies.}}

---

## Appendix B — Verification commands

Run these from the repository root when validating a phase exit.

```bash
# Phase exit gate
set -e
{{bash -n + linters + tests + build + smoke}}
```

---

## Acknowledgments / Lineage

{{What prior plans / projects / discussions this PRD inherits from. Even if the prior docs were deleted in the reality-reset step, credit the authors here. Link to the canonical example PRD this one followed (e.g. `docs/prd.md` for Mainspring-derived PRDs).}}

---

_Last edited: {{YYYY-MM-DD}}. This file is the canonical plan; if any other file in this scope disagrees, update it._
