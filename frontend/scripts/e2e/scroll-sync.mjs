/**
 * Phase 1 B slice 9 — anchor-based scroll sync between editor + preview
 * in split mode. Verifies:
 *   - rehypeSourceLine stamps every preview element with data-source-line
 *   - scrolling the editor moves the preview to the same source line
 *   - scrolling the preview moves the editor
 *   - sync activates ONLY in split mode
 *
 * The body is long enough that several headings live well below the
 * viewport, so we have room to scroll AND a clear ground truth for
 * which line should land on top.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

// 8 sections of "## H<N>\n\n<8 filler lines>". Total ~75 lines.
function buildLongBody() {
  const sections = [];
  for (let i = 1; i <= 8; i++) {
    sections.push(`## H${i}`);
    for (let j = 1; j <= 8; j++) sections.push(`Section ${i} para ${j}.`);
  }
  return sections.join("\n");
}

const env = await setupTestEnv({
  notes: [{ title: "long", body: buildLongBody() }],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function clickRow(title) {
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const row = page
    .locator(".group")
    .filter({ hasText: new RegExp(`^${escaped}$`) })
    .first();
  await row.waitFor({ state: "visible", timeout: 3000 });
  await row.click();
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("preview elements carry data-source-line attributes", async () => {
    await clickRow("long");
    await page.locator('button[data-mode="split"]').click();
    await page.waitForTimeout(400);
    const lines = await page
      .locator('[data-testid="markdown-preview"] [data-source-line]')
      .evaluateAll((els) =>
        els.map((el) => Number(el.getAttribute("data-source-line"))),
      );
    assert(
      lines.length >= 16,
      `at least one element per heading + paragraph — got ${lines.length}`,
    );
    // 1-based, ascending in DOM order.
    for (let i = 1; i < lines.length; i++) {
      assert(
        lines[i] >= lines[i - 1],
        `data-source-line non-decreasing — got ${JSON.stringify(lines.slice(0, 5))}…`,
      );
    }
  });

  await runTest("scrolling the editor moves the preview", async () => {
    await clickRow("long");
    await page.locator('button[data-mode="split"]').click();
    await page.waitForTimeout(400);
    const previewScrollBefore = await page.evaluate(
      () =>
        document.querySelector('[data-testid="markdown-preview"]')
          ?.scrollTop ?? 0,
    );
    // Drive the editor's scroll programmatically and dispatch a real
    // wheel event so our "active pane" tracking picks `editor`.
    await page.evaluate(() => {
      const scroller = document.querySelector(
        '[data-testid="markdown-editor"] .cm-scroller',
      );
      if (!scroller) throw new Error("cm-scroller not found");
      scroller.dispatchEvent(new WheelEvent("wheel", { bubbles: true }));
      scroller.scrollTop = 600;
      scroller.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await page.waitForTimeout(120);
    const previewScrollAfter = await page.evaluate(
      () =>
        document.querySelector('[data-testid="markdown-preview"]')
          ?.scrollTop ?? 0,
    );
    assert(
      previewScrollAfter > previewScrollBefore + 50,
      `preview scrolled in response — before=${previewScrollBefore} after=${previewScrollAfter}`,
    );
  });

  await runTest("scrolling the preview moves the editor", async () => {
    await clickRow("long");
    await page.locator('button[data-mode="split"]').click();
    await page.waitForTimeout(400);
    // Reset both to top so we have headroom to scroll.
    await page.evaluate(() => {
      const cm = document.querySelector(
        '[data-testid="markdown-editor"] .cm-scroller',
      );
      const pv = document.querySelector('[data-testid="markdown-preview"]');
      if (cm) cm.scrollTop = 0;
      if (pv) pv.scrollTop = 0;
    });
    await page.waitForTimeout(120);
    const editorScrollBefore = await page.evaluate(
      () =>
        document.querySelector(
          '[data-testid="markdown-editor"] .cm-scroller',
        )?.scrollTop ?? 0,
    );
    // Drive the preview, mark it active first via wheel.
    await page.evaluate(() => {
      const pv = document.querySelector('[data-testid="markdown-preview"]');
      if (!pv) throw new Error("preview not found");
      pv.dispatchEvent(new WheelEvent("wheel", { bubbles: true }));
      pv.scrollTop = 800;
      pv.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await page.waitForTimeout(120);
    const editorScrollAfter = await page.evaluate(
      () =>
        document.querySelector(
          '[data-testid="markdown-editor"] .cm-scroller',
        )?.scrollTop ?? 0,
    );
    assert(
      editorScrollAfter > editorScrollBefore + 50,
      `editor scrolled in response — before=${editorScrollBefore} after=${editorScrollAfter}`,
    );
  });

  await runTest(
    "round-trip split → preview-only → split keeps sync working + scroll position",
    async () => {
      await clickRow("long");
      await page.locator('button[data-mode="split"]').click();
      await page.waitForTimeout(400);
      // Scroll editor down so we have a remembered position.
      await page.evaluate(() => {
        const cm = document.querySelector(
          '[data-testid="markdown-editor"] .cm-scroller',
        );
        if (cm) cm.scrollTop = 500;
      });
      await page.waitForTimeout(120);
      const editorScrollFirstSplit = await page.evaluate(
        () =>
          document.querySelector(
            '[data-testid="markdown-editor"] .cm-scroller',
          )?.scrollTop ?? 0,
      );
      assert(editorScrollFirstSplit > 100, "editor scrolled down");
      // Toggle to preview-only, then back to split.
      await page.locator('button[data-mode="preview"]').click();
      await page.waitForTimeout(300);
      await page.locator('button[data-mode="split"]').click();
      await page.waitForTimeout(400);
      // Editor scroll position survived the round-trip (panes are
      // hidden via CSS, not unmounted).
      const editorScrollAfterRoundTrip = await page.evaluate(
        () =>
          document.querySelector(
            '[data-testid="markdown-editor"] .cm-scroller',
          )?.scrollTop ?? 0,
      );
      assert(
        Math.abs(editorScrollAfterRoundTrip - editorScrollFirstSplit) < 30,
        `editor scroll preserved through mode toggle — was ${editorScrollFirstSplit}, now ${editorScrollAfterRoundTrip}`,
      );
      // Reset both panes to top so we have headroom to verify sync,
      // then scroll editor enough to make preview move (but not past
      // preview's max — the preview's rendered HTML is shorter than
      // the markdown source's editor pixel height).
      await page.evaluate(() => {
        const cm = document.querySelector(
          '[data-testid="markdown-editor"] .cm-scroller',
        );
        const pv = document.querySelector(
          '[data-testid="markdown-preview"]',
        );
        if (cm) cm.scrollTop = 0;
        if (pv) pv.scrollTop = 0;
      });
      await page.waitForTimeout(150);
      const previewBefore = await page.evaluate(
        () =>
          document.querySelector('[data-testid="markdown-preview"]')
            ?.scrollTop ?? 0,
      );
      await page.evaluate(() => {
        const cm = document.querySelector(
          '[data-testid="markdown-editor"] .cm-scroller',
        );
        if (!cm) return;
        cm.dispatchEvent(new WheelEvent("wheel", { bubbles: true }));
        cm.scrollTop = 400;
        cm.dispatchEvent(new Event("scroll", { bubbles: true }));
      });
      await page.waitForTimeout(150);
      const previewAfter = await page.evaluate(
        () =>
          document.querySelector('[data-testid="markdown-preview"]')
            ?.scrollTop ?? 0,
      );
      assert(
        previewAfter > previewBefore + 30,
        `sync still drives preview after round-trip — before=${previewBefore} after=${previewAfter}`,
      );
    },
  );

  await runTest("sync only fires in split mode", async () => {
    await clickRow("long");
    // Preview-only mode: editor isn't visible → scrolling preview
    // shouldn't try to scroll a missing editor.
    await page.locator('button[data-mode="preview"]').click();
    await page.waitForTimeout(300);
    // Preview is visible; editor is not. Scroll the preview — must
    // not throw or try to manipulate a non-existent editor.
    await page.evaluate(() => {
      const pv = document.querySelector('[data-testid="markdown-preview"]');
      if (!pv) return;
      pv.dispatchEvent(new WheelEvent("wheel", { bubbles: true }));
      pv.scrollTop = 200;
      pv.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await page.waitForTimeout(120);
    // Edit-only mode: same in reverse.
    await page.locator('button[data-mode="edit"]').click();
    await page.waitForTimeout(300);
    await page.evaluate(() => {
      const cm = document.querySelector(
        '[data-testid="markdown-editor"] .cm-scroller',
      );
      if (!cm) return;
      cm.dispatchEvent(new WheelEvent("wheel", { bubbles: true }));
      cm.scrollTop = 200;
      cm.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await page.waitForTimeout(120);
    // Reaching here without a thrown pageerror is success; the
    // fixture's env.errors check below catches anything that broke.
  });

  if (env.errors.length > 0) {
    const real = env.errors.filter(
      (e) => e.type === "pageerror" || /TypeError|SyntaxError/.test(e.text),
    );
    if (real.length > 0) {
      console.log("✗ no console errors");
      for (const e of real) console.log("  ", e.type, e.text);
      process.exitCode = 1;
    } else {
      console.log("✓ no console errors (filtered noise)");
    }
  } else {
    console.log("✓ no console errors");
  }
} finally {
  await teardown();
  exitAfter();
}
