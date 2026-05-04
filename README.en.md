# Knowlet

> **English** | [中文](./README.md)

> **A personal knowledge base that organizes itself.**
> *会自己整理的个人知识库。*

Knowlet is an AI long-term memory layer + lower-burden PKM, built first for personal use and gradually opened to the public. AI takes over the low-ROI organization work — summarizing, classifying, sedimenting, retrieving — while you keep intent, thinking, and judgment. At the same time, any AI tool (Claude / Cursor / others) can actively retrieve from this knowledge base during a conversation — so the memory is visible not just inside knowlet, but across all your AI workflows.

> Knowlet's MVP is implemented (M0 end-to-end CLI / M1 user-context layer / M2 minimal web UI). It is in the "self-use first" phase; real-use feedback drives the roadmap. See [ADR-0007](./docs/decisions/0007-mvp-slice.en.md) and [`docs/design/mvp-slice.en.md`](./docs/design/mvp-slice.en.md).

## Quick start

```bash
# Install (requires Python 3.11+; optional [embed] extra pulls the local embedding model)
git clone https://github.com/FreeJolan/knowlet.git && cd knowlet
uv sync --extra embed                  # sync deps into project venv
uv tool install -e .                   # put `knowlet` on PATH (recommended; usable from any dir)

# Prepare a vault (any directory; iCloud / Syncthing / Dropbox work fine)
mkdir ~/my-vault && cd ~/my-vault
knowlet vault init .
knowlet config init       # wizard: OpenAI-compatible base_url / api_key / model
knowlet doctor            # smoke-test backend + LLM tool-call support
knowlet user edit         # (optional) write your own profile

# Use it
knowlet                   # no subcommand → drops into the chat REPL
knowlet web               # browser UI — http://127.0.0.1:8765
```

> **Don't want a global install?** Skip the `uv tool install` line and prefix commands with `uv run` from the source dir:
> ```bash
> cd /path/to/knowlet
> KNOWLET_VAULT=~/my-vault uv run knowlet web --port 8765
> KNOWLET_VAULT=~/my-vault uv run knowlet vault snapshot --label pre-upgrade
> ```
> Or `source .venv/bin/activate` once for bare `knowlet` commands in the current shell (`deactivate` to exit).
>
> **Upgrade** (all paths): `cd /path/to/knowlet && git pull && uv sync --extra embed && uv tool install -e . --force` (the trailing `uv tool install` only matters for that path).

The LLM endpoint can be any OpenAI-Chat-Completions-compatible service — OpenAI, OpenRouter, Ollama, or an open-source community wrapper that exposes Claude Code / Codex / Cursor as an OpenAI endpoint. See [ADR-0005](./docs/decisions/0005-llm-integration-strategy.en.md).

## Upgrade flow (data safety)

knowlet is still iterating fast (0.0.x). Before every `git pull`, **make a vault snapshot first** so you can roll back if anything goes sideways:

```bash
cd ~/my-vault
knowlet vault snapshot --label pre-upgrade   # full copy under .knowlet/snapshots/

cd ~/path/to/knowlet/source
git pull && uv sync --extra embed            # pull new code + sync deps

cd ~/my-vault
knowlet doctor                               # checks embedding / index / vault data integrity

# All clean → run for a while to confirm → delete the snapshot
ls .knowlet/snapshots/                       # or `knowlet vault list-snapshots`
rm -rf .knowlet/snapshots/<ts>-pre-upgrade

# Something broke → one-command rollback (also re-snapshots the broken state first, so you can undo the rollback if needed)
knowlet vault restore-snapshot pre-upgrade
knowlet reindex                              # rebuild FTS / vector index
```

**Guarantees**:

- Vault is a plain folder — you can `cp -R` / git commit / Syncthing back it up anytime
- Notes are Markdown + YAML frontmatter — any editor can read / repair
- Writes are atomic (`.tmp` → `rename`); a power cut won't leave half-files
- Delete is soft (`notes/.trash/`), recoverable via `knowlet notes restore <id>`
- Note frontmatter has `schema_version` (v1 default); future schema changes won't break old notes
- `knowlet doctor` walks every Note / Card / Draft / Task file and verifies they parse cleanly

## Core Principles

- **AI is an optional enhancement, not a requirement** — without AI, it's still a usable note library
- **Data sovereignty belongs to the user** — local-first, Markdown / JSON, you can pack up and leave anytime
- **Capability plugin-ization + AI compose, code execute** — code only exposes atomic capabilities; the LLM orchestrates workflows

See [ADR-0002 — Three Core Principles](./docs/decisions/0002-core-principles.en.md) and [ADR-0004 — AI Compose, Code Execute](./docs/decisions/0004-ai-compose-code-execute.en.md).

## Real Scenarios in Stage 1

See [ADR-0003](./docs/decisions/0003-wedge-pivot-ai-memory-layer.en.md):

- **A. Research / paper reading** — Discuss in embedded chat → AI draft → user reviews → save; later AI conversations auto-recall historical conclusions
- **B. Information stream subscription and organization** — Configure knowledge mining tasks → scheduled fetching + LLM organization → user reviews → save
- **C. Structured repeated memory + AI augmentation** — Foreign language vocabulary / domain concept distinction / writing assessment; SRS submodule + AI adjusts feedback by user context

The three scenarios share **one user context** (goals / preferences / mistake patterns / vocabulary mastery), and AI accumulates understanding across them.

## Document Index

- [`docs/`](./docs/) — Top-level entry to design documents
  - [`decisions/`](./docs/decisions/) — Architecture Decision Records (ADR)
  - [`design/`](./docs/design/) — Living docs: architecture / users / organization / tech stack / voice
  - [`roadmap/`](./docs/roadmap/) — Phase roadmap

## License

[MIT](./LICENSE)
