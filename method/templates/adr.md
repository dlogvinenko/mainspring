# ADR-{{NN}}: {{decision title in noun form}}

**Status:** {{`proposed` | `accepted YYYY-MM-DD` | `superseded by ADR-NN` | `rejected`}}.

## Context

{{2-4 sentences. What situation forces a decision NOW. What constraints exist. What hidden landmines lurk. Be specific — if a future reader can't tell why this had to be decided, the context is too thin.}}

## Options considered

1. **{{Option A}}** — {{1-line description}}. Trade-off: {{what we'd gain / lose}}.
2. **{{Option B}}** — {{...}}. Trade-off: {{...}}.
3. **{{Option C, status quo if applicable}}** — {{...}}. Trade-off: {{...}}.

{{Always include the status-quo / "do nothing" option when a decision could be deferred. If only one option is listed, this isn't a decision — it's documentation.}}

## Decision

{{The chosen option, in one sentence. Imperative form: "We will use Apache-2.0", not "Apache-2.0 might be best".}}

## Rationale

{{2-5 sentences. Why this option won — concrete, not "feels right". Anchor to the project's durability principles when possible. Cite specific past failures if a previous attempt informed the decision.}}

## Consequences

**Positive:**

- {{what we gain that wasn't there before}}
- {{...}}

**Negative / Cost:**

- {{what work this creates}}
- {{what's now constrained or harder}}

**Neutral:**

- {{things that change but aren't strictly better/worse}}

## Reversal cost

{{`trivial` | `low` | `medium` | `high` | `very high — get this right now, decision is effectively permanent`}}

{{One sentence on what reversing would cost: e.g. "trivial: change one default in wizard.sh", "very high: relicensing public OSS requires every contributor's consent".}}

## Related

- {{links to other ADRs that connect: superseded, depended-on, or informing}}
- {{links to specific code/doc paths affected by this decision}}
