# Voice Input & TTS Design

> **English** | [中文](./voice.md)

> Living doc. **Voice features are not prioritized in stage 1**; this document is preserved as a design reference for later stages.

## Current Position

[ADR-0003](../decisions/0003-wedge-pivot-ai-memory-layer.en.md) sets the wedge as "AI long-term memory layer + lower-burden PKM", with target users being desktop-primary, and mobile in stage 1 limited to responsive PWA. Voice features do not enter stage 1 core features.

But voice still has long-term value, especially in Scenario C (structured repeated memory)'s review sub-flow: commute / walking / workout — scenarios where the screen is inconvenient. This document records design ideas for stages 2/3.

## Two Core Scenarios

### 1. Voice answering (user speaks, system understands)

Review scenario: after the system shows a question, the user answers verbally rather than typing.

Design points:

- **Allow colloquial and imprecise expression**
- **LLM does semantic scoring, not character matching**
- **Recognize control commands**: "I don't know", "skip", "say it again"
- **Support text supplementation**: when ASR fails, the user can append typing to correct

### 2. Voice asking (system reads, user listens)

Commute / walking / workout:

- **TTS reads the card front**, user answers verbally or mentally then says "flip" / "next"
- **Adjustable pace**: reading speed, interval timing fit the scenario
- **Earbud control**: integrates with Bluetooth earbud buttons

## Known Pitfalls

### ASR accuracy

ASR accuracy on mixed-language technical terminology (common in tech learning) is significantly lower than pure-Chinese / pure-English.

**Mitigations:**

- Allow users to **append text** corrections (interaction must be low-cost)
- Maintain a **per-user terminology dictionary** (extracted from history notes / cards) used as a post-processing correction wordlist
- For critical review scenarios, prefer text + voice dual-track

### Edge cases of semantic scoring

LLM semantic scoring faces: partial-correct answers, "over-spec" correctness, misjudgment-appeal, etc.

**Mitigations:**

- Scoring granularity is "correct / partial / wrong / blank / skipped" (5-tier), not 0–100
- Each scoring **shows the AI's reasoning**, with one-click override
- User overrides are feedback, recorded for prompt improvement

## Connection with [ADR-0004](../decisions/0004-ai-compose-code-execute.en.md)

Voice processing naturally fits "AI compose + code execute":

- ASR / TTS are atomic capabilities (`transcribe_audio` / `synthesize_speech`)
- Semantic scoring is orchestrated by LLM, calling existing tools like `get_card / submit_review`
- No separate workflow needed for voice

## When Voice Enters the Roadmap

Trigger conditions for voice features entering the roadmap (stage 2 or 3):

- Sufficient review volume in Scenario C, with clear fragment-scenario demand
- ASR / TTS model cost and accuracy reach acceptable thresholds
- Mobile native capabilities (microphone / background playback / lock-screen control) are in place
