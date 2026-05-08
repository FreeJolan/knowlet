/**
 * Phase 1 D slice 2 — global full-text search focus mode (Cmd+Shift+F).
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    {
      title: "Quantum mechanics intro",
      body: "Fundamentals of superposition and entanglement in physical systems.",
    },
    {
      title: "Quantum computing basics",
      body: "Qubits, gates, and how entanglement enables algorithms.",
    },
    {
      title: "Cooking pasta",
      body: "Boil water with salt, drop pasta, stir occasionally for 8 minutes.",
    },
    {
      title: "Reading list 2026",
      body: "Books I plan to read, organized by genre.",
    },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Cmd+Shift+F opens search focus mode", async () => {
    await page.keyboard.press("Meta+Shift+F");
    await page.waitForTimeout(300);
    await page
      .locator('[data-testid="search-focus-mode"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="search-input"]')
      .waitFor({ state: "visible", timeout: 1000 });
  });

  await runTest("Idle state shows hint, no results", async () => {
    const focus = page.locator('[data-testid="search-focus-mode"]');
    const visible = await focus.isVisible();
    assert(visible, "search focus should still be visible from previous test");
    const rows = await page
      .locator('[data-testid="search-result-row"]')
      .count();
    assert(rows === 0, `idle state should have 0 results — got ${rows}`);
    // The idle copy includes "↑↓" / "Enter" hint per i18n.
    const hint = page.locator("text=Type a phrase").first();
    await hint.waitFor({ state: "visible", timeout: 2000 });
  });

  await runTest("Typing 'entanglement' returns the two quantum notes at top", async () => {
    const input = page.locator('[data-testid="search-input"]');
    await input.fill("entanglement");
    await page.waitForTimeout(700); // debounce + fetch
    const rows = page.locator('[data-testid="search-result-row"]');
    const count = await rows.count();
    assert(count >= 2, `expected ≥2 results — got ${count}`);
    // Top 2 should be the two quantum notes (cooking pasta has neither
    // word; reading list doesn't either).
    const top0 = await rows.nth(0).textContent();
    const top1 = await rows.nth(1).textContent();
    const combined = `${top0 ?? ""}|${top1 ?? ""}`;
    assert(
      /Quantum mechanics/.test(combined) && /Quantum computing/.test(combined),
      `top 2 should be the two quantum notes — got "${combined.slice(0, 120)}"`,
    );
  });

  await runTest("ArrowDown/Up + Enter opens the active result", async () => {
    const input = page.locator('[data-testid="search-input"]');
    await input.fill("quantum");
    await page.waitForTimeout(600);
    const rows = page.locator('[data-testid="search-result-row"]');
    await rows.first().waitFor({ state: "visible", timeout: 2000 });
    // First row is active by default (data-active="1"); ArrowDown moves to row 1.
    await input.press("ArrowDown");
    await page.waitForTimeout(100);
    const activeIdx = await page.evaluate(() => {
      const all = document.querySelectorAll(
        '[data-testid="search-result-row"]',
      );
      let idx = -1;
      all.forEach((el, i) => {
        if (el.getAttribute("data-active") === "1") idx = i;
      });
      return idx;
    });
    assert(activeIdx === 1, `after ArrowDown, active row should be 1 — got ${activeIdx}`);
    // Enter opens the active result + closes focus mode.
    await input.press("Enter");
    await page.waitForTimeout(500);
    const stillOpen = await page
      .locator('[data-testid="search-focus-mode"]')
      .isVisible()
      .catch(() => false);
    assert(!stillOpen, "after Enter, focus mode should close");
    const titleH1 = page.locator('[data-testid="note-title"]').first();
    await titleH1.waitFor({ state: "visible", timeout: 3000 });
    const titleText = (await titleH1.textContent()) ?? "";
    assert(
      /Quantum/.test(titleText),
      `should have opened a Quantum note — got "${titleText}"`,
    );
  });

  await runTest("Click a result row opens that note", async () => {
    await page.keyboard.press("Meta+Shift+F");
    await page.waitForTimeout(400);
    await page.locator('[data-testid="search-input"]').fill("pasta");
    await page.waitForTimeout(600);
    const rows = page.locator('[data-testid="search-result-row"]');
    const count = await rows.count();
    assert(count >= 1, `expected ≥1 result for 'pasta' — got ${count}`);
    await rows.first().click();
    await page.waitForTimeout(500);
    const titleH1 = page.locator('[data-testid="note-title"]').first();
    const titleText = (await titleH1.textContent()) ?? "";
    assert(
      /Cooking pasta/.test(titleText),
      `clicking pasta result should open Cooking pasta — got "${titleText}"`,
    );
  });

  await runTest("Esc closes focus mode", async () => {
    await page.keyboard.press("Meta+Shift+F");
    await page.waitForTimeout(300);
    await page
      .locator('[data-testid="search-focus-mode"]')
      .waitFor({ state: "visible" });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    const stillOpen = await page
      .locator('[data-testid="search-focus-mode"]')
      .isVisible()
      .catch(() => false);
    assert(!stillOpen, "Esc should close focus mode");
  });

  await runTest(
    "IME composition: Enter during pinyin compose must NOT trigger open",
    async () => {
      // Regression: Phase 1 D slice 2 dogfood — Enter during a Chinese
      // IME composition was committing the active result + closing the
      // panel instead of letting the IME confirm its candidate.
      // Playwright doesn't run a real IME but we can simulate with
      // composition events + the CompositionEvent / KeyboardEvent
      // API; the handler reads `e.nativeEvent.isComposing` so a
      // dispatched Enter while isComposing=true must be a no-op.
      await page.keyboard.press("Meta+Shift+F");
      await page.waitForTimeout(300);
      const input = page.locator('[data-testid="search-input"]');
      await input.fill("quantum");
      await page.waitForTimeout(600);
      // Sanity: there are results (so Enter would naïvely fire open).
      const before = await page
        .locator('[data-testid="search-result-row"]')
        .count();
      assert(before >= 1, `expected results before IME test — got ${before}`);
      // Simulate IME composition and dispatch Enter as if from IME.
      // Browsers set keyCode=229 + isComposing=true for IME-driven
      // Enters; the imeSafeKeyHandler must skip them.
      const handlerFiredOpen = await page.evaluate(() => {
        const el = document.querySelector(
          '[data-testid="search-input"]',
        );
        if (!(el instanceof HTMLInputElement)) return "no-input";
        // Start composition.
        el.dispatchEvent(new CompositionEvent("compositionstart"));
        // Dispatch Enter while still composing. React listens via
        // synthetic events, so we use KeyboardEvent and `isComposing`.
        const ev = new KeyboardEvent("keydown", {
          key: "Enter",
          code: "Enter",
          keyCode: 229,
          which: 229,
          bubbles: true,
          cancelable: true,
          composed: true,
        });
        // `isComposing` is read-only on KeyboardEvent so we override
        // via property descriptor — same trick the React testing
        // ecosystem uses.
        Object.defineProperty(ev, "isComposing", { get: () => true });
        el.dispatchEvent(ev);
        // End composition cleanly.
        el.dispatchEvent(new CompositionEvent("compositionend"));
        // Was the focus mode closed? If yes, the handler fired
        // through the IME guard (BUG). If no, guard worked (good).
        return !!document.querySelector('[data-testid="search-focus-mode"]');
      });
      assert(
        handlerFiredOpen === true,
        `IME-Enter must NOT close focus mode; got handlerFiredOpen=${handlerFiredOpen}`,
      );
      // Now press Enter normally (no composition) — should open.
      await input.press("Enter");
      await page.waitForTimeout(500);
      const stillOpen = await page
        .locator('[data-testid="search-focus-mode"]')
        .isVisible()
        .catch(() => false);
      assert(!stillOpen, "real Enter (no IME) should still close the panel");
    },
  );

  await runTest("Result rows render highlighted matches", async () => {
    await page.keyboard.press("Meta+Shift+F");
    await page.waitForTimeout(300);
    await page.locator('[data-testid="search-input"]').fill("entanglement");
    await page.waitForTimeout(600);
    // The query word should be wrapped in <mark> within the snippet
    // for at least one result.
    const marks = await page
      .locator('[data-testid="search-result-row"] mark')
      .count();
    assert(marks >= 1, `expected ≥1 highlighted match — got ${marks}`);
    await page.keyboard.press("Escape");
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase1d-slice2 e2e failed:", e);
  await teardown();
  exitAfter(1);
}
