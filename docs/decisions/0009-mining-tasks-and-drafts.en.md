# 0009 — Knowledge-mining tasks + drafts review queue

> **English** | [中文](./0009-mining-tasks-and-drafts.md)

- Status: Accepted
- Date: 2026-05-01

## Context

[ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md) names "information-stream subscription and organization" as one of the three real Stage-1 scenarios (Scenario B):

> The user configures a "knowledge-mining task" (frequency + source constraints + Prompt) → scheduled execution → transparent fetch process → produces multiple atomic Notes + index Notes → user reviews and saves to library.

M0–M3 covered scenarios A (paper reading) and C (SRS); Scenario B was untouched. M4 lands the minimum usable slice of Scenario B.

A few forks were not obvious initially and need to be pinned in this ADR so future agents don't relitigate:

- Which scheduler backend (in-daemon scheduler / system cron / fully manual)
- What source types fall in scope (RSS / URL / web crawler / email / Webhook — costs vs value)
- Where "AI draft → user review → Note" lives physically (separate drafts dir / inbox tag / hidden queue)
- Where task definitions live (vault Markdown / vault-external config / database)
- How "already seen" state persists across runs (avoid re-fetching)

## Decision

### 1. Scheduler: **APScheduler in-daemon + manual override always available**

- When `knowlet web` starts, the FastAPI lifespan brings up an `APScheduler.BackgroundScheduler` (UTC timezone).
- Each task's `schedule.every` / `schedule.cron` becomes an `IntervalTrigger` / `CronTrigger`.
- `misfire_grace_time=300`, `coalesce=True`, `max_instances=1` — no burst catch-up after restart / brief downtime.
- **Manual triggers always work:** `knowlet mining run <id>` and `knowlet mining run-all` do not depend on the scheduler. Users can wrap `knowlet mining run-all` in system cron as a backup.
- `knowlet chat` (non-daemon) does not start the scheduler.

**Why not system-level launchd / cron:** macOS / Linux differ; permission boundaries are large; debugging is hard; violates the "install and use" promise.

**Why not manual-only:** Scenario B literally requires "scheduled execution"; otherwise it's no different from bookmarking the RSS link, and product value drops.

### 2. Source types (M4): **RSS / Atom + single-URL fetch**

- **RSS / Atom:** `feedparser` parses; each entry is a `SourceItem`.
- **URL:** `httpx` GET → `trafilatura.extract` for main content → a single `SourceItem`.
- **Explicitly out of scope** (post-M4):
  - Web crawlers (multi-page / login / JS rendering) — per-site adapters not worth M4
  - Email IMAP — auth complexity, narrow value surface
  - Webhooks — needs a long-running listener; orthogonal to current daemon model but bigger scope; M5+

Source design: **all fetchers return a list of `SourceItem`** so runner / extractor are source-type-agnostic. New types just add a `_fetch_<type>` in `sources.py`.

### 3. Drafts location: **`<vault>/drafts/<id>-<slug>.md`**

Each draft is a standalone Markdown (with frontmatter, `status: draft`).

- **Pros:** Same shape as Notes; user editors (Obsidian / VS Code / etc.) see + edit them directly; ADR-0002 data sovereignty literally satisfied; matches "AI draft + user review" promise from ADR-0003 word-for-word.
- **Review actions:**
  - **approve** → project Draft to Note (`Draft.to_note()` keeps id / title / body / tags / source), write to `<vault>/notes/`, `Index.upsert_note` to index, then delete the file in drafts/.
  - **reject** → delete the file in drafts/; **the seen-set keeps the source item id**, so the same item won't re-extract.
- **Not indexed**: drafts directory does **not** go into FTS5 / vector indexes. RAG retrieval only touches approved Notes. Drafts are tentative; indexing them would pollute RAG answers.

**Why not `tags: [inbox]`:** drafts mixed with Notes pollute retrieval; review state hidden in a tag is brittle (other tags can mask it).

**Why not a hidden JSON queue (`.knowlet/pending/`):** invisible to user editors; violates ADR-0002's "pack up and walk away" promise; review UX would have to be knowlet-only, conflicting with "zero forced learning curve".

### 4. Task definition: **`<vault>/tasks/<id>-<slug>.md`, frontmatter config + body description**

```yaml
---
id: 01HX...
name: AI papers daily
enabled: true
schedule:
  every: "1h"      # or cron: "0 9 * * *"
sources:
  - rss: "https://arxiv.org/rss/cs.AI"
  - url: "https://example.com/blog"
prompt: |
  Summarize each item in 2-3 sentences ...
created_at: ...
updated_at: ...
---
optional Markdown body — why this task exists
```

- **Travels with the vault**: tasks are user configuration; iCloud / Syncthing carry them across devices.
- **frontmatter + body**: friendly to user editors.
- **Not in `.knowlet/`**: that's knowlet's derived state (index, conversation log), not user-owned content.

### 5. Cross-run "seen" state: **`<vault>/.knowlet/mining/<task_id>.json`**

```json
{ "seen": ["<item_id_1>", "<item_id_2>", ...] }
```

- One file per task; item_id prefers `entry.id` (RSS), then link, then URL.
- Failed items also enter the seen-set to avoid retry loops on bad items.
- The file lives in `.knowlet/` (derived state); cross-device sync is **not enforced** — separate seen-sets per device works (cost: first sync may dup a batch of drafts; one reject pass clears it).
- **Not at the vault root** (user content) and **not in SQLite** (derived state: JSON is easier to debug + recreate).

### 6. LLM-extraction prompt shape

Same lesson `chat/sediment.py` learned per [ADR-0008](./0008-cli-parity-discipline.en.md): **fold the whole extraction prompt into the user message**; do not rely on `role: "system"` (some OpenAI-compatible proxies ignore role-assignment in system prompts).

One LLM call per source item (not batched), trading volume for:

- **Error isolation**: one item's prompt failing doesn't affect others.
- **Stable token boundary**: items don't compete for context length.
- **Clear provenance**: each draft maps to one source item.

The cost is N× LLM calls; acceptable when an RSS feed adds tens of items per run. A future `batch_size` parameter on extractor is M5+.

## Consequences

### Benefits

- **Scenario B becomes real.** Leave the daemon running; come back in the evening to find a few drafts in the inbox; review; commit. The first concrete realization of the "AI organizes for me" product promise.
- **Fully consistent with ADR-0008.** Six atomic tools (`list_mining_tasks / run_mining_task / list_drafts / get_draft / approve_draft / reject_draft`) are thin shells over backend functions; CLI / slash / web all call them; the LLM orchestrates "run task → list drafts → review one by one" via tool calls.
- **Architecture stays clean.** Drafts don't enter RAG until approved — matches the "AI draft + human review" promise verbatim, no shortcuts.
- **Manual + auto dual-track.** When the daemon is offline, users still wrap `knowlet mining run-all` in cron without losing Scenario B.
- **Easy to test.** Source fetch is monkeypatched out; the LLM is stubbed — `runner.run_task` is functional-ish (all state in vault files + seen-set JSON), making assertions straightforward.

### Costs / constraints

- **APScheduler dep** (~1 MB pure Python). Heavier than zero-dep manual; far less invasive than launchd integration. Acceptable.
- **Tasks pause while the daemon is offline.** `misfire_grace_time` decides whether to catch up; we picked "brief downtime fine, long downtime defers to the next interval", which fits RSS / URL fetch (the next run pulls all new items). It doesn't fit "must never miss" use cases. Future option: explicit catch-up logic if scenario demands.
- **One LLM call per item**: token cost is non-trivial when an RSS feed pushes many updates. MVP accepts it; batching is an M5+ optimization.
- **Drafts not indexed.** If the user wants to "search through pending drafts", that's not supported. A `search_drafts(query)` tool could be added; M4 skips it (drafts are short-lived, search value low).
- **Cron expressions are 5-field standard only.** `@daily` / `@weekly` macros are unsupported (APScheduler's `CronTrigger.from_crontab` doesn't take macros). Could preprocess at task load time; M4 skips.
- **Task edits require a scheduler reload** (`MiningScheduler.reload()`), otherwise the daemon keeps the old trigger. Web PUT/POST triggers reload automatically; CLI edits (direct `<vault>/tasks/*.md` modifications) do not — restart the daemon or add `:mining reload` (future). Documented as a known limitation in M4.

### Relation to existing ADRs

- **Subordinate to** [ADR-0003](./0003-wedge-pivot-ai-memory-layer.en.md): Scenario B realized.
- **Follows** [ADR-0004](./0004-ai-compose-code-execute.en.md): runner / extractor / scheduler are atomic capabilities; LLM orchestrates via tool calls.
- **Follows** [ADR-0008](./0008-cli-parity-discipline.en.md): 6 atomic tools + CLI subcommands + slash + web endpoints + UI panel share backend functions; tests primarily target the backend.
- **Follows** [ADR-0006](./0006-storage-and-sync.en.md): tasks / drafts as user-facing Markdown; seen-set as derived JSON.
- **Does not conflict** with [ADR-0005](./0005-llm-integration-strategy.en.md): LLM still flows through the same OpenAI-compatible client; no new channel introduced.
