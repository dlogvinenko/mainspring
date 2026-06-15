# Mainspring Method

A development methodology for autonomous AI-assisted work. Pairs with
[Mainspring](../docs/prd.md) — the autonomous execution loop — to form a complete
system: the Method decides _what_ to build and _how_ to plan it; Mainspring executes.

You can use the Method without Mainspring. You can use Mainspring without the Method.
They're better together.

## What this directory contains

```
method/
  README.md                        # this file
  install.sh                       # copies skill into ~/.claude/skills/
  skill/                           # source of truth for the Claude Code skill
    SKILL.md                       # auto-trigger frontmatter + 11 commandments + 8-step flow
    templates/
      prd.md                       # Product Requirements Document template (17 sections)
      adr.md                       # Architecture Decision Record template
      task.md                      # atomic Taskmaster task template
      audit-prompt.md              # prompt for spawning a parallel audit agent
      reality-reset-prompt.md      # prompt for the obsolete-doc cleanup pass
```

## What is the Mainspring Method

A 3-bullet pitch:

1. **PRD before code.** Every non-trivial scope starts with a written PRD. No
   exceptions, no "I'll plan as I go". The PRD is the contract: mission, principles,
   current truth, target, phases, ADRs, non-goals, definition of done, ranked backlog.
2. **Truth before plans.** Before writing the PRD, audit reality. Real numbers from
   real commands; verified facts, not hopes or AI-generated guesses. Reality-reset old
   planning artifacts before adding new ones.
3. **Atomic tasks, manual blockers deferred.** Decompose the PRD into Taskmaster tasks
   that name file paths, line numbers, and acceptance criteria. Anything requiring
   human action (secrets, sign-offs, submissions) is its own narrow `blocked` task
   pushed to the end. Coding work never waits on humans.

The 11 commandments and the 8-step flow live in [skill/SKILL.md](skill/SKILL.md).

## What is a PRD?

PRD = **Product Requirements Document**. It is a widely used product-management term,
which matters because new contributors can understand the category before learning
Mainspring-specific details. The Method uses the term for consistency; the 17-section
template defines the actual shape.

**A PRD is not just requirements.** The Method's PRD covers far more than feature specs.
It captures:

| Section                   | What it defines                                                                  |
| ------------------------- | -------------------------------------------------------------------------------- |
| Mission                   | Who the product is for, what three verbs it lives by, who it's NOT for           |
| Durability principles     | The N commandments — non-negotiables that survive every refactor                 |
| Current truth snapshot    | Verified facts (LOC, lint status, command output) — not estimates                |
| Naming and brand boundary | What's in this thing vs adjacent dependencies                                    |
| Target architecture       | File layout, public contract, data shapes, frozen at v1.0                        |
| Phase map                 | Phases with explicit acceptance criteria, each ending green                      |
| ADRs                      | Load-bearing decisions, Context → Options → Decision → Rationale → Reversal cost |
| Operational doctrine      | When to use what, in daily work                                                  |
| Health rituals            | Weekly + monthly checks against drift                                            |
| Disaster recovery         | Concrete failure modes with recovery commands                                    |
| Versioning + migration    | SemVer policy, schema versions, deprecation windows                              |
| Definition of Done        | The release checklist                                                            |
| Explicit non-goals        | What this thing will NEVER become                                                |
| Backlog                   | Must / Should / Could / Won't, ranked by value-per-effort                        |

The full template (with every section explained, with placeholders) is at
[`skill/templates/prd.md`](skill/templates/prd.md). The canonical real-world example is
[`docs/prd.md`](../docs/prd.md) — Mainspring's own living PRD.

## How to write a PRD

Total time budget: 60-90 minutes for a medium scope, 2-3 hours for a major refactor.
Less than 30 minutes means corners were cut.

The full procedure is the Mainspring Method's 8-step flow, but the PRD-writing portion
is steps 4-5:

1. **Audit reality first** (Step 2 of the Method). Run parallel audit lanes using
   [`skill/templates/audit-prompt.md`](skill/templates/audit-prompt.md). Get verified
   numbers — LOC, lint status, command output, file sizes. **Never** start a PRD on
   estimates.
2. **Reality-reset old planning artifacts** (Step 3). Use
   [`skill/templates/reality-reset-prompt.md`](skill/templates/reality-reset-prompt.md)
   to find every prior plan / refactor doc / RFC / parallel planning artifact related to
   this scope. Delete the obsolete ones BEFORE writing the new PRD. Commandment 3: one
   canonical document per scope.
3. **Resolve ADRs with the operator** (Step 4). For
   every load-bearing decision the PRD will lock, draft a one-paragraph ADR per
   [`skill/templates/adr.md`](skill/templates/adr.md): Context → Options → Decision →
   Rationale → Consequences → Reversal cost. **Ask the operator to ratify each.** Don't
   unilaterally decide architecture.
4. **Open the template** (Step 5). Read
   [`skill/templates/prd.md`](skill/templates/prd.md). The 17 sections are mandatory;
   fill in every `{{placeholder}}`. Cross-reference the audit (for Current truth
   snapshot) and the ADRs (for the ADR section). The PRD must be self-contained: a
   future agent reading only the PRD must be able to act without other docs.
5. **Save and decompose**. Save at `docs/<scope>/prd.md`. Then decompose each phase into
   atomic Taskmaster tasks per [`skill/templates/task.md`](skill/templates/task.md),
   with manual blockers separated to the LAST phase.

**Common mistakes to refuse:**

- Writing a PRD for a 30-line bug fix. The Method skips trivial work.
- Writing the PRD without auditing first. Every claim in "Current truth snapshot" must
  have a Source command.
- Skipping ADRs because "the answer is obvious". The operator owns architecture; you
  draft, they ratify.
- Mixing manual blockers into coding tasks. Manual = human action = `blocked` status =
  last phase.
- Half-filling sections. A blank section means the scope wasn't thought through. Fill it
  or write "N/A — reason".

**A finished PRD looks like:** [`docs/prd.md`](../docs/prd.md) — every claim sourced,
ADRs ratified by the operator, explicit acceptance criteria, and manual owner actions
separated instead of hidden in coding tasks. That's the bar.

## Why it exists

The Method was created after repeated AI-planning failures where agents generated plans
that:

- referenced features that didn't exist
- proposed refactors that ignored real constraints
- duplicated existing planning docs without deleting them
- mixed coding work with manual blockers
- made progress impossible to verify because no metric was wired up

The Method is the negative of all of that. Each commandment is a defense against a
specific past failure mode.

The canonical example of the Method applied is [Mainspring's own PRD](../docs/prd.md) —
the document that drove Mainspring from a monolith toward a modular Apache-2.0 OSS
release. We wrote that PRD using the Method we're now codifying. The Method works
because we lived it before we wrote it down.

## Install

From this repo's root:

```bash
./method/install.sh
```

This:

1. Copies `skill/` into `~/.claude/skills/mainspring-method/` (creating dirs as needed).
2. Leaves project memory files alone. The public repository ships the Method skill, not
   private per-user memory entries.

Re-install with `--force` to overwrite. Use `--link` for development (symlinks instead
of copies — updates in the repo reflect immediately).

## Use

Once installed, the skill auto-triggers when you start a non-trivial scope:

> _"new feature — automatic CSV import for a portfolio app"_
> → skill activates, walks you through audit → reality-reset → PRD → ADRs → Taskmaster decomposition

Trigger phrases: `new feature`, `let's build`, `let's refactor`, `plan for`, `PRD`,
`method`, `doctrine`, `refactor X`.

The skill **skips** trivial work: single-file bug fixes, simple questions, work already
mid-flight under an existing plan, renames, doc-only edits.

You can also force-invoke by saying _"apply the Mainspring Method to X"_.

## Relationship to Mainspring (the tool)

| Layer              | What it is                                                                            | Where it lives                                                                     |
| ------------------ | ------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| **Method**         | The process: audit → PRD → ADRs → atomic tasks → execute                              | This directory + `~/.claude/skills/mainspring-method/`                             |
| **Mainspring CLI** | The execution engine: runs Taskmaster tasks via writer+reviewer LLM pairs, logs JSONL | `mainspring` or `./mainspring.sh` from a source checkout |
| **PRD**            | The output of the Method, the input to Mainspring                                     | `docs/<scope>/prd.md`                                                              |

After the Method produces a PRD, Mainspring can decompose one active phase into atomic
Taskmaster tasks with `mainspring decompose <prd.md> --phase <name> --apply`. The
command validates the PRD first, writes a backup, and uses generated digests so a second
run updates existing generated tasks instead of duplicating them. Mainspring then picks
up the resulting work via `mainspring next` and runs waves.

## Versioning

Method commandments are versioned in [skill/SKILL.md](skill/SKILL.md). Templates evolve
with examples. Breaking changes (e.g. removing a commandment, renaming a section) bump a
major version and document the migration in this README.

Current Method version: **v0.1** (lived in practice on Mainspring's own PRD, formalized
2026-04-26).

## License

Apache-2.0 (matches Mainspring). When the Method ships as part of Mainspring's public
OSS release, the Method is free to copy, fork, and adapt. Attribution appreciated, not
required.
