/**
 * Phase 1 B slice 3 — three-mode editor (edit / split / preview).
 * Verifies toggle visibility, mode-specific pane rendering, live mirror
 * in split mode, and localStorage persistence.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    {
      title: "doc",
      body: "# Big heading\n\nSome **bold** text and a [link](https://example.com).",
    },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function clickRow(title) {
  const row = page.locator(".group").filter({ hasText: title }).first();
  await row.waitFor({ state: "visible", timeout: 3000 });
  await row.click();
}

async function clickMode(mode) {
  await page.locator(`button[data-mode="${mode}"]`).click();
  // Brief pause so the React state flush + remount happens before the
  // next assertion.
  await page.waitForTimeout(80);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("toggle has three modes; default is 'edit'", async () => {
    await clickRow("doc");
    const toggle = page.locator('[data-testid="view-mode-toggle"]');
    await toggle.waitFor({ state: "visible", timeout: 3000 });
    const buttons = await page
      .locator('[data-testid="view-mode-toggle"] button[data-mode]')
      .count();
    assert(buttons === 3, `three buttons, got ${buttons}`);
    const editActive = await page
      .locator('button[data-mode="edit"][data-active="true"]')
      .count();
    assert(editActive === 1, "edit mode is active by default");
    // Slice 9 changed pane unmount → display:none toggle (so scroll
    // position + EditorView ref survive mode switches). `.count()`
    // sees the hidden DOM node; `isVisible()` respects display:none.
    const previewVisible = await page
      .locator('[data-testid="markdown-preview"]')
      .isVisible();
    assert(previewVisible === false, "preview hidden in edit mode");
  });

  await runTest("preview mode renders markdown as HTML", async () => {
    await clickRow("doc");
    await clickMode("preview");
    const preview = page.locator('[data-testid="markdown-preview"]');
    await preview.waitFor({ state: "visible", timeout: 3000 });
    // The body has a `# Big heading` — should render as <h1>.
    const h1 = await preview.locator("h1").innerText();
    assert(/Big heading/.test(h1), `preview shows h1 — got "${h1}"`);
    const strong = await preview.locator("strong").innerText();
    assert(/bold/.test(strong), `preview shows <strong> — got "${strong}"`);
    const link = await preview.locator('a[href="https://example.com"]').count();
    assert(link === 1, "preview renders the link as an anchor");
    // Editor pane is in DOM but display:none in preview-only mode —
    // `isVisible()` returns false, `.count()` returns 1.
    const editorVisible = await page
      .locator('[data-testid="markdown-editor"]')
      .isVisible();
    assert(editorVisible === false, "editor hidden in preview mode");
  });

  await runTest("split mode shows both panes; typing live-updates preview", async () => {
    await clickRow("doc");
    await clickMode("split");
    const editor = page.locator('[data-testid="markdown-editor"] .cm-content');
    const preview = page.locator('[data-testid="markdown-preview"]');
    await editor.waitFor({ state: "visible", timeout: 3000 });
    await preview.waitFor({ state: "visible", timeout: 3000 });
    // Add new content; verify the preview reflects it within ~500ms.
    await editor.click();
    await page.keyboard.press("Meta+End");
    await page.keyboard.type("\n\n## Live mirror", { delay: 15 });
    // Wait briefly for React to batch the state update.
    await page.waitForFunction(
      () => {
        const h2s = document.querySelectorAll(
          '[data-testid="markdown-preview"] h2',
        );
        return Array.from(h2s).some((el) => /Live mirror/.test(el.textContent ?? ""));
      },
      null,
      { timeout: 2000, polling: 50 },
    );
    const h2text = await preview.locator("h2").innerText();
    assert(
      /Live mirror/.test(h2text),
      `split-mode preview live-updated — got "${h2text}"`,
    );
  });

  await runTest("view-mode choice persists across reload", async () => {
    await clickRow("doc");
    await clickMode("preview");
    // Wait until the persistence useEffect has actually written to
    // localStorage. The button click commits state synchronously inside
    // React 18, but the effect that calls setItem runs after commit.
    await page.waitForFunction(
      () =>
        window.localStorage.getItem("knowlet:view-mode") === "preview",
      null,
      { timeout: 2000, polling: 30 },
    );
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(400);
    const lsAfterReload = await page.evaluate(() =>
      window.localStorage.getItem("knowlet:view-mode"),
    );
    await clickRow("doc");
    await page.waitForTimeout(200);
    const allButtons = await page
      .locator('[data-testid="view-mode-toggle"] button[data-mode]')
      .evaluateAll((els) =>
        els.map((el) => ({
          mode: el.getAttribute("data-mode"),
          active: el.getAttribute("data-active"),
        })),
      );
    const previewActive = await page
      .locator('button[data-mode="preview"][data-active="true"]')
      .count();
    assert(
      previewActive === 1,
      `preview mode persisted across reload — localStorage=${lsAfterReload} buttons=${JSON.stringify(allButtons)}`,
    );
    // Reset for any later tests.
    await clickMode("edit");
  });

  await runTest(
    "switching from edit → preview → edit preserves user's edits",
    async () => {
      await clickRow("doc");
      // Make sure we're back in edit mode.
      await clickMode("edit");
      const editor = page.locator(
        '[data-testid="markdown-editor"] .cm-content',
      );
      await editor.click();
      await page.keyboard.press("Meta+End");
      await page.keyboard.type(" + scratch", { delay: 15 });
      await page.waitForTimeout(1500); // let auto-save flush
      await clickMode("preview");
      const preview = page.locator('[data-testid="markdown-preview"]');
      const text = await preview.innerText();
      assert(
        /\+ scratch/.test(text),
        `preview reflects edits made in edit mode — got "${text.slice(0, 80)}"`,
      );
      await clickMode("edit");
      const cmText = await editor.innerText();
      assert(
        /\+ scratch/.test(cmText),
        `editor still holds the same content after the round-trip — got "${cmText.slice(0, 80)}"`,
      );
    },
  );

  await runTest("preview link does NOT navigate the SPA away", async () => {
    await clickRow("doc");
    await clickMode("preview");
    const url0 = page.url();
    // Click an external link — it must open in a NEW context (target=_blank
    // returns a popup) and the current page URL must NOT change.
    const link = page
      .locator('[data-testid="markdown-preview"] a[href="https://example.com"]')
      .first();
    await link.waitFor({ state: "visible", timeout: 3000 });
    // We don't actually want to wait for the new tab to load — just verify
    // the SPA didn't navigate. Use middle-click? No — easier: assert the
    // anchor has target=_blank, which is what prevents in-place nav.
    const target = await link.getAttribute("target");
    assert(target === "_blank", `external link gets target=_blank — got "${target}"`);
    const rel = await link.getAttribute("rel");
    assert(
      typeof rel === "string" && /noopener/.test(rel) && /noreferrer/.test(rel),
      `external link gets rel=noopener noreferrer — got "${rel}"`,
    );
    // Empty hrefs should not navigate either.
    const url1 = page.url();
    assert(url0 === url1, `URL unchanged after preview render — ${url0} → ${url1}`);
    await clickMode("edit");
  });

  await runTest("autosave badge does NOT shift the toolbar layout", async () => {
    // Synthetic check — toggling between hidden / visible / idle / saving
    // states must produce identical widths for the autosave-state slot.
    // We measure once with each text, by setting the inner text via DOM,
    // and assert the outer slot's width is identical.
    await clickRow("doc");
    await clickMode("edit");
    const slot = page.locator('[data-testid="autosave-state"]');
    await slot.waitFor({ state: "attached" });
    const widths = await slot.evaluate((el) => {
      const inner = el.querySelector("span");
      if (!(inner instanceof HTMLElement)) return null;
      const original = inner.textContent;
      const originalVis = inner.style.visibility;
      const measure = (text, vis) => {
        inner.textContent = text;
        inner.style.visibility = vis;
        return el.getBoundingClientRect().width;
      };
      const idleW = measure("saved", "hidden");
      const savingW = measure("saving…", "visible");
      const savedW = measure("saved", "visible");
      // Restore.
      inner.textContent = original;
      inner.style.visibility = originalVis;
      return { idleW, savingW, savedW };
    });
    assert(widths !== null, "autosave-state has an inner span we can measure");
    const ws = [widths.idleW, widths.savingW, widths.savedW];
    const drift = Math.max(...ws) - Math.min(...ws);
    assert(
      drift <= 0.5,
      `autosave badge slot has same width across all states — got ${JSON.stringify(widths)}, drift=${drift}px`,
    );
  });

  if (env.errors.length > 0) {
    console.log("✗ no console errors");
    for (const e of env.errors) console.log("  ", e.type, e.text);
    process.exitCode = 1;
  } else {
    console.log("✓ no console errors");
  }
} finally {
  await teardown();
  exitAfter();
}
