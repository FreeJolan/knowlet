/**
 * Regression suite for the frontend-core audit batch.
 *
 * Covers:
 *   - tree rename racing an in-flight autosave keeps BOTH the typed body
 *     and the new title on disk
 *   - tree rename during an autosave retry back-off is not reverted by the
 *     retried PUT (which captured the old title)
 *   - ⌘⇧V inside the editor is left to the browser (plain-text paste);
 *     outside text fields it still opens CaptureBox
 *   - a late clipboard read does not overwrite what the user already typed
 *     into CaptureBox
 *   - applying an AI edit surfaces a failed write, and refuses to write
 *     over a note that changed since the proposal
 *   - a failing palette quick action shows an error and the palette can
 *     be dismissed afterwards
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const AI_OLD = "RAG retrieves relevant chunks, then generates an answer.";
const AI_NEW = "RAG retrieves relevant chunks, reranks them, then generates an answer.";

const env = await setupTestEnv({
  notes: [
    { title: "rename-inflight", body: "seed one" },
    { title: "rename-retry", body: "seed two" },
    { title: "paste-target", body: "paste body" },
    { title: "ai-target", body: AI_OLD },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Route handlers can outlive the test that installed them; a late
 *  continue / fulfill on a settled route must not crash the suite. */
function safeRoute(handler) {
  return async (route) => {
    try {
      await handler(route);
    } catch {
      // route already handled / page torn down
    }
  };
}

function treeRow(title) {
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return page
    .locator(".group")
    .filter({ hasText: new RegExp(`^${escaped}$`) })
    .first();
}

async function openNote(title) {
  const row = treeRow(title);
  await row.waitFor({ state: "visible", timeout: 3000 });
  await row.click();
  await page
    .locator('[data-testid="note-title"]')
    .filter({ hasText: title })
    .waitFor({ state: "visible", timeout: 3000 });
  await editor().waitFor({ state: "visible", timeout: 3000 });
}

function editor() {
  return page.locator('[data-testid="markdown-editor"] .cm-content');
}

async function noteIdByTitle(title) {
  const r = await page.request.get(`${baseURL}/api/tree`);
  const tree = await r.json();
  const flat = [];
  const walk = (node) => {
    for (const n of node.notes ?? []) flat.push(n);
    for (const f of node.folders ?? []) walk(f);
  };
  walk(tree);
  const hit = flat.find((n) => n.title === title);
  if (!hit) throw new Error(`note "${title}" not in tree`);
  return hit.id;
}

async function serverNote(id) {
  const r = await page.request.get(`${baseURL}/api/notes/${id}`);
  return r.json();
}

async function waitForServer(id, pred, timeoutMs, label) {
  const t0 = Date.now();
  let snap = null;
  while (Date.now() - t0 < timeoutMs) {
    snap = await serverNote(id);
    if (pred(snap)) return snap;
    await sleep(150);
  }
  throw new Error(
    `timed out waiting for ${label}; server has ${JSON.stringify({
      title: snap?.title,
      body: snap?.body,
    })}`,
  );
}

/** Leave no modal behind for the next test, whatever this one did. */
async function dismissDialogs() {
  for (let i = 0; i < 3; i++) {
    const open = await page.locator('[role="dialog"]').count();
    if (open === 0) return;
    await page.keyboard.press("Escape");
    await sleep(200);
  }
}

async function blurActive() {
  await page.evaluate(() => {
    const a = document.activeElement;
    if (a instanceof HTMLElement) a.blur();
  });
}

async function renameViaTree(oldTitle, newTitle) {
  const row = treeRow(oldTitle);
  await row.click({ button: "right" });
  await page.getByRole("menuitem", { name: "Rename" }).click();
  const input = page.locator('input[data-rename-input="true"]');
  await input.waitFor({ state: "visible", timeout: 3000 });
  await input.fill(newTitle);
  await input.press("Enter");
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest(
    "tree rename while an autosave PUT is in flight keeps body and title",
    async () => {
      const id = await noteIdByTitle("rename-inflight");
      await openNote("rename-inflight");
      // Hold the first PUT (the blur-flush autosave) for 2.5 s.
      let puts = 0;
      const hold = safeRoute(async (route) => {
        if (route.request().method() !== "PUT") return route.continue();
        puts += 1;
        if (puts === 1) await sleep(2500);
        await route.continue();
      });
      await page.route(`**/api/notes/${id}`, hold);
      try {
        await editor().click();
        await page.keyboard.press("Meta+End");
        await page.keyboard.type(" typed-inflight");
        // Right-click on the tree blurs the editor → autosave PUT starts.
        await renameViaTree("rename-inflight", "renamed-inflight");
        const snap = await waitForServer(
          id,
          (n) => n.title === "renamed-inflight" && n.body.includes("typed-inflight"),
          10000,
          "rename + typed body on disk",
        );
        assert(
          snap.body.includes("typed-inflight"),
          `typed text must survive the rename — body=${JSON.stringify(snap.body)}`,
        );
        // Nothing else lands afterwards and flips it back.
        await sleep(1500);
        const settled = await serverNote(id);
        assert(
          settled.title === "renamed-inflight" &&
            settled.body.includes("typed-inflight"),
          `final state drifted: ${JSON.stringify({ title: settled.title, body: settled.body })}`,
        );
      } finally {
        await page.unroute(`**/api/notes/${id}`, hold);
      }
    },
  );

  await runTest(
    "tree rename during an autosave retry back-off is not reverted",
    async () => {
      const id = await noteIdByTitle("rename-retry");
      await openNote("rename-retry");
      // First PUT fails → NoteView's saveMutation waits ~2 s and retries
      // with the payload it captured (old title).
      let puts = 0;
      const failFirst = safeRoute(async (route) => {
        if (route.request().method() !== "PUT") return route.continue();
        puts += 1;
        if (puts === 1) {
          await route.fulfill({
            status: 503,
            contentType: "application/json",
            body: JSON.stringify({ detail: "simulated blip" }),
          });
          return;
        }
        await route.continue();
      });
      await page.route(`**/api/notes/${id}`, failFirst);
      try {
        await editor().click();
        await page.keyboard.press("Meta+End");
        await page.keyboard.type(" typed-retry");
        await renameViaTree("rename-retry", "renamed-retry");
        await waitForServer(
          id,
          (n) => n.title === "renamed-retry" && n.body.includes("typed-retry"),
          20000,
          "rename + retried body on disk",
        );
        // Give any straggling retry time to land.
        await sleep(3000);
        const settled = await serverNote(id);
        assert(
          settled.title === "renamed-retry",
          `retried autosave reverted the rename: title=${settled.title}`,
        );
        assert(
          settled.body.includes("typed-retry"),
          `typed text lost: body=${JSON.stringify(settled.body)}`,
        );
      } finally {
        await page.unroute(`**/api/notes/${id}`, failFirst);
      }
    },
  );

  await runTest("⌘⇧V inside the editor does not open CaptureBox", async () => {
    try {
      await openNote("paste-target");
      await editor().click();
      await page.keyboard.press("Meta+Shift+V");
      await sleep(400);
      const boxes = await page.locator('[data-testid="capture-box"]').count();
      assert(boxes === 0, `CaptureBox must not hijack ⌘⇧V in the editor (count=${boxes})`);
      const focusedInEditor = await page.evaluate(() =>
        Boolean(document.activeElement?.closest(".cm-editor")),
      );
      assert(focusedInEditor, "focus stays in the editor");
    } finally {
      await dismissDialogs();
    }
  });

  await runTest("⌘⇧V outside text fields still opens CaptureBox", async () => {
    try {
      await blurActive();
      await page.keyboard.press("Meta+Shift+V");
      await page
        .locator('[data-testid="capture-box"]')
        .waitFor({ state: "visible", timeout: 3000 });
      await page.keyboard.press("Escape");
      await page
        .locator('[data-testid="capture-box"]')
        .waitFor({ state: "hidden", timeout: 3000 });
    } finally {
      await dismissDialogs();
    }
  });

  await runTest("late clipboard read does not overwrite typed CaptureBox URL", async () => {
    try {
      await lateClipboardCase();
    } finally {
      await dismissDialogs();
    }
  });

  async function lateClipboardCase() {
    await page.evaluate(() => {
      let release;
      const pending = new Promise((resolve) => {
        release = resolve;
      });
      window.__releaseClipboard = (text) => release(text);
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { readText: () => pending },
      });
    });
    await blurActive();
    await page.keyboard.press("Meta+Shift+V");
    const input = page.locator('[data-testid="capture-url-input"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.click();
    await page.keyboard.type("https://typed.example/a");
    await page.evaluate(() => window.__releaseClipboard("https://clipboard.example/b"));
    await sleep(300);
    const value = await input.inputValue();
    assert(
      value === "https://typed.example/a",
      `typed URL was overwritten by the late clipboard read: "${value}"`,
    );
    await page.keyboard.press("Escape");
    await page
      .locator('[data-testid="capture-box"]')
      .waitFor({ state: "hidden", timeout: 3000 });
  }

  async function openAiProposal() {
    await openNote("ai-target");
    const pane = page.locator('[data-testid="discuss-pane"]');
    if (!(await pane.isVisible())) {
      await page.locator('[data-testid="header-discuss-button"]').click();
      await pane.waitFor({ state: "visible", timeout: 3000 });
    }
    const reset = page.locator('[data-testid="discuss-reset"]');
    if (await reset.isEnabled()) await reset.click();
    const stream = safeRoute(async (route) => {
      const noteId = new URL(route.request().url()).pathname.match(
        /\/api\/chat\/note\/([^/]+)\/stream$/,
      )?.[1];
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"tool_call","id":"edit_1","name":"propose_current_note_edit","arguments":{"instruction":"x"}}\n\n' +
          `data: {"type":"tool_result","id":"edit_1","name":"propose_current_note_edit","payload":{"kind":"note_edit_proposal","note_id":"${noteId}","title":"ai-target","changed":true,"summary":"ok","old_body":${JSON.stringify(AI_OLD)},"new_body":${JSON.stringify(AI_NEW)}}}\n\n` +
          'data: {"type":"reply_chunk","text":"ok"}\n\n' +
          'data: {"type":"turn_done","final_text":"ok"}\n\n',
      });
    });
    await page.route("**/api/chat/note/*/stream", stream);
    try {
      await page.locator('[data-testid="discuss-input"]').fill("propose");
      await page.locator('[data-testid="discuss-send"]').click();
      await page
        .locator('[data-testid="diff-review"]')
        .waitFor({ state: "visible", timeout: 5000 });
    } finally {
      await page.unroute("**/api/chat/note/*/stream", stream);
    }
  }

  await runTest("AI edit apply failure is surfaced and the diff stays", async () => {
    const id = await noteIdByTitle("ai-target");
    await openAiProposal();
    const fail = safeRoute(async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated apply failure" }),
      });
    });
    await page.route(`**/api/notes/${id}`, fail);
    try {
      await page.locator('[data-testid="diff-apply"]').click();
      const err = page.locator('[data-testid="diff-apply-error"]');
      await err.waitFor({ state: "visible", timeout: 5000 });
      const text = (await err.textContent()) ?? "";
      assert(
        text.includes("simulated apply failure"),
        `apply error should carry the backend detail — got "${text}"`,
      );
      await page
        .locator('[data-testid="diff-review"]')
        .waitFor({ state: "visible", timeout: 1000 });
    } finally {
      await page.unroute(`**/api/notes/${id}`, fail);
    }
    const snap = await serverNote(id);
    assert(snap.body === AI_OLD, `failed apply must not change disk: ${snap.body}`);
    // Retrying once the backend is back writes the proposal.
    await page.locator('[data-testid="diff-apply"]').click();
    await page
      .locator('[data-testid="diff-review"]')
      .waitFor({ state: "hidden", timeout: 5000 });
    await waitForServer(id, (n) => n.body === AI_NEW, 5000, "AI edit applied");
  });

  await runTest("AI edit apply refuses to overwrite a note changed since the proposal", async () => {
    const id = await noteIdByTitle("ai-target");
    // Reset the note to the proposal's base.
    const base = await serverNote(id);
    await page.request.put(`${baseURL}/api/notes/${id}`, {
      data: { title: base.title, tags: base.tags, body: AI_OLD, aliases: base.aliases ?? [] },
    });
    await openAiProposal();
    // Another writer (CLI / other window) changes the note meanwhile.
    const outside = "edited elsewhere while the diff was open";
    await page.request.put(`${baseURL}/api/notes/${id}`, {
      data: { title: base.title, tags: base.tags, body: outside, aliases: base.aliases ?? [] },
    });
    await page.locator('[data-testid="diff-apply"]').click();
    await page
      .locator('[data-testid="diff-apply-error"]')
      .waitFor({ state: "visible", timeout: 5000 });
    const snap = await serverNote(id);
    assert(snap.body === outside, `stale apply overwrote the newer body: ${snap.body}`);
    await page.locator('[data-testid="diff-reject"]').click();
    await page
      .locator('[data-testid="diff-review"]')
      .waitFor({ state: "hidden", timeout: 3000 });
  });

  await runTest("palette quick action failure is shown and the palette can close", async () => {
    const fail = safeRoute(async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated action failure" }),
      });
    });
    await page.route("**/api/quick-actions/*/run", fail);
    try {
      await blurActive();
      await page.keyboard.press("Meta+Shift+P");
      const row = page.locator('[data-testid="palette-action-item"]').first();
      await row.waitFor({ state: "visible", timeout: 3000 });
      await row.click();
      const err = page.locator('[data-testid="palette-action-error"]');
      await err.waitFor({ state: "visible", timeout: 5000 });
      const text = (await err.textContent()) ?? "";
      assert(
        text.includes("simulated action failure"),
        `palette error should carry the backend detail — got "${text}"`,
      );
      await page.keyboard.press("Escape");
      await page
        .locator('[data-testid="palette-input"]')
        .waitFor({ state: "hidden", timeout: 3000 });
    } finally {
      await page.unroute("**/api/quick-actions/*/run", fail);
      await dismissDialogs();
    }
  });
} catch (e) {
  console.error("audit-frontend-core e2e failed:", e);
  process.exitCode = 1;
} finally {
  await teardown();
  exitAfter();
}
