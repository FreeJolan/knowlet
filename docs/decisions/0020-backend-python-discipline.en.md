# 0020 — Backend Python engineering discipline

> **English** | [中文](./0020-backend-python-discipline.md)

- Status: Accepted
- Date: 2026-05-05

## Context

knowlet's backend is ~17k LOC of Python with 376 passing tests. It has **no known functional bugs** (every frustration in the 2026-05-04 dogfood report was about the frontend, not the backend).

But the project owner highlighted Python's real weakness in the 5/5 conversation:

> "Python's strength is that it's easy to write; its weakness is that it's easy to write badly, especially in larger projects."

This is true — but it's not really Python's fault, it's **default config + lack of automated guardrails**. Today we're "half-way enabled":

| Guard | Status |
|---|---|
| Python 3.11+ pinned | ✅ |
| Type hints | 🟡 mostly present, **but no one runs mypy to check** |
| Pydantic v2 at API boundaries | ✅ |
| ruff (lint) | ✅ installed, **but not enforced (no pre-commit / CI)** |
| pytest 376 tests | ✅ all pass, **but no CI to run them automatically** |
| **mypy strict** | ❌ |
| **pre-commit hooks** | ❌ |
| **GitHub Actions CI** | ❌ |
| **Architectural dependency tests** | ❌ |

The result: any commit slips through when my discipline lapses (this round's chat SSE bug). Need to **upgrade "discipline" to "automated guardrails"**.

## Decision

### Add 4 layers of guards (strong → soft)

#### Layer 1: Types (strong, must pass)

Add `mypy --strict` config to `pyproject.toml`; commits with type errors are blocked:

```toml
[tool.mypy]
python_version = "3.11"
strict = true
disallow_untyped_defs = true
disallow_any_unimported = true
warn_return_any = true
warn_unused_ignores = true
no_implicit_optional = true
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
# Third-party libs without type stubs allow Any (temporary)
module = ["sqlite_vec", "trafilatura", "feedparser", "fsrs", "ulid", "frontmatter"]
ignore_missing_imports = true
```

Expected: **first run with strict mode reveals 50-100 type holes**, fixing them eliminates a large class of runtime AttributeError / TypeError / None dereference bugs.

#### Layer 2: Lint + format (strong, must pass)

ruff with a stricter ruleset; format auto-applied:

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = [
    "E", "W",      # pycodestyle
    "F",           # pyflakes
    "B",           # bugbear (mutable default args, late-binding closures, etc)
    "I",           # isort
    "UP",          # pyupgrade
    "RUF",         # ruff-specific
    "SIM",         # simplify
    "S",           # security (bandit-like)
]
ignore = [
    "E501",        # line length handled by formatter
    "S101",        # assert in tests is fine
    "B008",        # default arg in function call (FastAPI Depends)
]
```

#### Layer 3: Pre-commit hook (strong, blocks at local commit)

`.pre-commit-config.yaml`: every `git commit` runs mypy + ruff + pytest -x. Any failure blocks the commit.

```yaml
repos:
  - repo: local
    hooks:
      - id: mypy
        name: mypy strict
        entry: uv run mypy knowlet
        language: system
        types: [python]
        pass_filenames: false
      - id: ruff
        name: ruff check + format
        entry: uv run ruff check --fix && uv run ruff format
        language: system
        types: [python]
        pass_filenames: false
      - id: pytest-fast
        name: pytest -x (fast subset)
        entry: uv run pytest -x -m "not slow"
        language: system
        types: [python]
        pass_filenames: false
```

#### Layer 4: CI (GitHub Actions, re-runs on push)

`.github/workflows/ci.yml`: pushes / PRs run lint + types + tests + coverage.
Branch protection: **main can't be force-pushed**, must go through PR + green CI.

```yaml
name: CI
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --extra dev --extra embed
      - run: uv run ruff check
      - run: uv run ruff format --check
      - run: uv run mypy knowlet
      - run: uv run pytest --cov=knowlet --cov-report=xml
      - uses: codecov/codecov-action@v4
        with: { file: coverage.xml, fail_ci_if_error: false }
```

#### Layer 5: Architecture dependency tests (soft, but baked into pytest)

`tests/test_architecture.py` using `import_linter` or pure `ast`, asserting:

```python
# core/* must NOT import web/* or cli/*
# web/* may import core/*, NOT cli/*
# cli/* may import core/*, NOT web/*
# tests/* may import anything
```

This guards against "shortcut" cross-layer imports during refactors.

### Datatype style policy

Python has multiple ways to define data shapes (`dataclass` / `BaseModel` / `TypedDict` / `NamedTuple` / plain `dict`). Without rules they drift. This ADR pins:

| Use case | Tool | Reason |
|---|---|---|
| **Vault entities** (Note / Card / Draft / MiningTask) | `@dataclass` | Light syntax / Python-native / mypy-strict |
| **API wire schema** (request / response) | `pydantic.BaseModel` | Boundary runtime validation; rejects garbage at the seam |
| **Transient dict-shaped data** (SQL rows / JSON parses) | `TypedDict` | Typed but no runtime validation |
| **Simple value objects** (SearchHit / QuoteRef) | `@dataclass(frozen=True)` | Immutable + strict |
| **Forbidden**: `dict[str, Any]` crossing modules | — | No type protection = no value |

### Banned Python idioms (not enforced in dev phase, but blocked in review)

- `from x import *` (namespace pollution)
- `getattr(obj, name_str)` / `setattr` across modules (mypy can't see through)
- `**kwargs` forwarded to unknown signatures
- `# type: ignore` without a reason comment (ruff already warns)
- Global mutable state (use dependency injection / contextvars)

### Out of scope

- 100% test coverage — over-strict slows shipping
- 100% type coverage — `# type: ignore[<reason>]` at third-party seams remains OK
- Python 3.12 / 3.13 upgrade — postpone until typing features need it

## Implementation

[ADR-0021](./0021-knowledge-base-first-roadmap.en.md) §"Phase 0" runs this in parallel with the React scaffold (estimated 1-2 days).

Sequence:
1. Add mypy config + run + fix exposed ~50-100 type holes (1 day)
2. Add ruff strict config + fix exposed lint (½ day)
3. Add `pre-commit-config.yaml` + `pip install pre-commit && pre-commit install` (½ day)
4. Add GitHub Actions CI (½ day)
5. Add architecture dependency tests + datatype style audit (a few hours)

After this, ongoing cost: 0 (auto-runs on commit).

## Consequences

### Positive

- **Discipline → automation**: agents / contributors that don't pass these checks can't commit
- **Three-layer coverage** (types + lint + boundary validation) catches most silent runtime errors
- **Refactor safety**: change a schema → mypy reports every affected site; comparable to TS rename
- **Agent maintenance friendly**: LLMs writing Python with type hints "know what they're changing"
- **Tests + CI prevent regression**: every push runs 376 + new e2e tests (per ADR-0019)

### Negative

- **First mypy strict pass exposes ~50-100 holes**: 1-2 days of fixing, but **only once**
- **Third-party lib stub gaps** (`sqlite_vec` / `trafilatura` etc): `ignore_missing_imports = true` mitigates, but `Any` leaks at that boundary
- **Pre-commit occasionally blocks a commit**: slow but life-saving

### Remaining Python weaknesses (honest)

After all guards above, Python still has weaknesses TS / Go don't:

- **Rename / refactor tooling lags TS-in-VS-Code** (`pyright` in IDE helps; not enforced by this ADR)
- **Third-party `Any` holes** (when lib types are weak, mypy silently allows that layer)
- **Dynamic Python features** (`getattr` / `__getattr__` / `**kwargs`) not visible to mypy; mitigated via lint + ADR conventions

But those are **gentler than "easy to write badly"**, and have lint / convention safety nets.

## References

- [ADR-0019 frontend stack](./0019-frontend-stack.en.md) — frontend hardening; this ADR is the backend counterpart
- [ADR-0021 implementation order](./0021-knowledge-base-first-roadmap.en.md) — this ADR runs in Phase 0
- [feedback_no_hidden_debt](memory) — this ADR's spirit: guards are the engineering action that prevents latent debt
