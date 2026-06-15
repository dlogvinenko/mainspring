# Golden Replay Prompt: P-Comp-2 Slice Implementation

You are running Mainspring night mode against docs/prd.md.

Implement the P-Comp-2 replay slice:

- read a recorded wave from waves.jsonl
- reconstruct the replay command and replay-specific environment
- support reviewer, model, writer-engine, and save-as overrides
- fail closed when deterministic prompt replay material is missing or drifted
- record replay provenance for the appended wave row

Do not call live model providers while validating this fixture.
