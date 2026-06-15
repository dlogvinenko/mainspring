# Contributing

Read `docs/prd.md` first; it is the release contract. Read `docs/architecture.md`
before changing engine dispatch, ledger schema, replay, or notification behavior.

## Local Checks

Run the focused checks for your change first. Before handing off a general code
change, run:

```bash
python3 -m pytest py/tests -q
bash tests/bats/run.sh
ruff check py
ruff format --check py
```

Keep diffs small, preserve the reviewer hard gate, and add Apache-2.0 SPDX
headers to new source files.

## Add An Engine Adapter

Engines live under `py/engines/`. The registry imports every non-private module
in that directory and requires each one to expose `ADAPTER.info` as an
`EngineInfo`.

1. Pick the adapter shape.
   - For a provider already supported by LiteLLM, add a thin module like
     `py/engines/gemini.py` that wraps `LiteLLMProviderAdapter`.
   - For a CLI or custom runtime, add a class that implements the
     `EngineAdapter` protocol in `py/engines/_base.py`.

2. Declare honest metadata.
   - `name` is the CLI-facing engine id.
   - `default_model` must be the premium/default model from the PRD.
   - `required_python_module` and `required_env_vars` must name real
     dependencies so doctor, dry-run, and preflight fail closed.
   - `notes` should say whether dispatch is CLI-backed or LiteLLM-backed.

3. Implement the runtime methods.
   - `build_command()` returns an `EngineCommand` with argv only; Bash owns
     pipes, logs, and signal handling.
   - `parse_usage()` returns structured usage when available, otherwise `{}`.
   - `quota_snapshot()` returns a common quota payload when available,
     otherwise `{}`.
   - `detect_failure()` must classify auth, quota, missing dependency, and
     non-zero exits without silently falling back to another engine.

4. Wire no special cases.
   - Do not edit `mainspring.sh` to recognize the engine by name.
   - Do not add fallback provider behavior.
   - Use `mainspring engines --json` to verify registration from the public CLI.
   - Use `mainspring --engine <name> --review-engine codex --dry-run --once`
     to inspect the writer/reviewer command shape without launching a wave.

5. Add tests and docs.
   - Extend `py/tests/test_engine_registry.py` for inventory, command building,
     credential validation, and failure classification.
   - Add or update Bats coverage when CLI flags or dry-run output change.
   - Update the README engine matrix when the engine becomes public-facing.
   - Keep provider credentials out of fixtures; use monkeypatching or dry-run
     command construction for automated tests.
