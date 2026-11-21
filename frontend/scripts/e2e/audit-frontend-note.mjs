/**
 * Regression suite for the frontend-note audit batch (NoteView editor
 * data flow + header/editor satellites).
 *
 * Covers:
 *   - an in-flight autosave response must not roll back text typed
 *     while the PUT was in flight (editor value pushback)
 *   - a genuine server-side change still reaches a clean editor
 *   - tag removal / title rename racing the blur-flush autosave must
 *     land BOTH the body and the metadata on disk (serialized PUTs that
 *     always carry the editor's current body)
 *   - title input keeps the user's draft across background re-renders
 *   - F2 on the title doesn't also open a file-tree rename
 *   - tag input blur does not steal focus back from the editor
 *   - graph panel / focus mode surface fetch failures
 *   - New document / New template dialogs surface create failures
 *   - image upload result survives an undo of its placeholder
 *   - slash-template {{title}} uses the title after an inline rename
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

const env = await setupTestEnv({
  notes: [
    { title: "race-body", body: "seed" },
    { title: "external", body: "orig" },
    { title: "race-tags", body: "tagbody", tags: ["keep", "drop"] },
    { title: "race-title", body: "titlebody" },
    { title: "title-reselect", body: "reselect body" },
    { title: "tag-blur", body: "blur body", tags: ["one"] },
    { title: "img-undo", body: "before" },
    { title: "slash-old", body: "slash body" },
    { title: "graph-note", body: "graph body" },
    { title: "tpl", body: "T={{title}}", folder: "_templates" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Route handlers outlive the test that installed them (delayed
 *  requests still in flight at unroute time); a late continue /
 *  fulfill on an already-settled route must not crash the suite. */
function safeRoute(handler) {
  return async (route) => {
    try {
      await handler(route);
    } catch {
      // route already handled / page torn down
    }
  };
}

async function clickRow(title) {
  await page.locator('[data-testid="activity-bar-notes"]').click();
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const row = page
    .locator(".group")
    .filter({ hasText: new RegExp(`^${escaped}$`) })
    .first();
  await row.waitFor({ state: "visible", timeout: 3000 });
  await row.click();
  await page
    .locator('[data-testid="note-title"]')
    .filter({ hasText: title })
    .waitFor({ state: "visible", timeout: 3000 });
  await page
    .locator('[data-testid="markdown-editor"] .cm-content')
    .waitFor({ state: "visible", timeout: 3000 });
}

function editor() {
  return page.locator('[data-testid="markdown-editor"] .cm-content');
}

async function editorText() {
  return page.evaluate(() => {
    const lines = document.querySelectorAll(
      '[data-testid="markdown-editor"] .cm-content .cm-line',
    );
    return Array.from(lines)
      .map((l) => l.textContent ?? "")
      .join("\n");
  });
}

async function focusEditorEnd() {
  await editor().click();
  await page.keyboard.press("Meta+End");
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

async function waitFor(pred, timeoutMs, label) {
  const t0 = Date.now();
  let last;
  while (Date.now() - t0 < timeoutMs) {
    last = await pred();
    if (last) return last;
    await sleep(100);
  }
  throw new Error(`timed out waiting for ${label}`);
}

async function waitForServer(id, pred, timeoutMs, label) {
  let snapshot = null;
  try {
    await waitFor(
      async () => {
        snapshot = await serverNote(id);
        return pred(snapshot);
      },
      timeoutMs,
      label,
    );
  } catch {
    throw new Error(
      `timed out waiting for ${label}; server has ${JSON.stringify({
        title: snapshot?.title,
        tags: snapshot?.tags,
        body: snapshot?.body,
      })}`,
    );
  }
  return snapshot;
}

async function dispatchPaste(b64) {
  await page.evaluate(async (b64) => {
    const target = document.querySelector(
      '[data-testid="markdown-editor"] .cm-content',
    );
    if (!target) throw new Error("editor not found");
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const file = new File([new Blob([bytes], { type: "image/png" })], "pasted.png", {
      type: "image/png",
    });
    const dt = new DataTransfer();
    dt.items.add(file);
    target.dispatchEvent(
      new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }),
    );
  }, b64);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("graph panel + focus mode surface /api/graph failures", async () => {
    const failGraph = safeRoute(async (route) => {
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated graph failure" }),
      });
    });
    await page.route("**/api/graph", failGraph);
    try {
      await clickRow("graph-note");
      await page.locator('[data-testid="rail-tab-graph"]').click();
      const panelErr = page.locator('[data-testid="graph-panel-error"]');
      await panelErr.waitFor({ state: "visible", timeout: 8000 });
      const text = (await panelErr.textContent()) ?? "";
      assert(
        text.includes("simulated graph failure"),
        `panel error should carry the backend detail — got "${text}"`,
      );
      await page.keyboard.press("Meta+Shift+G");
      const focus = page.locator('[data-testid="graph-focus-mode"]');
      await focus.waitFor({ state: "visible", timeout: 3000 });
      await page
        .locator('[data-testid="graph-focus-error"]')
        .waitFor({ state: "visible", timeout: 8000 });
      await page.keyboard.press("Escape");
      await focus.waitFor({ state: "hidden", timeout: 3000 });
    } finally {
      await page.unroute("**/api/graph", failGraph);
    }
    // Retry from the panel recovers once the backend is healthy again.
    await page.locator('[data-testid="graph-panel-retry"]').click();
    await page
      .locator('[data-testid="graph-panel-error"]')
      .waitFor({ state: "hidden", timeout: 5000 });
    await page.locator('[data-testid="rail-tab-backlinks"]').click();
  });

  await runTest(
    "in-flight autosave response does not roll back text typed meanwhile",
    async () => {
      await clickRow("race-body");
      const id = await noteIdByTitle("race-body");
      let puts = 0;
      const slowPut = safeRoute(async (route) => {
        if (route.request().method() !== "PUT") return route.continue();
        puts += 1;
        const resp = await route.fetch();
        await sleep(3000);
        await route.fulfill({ response: resp });
      });
      await page.route(`**/api/notes/${id}`, slowPut);
      try {
        await focusEditorEnd();
        await page.keyboard.type(" one");
        await waitFor(() => puts >= 1, 4000, "first autosave PUT");
        await page.keyboard.type(" two");
        // First response lands ~3 s after it was sent; the second PUT
        // (if any) cannot have landed yet.
        await page.waitForTimeout(3400);
        const text = await editorText();
        assert(
          text === "seed one two",
          `editor must keep text typed during the in-flight save — got "${text}"`,
        );
        await waitForServer(
          id,
          (n) => n.body === "seed one two",
          12000,
          "server body to include the in-flight keystrokes",
        );
        const finalText = await editorText();
        assert(finalText === "seed one two", `editor final text — got "${finalText}"`);
      } finally {
        await page.unroute(`**/api/notes/${id}`, slowPut);
      }
    },
  );

  await runTest("a genuine server-side change still reaches a clean editor", async () => {
    await clickRow("external");
    const id = await noteIdByTitle("external");
    // Outline panel's note query is stale after 10 s → mounting it
    // refetches QK.note(id), which is how sync / AI-apply / merge
    // results reach an open note.
    await page.waitForTimeout(10500);
    const current = await serverNote(id);
    const put = await page.request.put(`${baseURL}/api/notes/${id}`, {
      data: {
        title: current.title,
        tags: current.tags,
        body: "changed elsewhere",
        aliases: current.aliases ?? [],
      },
    });
    assert(put.ok(), `external PUT ok — got ${put.status()}`);
    await page.locator('[data-testid="rail-tab-outline"]').click();
    await waitFor(
      async () => (await editorText()) === "changed elsewhere",
      5000,
      "editor to adopt the external body",
    );
    await page.locator('[data-testid="rail-tab-backlinks"]').click();
  });

  await runTest(
    "removing a tag right after typing keeps both the body and the tag change",
    async () => {
      await clickRow("race-tags");
      const id = await noteIdByTitle("race-tags");
      let held = false;
      const holdFirstPut = safeRoute(async (route) => {
        if (route.request().method() === "PUT" && !held) {
          held = true;
          await sleep(1500);
        }
        await route.continue();
      });
      await page.route(`**/api/notes/${id}`, holdFirstPut);
      try {
        await focusEditorEnd();
        await page.keyboard.type(" typed");
        await page
          .locator('[data-testid="tag-chip-remove"][data-tag="drop"]')
          .click();
        const final = await waitForServer(
          id,
          (n) =>
            n.body === "tagbody typed" &&
            JSON.stringify(n.tags) === JSON.stringify(["keep"]),
          8000,
          "server to hold typed body + tag removal",
        );
        // Stay settled: a late response must not resurrect the old state.
        await page.waitForTimeout(1500);
        const again = await serverNote(id);
        assert(
          again.body === final.body &&
            JSON.stringify(again.tags) === JSON.stringify(["keep"]),
          `server state regressed after settle — got ${JSON.stringify(again)}`,
        );
        const chips = await page
          .locator('[data-testid="tag-chip"]')
          .evaluateAll((els) => els.map((e) => e.getAttribute("data-tag")));
        assert(
          JSON.stringify(chips) === JSON.stringify(["keep"]),
          `chip strip shows ${JSON.stringify(chips)}`,
        );
        const text = await editorText();
        assert(text === "tagbody typed", `editor text — got "${text}"`);
      } finally {
        await page.unroute(`**/api/notes/${id}`, holdFirstPut);
      }
    },
  );

  await runTest(
    "renaming the title right after typing keeps both the body and the new title",
    async () => {
      await clickRow("race-title");
      const id = await noteIdByTitle("race-title");
      let held = false;
      const holdFirstPut = safeRoute(async (route) => {
        if (route.request().method() === "PUT" && !held) {
          held = true;
          await sleep(1500);
        }
        await route.continue();
      });
      await page.route(`**/api/notes/${id}`, holdFirstPut);
      try {
        await focusEditorEnd();
        await page.keyboard.type(" typed");
        await page.locator('[data-testid="note-title"]').click();
        const input = page.locator('[data-testid="title-edit-input"]');
        await input.waitFor({ state: "visible", timeout: 2000 });
        await input.fill("renamed-title");
        await page.keyboard.press("Enter");
        await waitForServer(
          id,
          (n) => n.title === "renamed-title" && n.body === "titlebody typed",
          8000,
          "server to hold new title + typed body",
        );
        await page.waitForTimeout(1500);
        const again = await serverNote(id);
        assert(
          again.title === "renamed-title" && again.body === "titlebody typed",
          `server state regressed after settle — got ${JSON.stringify(again)}`,
        );
      } finally {
        await page.unroute(`**/api/notes/${id}`, holdFirstPut);
      }
    },
  );

  await runTest("title input keeps the draft across background re-renders", async () => {
    await clickRow("title-reselect");
    await focusEditorEnd();
    await page.keyboard.type(" x");
    // Clicking the h1 blurs the editor → flush save → saving / saved /
    // idle re-renders of NoteView while the title input is open.
    await page.locator('[data-testid="note-title"]').click();
    const input = page.locator('[data-testid="title-edit-input"]');
    await input.waitFor({ state: "visible", timeout: 2000 });
    // Collapse the initial select-all to the end (End doesn't on macOS).
    await page.keyboard.press("ArrowRight");
    await page.keyboard.type("abc");
    await page.waitForTimeout(1800);
    await page.keyboard.type("d");
    const value = await input.inputValue();
    assert(
      value === "title-reselectabcd",
      `title draft must survive re-renders — got "${value}"`,
    );
    await page.keyboard.press("Escape");
  });

  await runTest("F2 on the note title opens only the title editor", async () => {
    await clickRow("title-reselect");
    const h1 = page.locator('[data-testid="note-title"]');
    await h1.focus();
    await page.keyboard.press("F2");
    const input = page.locator('[data-testid="title-edit-input"]');
    await input.waitFor({ state: "visible", timeout: 2000 });
    const open = await page.locator('input[data-rename-input="true"]').count();
    assert(open === 1, `exactly one rename input expected (title) — got ${open}`);
    await page.keyboard.press("Escape");
    const left = await page.locator('input[data-rename-input="true"]').count();
    assert(left === 0, `Esc closes the title editor, nothing left open — got ${left}`);
  });

  await runTest("tag input blur does not steal focus back from the editor", async () => {
    await clickRow("tag-blur");
    await page.locator('[data-testid="tag-add-button"]').first().click();
    const input = page.locator('[data-testid="tag-add-input"]');
    await input.waitFor({ state: "visible", timeout: 2000 });
    await input.type("half");
    await focusEditorEnd();
    await page.waitForTimeout(400);
    const inEditor = await page.evaluate(() => {
      const a = document.activeElement;
      return !!a && !!a.closest('[data-testid="markdown-editor"]');
    });
    assert(inEditor, "focus must stay in the editor after leaving the tag input");
    await page.keyboard.type(" zz");
    const text = await editorText();
    assert(text === "blur body zz", `keystrokes must land in the editor — got "${text}"`);
    const inputVisible = await input.isVisible().catch(() => false);
    assert(!inputVisible, "tag input should close after blur");
  });

  await runTest("image upload result survives an undo of its placeholder", async () => {
    await clickRow("img-undo");
    const slowUpload = safeRoute(async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await sleep(1500);
      await route.continue();
    });
    await page.route("**/api/attachments", slowUpload);
    try {
      await focusEditorEnd();
      await dispatchPaste(PNG_BASE64);
      await waitFor(
        async () => (await editorText()).includes("uploading"),
        2000,
        "upload placeholder",
      );
      await page.keyboard.press("Meta+Z");
      await waitFor(
        async () => !(await editorText()).includes("uploading"),
        2000,
        "placeholder removed by undo",
      );
      await waitFor(
        async () => /_attachments\//.test(await editorText()),
        5000,
        "uploaded image reference to be inserted",
      );
    } finally {
      await page.unroute("**/api/attachments", slowUpload);
    }
  });

  await runTest("slash-template {{title}} uses the title after an inline rename", async () => {
    await clickRow("slash-old");
    await page.locator('[data-testid="note-title"]').click();
    const input = page.locator('[data-testid="title-edit-input"]');
    await input.waitFor({ state: "visible", timeout: 2000 });
    await input.fill("slash-new");
    await page.keyboard.press("Enter");
    await page
      .locator('[data-testid="note-title"]')
      .filter({ hasText: "slash-new" })
      .waitFor({ state: "visible", timeout: 3000 });
    await focusEditorEnd();
    await page.keyboard.press("Enter");
    await page.keyboard.type("/", { delay: 30 });
    await page
      .locator(".cm-tooltip-autocomplete")
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page.keyboard.type("tpl", { delay: 30 });
    await page.waitForTimeout(300);
    await page.keyboard.press("Enter");
    await waitFor(
      async () => /T=slash-/.test(await editorText()),
      4000,
      "template insertion",
    );
    const text = await editorText();
    assert(/T=slash-new/.test(text), `{{title}} must be the current title — got "${text}"`);
  });

  await runTest("New document dialog shows the create failure", async () => {
    const failCreate = safeRoute(async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated create conflict" }),
      });
    });
    await page.route("**/api/notes/new", failCreate);
    try {
      await page.locator('[data-testid="activity-bar-notes"]').click();
      await page.locator('button[aria-label="New note"]').click();
      const dialog = page.locator('[data-testid="new-document-dialog"]');
      await dialog.waitFor({ state: "visible", timeout: 3000 });
      await page.locator('[data-testid="new-document-title"]').fill("will fail");
      await page.locator('[data-testid="new-document-submit"]').click();
      const err = page.locator('[data-testid="new-document-error"]');
      await err.waitFor({ state: "visible", timeout: 3000 });
      const text = (await err.textContent()) ?? "";
      assert(
        text.includes("simulated create conflict"),
        `error should carry the backend detail — got "${text}"`,
      );
      assert(await dialog.isVisible(), "dialog stays open so the user can fix + retry");
      await page.locator('[data-testid="new-document-cancel"]').click();
      await dialog.waitFor({ state: "hidden", timeout: 3000 });
    } finally {
      await page.unroute("**/api/notes/new", failCreate);
      if (await page.locator('[data-testid="new-document-dialog"]').isVisible()) {
        await page.keyboard.press("Escape");
      }
    }
  });

  await runTest("New template dialog shows the create failure", async () => {
    const failCreate = safeRoute(async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "simulated template failure" }),
      });
    });
    await page.route("**/api/templates", failCreate);
    try {
      await page.locator('[data-testid="activity-bar-templates"]').click();
      await page.locator('[data-testid="template-tree-new-template"]').click();
      const dialog = page.locator('[data-testid="template-create-dialog"]');
      await dialog.waitFor({ state: "visible", timeout: 3000 });
      await page.locator('[data-testid="template-title"]').fill("will fail");
      await page.locator('[data-testid="template-create-submit"]').click();
      const err = page.locator('[data-testid="template-create-error"]');
      await err.waitFor({ state: "visible", timeout: 3000 });
      const text = (await err.textContent()) ?? "";
      assert(
        text.includes("simulated template failure"),
        `error should carry the backend detail — got "${text}"`,
      );
      await page.locator('[data-testid="template-create-cancel"]').click();
      await dialog.waitFor({ state: "hidden", timeout: 3000 });
    } finally {
      await page.unroute("**/api/templates", failCreate);
    }
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("audit-frontend-note e2e failed:", e);
  process.exitCode = 1;
  await teardown();
  exitAfter(0);
}
