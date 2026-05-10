# Vault fixtures (ADR-0018 §3)

Frozen vault snapshots used as regression oracles. Each fixture lives
in its own directory and ships with `metadata.json` describing:
- Which schema versions / features it covers.
- When + why it was added.
- What the regression suite (`tests/test_vault_fixtures.py`) is
  expected to assert against it.

## Contract

Per ADR-0018 §3, every schema_version bump MUST:

1. Add a new fixture vault here that captures the new shape.
2. Make `pytest tests/test_vault_fixtures.py` keep passing — i.e. the
   current code can still read every prior fixture (1-major-backward
   compat clause of ADR-0018 §1).
3. Optionally retire the oldest fixture once it's > 2 majors back
   (we don't promise unbounded backward read).

## Don't edit fixture files casually

These files are **frozen evidence** of "what knowlet wrote at this
schema version". Re-running tests must not mutate them. The test
suite copies each fixture to `tmp_path` before exercising any
write paths.
