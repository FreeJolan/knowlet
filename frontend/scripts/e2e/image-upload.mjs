/**
 * Phase 1 B slice 4 — image paste + drop into the editor.
 *
 * The browser's clipboard / drag-drop APIs aren't easy to invoke from
 * Playwright in headless mode. We dispatch synthetic ClipboardEvent /
 * DragEvent objects with a constructed DataTransfer that contains a
 * Blob — this is what real native paste/drop produces and triggers our
 * CodeMirror extension's `paste` / `drop` handlers.
 *
 * Verifications:
 *  - markdown gets the `![](_attachments/...)` link inserted
 *  - file actually lands on disk (vault `_attachments/` dir non-empty)
 *  - preview pane resolves the path to `/files/_attachments/...` and
 *    renders an <img> with that src
 *  - non-image paste (plain text) is unaffected — falls through to CM
 *    default behavior
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

// Tiny 1x1 transparent PNG — base64 inlined so the test has zero
// filesystem dependencies. (89 bytes.)
const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

const env = await setupTestEnv({
  notes: [{ title: "scratch", body: "before" }],
  language: "en",
});
const { page, baseURL, vaultDir, teardown } = env;

async function clickRow(title) {
  const row = page.locator(".group").filter({ hasText: title }).first();
  await row.waitFor({ state: "visible", timeout: 3000 });
  await row.click();
}

async function clickIntoEditor() {
  const c = page.locator('[data-testid="markdown-editor"] .cm-content');
  await c.waitFor({ state: "visible", timeout: 3000 });
  await c.click();
  return c;
}

/**
 * Dispatch a ClipboardEvent on the editor's contenteditable element
 * with a synthetic DataTransfer carrying the supplied PNG bytes.
 */
async function dispatchPaste(b64) {
  await page.evaluate(async (b64) => {
    const target = document.querySelector(
      '[data-testid="markdown-editor"] .cm-content',
    );
    if (!target) throw new Error("editor not found");
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const blob = new Blob([bytes], { type: "image/png" });
    const file = new File([blob], "pasted.png", { type: "image/png" });
    const dt = new DataTransfer();
    dt.items.add(file);
    const ev = new ClipboardEvent("paste", {
      clipboardData: dt,
      bubbles: true,
      cancelable: true,
    });
    target.dispatchEvent(ev);
  }, b64);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("paste image inserts ![](_attachments/...) into the doc", async () => {
    await clickRow("scratch");
    await clickIntoEditor();
    // Drop existing content + position cursor at end.
    await page.keyboard.press("Meta+End");
    await dispatchPaste(PNG_BASE64);
    // Wait until the placeholder is replaced with the real path.
    await page.waitForFunction(
      () => {
        const cmContent = document.querySelector(
          '[data-testid="markdown-editor"] .cm-content',
        );
        const text = cmContent?.textContent ?? "";
        return /_attachments\/[A-Za-z0-9]+\.png/.test(text);
      },
      null,
      { timeout: 5000, polling: 80 },
    );
    const text = await page
      .locator('[data-testid="markdown-editor"] .cm-content')
      .textContent();
    assert(
      /\!\[.*\]\(_attachments\/[A-Za-z0-9]+\.png\)/.test(text ?? ""),
      `markdown image inserted — got "${(text ?? "").slice(0, 120)}"`,
    );
  });

  await runTest("uploaded file lands on disk in _attachments/", async () => {
    const { readdirSync } = await import("node:fs");
    const dir = join(vaultDir, "notes", "_attachments");
    let files;
    try {
      files = readdirSync(dir);
    } catch {
      files = [];
    }
    const pngs = files.filter((n) => n.endsWith(".png"));
    assert(pngs.length >= 1, `at least one .png in _attachments — got ${JSON.stringify(files)}`);
  });

  await runTest("preview pane renders <img> with rewritten /files/ src", async () => {
    // Switch to preview mode on the same note.
    await page.locator('button[data-mode="preview"]').click();
    await page.waitForTimeout(400);
    // The preview component should render an <img> with src starting
    // with /files/_attachments/.
    const imgSrc = await page
      .locator('[data-testid="markdown-preview"] img')
      .first()
      .getAttribute("src");
    assert(
      typeof imgSrc === "string" && imgSrc.startsWith("/files/_attachments/"),
      `preview <img src> rewritten to /files/ — got "${imgSrc}"`,
    );
    // And the URL should actually 200 — backend serves it.
    const r = await page.request.get(`${baseURL}${imgSrc}`);
    assert(r.ok(), `GET ${imgSrc} returns 2xx — got ${r.status()}`);
    // Reset to edit mode for any later tests.
    await page.locator('button[data-mode="edit"]').click();
    await page.waitForTimeout(200);
  });

  await runTest("drop image inserts ![](_attachments/...)", async () => {
    // We avoid a full DragEvent dispatch here because the page also
    // hosts react-arborist + react-dnd HTML5 backend, whose global
    // drag tracker hits an invariant when fed a synthetic drop. Instead,
    // we synthesise a File-bearing DataTransfer and dispatch directly
    // on the editor's contentDOM in capture phase — this is exactly
    // the path our extension's listener is wired for, with no global
    // dnd surface to upset.
    await clickRow("scratch");
    await clickIntoEditor();
    await page.keyboard.press("Meta+End");
    const before = await page
      .locator('[data-testid="markdown-editor"] .cm-content')
      .textContent();
    const beforeCount = (before ?? "").match(/_attachments\//g)?.length ?? 0;
    await page.evaluate((b64) => {
      const target = document.querySelector(
        '[data-testid="markdown-editor"] .cm-content',
      );
      if (!target) throw new Error("editor not found");
      const bin = atob(b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: "image/png" });
      const file = new File([blob], "dropped.png", { type: "image/png" });
      const dt = new DataTransfer();
      dt.items.add(file);
      const rect = target.getBoundingClientRect();
      // Bypass document-level react-dnd by stopPropagation early: the
      // event still reaches the editor's capture-phase listener.
      target.addEventListener(
        "drop",
        (e) => e.stopPropagation(),
        { once: true, capture: true },
      );
      const ev = new DragEvent("drop", {
        dataTransfer: dt,
        bubbles: true,
        cancelable: true,
        clientX: rect.left + 20,
        clientY: rect.top + 20,
      });
      target.dispatchEvent(ev);
    }, PNG_BASE64);
    await page.waitForFunction(
      (count) => {
        const cm = document.querySelector(
          '[data-testid="markdown-editor"] .cm-content',
        );
        const text = cm?.textContent ?? "";
        return (text.match(/_attachments\//g)?.length ?? 0) > count;
      },
      beforeCount,
      { timeout: 5000, polling: 80 },
    );
    const after = await page
      .locator('[data-testid="markdown-editor"] .cm-content')
      .textContent();
    assert(
      /\!\[.*\]\(_attachments\/[A-Za-z0-9]+\.png\)/.test(after ?? ""),
      `drop inserted markdown image — got "${(after ?? "").slice(-120)}"`,
    );
  });

  await runTest(
    "dragover renders a drop indicator that survives loss of focus",
    async () => {
      // Critical regression: when the user starts a drag in Finder, the
      // browser editor loses focus → CM6's built-in caret stops
      // rendering → the user has no visual cue where the image will
      // land. Our extension MUST render an indicator independent of
      // focus state. Verify by blurring the editor *first* and then
      // dispatching a dragover — the indicator must appear.
      await clickRow("scratch");
      const cmContent = await clickIntoEditor();
      await page.keyboard.press("Meta+A");
      await page.keyboard.press("Delete");
      await page.keyboard.type("aaaa\nbbbb\ncccc\ndddd\neeee", { delay: 10 });
      // Blur the editor — simulates the user clicking into Finder to
      // start a drag.
      await page.evaluate(() => {
        if (document.activeElement instanceof HTMLElement) {
          document.activeElement.blur();
        }
      });
      // No drop indicator before dragover.
      const beforeCount = await page
        .locator('[data-testid="markdown-editor"] .kn-drop-indicator')
        .count();
      assert(beforeCount === 0, `no indicator before dragover — got ${beforeCount}`);
      // Dispatch dragover at a specific position inside the editor.
      const targetBox = await cmContent.boundingBox();
      if (!targetBox) throw new Error("editor has no bounding box");
      await page.evaluate(
        ([dx, dy]) => {
          const target = document.querySelector(
            '[data-testid="markdown-editor"] .cm-content',
          );
          if (!target) return;
          const dt = new DataTransfer();
          const file = new File([new Uint8Array([0])], "x.png", {
            type: "image/png",
          });
          dt.items.add(file);
          const ev = new DragEvent("dragover", {
            dataTransfer: dt,
            bubbles: true,
            cancelable: true,
            clientX: dx,
            clientY: dy,
          });
          target.dispatchEvent(ev);
        },
        [targetBox.x + 20, targetBox.y + targetBox.height - 30],
      );
      await page.waitForTimeout(120);
      const afterCount = await page
        .locator('[data-testid="markdown-editor"] .kn-drop-indicator')
        .count();
      assert(
        afterCount === 1,
        `exactly one indicator visible during dragover (even when blurred) — got ${afterCount}`,
      );
      // Indicator must clear when the drag leaves the editor.
      // (Dispatch a drop event in tests would bubble to react-dnd's
      // global HTML5 backend and trip its invariant; dragleave is
      // safe and exercises the same clear path the production code
      // takes when the user drags off the editor.)
      await page.evaluate(() => {
        const target = document.querySelector(
          '[data-testid="markdown-editor"] .cm-content',
        );
        if (!target) return;
        const ev = new DragEvent("dragleave", {
          bubbles: true,
          cancelable: true,
          // relatedTarget = body to indicate we left the editor
          // entirely, not just hopped to a child node.
          relatedTarget: document.body,
        });
        target.dispatchEvent(ev);
      });
      await page.waitForTimeout(120);
      const finalCount = await page
        .locator('[data-testid="markdown-editor"] .kn-drop-indicator')
        .count();
      assert(
        finalCount === 0,
        `indicator cleared after dragleave — got ${finalCount}`,
      );
    },
  );

  // Drop's pre-condition: dragover with a file payload calls
  // preventDefault. Without this the browser cancels the drop
  // entirely, which was the "drag from Finder does nothing" bug.
  //
  // We use a synthetic DataTransfer with a File added via items.add().
  // In Playwright this populates `dt.types` with "Files" — the same
  // signal real Finder drags expose during dragover, before per-item
  // mime details are unmasked.
  await runTest("dragover with a file payload calls preventDefault", async () => {
    await clickRow("scratch");
    await clickIntoEditor();
    const defaultPrevented = await page.evaluate(() => {
      const target = document.querySelector(
        '[data-testid="markdown-editor"] .cm-content',
      );
      if (!target) return null;
      const dt = new DataTransfer();
      const file = new File([new Uint8Array([0])], "x.png", {
        type: "image/png",
      });
      dt.items.add(file);
      const ev = new DragEvent("dragover", {
        dataTransfer: dt,
        bubbles: true,
        cancelable: true,
      });
      // dispatchEvent returns false if any listener called preventDefault.
      return target.dispatchEvent(ev) === false;
    });
    assert(
      defaultPrevented === true,
      `dragover handler called preventDefault — got ${defaultPrevented}`,
    );
  });

  // (Note: we intentionally do not assert text-only dragover skips
  // preventDefault. CM6 has its own DnD handling for text selections
  // and calls preventDefault itself in that path — that's correct,
  // unrelated to our extension. Our contract is "image drags must
  // succeed", verified by the test above.)

  await runTest("plain-text paste falls through to default CM behavior", async () => {
    await clickRow("scratch");
    await clickIntoEditor();
    await page.keyboard.press("Meta+End");
    // Set clipboard with plain text only — no images. Our extension
    // returns false, CM should insert the text verbatim.
    await page.evaluate(() => {
      const target = document.querySelector(
        '[data-testid="markdown-editor"] .cm-content',
      );
      const dt = new DataTransfer();
      dt.setData("text/plain", "PASTED-PLAIN-TEXT");
      const ev = new ClipboardEvent("paste", {
        clipboardData: dt,
        bubbles: true,
        cancelable: true,
      });
      target.dispatchEvent(ev);
    });
    await page.waitForTimeout(300);
    const text = await page
      .locator('[data-testid="markdown-editor"] .cm-content')
      .textContent();
    assert(
      (text ?? "").includes("PASTED-PLAIN-TEXT"),
      `plain text inserted — got "${(text ?? "").slice(-60)}"`,
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

// Used to satisfy the compiler about an unused import in some JS engines;
// readFileSync is left available in case future tests want a real on-disk
// fixture.
void readFileSync;
