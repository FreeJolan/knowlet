# Knowlet

> **English** | [中文](./README.md)

> **A personal knowledge base that organizes itself.**
> *会自己整理的个人知识库。*

Knowlet is an AI long-term memory layer + lower-burden PKM, built first for personal use and gradually opened to the public. AI takes over the low-ROI organization work — summarizing, classifying, sedimenting, retrieving — while you keep intent, thinking, and judgment. At the same time, any AI tool (Claude / Cursor / others) can actively retrieve from this knowledge base during a conversation — so the memory is visible not just inside knowlet, but across all your AI workflows.

> Knowlet's MVP is implemented (M0 end-to-end CLI / M1 user-context layer / M2 minimal web UI). It is in the "self-use first" phase; real-use feedback drives the roadmap. See [ADR-0007](./docs/decisions/0007-mvp-slice.en.md) and [`docs/design/mvp-slice.en.md`](./docs/design/mvp-slice.en.md).

## Quick start

```bash
# One-time install (requires Python 3.11+; optional [embed] extra pulls the local embedding model)
git clone https://github.com/FreeJolan/knowlet.git && cd knowlet
uv venv --python 3.12
uv pip install -e '.[embed]'

# Prepare a vault (any directory; iCloud / Syncthing / Dropbox work fine)
mkdir ~/my-vault && cd ~/my-vault
knowlet vault init .
knowlet config init       # wizard: OpenAI-compatible base_url / api_key / model
knowlet doctor            # smoke-test backend + LLM tool-call support
knowlet user edit         # (optional) write your own profile

# Use it
knowlet                   # no subcommand → drops into the chat REPL
# or, browser-based UI
knowlet web               # default http://127.0.0.1:8765
```

The LLM endpoint can be any OpenAI-Chat-Completions-compatible service — OpenAI, OpenRouter, Ollama, or an open-source community wrapper that exposes Claude Code / Codex / Cursor as an OpenAI endpoint. See [ADR-0005](./docs/decisions/0005-llm-integration-strategy.en.md).

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
