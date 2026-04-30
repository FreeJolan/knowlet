# Knowlet Design Docs

> **English** | [中文](./README.md)

This directory records Knowlet's design discussions and plans, serving as the formal continuation of the original draft.

## Structure

- [`decisions/`](./decisions/) — ADR-style decision records, one decision per file. **Immutable**, append-only; if a decision is overturned, add a new ADR marked `Supersedes`.
- [`design/`](./design/) — Living docs on architecture, domain model, loop diagrams, etc. Updated continuously as the project evolves.
- [`roadmap/`](./roadmap/) — Phase roadmap, feature priorities, milestones.

## Writing Conventions

- All documents in Markdown, prefer plain text and lightweight expression
- Diagrams use Mermaid / ASCII / external image links — avoid binaries
- Decision documents (ADR) named `NNNN-kebab-case-title.md`, starting from 0001
- Each document has a one-sentence summary at the top for quick scanning in indexes
- Bilingual: each doc has both `<name>.md` (Chinese) and `<name>.en.md` (English) versions
