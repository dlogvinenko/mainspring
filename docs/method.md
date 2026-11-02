# The Mainspring Method

A development methodology for autonomous AI-assisted work. Codifies the doctrine-first
flow used to build [Mainspring](prd.md) itself.

This document is the **public-facing explanation** of the Method — for anyone (human or
AI) who wants to understand the philosophy, adopt it on their own projects, or extend
it. The actionable, machine-readable form lives at
[`method/skill/SKILL.md`](../method/skill/SKILL.md) (Claude Code skill) and is installed
via [`method/install.sh`](../method/install.sh).

The Method practices itself: this document is Product Requirements Document
(PRD)-shaped, so the Method is explained through the same structure it asks
projects to use.

---

## Contents

1. [Mission](#mission)
2. [Durability principles — the 11 commandments](#durability-principles-the-11-commandments)
3. [Current truth snapshot (verified)](#current-truth-snapshot-verified)
4. [Naming and brand boundary](#naming-and-brand-boundary)
5. [The 8-step flow](#the-8-step-flow)
6. [Architecture decisions (ADRs)](#architecture-decisions-adrs)
7. [Templates index](#templates-index)
8. [Health rituals](#health-rituals)
9. [Failure modes](#failure-modes)
10. [Versioning](#versioning)
11. [Definition of Done (Method v1.0 release)](#definition-of-done-method-v10-release)
12. [Explicit non-goals](#explicit-non-goals)
13. [Lineage](#lineage)

---

## Mission

The Mainspring Method exists to prevent the four most expensive failure modes of AI-
assisted development:

1. **Fictional plans** — AI-generated documents proposing features that don't exist in
   the codebase.
2. **Parallel planning artifacts** — multiple plan docs that contradict each other,
   with no clear canonical source.
3. **Manual blockers smuggled into coding
   work** — tasks that secretly require human action (secrets, sign-offs, account
   creation) blocking otherwise-shippable code.
4. **Unverifiable progress** — work
   claimed "done" without mechanically-checkable acceptance criteria.

The Method's promise: **doctrine before code; truth before plans; one canonical document
per scope; atomic tasks; manual blockers separated and deferred; phases end green or
they don't end.** Apply the Method consistently and these four failure modes become
structurally impossible.

**Three verbs**: define, decompose, ship. **Audience**: solo or small-team developers
using LLM agents as primary execution. Especially valuable when the agent produces plans
(Codex, Claude, Cursor, Aider) — the Method's reality-reset and audit gates compensate
for AI's tendency to hallucinate context. **Non-audience**: enterprise teams with
dedicated PMs, formal change-management processes, or compliance regimes. The Method is
lightweight on purpose; it is a production operator workflow, not a heavyweight process
framework.

---

## Durability principles — the 11 commandments

The non-negotiables. Anything below this line bows to them. Each commandment is a
defense against a specific failure mode seen in real AI-assisted projects.

1. **PRD before code.** Every non-trivial scope starts with a written Product
   Requirements Document of fixed shape. No exceptions, no "I'll plan as I go". _Defense
   against_: starting a feature, getting halfway, realizing the architecture is wrong,
   throwing away the work.

2. **Truth before plans.** Before writing the PRD, audit reality with parallel audit
   lanes. Verified numbers, not estimates; real command output, not memory. _Defense
   against_: building on prior plans that have rotted; PRDs that hallucinate the
   codebase.

3. **Reality reset before adding new docs.** Find and delete obsolete planning
   artifacts. One canonical document per scope. _Defense against_: parallel planning
   artifacts that contradict each other and silently mislead future agents.

4. **Atomic tasks, not vibes.** Each Taskmaster task names: file paths, line numbers
   (when refactoring), exact acceptance criteria, test plan. _Defense against_: "improve
   X" / "clean up Y" tasks that mean different things to different agents and never get
   verifiably done.

5. **Manual blockers separated and deferred.** Anything requiring human action becomes a
   narrow `blocked` task in the LAST phase. Coding work never waits on humans. _Defense
   against_: a coding task that's 95% complete but blocked on "obtain Stripe live key" —
   wasted velocity.

6. **Phases are commit-able milestones.** Each phase ends with all gates green: tests +
   typecheck + build + docs. _Defense against_: half-finished phases that ship as "done"
   and rot the next phase's foundation.

7. **4-step verification.** Tests + typecheck + build + docs. Always. _Defense against_:
   claiming done because one of the four passes; finding out later the other three were
   broken.

8. **The wave is the unit.** When Mainspring runs, one writer+reviewer pass = one wave =
   one JSONL line. Phases → Taskmaster tasks → waves. Clean atomic concept; never blur
   it. _Defense against_: progress that can't be counted, tracked, or compared across
   pairs.

9. **Metrics drive routing decisions.** What pair produced what verdict per dollar over
   what task class? Use the data. _Defense against_: defaulting to a familiar pair that
   the metrics show is actually losing.

10. **Health rituals.** Weekly (10 min) + monthly (30 min) checks against drift.
    _Defense against_: tools and processes that work for three weeks and then silently
    rot.

11. **Practice the Method on itself.** Use the Method on the Method, on Mainspring,
    and on every new project. _Defense against_: methodologies that look great on
    paper but don't survive contact with their own creators' workflows.

---

## Current truth snapshot (verified)

Captured 2026-04-26 alongside the formalization of the Method; refreshed 2026-06-15 for
the public Mainspring source release.

| Metric                   | Value                                                  | Source                                                                 |
| ------------------------ | ------------------------------------------------------ | ---------------------------------------------------------------------- |
| Method commandments      | 11                                                     | hand-counted; canonical                                                |
| Method flow steps        | 8                                                      | hand-counted; canonical                                                |
| Templates shipped        | 5 (prd, adr, task, audit-prompt, reality-reset-prompt) | `ls method/skill/templates/`                                           |
| Skill source LOC         | 253 (`SKILL.md`)                                       | `wc -l method/skill/SKILL.md`                                          |
| Method package LOC       | 1842 (skill + templates + install + README)            | `find method -type f \| sort \| xargs wc -l`                           |
| Public Method doc LOC    | 542                                                    | `wc -l docs/method.md`                                                 |
| Canonical example        | `docs/prd.md` (1443 LOC)                               | `wc -l docs/prd.md`                                                    |
| Method CLI commands      | 5 shipped                                              | `mainspring init`, `decompose`, `scope-check`, `next`, `validate-prd`  |
| Real-world applications  | 1 (Mainspring itself)                                  | this is v0.1; more applications will validate or revise                |

**What's proven:** the Method was lived (start to finish) on Mainspring's own PRD before
being written down. Audit + reality-reset + ADRs + 17-section PRD + manual-blocker
separation all happened in a single session. The principles aren't aspirational; they're
descriptive of what worked. Mainspring now also ships local Method CLI support for
`init`, `decompose`, `scope-check`, `next`, and `validate-prd`.

**What's NOT proven:** the Method has not yet been applied to a non-Mainspring scope.
Failure modes specific to other domains (frontend-heavy work, data pipelines, embedded)
may surface gaps that v0.1 doesn't cover.

**What's still unproven / external:**

- No published examples of the Method on non-Mainspring projects — adoption pattern
  unproven.
- No documented "saved-by-this-rule" anecdote set across all 11 commandments yet.
- No external write-up explaining the Method outside this repo yet.

---

## Naming and brand boundary

| Name                      | What it is                                                                                                                  | Where it lives                                                                                                                 |
| ------------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| **The Mainspring Method** | This methodology. The 11 commandments + 8-step flow + 5 templates.                                                          | `method/` (source); `~/.claude/skills/mainspring-method/` (installed); `docs/method.md` (this doc)                             |
| **PRD**                   | Product Requirements Document — the canonical document the Method produces. 17 sections, fixed shape.                       | `docs/<scope>/prd.md` per project                                                                                              |
| **ADR**                   | Architecture Decision Record — load-bearing decisions captured inside the PRD.                                              | A subsection of the PRD, never a separate file                                                                                 |
| **Mainspring (the tool)** | Autonomous execution engine — runs Taskmaster tasks via writer+reviewer LLM pairs. Separate from the Method, complementary. | `mainspring.sh` (entry); `lib/`, `py/`                                                                                          |
| **Taskmaster**            | External backlog source the Method decomposes into. Not part of the Method or Mainspring.                                   | `task-master` CLI + `.taskmaster/`                                                                                             |

The Method is a **methodology**, not a tool. You can adopt the Method without adopting
Mainspring (just follow the flow, write the PRD, decompose manually). The reverse is
also true (Mainspring without the Method is a fancy bash script). They're better
together.

---

## The 8-step flow

Walk these steps in order. Each step has a clear input, a clear output, and a time
budget. The user can pause and resume between steps.

### Step 1 — Frame the scope (≤ 5 min)

Three questions:

- What is the scope? (one sentence)
- What's the smallest visible end state that means "done"?
- What's explicitly NOT in this scope?

**Input:** vague intent. **Output:** 3-line scope statement quoted in the PRD's Mission
section.

### Step 2 — Audit reality, in parallel (≤ 10 min)

Run 3-5 parallel audit lanes with `templates/audit-prompt.md`. Each angle is different:
code structure, duplication, dead code, coupling, cross-repo references, doc drift, test
coverage, etc. Use whichever agent runner the project already has; the Method requires
independent parallel evidence, not a specific vendor tool. Run these lanes in parallel.
**Never** sequentially.

**Input:** 3-line scope statement. **Output:** structured audit reports with verified
numbers and file:line references. Feeds the PRD's "Current truth snapshot" section.

### Step 3 — Reality reset (≤ 5 min)

Run one reality-reset lane with `templates/reality-reset-prompt.md`. It produces 4
lists: Delete / Demote-to-historical / Keep / Update. The user reviews, confirms
deletions, and the operator deletes obsolete files BEFORE writing the new PRD.

**Input:** the repo + scope. **Output:** clean repo state, one canonical document per
scope.

### Step 4 — Resolve open decisions (≤ 15 min)

Identify decisions the PRD must lock. Draft each as a one-paragraph ADR per
`templates/adr.md`. Ask the operator for explicit ratification on each. Don't guess
load-bearing things; the operator owns architecture.

**Input:** scope + audit findings. **Output:** ratified ADRs for inclusion in the PRD's
ADR section.

### Step 5 — Write the PRD (≤ 30 min for a fresh PRD)

Read `templates/prd.md` and follow its 17-section structure exactly. The PRD must be
self-contained: a future agent reading only the PRD must be able to act without other
docs.

**Input:** scope + audit + reality-reset + ADRs. **Output:** `docs/<scope>/prd.md`.

### Step 6 — Decompose the ACTIVE phase into Taskmaster (≤ 15 min per phase)

**Phase-by-phase pattern.** Decompose ONLY the currently-active phase, not all phases at
once. Future phases stay as outlines in the PRD until they activate. Premature
decomposition is wasted work — task shapes change based on what earlier phases produced.

For each task in the active PRD phase, create one Taskmaster task via
`templates/task.md`. Apply the Manual Blocker Separation Rule: any human action becomes
a narrow `blocked` task pushed to the last phase.

Use Mainspring's local tooling when available: `mainspring decompose <prd> --phase
<name>` previews the phase plan, and `mainspring decompose <prd> --phase <name> --apply
--tasks-file <tasks.json>` writes generated Taskmaster tasks idempotently. Manual `task-
master add-task --prompt="..."` remains the fallback for projects adopting the Method
without Mainspring.

When current phase completes, the Playbook's [Phase activation
ritual](playbook.md#phase-activation-ritual) re-invokes Step 6 for the next phase.

**Input:** PRD + name of the active phase. **Output:** Taskmaster backlog (under the
PRD's tag) — 4-10 atomic tasks for the active phase, dependencies set, manual blockers
in last phase.

### Step 7 — Sanity-check the backlog (≤ 5 min)

- Any "improve X" tasks left? Reject them.
- Manual blockers in last phase? Yes / no.
- `task-master validate-dependencies` green?
- `mainspring scope-check <tasks.json>` green?
- Phase 1 tasks atomic enough that an LLM can finish each in <2 hours?

**Input:** Taskmaster backlog. **Output:** ready-to-execute backlog, or expansion / re-
write of vague tasks.

### Step 8 — Hand off (≤ 1 min)

Print: PRD path, top 3 next-up Taskmaster ids, recommended Mainspring invocation,
reminder of weekly + monthly health rituals. The Method's job is done; Mainspring runs
the loop.

**Total time budget**: 60-90 min for a medium scope, 2-3 hours for a major refactor.
Less than 30 min means corners were cut — check which commandment was violated.

---

## Architecture decisions (ADRs)

Six load-bearing decisions in the Method's design.

### ADR-01: Method codified as a Claude Code skill (auto-trigger), not a slash command

**Context:** the Method must apply consistently without the user having to remember to
invoke it.

**Options:** (a) Skill with auto-trigger description; (b) Slash command requiring
explicit invocation; (c) Pure prose doc the user reads and applies manually.

**Decision:** Skill, with auto-trigger keywords covering the most common intent
phrasings in English and Russian.

**Rationale:** the failure mode the Method exists to prevent (skipping straight to code)
is most common precisely when the user is excited about a new feature — exactly when
remembering "invoke /method first" is hardest. Auto-triggering compensates for human
bias toward action.

**Consequences:** occasional false-positive activation; the skill's description must
include explicit skip-conditions to limit this.

**Reversal cost:** trivial — disable the skill, write a slash command in 15 minutes.

### ADR-02: Templates as standalone files, not embedded in SKILL.md

**Context:** the skill body and its templates evolve at different cadences.

**Options:** (a) inline templates inside SKILL.md; (b) separate files under
`skill/templates/`.

**Decision:** separate files.

**Rationale:** a 17-section PRD template would bloat SKILL.md beyond readability.
Separate files are also editable by future contributors without touching the skill's
auto-trigger contract.

**Consequences:** SKILL.md must reference template paths and explicitly tell Claude to
read them at runtime.

**Reversal cost:** low — sed-merge templates back into SKILL.md.

### ADR-03: Source-of-truth in repo, installation via copy

**Context:** the skill must be portable across machines and versioned via git.

**Options:** (a) skill files only in `~/.claude/skills/` (per-machine, ungitted); (b)
repo as source of truth, install.sh copies into `~/.claude/skills/`; (c) symlink-only
install (repo paths must stay stable).

**Decision:** (b), with `--link` option for development.

**Rationale:** copy is stable across worktree moves and repo renames; symlink is fragile
when worktrees come and go. `--link` available for fast iteration during Method
development.

**Consequences:** users must re-run `install.sh --force` after upstream Method updates.

**Reversal cost:** trivial.

### ADR-04: Document type = PRD (Product Requirements Document)

**Context:** what to call the canonical 17-section document the Method produces.
Multiple terms exist in industry: PRD, PDD, RFC, Design Doc, Spec, Charter.

**Options considered:**

1. **PRD** (Product Requirements Document) — industry standard, especially in product
   management. Used by Stripe, Linear, most YC companies, every PM textbook.
2. **PDD** (Product Definition Document) — uncommon, used at a few companies. Easy to
   confuse with PRD.
3. **Design Doc** — Google internal style. Engineering-flavored, less product-shaped.
4. **RFC** (Request for Comments) — open-source / Meta engineering style. Implies the
   doc is provisional and seeks feedback; the Method's PRD is the opposite (it's
   canonical and ratified).
5. **Spec** — generic. Loses the upstream mission/principles framing.
6. **Charter** — too corporate.

**Decision:** **PRD = Product Requirements Document.**

**Rationale:** PRD is the universally-recognized term. A new contributor sees "PRD" and
immediately knows roughly what's inside — no glossary needed. "Requirements" reads
narrowly to engineers (just specs?), but the Method's PRD covers far more (mission,
principles, ADRs, non-goals, phase plan, definition of done). That broader scope is
taught in the template, not in the acronym. Inventing a new acronym (PDD) for a concept
that already has industry naming is friction without payoff, and creates the "what's
PDD?" question the Method explicitly avoids.

**Consequences:**

- Every Method-produced document is named `prd.md` and lives at `docs/<scope>/prd.md`.
- The 17-section template still goes far beyond requirements; the template itself is
  what defines the shape.
- New contributors immediately understand the role of the document by name.

**Reversal cost:** medium — every existing PRD across every project would need its
filename and references updated. Not worth doing again; pick once, stay consistent.

### ADR-05: Method ships under Apache-2.0, identical to Mainspring

**Context:** the Method ships alongside Mainspring under a single license to remove
license-confusion at consumption time.

**Options:** Apache-2.0, MIT, BSD-2-Clause, CC-BY (it's mostly docs).

**Decision:** Apache-2.0.

**Rationale:** matches Mainspring; eliminates license-confusion at extraction; the
patent grant matters the same way it matters for Mainspring (the flow could conceivably
be patent-claimed by a forker).

**Consequences:** SPDX headers on every Method file; NOTICE file required at extraction.

**Reversal cost:** very high (requires consent from contributors after they exist).

### ADR-06: Method version is independent of Mainspring version

**Context:** the Method may evolve faster or slower than Mainspring.

**Options:** lockstep versioning, independent versioning.

**Decision:** independent. Method v0.1 and Mainspring v1.0 can drift.

**Rationale:** the Method is a methodology, applicable beyond Mainspring. Lockstep
versioning would force a Method bump every time Mainspring's CLI changes, which is
unrelated.

**Consequences:** README must list compatible Method ↔ Mainspring versions when
integrations exist.

**Reversal cost:** medium.

---

## Templates index

| Template                                                                  | Step it serves   | One-line purpose                                                         |
| ------------------------------------------------------------------------- | ---------------- | ------------------------------------------------------------------------ |
| [`templates/prd.md`](../method/templates/prd.md)                          | 5 (Write PRD)    | The 17-section canonical document shape                                  |
| [`templates/adr.md`](../method/templates/adr.md)                          | 4 (Resolve ADRs) | Context / Options / Decision / Rationale / Consequences / Reversal Cost  |
| [`templates/task.md`](../method/templates/task.md)                        | 6 (Decompose)    | Atomic Taskmaster task with file:line specificity + manual-blocker check |
| [`templates/audit-prompt.md`](../method/templates/audit-prompt.md)        | 2 (Audit)        | Spawn-an-audit-agent prompt, with rules and common angles                |
| [`templates/reality-reset-prompt.md`](../method/templates/reality-reset-prompt.md) | 3 (Reset)        | Find-obsolete-docs prompt, with classification rubric                    |

---

## Health rituals

### Weekly (≤ 10 min)

1. List PRDs touched in the last week
   (`git log --diff-filter=AM --name-only --since='1 week' | grep prd.md`). Glance: are
   they still active or dormant?
2. For each active PRD, confirm the next-up phase has at least one atomic task in
   Taskmaster `pending`.
3. Spot-check one Taskmaster task that's been `pending` for >7 days — is it stuck? Move
   to `blocked` with a reason, or expand into smaller subtasks.

### Monthly (≤ 30 min)

1. Run weekly first.
2. Read every PRD's "Health rituals" section — are the per-PRD rituals being done?
3. Audit the Method itself: any commandment violated in the last month? File an ADR
   amendment if a rule should evolve.
4. Check `method/templates/` for templates that have drifted from PRDs you actually
   wrote — sync.
5. If you've used the Method on a non-Mainspring scope, log what worked and what didn't
   in `docs/method-applications.md` (create on first use).

---

## Failure modes

The Method itself has failure modes. Recognize and refuse them.

- **PRD theatre** — writing a 1000-line PRD for a 30-line bug fix. The skill must skip
  trivial work; if the user is forcing the Method on a tiny scope, push back.
- **Audit overrun** — spawning 12 audit agents for a 100-LOC change. Cap audit angles to
  3-5; otherwise the audit costs more than the work.
- **ADR theatre** — writing ADRs for decisions that aren't load-bearing ("which color
  for the button"). ADRs are for decisions with reversal cost ≥ medium.
- **Task fan-out** — decomposing a phase into 30 sub-tasks when 5 would do. Atomic ≠
  minimal; aim for tasks an LLM can finish in 30 min - 2 hrs each.
- **Reality-reset over-deletion** — deleting docs the user needs as operational
  reference (operator guides, schemas). The reality-reset agent is conservative on
  Keep, aggressive on Delete only for AI-generated stale plans.
- **Method-on-Method recursion** — applying the Method to plan changes to the Method
  itself, then applying the Method to plan changes to that plan, etc. One level of
  recursion is healthy (this PRD is one level); two levels is process overkill.

---

## Versioning

**Method v0.1** — formalized 2026-04-26. Lived in practice on Mainspring's own PRD
before being written down.

**SemVer:**

- **MAJOR**: removing or renaming a commandment, removing a flow step, breaking a
  template's required sections.
- **MINOR**: adding a commandment, adding a flow step, adding a template, adding
  optional template sections.
- **PATCH**: clarifying language, adding examples, fixing typos.

**Compatibility window**: when commandments change, prior PRDs remain valid for one
MINOR version. After that, migrate.

---

## Definition of Done (Method v1.0 release)

The Method is v1.0 (extracted to its own dir / repo, public-OSS-grade) when:

- [ ] Applied successfully on at least 3 non-Mainspring scopes by at least 1 person
  other than the original maintainer.
- [ ] Each commandment has at least one documented "saved-by-this-rule" anecdote in
  `docs/method-applications.md`.
- [ ] All 5 templates have at least 2 example uses linked from this doc.
- [x] `mainspring init` and `mainspring decompose` CLI commands ship (Phase P4.5 of
  Mainspring's PRD).
- [x] PRD-shape validator exists (`mainspring validate-prd docs/prd.md` checks 17
  sections, placeholders, truth sources, ADR shape, and backlog lanes).
- [x] Public README explains how to install Mainspring, how to verify PATH visibility,
  why Mainspring exists, how Product Requirements Documents (PRDs) differ from vibe
  coding, and how to start with one `mainspring` command.
- [ ] At least one external write-up exists explaining the Method (blog post, talk,
  video).

---

## Explicit non-goals

The Method will NOT become:

- **A project management framework.** No sprints, velocity tracking, story points. The
  Method is upstream of all of those.
- **A standards-body methodology.** No certification, no auditor program, no
  "Mainspring Method Certified" stamp.
- **An anti-AI guardrail.** The Method assumes you USE LLM agents; it just constrains
  them so their hallucinations are caught early.
- **A dependency-graph theorem.** No formal proofs of correctness. The 11 commandments
  are folk wisdom hardened by repeated failure, not theorems.
- **A replacement for engineering judgment.** The Method removes structural traps;
  humans still decide everything that matters (ADRs, scope, principles, non-goals).
- **A no-code tool.** The Method's output is plain markdown + Taskmaster tasks. No
  proprietary editors, no GUI, no SaaS.
- **A guru lifestyle.** No "Method coaches", no consulting practice, no Patreon. Keep
  it practical, inspectable, and tool-backed.


## Lineage

Influences:

- Google's Design Doc culture (the 17-section PRD inherits the "explicit non-goals" +
  "alternatives considered" sections from internal Google design doc templates).
- Amazon's PR/FAQ / Working Backwards (the "what's the smallest visible end state" frame
  in Step 1).
- ADR practice (Michael Nygard's 2011 "Documenting Architecture Decisions" template,
  simplified).
- Linear's Spec format (one-pager, atomic tasks, manual blockers separated).
- Maintainer scar tissue (every commandment has a story; no commandment is
  theoretical).

---

_Last edited: 2026-06-15. This file is the canonical explanation of the Method; if any
other file in this repo disagrees, update it._
