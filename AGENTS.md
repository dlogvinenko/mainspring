# Mainspring Agent Guide

This repository is the public Mainspring source tree.

## Working Rules

- Keep public CLI help focused on commands a normal operator should run.
- Do not expose local runtime state, personal memory dumps, private paths, or
  temporary local procedures in tracked docs.
- Prefer small, test-backed changes over broad rewrites.
- Run focused tests for the area you changed, then run the full gate before
  claiming release readiness.
- Update `README.md`, `docs/guide.md`, and `docs/prd.md` when behavior changes.

## Verification

Use these gates from the repository root:

```bash
make all
make package-smoke
python3 py/prd_validate.py docs/prd.md
git diff --check
```

For CLI help changes, also verify:

```bash
./mainspring.sh --help
./mainspring.sh help --full
./mainspring.sh hud --help
```
