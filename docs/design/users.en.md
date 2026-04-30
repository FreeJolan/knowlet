# Target Users

> **English** | [中文](./users.md)

> Living doc. The composite persona may evolve as the product matures.

## Common Persona

Knowlet's core audience is **knowledge workers**: people who do long-term deep learning in some domain (reading papers / writing code / doing research / systematically learning a technology), and occasionally enter scenarios needing structured memorization (foreign language / exam prep / domain concept distinction).

These two activities are not separate in their daily lives but run in parallel. **No tool currently serves both lines** — Anki only handles review (not research), Obsidian only handles notes (not active recall), ChatGPT memory is neither persistent nor user-owned.

## Composite Persona Traits

| Dimension | Description |
|---|---|
| **Profession / identity** | Programmer / researcher / technical professional / continuous-learning knowledge worker |
| **AI usage** | Already accustomed to Claude / Cursor / ChatGPT and similar tools; **heavy but prefers tool-bring-your-own-LLM rather than new tool's own AI** |
| **Data sovereignty sensitivity** | High — cares about "my notes / conversations / learning data belong to me" |
| **Willingness to pay** | Willing to pay for LLM API; willing to pay small overhead to self-host open-source tools |
| **Learning mode** | Desktop-primary (deep reading / writing); mobile for fragment review and questioning |
| **Source of frustration** | Existing PKM tools' organizing burden; AI tools' session amnesia; cross-tool memory fragmentation |

## Three Real Scenarios in Stage 1

See [ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) Scenarios A / B / C:

- **A. Research / paper reading** — Desktop-primary, periodically high-intensity
- **B. Information stream subscription and organization** — Background scheduled, user reviews in scattered times
- **C. Structured repeated memory + AI augmentation** — Review high-frequency (mobile-friendly); writing tasks low-frequency but important

The three scenarios share **one user context** (goals / preferences / mistake patterns / vocabulary mastery). AI accumulates understanding across them — this is knowlet's core differentiation from existing tools.

## Explicitly Not Served (Stage 1)

- **Team / collaborative scenarios**: knowlet never does multi-user (B1 in [ADR-0003](./../decisions/0003-wedge-pivot-ai-memory-layer.en.md))
- **Beginners unwilling to configure LLM**: stage 1 first-time configuration has nonzero friction (see [ADR-0005](./../decisions/0005-llm-integration-strategy.en.md))
- **Heavy mobile-only users**: stage 1 is desktop + PWA; native mobile experience deferred to stage 2
- **Pure SRS users for exam / language learning**: Anki / Duolingo / etc. are already familiar; stage 1 knowlet does not try to displace their core scenarios

## Persona as a "Decision Lens"

All product trade-offs in stage 1 use this composite persona as a **decision lens** (see "Wedge" discussion in [ADR-0003](./../decisions/0003-wedge-pivot-ai-memory-layer.en.md)). For example:

- "Should default SRS parameters be aggressive or gentle?" → Knowledge workers' review intensity is typically gentle (unlike grad-school applicants), so FSRS defaults gentle
- "Should users wait for index rebuild on first launch?" → Programmers can accept 30 seconds ~ 1 minute with progress indicators
- "Should card front default to showing / hiding hints?" → In writing assessment scenarios AI needs to see the source sentence; so Card content is by default visible to LLM

Specific decision logic is recorded in the corresponding ADR / design docs; this document only describes the "persona".
