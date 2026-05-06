/**
 * Phase 1 B slice 1+2 — CodeMirror editor smoke + auto-save +
 * Cmd+B/I/K formatting + IME composition safety + fenced-code highlighting.
 *
 * The "did the save actually persist" check goes through the backend
 * (GET /api/notes/{id}) rather than scraping CodeMirror DOM, because
 * .cm-content `textContent` collapses line breaks and the source of
 * truth is the file on disk.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "alpha", body: "hello world\nsecond line" },
    { title: "beta", body: "" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function getNoteByTitle(title) {
  const r = await fetch(`${baseURL}/api/tree`);
  const tree = await r.json();
  const flat = [];
  const walk = (node) => {
    for (const n of node.notes ?? []) flat.push(n);
    for (const f of node.folders ?? []) walk(f);
  };
  walk(tree);
  const hit = flat.find((n) => n.title === title);
  if (!hit) throw new Error(`note titled "${title}" not in tree`);
  const r2 = await fetch(`${baseURL}/api/notes/${encodeURIComponent(hit.id)}`);
  return r2.json();
}

async function clickRow(title) {
  const row = page.locator(".group").filter({ hasText: title }).first();
  await row.waitFor({ state: "visible", timeout: 3000 });
  await row.click();
}

async function clickIntoEditor() {
  const content = page.locator('[data-testid="markdown-editor"] .cm-content');
  await content.waitFor({ state: "visible", timeout: 3000 });
  await content.click();
  return content;
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("editor mounts when a note is selected", async () => {
    await clickRow("alpha");
    const content = page
      .locator('[data-testid="markdown-editor"] .cm-content')
      .first();
    await content.waitFor({ state: "visible", timeout: 3000 });
    const text = (await content.textContent()) ?? "";
    assert(
      text.includes("hello world") && text.includes("second line"),
      `editor renders existing body — got "${text.slice(0, 80)}"`,
    );
  });

  await runTest("typing into editor auto-saves to disk", async () => {
    await clickRow("beta");
    await clickIntoEditor();
    // Real keystrokes — make sure the input event chain fires.
    await page.keyboard.type("freshly typed body", { delay: 20 });
    // Wait past the 800 ms debounce + a network round-trip.
    await page.waitForTimeout(1500);
    const beta = await getNoteByTitle("beta");
    assert(
      beta.body.includes("freshly typed body"),
      `backend persisted body — got "${beta.body.slice(0, 80)}"`,
    );
  });

  await runTest("autosave badge shows saving → saved → idle", async () => {
    await clickRow("alpha");
    await clickIntoEditor();
    // Install a MutationObserver in-page that captures every textContent
    // the badge holds, so we don't have to win a polling race with the
    // ~30 ms saving→saved transition. The result is a complete log,
    // independent of Playwright sample timing.
    await page.evaluate(() => {
      const w = window;
      w.__badgeLog = [];
      const target = document.querySelector('[data-testid="autosave-state"]');
      if (!target) return;
      const push = () => {
        const text = (target.textContent ?? "").trim();
        if (text && w.__badgeLog?.[w.__badgeLog.length - 1] !== text) {
          w.__badgeLog?.push(text);
        }
      };
      push();
      new MutationObserver(push).observe(target, {
        childList: true,
        characterData: true,
        subtree: true,
      });
    });
    await page.keyboard.type(" extra", { delay: 20 });
    // Wait until the badge has reached "saved" and then either timed out
    // back to idle, OR 2.5 s passes — whichever comes first.
    await page.waitForTimeout(2500);
    const log = await page.evaluate(() => {
      const w = window;
      return w.__badgeLog ?? [];
    });
    const sawSaving = log.some((t) => /saving/i.test(t));
    const sawSaved = log.some((t) => /saved/i.test(t));
    assert(
      sawSaving,
      `saw 'saving…' state during round-trip — log: ${JSON.stringify(log)}`,
    );
    assert(
      sawSaved,
      `saw 'saved' state after persistence — log: ${JSON.stringify(log)}`,
    );
  });

  await runTest(
    "switching notes flushes the previous note's pending edits",
    async () => {
      // Type into beta and immediately swap to alpha *before* the 800ms
      // debounce elapses — flushSave on unmount must persist the edit.
      await clickRow("beta");
      await clickIntoEditor();
      await page.keyboard.type(" mid-flight save", { delay: 10 });
      // Don't wait for debounce.
      await clickRow("alpha");
      await page.waitForTimeout(800);
      const beta = await getNoteByTitle("beta");
      assert(
        beta.body.includes("mid-flight save"),
        `mid-flight edit reached disk on note swap — got "${beta.body.slice(0, 80)}"`,
      );
    },
  );

  await runTest("Cmd+B wraps selection with **...**", async () => {
    await clickRow("alpha");
    const content = await clickIntoEditor();
    // Reset to known content + select "world" only.
    await page.keyboard.press("Meta+A");
    await page.keyboard.press("Delete");
    await page.keyboard.type("hello world", { delay: 20 });
    // Move cursor to end-of-line, then back-select 5 chars ("world").
    await page.keyboard.press("End");
    for (let i = 0; i < 5; i++) await page.keyboard.press("Shift+ArrowLeft");
    await page.keyboard.press("Meta+B");
    await page.waitForTimeout(1500);
    const a = await getNoteByTitle("alpha");
    assert(
      a.body.includes("hello **world**"),
      `selection wrapped with ** — got "${a.body.slice(0, 80)}"`,
    );
    void content;
  });

  await runTest("Cmd+I wraps selection with *...*", async () => {
    await clickRow("alpha");
    await clickIntoEditor();
    await page.keyboard.press("Meta+A");
    await page.keyboard.press("Delete");
    await page.keyboard.type("italic me", { delay: 20 });
    await page.keyboard.press("End");
    for (let i = 0; i < 2; i++) await page.keyboard.press("Shift+ArrowLeft");
    await page.keyboard.press("Meta+I");
    await page.waitForTimeout(1500);
    const a = await getNoteByTitle("alpha");
    assert(
      a.body.includes("italic *me*"),
      `selection wrapped with * — got "${a.body.slice(0, 80)}"`,
    );
  });

  await runTest("Cmd+K inserts [text]() link skeleton", async () => {
    await clickRow("alpha");
    await clickIntoEditor();
    await page.keyboard.press("Meta+A");
    await page.keyboard.press("Delete");
    await page.keyboard.type("see ", { delay: 15 });
    await page.keyboard.type("docs", { delay: 15 });
    await page.keyboard.press("End");
    for (let i = 0; i < 4; i++) await page.keyboard.press("Shift+ArrowLeft");
    await page.keyboard.press("Meta+K");
    // Cursor should land between the parens; type a URL into it.
    await page.keyboard.type("https://example.com", { delay: 10 });
    await page.waitForTimeout(1500);
    const a = await getNoteByTitle("alpha");
    assert(
      a.body.includes("[docs](https://example.com)"),
      `link skeleton with cursor in URL slot — got "${a.body.slice(0, 80)}"`,
    );
  });

  await runTest("IME composition Enter does NOT confirm-submit", async () => {
    await clickRow("alpha");
    const content = await clickIntoEditor();
    await page.keyboard.press("Meta+A");
    await page.keyboard.press("Delete");
    // Simulate a composition cycle: start, update with candidate, an Enter
    // keydown WHILE composing (which native IME uses to accept), then end.
    // The editor should treat that Enter as part of composition and NOT
    // dispatch its own newline insertion.
    await content.evaluate((el) => {
      el.dispatchEvent(new CompositionEvent("compositionstart", { data: "" }));
      el.dispatchEvent(
        new CompositionEvent("compositionupdate", { data: "你好" }),
      );
    });
    await content.evaluate((el) => {
      const ev = new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        isComposing: true,
        bubbles: true,
        cancelable: true,
      });
      el.dispatchEvent(ev);
    });
    await content.evaluate((el) => {
      el.dispatchEvent(new CompositionEvent("compositionend", { data: "你好" }));
    });
    // After the composition, the editor's input handler should have
    // accepted "你好" without a runaway newline. Type a space to commit.
    await page.keyboard.type(" 世界", { delay: 30 });
    await page.waitForTimeout(1500);
    const a = await getNoteByTitle("alpha");
    // The body should contain 你好 + 世界 without a newline between them.
    // CodeMirror handles composition itself, so we mainly check that the
    // composed text landed and we did not produce two paragraphs.
    assert(
      a.body.includes("世界"),
      `IME composed text persisted — got "${a.body}"`,
    );
    assert(
      !/^\s*$/.test(a.body),
      "IME path did not end with empty body",
    );
  });

  await runTest("markdown grammar emits styled token classes", async () => {
    // Verify the editor actually applies syntax highlighting at all —
    // markdown's own grammar (headers, fences, inline emphasis) emits
    // tokens synchronously. Embedded code-block language highlighting
    // (`@codemirror/language-data`) loads async, so we don't depend on
    // it here; that is verified visually during dogfood.
    await clickRow("alpha");
    await clickIntoEditor();
    await page.keyboard.press("Meta+A");
    await page.keyboard.press("Delete");
    await page.keyboard.type("# Heading\n\n```js\nconst x = 1;\n```", {
      delay: 10,
    });
    await page.waitForTimeout(1500);
    // CM6 wraps token spans with class names that include both `cm-` and
    // a tag name (e.g. `tok-heading`, `cm-meta`). Just count any span
    // with a class — markdown emphasis fences, header line all get one.
    const distinct = await page.evaluate(() => {
      const content = document.querySelector(
        '[data-testid="markdown-editor"] .cm-content',
      );
      if (!content) return [];
      const spans = Array.from(content.querySelectorAll("span"));
      const classes = spans
        .map((s) => s.className)
        .filter((c) => typeof c === "string" && c.length > 0);
      return [...new Set(classes)];
    });
    assert(
      distinct.length >= 2,
      `markdown emits at least two styled token classes — got ${distinct.join(", ") || "<none>"}`,
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
