# Audit-agent prompt template

Use this when running a parallel audit lane to gather verified facts during
Step 2 of the Method flow. The PRD's "Current truth snapshot" section is built
from these audits.

Run audit lanes in parallel — never sequentially. Multiple lanes on different
audit angles is the norm.

---

## Template

> I'm planning a {{change | refactor | new feature | new project}} on {{specific scope}}: {{1-line scope statement}}. Before writing the PRD, I need a verified-facts audit. Read the relevant code/docs and produce a structured report under {{800-1500}} words.
>
> Already known from initial scan:
>
> - {{any quick facts already confirmed: LOC, file existence, command outputs, etc.}}
>
> Read these sources:
>
> - {{specific file paths or globs}}
> - {{specific commands to run that don't have side effects: `wc -l`, `shellcheck`, `grep -c`, `git log --oneline`, `npm ls`, etc.}}
>
> Produce a structured audit report with these sections:
>
> 1. **{{Audit angle 1, e.g. "Heredoc extraction map"}}**: {{specific deliverable, e.g. "every `python3 - <<` location with line range, parent function name, what the Python does in one line, and proposed target filename"}}.
> 2. **{{Audit angle 2, e.g. "Bash module split proposal"}}**: {{specific deliverable, with line ranges and target module names}}.
> 3. **{{Audit angle 3, e.g. "Duplication hotspots"}}**: {{specific deliverable, naming line ranges that are byte-identical or near-identical}}.
> 4. **{{Audit angle 4, e.g. "Dead code candidates"}}**: {{specific deliverable, with grep proof that suspected-dead code is actually unreferenced}}.
> 5. **{{Audit angle 5, e.g. "Hidden coupling concerns"}}**: {{globals/env vars set in one place and read in another, listing the worst N}}.
> 6. **{{Audit angle 6, e.g. "Top 3 highest-risk subtasks"}}**: {{with concrete mitigation per item}}.
>
> Format output as markdown with file:line links like `path/to/file.sh:1234`. Concise, factual, no editorializing. Don't repeat what I already gave you in "Already known". If a claim is unverifiable, say so explicitly — never guess or estimate.

---

## Rules for writing audit prompts

- **State the goal in 1 line, then jump to deliverables.** Audit agents waste tokens summarizing the request back; cut that off.
- **Cite specific files/globs.** "Read the codebase" produces noise; "Read `mainspring.sh` and grep for `MAINSPRING_*` plus compatibility aliases across docs/" produces signal.
- **Specify the OUTPUT FORMAT explicitly.** Markdown sections, table columns, file:line links. Without specification, agents output prose.
- **List "Already known" facts.** Otherwise the audit re-derives them and you pay tokens twice.
- **Cap word count.** 800-1500 words is right for most audits; longer becomes essay.
- **Forbid editorializing.** The audit produces facts, not opinions. Opinions go in the PRD's principles + ADRs, written by you.
- **Run audits in parallel.** Spawn 3-5 agents at once (different angles), never one after the other.

## Common audit angles

Pick the 3-6 that fit your scope:

- **Code structure**: LOC, function sizes, module boundaries, longest functions.
- **Duplication**: byte-identical or near-identical blocks, factor-out candidates.
- **Dead code**: unreferenced functions/files, unreachable branches, unused exports.
- **Coupling**: globals, env vars, side-effects, hidden dependencies between modules.
- **Cross-repo references**: every place that mentions a thing being renamed/deleted, so the rename pass is complete.
- **Documentation drift**: which docs claim features that don't exist; which features exist that aren't documented.
- **Test coverage**: what's covered, what's covered by stub-tests, what's uncovered.
- **Lint/typecheck baseline**: error count by rule, distribution.
- **Performance baseline**: timings of critical paths from local runs.
- **Dependency surface**: external deps, version pins, optional vs required.
- **Security posture**: secrets in source, hardcoded paths, write-scope violations.
- **Operational state**: what's running today, what's stale, what's broken right now.

## Anti-patterns to avoid in audit prompts

- **"What do you think about X?"** — opinion-seeking, produces vibes. Ask for facts.
- **"Find improvements"** — too broad. Specify what category of improvements (lint? perf? clarity?).
- **"Should we refactor this?"** — that's a YOUR decision after the audit. Audit produces inputs, not decisions.
- **"Be thorough"** without scope — produces 5000-word essays. Always cap.
