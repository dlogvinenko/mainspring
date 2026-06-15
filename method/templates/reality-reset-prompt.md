# Reality-reset prompt template

Use this in Step 3 of the Method flow, BEFORE writing a new PRD. Run one
reality-reset lane with this prompt; it produces a list of files to delete or
consolidate so the new PRD doesn't layer on top of stale ones.

The user reviews and confirms the deletion list before you actually `rm`.

---

## Template

> I'm about to write a PRD for {{scope}}. Before I write a new canonical document, I need to find and delete every prior planning artifact that would become obsolete or contradict the new PRD. The Mainspring Method commandment is: **one canonical document per scope; no parallel planning artifacts; no AI-generated stale plans.**
>
> Search the entire repo for planning artifacts related to {{scope}}:
>
> - Files in `docs/`, `docs/<scope>/`, `docs/execution/`, `docs/planning/`, etc.
> - Files with names like `*plan*.md`, `*roadmap*.md`, `*architecture*.md`, `*design*.md`, `*proposal*.md`, `*refactor*.md`, `*PRD*.md`, `*PDD*.md`, `*RFC*.md`, `*spec*.md`, `*doctrine*.md`.
> - Any files inside `scripts/<scope>/docs/`, `tools/<scope>/docs/`, etc.
> - Any markdown file in the repo whose CONTENT references the scope and proposes future work (regardless of filename).
>
> For each candidate file, classify it into one of:
>
> 1. **Delete** — superseded, AI-generated stale, parallel-planning, references features that don't exist, contradicts known reality. Justify with one sentence.
> 2. **Demote-to-historical** — has historical value (lineage, prior decisions worth preserving) but should not drive future work. Move to `docs/<scope>/archive/` or annotate with a "HISTORICAL — superseded by …" banner. Justify.
> 3. **Keep** — currently accurate operational doc (operator guide, metrics schema doc, working architecture doc that matches code). Don't touch.
> 4. **Update** — references this scope in a sentence or two; needs path/name updates after the new PRD lands. List the lines that need changing.
>
> Also flag:
>
> - Any AI-generated artifacts (telltales: stilted prose, over-detailed file structures that don't match the repo, "fictional features" sections, claims of completed work that has no commit). Default classification: Delete.
> - Any file that mentions a tool/feature that has since been renamed/removed/abandoned. Default classification: Update or Delete depending on recency.
> - Any files in `scripts/v*/`, `_old/`, `archive/`, `legacy/`, `WIP/`. Default classification: Delete unless the operator explicitly asked to keep them.
>
> Output format: 4 sections (Delete / Demote / Keep / Update), each with a markdown table:
>
> | File              | Classification reason   | Confidence                      |
> | ----------------- | ----------------------- | ------------------------------- |
> | `path/to/file.md` | {{one-sentence reason}} | {{`high` \| `medium` \| `low`}} |
>
> Sort each table by confidence (high first). For low-confidence rows, add a "second opinion needed" note in the reason.
>
> Under 600 words total. The operator will read this list, confirm the deletions, and only then will the new PRD be written. Be conservative on Keep, aggressive on Delete — the cost of keeping a stale doc is higher than the cost of deleting one we'll re-derive from code.

---

## Rules for using this prompt

- **Run it BEFORE the audit prompt, not after.** If the audit references stale docs as "current truth", the audit becomes wrong.
- **Always show the user the list.** Never auto-delete from this output. The user is the gate.
- **Be aggressive in default classification.** Old AI-generated plans rot; the cost of regenerating from code is lower than the cost of operating on a fictional plan.
- **Preserve lineage in the new PRD's "Acknowledgments / Lineage" section** — credit the prior docs even if you're deleting them.

## What "stale AI-generated plan" looks like

Tell-tales of an artifact that should be deleted:

- Mentions features in a file structure that doesn't exist in the repo (`grep` reveals zero hits).
- Claims a phase is "completed 2026-XX-XX" but the work it describes shows no commits matching that date/scope.
- Uses identical phrasing to other plan documents in the repo (model-output style match).
- Has more detail in the "future" sections than the "current" sections (sign of guessing).
- References version numbers, deadlines, or rubric scores that don't appear anywhere else in the repo.
- Repeats principles that another canonical doc states, in slightly different wording.
- Contains a "What we are NOT doing" section that disagrees with another doc's "non-goals".

## What to KEEP even when tempted to delete

- Operator guides (commands, recovery, troubleshooting). Always keep; rename/update if needed.
- Schema documents (JSONL field list, DB schema, API spec). Keep; merge updates into the new PRD's relevant sections.
- ADR archives — keep all, even superseded ones. They explain why current state is what it is.
- Public-facing documents (README, LICENSE, CONTRIBUTING). Keep; update at PRD finalization time.
- Anything with `git log --follow` showing recent author commits (the file is being maintained).

## Failure modes to refuse

- **Deleting a doc the user is currently using as operational reference.** Always check `docs/execution/` and operator guides before deleting.
- **Keeping every doc "just in case".** Cargo-cult preservation produces the parallel-planning problem we're trying to fix.
- **Auto-rm-ing from this output.** The user's confirmation is the gate. No exceptions.
