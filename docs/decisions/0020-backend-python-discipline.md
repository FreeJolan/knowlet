# 0020 — 后端 Python 工程纪律

> [English](./0020-backend-python-discipline.en.md) | **中文**

- Status: Accepted
- Date: 2026-05-05

## Context

knowlet 后端 ~17k LOC Python,376 测试全过,功能性上**无已知 bug**(2026-05-04 dogfood 报告里所有 frustration 全是前端,0 是后端)。

但项目负责人在 5/5 对话里指出 Python 的真实弱点:

> "它的优点是容易写,缺点是容易写坏,特别是在一个稍大的项目中"

这是真的 — 只是不是 Python 本身的问题,是**默认配置 + 没自动化拦截**的问题。我们目前是"开了一半":

| 防护层 | 状态 |
|---|---|
| Python 3.11+ pinned | ✅ |
| 类型注解 | 🟡 大部分函数有,**但没人在跑 mypy 验证** |
| Pydantic v2 在 API 边界 | ✅ |
| ruff(lint)| ✅ 装了,**但没强制(没 pre-commit / CI)** |
| pytest 376 测试 | ✅ 全过,但**没 CI 自动跑** |
| **mypy strict** | ❌ |
| **pre-commit hooks** | ❌ |
| **GitHub Actions CI** | ❌ |
| **架构层依赖测试** | ❌ |

后果:任何 commit 在我自律不够时(此次 chat SSE bug)就漏过去了。需要**把"自律"升级成"自动化拦截"**。

## Decision

### 加 4 层防护(强 → 弱)

#### Layer 1:类型(强,必过)

`mypy --strict` 配置进 `pyproject.toml`,运行时检查必须 0 错误才可 commit:

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
# 三方库无类型 stub 的允许 Any(临时)
module = ["sqlite_vec", "trafilatura", "feedparser", "fsrs", "ulid", "frontmatter"]
ignore_missing_imports = true
```

预期:**第一次开 strict 会暴露 50-100 个类型漏**,补完后**消灭一大类 runtime AttributeError / TypeError / None 解引用**。

#### Layer 2:Lint + format(强,必过)

ruff 严格 ruleset,format 自动:

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

#### Layer 3:Pre-commit hook(强,本地 commit 时拦)

`.pre-commit-config.yaml`:每次 `git commit` 自动跑 mypy + ruff + pytest -x。失败 = commit 不过。

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

#### Layer 4:CI(GitHub Actions,push 时复跑)

`.github/workflows/ci.yml`:push 到 main / 任何 PR 跑同样的 lint + types + tests + coverage。
Branch protection:**main 不能 fast-forward 推**,必须走 PR + CI 全绿。

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

#### Layer 5:架构依赖测试(软,但写进 pytest)

`tests/test_architecture.py` 用 `import_linter` 或纯 `ast` 写一个测试,断言:

```python
# core/* 不能 import web/* 或 cli/*
# web/* 可以 import core/*,不能 import cli/*
# cli/* 可以 import core/*,不能 import web/*
# tests/* 可以 import 全部
```

这一条在重构期作为防御,避免"图省事跨层 import 出现"。

### Datatype 风格统一

Python 多种数据类型方式并存(`dataclass` / `BaseModel` / `TypedDict` / `NamedTuple` / 普通 `dict`),不约束就漂移。本 ADR 钉:

| 用途 | 用什么 | 理由 |
|---|---|---|
| **Vault 实体**(Note / Card / Draft / MiningTask)| `@dataclass` | 写法轻 / Python 自带 / mypy 严 |
| **API wire schema**(请求 / 响应)| `pydantic.BaseModel` | 边界做运行时 validation,把脏数据 reject 在边界 |
| **临时 dict-shaped 数据**(SQL 行 / JSON 解析) | `TypedDict` | 类型化但不带 runtime validation |
| **简单值对象**(SearchHit / QuoteRef etc) | `@dataclass(frozen=True)` | 不可变 + 类型严 |
| **不应该出现**:plain `dict[str, Any]` 跨模块传 | — | 没类型保护 = 等于无 |

### 禁某些 Python 特性(开发期不强制,但 review 时打回)

- `from x import *`(命名空间污染)
- `getattr(obj, name_str)` / `setattr` 跨模块(mypy 看不穿)
- `**kwargs` 转发到不知道签名的函数(同上)
- `# type: ignore` 没注释原因 → ruff 已会警告
- 全局可变状态(用 dependency injection / contextvars 替代)

### 不在本 ADR 范围

- 100% 测试覆盖 — 过度严格反而拖慢
- 100% 类型覆盖 — `# type: ignore[<reason>]` 在三方库边界仍然 OK
- Python 版本升级到 3.12 / 3.13 — 等到对应 typing 特性需要时再升

## 实施

[ADR-0021](./0021-knowledge-base-first-roadmap.md) §"Phase 0" 把这套防护跟前端 React 脚手架并行做(估计 1-2 天)。

落地 sequence:
1. 加 mypy 配置 + 跑 + 修暴露的 ~50-100 个类型漏(1 天)
2. 加 ruff 严配置 + 修暴露的 lint(半天)
3. 加 `pre-commit-config.yaml` + `pip install pre-commit && pre-commit install`(半天)
4. 加 GitHub Actions CI(半天)
5. 加架构依赖测试 + datatype 风格 audit(几小时)

完成后 ongoing 成本:0(每次 commit 自动跑)。

## Consequences

### Positive

- **自律变自动化**:agent / 贡献者 commit 不过这关就 commit 不进
- **类型 + lint + 边界 validation 三层**捕获绝大多数 silent runtime 错误
- **重构安全**:改 schema → mypy 报全部影响点,跟 TS 重命名体验接近
- **agent 维护友好**:LLM 写 Python 时类型提示让它"知道自己在改什么"
- **测试 + CI 防 regression**:每次 push,376 + 新增的 e2e 测试(per ADR-0019)全跑一遍

### Negative

- **第一次开 mypy strict 暴露的 ~50-100 个漏需要补**:1-2 天工作,但**就这一次**
- **三方库 stub 不全**(`sqlite_vec` / `trafilatura` 等):用 `ignore_missing_imports = true` 兜底,期间 `Any` 在那一层泄露但不蔓延
- **pre-commit 偶尔卡 commit**:慢但救命

### 仍然存在的 Python 软肋(诚实)

加完上面后,Python 仍然有这些 TS / Go 没有的弱点:

- **重命名工具不如 TS-in-VS-Code**(`pyright` 在 IDE 里好一些,可补,本 ADR 不强制)
- **三方库 `Any` 黑洞**(库类型差时,mypy 静默放过那一层)
- **运行时 dynamic 特性**(`getattr` / `__getattr__` / `**kwargs`)mypy 看不穿;靠 lint + ADR 约束

但这些都**比"易写坏"温柔**,且都有 lint / convention 兜底。

## References

- [ADR-0019 前端栈](./0019-frontend-stack.md) — 前端独立硬化,本 ADR 是后端的对应
- [ADR-0021 实施顺序](./0021-knowledge-base-first-roadmap.md) — 本 ADR 在 Phase 0
- [feedback_no_hidden_debt](memory) — 本 ADR 的精神延伸:防护层是消灭潜在债务的工程动作
