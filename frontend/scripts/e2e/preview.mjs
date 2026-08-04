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
      body: [
        "# Big heading",
        "",
        "Some **bold** text and a [link](https://example.com).",
        "",
        "[mouse external](https://example.com/search?q=knowlet&view=full#result-2)",
        "",
        "[keyboard external](http://example.org/reference?from=preview#keyboard)",
        "",
        "[empty]() [unsafe](javascript:alert%281%29) [heading target](#big-heading) [relative](docs/help) [[target]] [[missing target]] #project-tag",
        "",
        ...Array.from(
          { length: 48 },
          (_, index) => `Long preview line ${index + 1} keeps scroll state observable.`,
        ),
      ].join("\n"),
    },
    { title: "target", body: "# Internal target\n\nReached inside Knowlet." },
  ],
  language: "en",
});
const { page, browser, baseURL, teardown } = env;

await page.addInitScript(() => {
  const opener = {
    calls: [],
    rejectRemaining: 0,
    responses: [],
  };
  globalThis.isTauri = true;
  window.__KNOWLET_OPENER_MOCK__ = opener;
  window.__TAURI_INTERNALS__ = {
    invoke: async (cmd, args = {}) => {
      if (cmd === "plugin:opener|open_url") {
        opener.calls.push({ cmd, args });
        const response = opener.responses.shift();
        // Keep the first request in flight long enough for a rapid second
        // activation to exercise the product's duplicate suppression.
        await new Promise((resolve) => setTimeout(resolve, response?.delayMs ?? 80));
        if (response?.reject || opener.rejectRemaining > 0) {
          if (!response?.reject) opener.rejectRemaining -= 1;
          throw new Error("mock system opener rejected the URL");
        }
        return null;
      }
      if (cmd === "plugin:event|listen") return 1;
      return null;
    },
    transformCallback: () => 0,
    unregisterCallback: () => {},
    runCallback: () => {},
    callbacks: new Map(),
    convertFileSrc: (filePath) => filePath,
  };
});

// The pre-feature implementation still uses target=_blank. Close those
// temporary pages immediately so a red opener assertion cannot leak tabs or
// external navigation into later cases in this shared-page suite.
page.on("popup", (popup) => {
  void popup.close();
});

async function resetOpenerMock({ rejectNext = false } = {}) {
  await page.evaluate((shouldReject) => {
    const opener = window.__KNOWLET_OPENER_MOCK__;
    opener.calls.length = 0;
    opener.rejectRemaining = shouldReject ? 1 : 0;
    opener.responses.length = 0;
  }, rejectNext);
}

async function setOpenerResponses(responses) {
  await page.evaluate((nextResponses) => {
    window.__KNOWLET_OPENER_MOCK__.responses = nextResponses;
  }, responses);
}

async function openerCalls() {
  return page.evaluate(() => [...window.__KNOWLET_OPENER_MOCK__.calls]);
}

async function workspaceSnapshot() {
  return {
    url: page.url(),
    selectedNoteId: await page
      .locator('[data-testid="tab"][data-active="true"]')
      .getAttribute("data-note-id"),
    title: await page.locator('[data-testid="note-title"]').first().textContent(),
    mode: await page
      .locator('[data-testid="view-mode-toggle"] button[data-active="true"]')
      .getAttribute("data-mode"),
  };
}

async function assertWorkspaceUnchanged(before, label) {
  const after = await workspaceSnapshot();
  assert(after.url === before.url, `${label}: current page stays at ${before.url}`);
  assert(
    after.selectedNoteId === before.selectedNoteId,
    `${label}: selected note stays ${before.selectedNoteId}, got ${after.selectedNoteId}`,
  );
  assert(after.title === before.title, `${label}: selected note title stays ${before.title}`);
  assert(after.mode === before.mode, `${label}: view mode stays ${before.mode}`);
}

async function noteBody(noteId) {
  const response = await page.request.get(
    `${baseURL}/api/notes/${encodeURIComponent(noteId)}`,
  );
  assert(response.ok(), `note ${noteId} can be read from the backend`);
  return (await response.json()).body;
}

async function vaultNoteBodies() {
  const response = await page.request.get(`${baseURL}/api/tree`);
  assert(response.ok(), "vault tree can be read from the backend");
  const tree = await response.json();
  const noteIds = [];
  const walk = (node) => {
    for (const note of node.notes ?? []) noteIds.push(note.id);
    for (const folder of node.folders ?? []) walk(folder);
  };
  walk(tree);
  const entries = await Promise.all(
    noteIds.sort().map(async (noteId) => [noteId, await noteBody(noteId)]),
  );
  return Object.fromEntries(entries);
}

function captureBackendMutations() {
  const requests = [];
  const listener = (request) => {
    if (
      request.url().startsWith(`${baseURL}/api/`) &&
      !["GET", "HEAD", "OPTIONS"].includes(request.method())
    ) {
      requests.push(`${request.method()} ${request.url()}`);
    }
  };
  page.on("request", listener);
  return {
    requests,
    stop: () => page.off("request", listener),
  };
}

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

  await runTest("desktop preview click opens the exact URL once and keeps context", async () => {
    await clickRow("doc");
    await clickMode("preview");
    await resetOpenerMock();
    const before = await workspaceSnapshot();
    const expected = "https://example.com/search?q=knowlet&view=full#result-2";
    const link = page
      .locator(`[data-testid="markdown-preview"] a[href="${expected}"]`)
      .first();
    await link.waitFor({ state: "visible", timeout: 3000 });
    await link.click();
    await page.waitForTimeout(160);

    const calls = await openerCalls();
    assert(
      calls.length === 1,
      `one system-browser handoff after click — got ${JSON.stringify(calls)}`,
    );
    assert(calls[0]?.cmd === "plugin:opener|open_url", "uses the Tauri opener command");
    assert(calls[0]?.args?.url === expected, `query and hash stay intact — got ${calls[0]?.args?.url}`);
    await assertWorkspaceUnchanged(before, "external-link click");
  });

  await runTest("desktop preview keyboard activation opens the exact URL once", async () => {
    await clickRow("doc");
    await clickMode("preview");
    await resetOpenerMock();
    const before = await workspaceSnapshot();
    const expected = "http://example.org/reference?from=preview#keyboard";
    const link = page
      .locator(`[data-testid="markdown-preview"] a[href="${expected}"]`)
      .first();
    await link.focus();
    await page.keyboard.press("Enter");
    await page.waitForTimeout(160);

    const calls = await openerCalls();
    assert(
      calls.length === 1,
      `one system-browser handoff after Enter — got ${JSON.stringify(calls)}`,
    );
    assert(calls[0]?.args?.url === expected, `keyboard path preserves URL — got ${calls[0]?.args?.url}`);
    await assertWorkspaceUnchanged(before, "external-link keyboard activation");
  });

  await runTest("split-mode activation preserves buffered text, scroll, and backend state", async () => {
    await clickRow("doc");
    await clickMode("split");
    await resetOpenerMock();
    const before = await workspaceSnapshot();
    const noteId = before.selectedNoteId;
    assert(typeof noteId === "string" && noteId.length > 0, "selected note has an id");
    const serverBodyBefore = await noteBody(noteId);
    const marker = " buffered-external-link-state";
    const editor = page.locator('[data-testid="markdown-editor"] .cm-content');
    await editor.click();
    await page.keyboard.press("Meta+End");
    await page.keyboard.type(marker);
    await page.waitForTimeout(40);

    const preview = page.locator('[data-testid="markdown-preview"]');
    const scrollBefore = await preview.evaluate((element) => {
      const maxScroll = element.scrollHeight - element.clientHeight;
      if (maxScroll <= 0) throw new Error("preview needs enough content to scroll");
      element.scrollTop = Math.min(180, maxScroll);
      return element.scrollTop;
    });
    const link = preview
      .locator("a")
      .filter({ hasText: /^mouse external$/ })
      .first();
    const mutations = captureBackendMutations();
    try {
      await link.dispatchEvent("click", { button: 0 });
      await page.waitForTimeout(160);
    } finally {
      mutations.stop();
    }

    const calls = await openerCalls();
    assert(calls.length === 1, `buffered path opens once, got ${calls.length}`);
    assert(
      calls[0]?.args?.url ===
        "https://example.com/search?q=knowlet&view=full#result-2",
      "buffered path preserves the exact URL",
    );
    assert(
      (await editor.innerText()).includes(marker.trim()),
      "editor keeps buffered text after the handoff",
    );
    assert(
      (await preview.innerText()).includes(marker.trim()),
      "split preview keeps the same buffered text",
    );
    const scrollAfter = await preview.evaluate((element) => element.scrollTop);
    assert(
      Math.abs(scrollAfter - scrollBefore) <= 1,
      `preview scroll stays ${scrollBefore}, got ${scrollAfter}`,
    );
    assert(
      (await noteBody(noteId)) === serverBodyBefore,
      "external-link activation does not write the unsaved buffer",
    );
    assert(
      mutations.requests.length === 0,
      `external-link activation sends no backend mutation, got ${mutations.requests.join(", ")}`,
    );
    await assertWorkspaceUnchanged(before, "buffered split external-link activation");
    await page.waitForTimeout(900);
  });

  await runTest("ordinary browser fallback opens a safe new tab", async () => {
    const webContext = await browser.newContext({
      viewport: { width: 1000, height: 720 },
    });
    await webContext.route("https://example.com/**", async (route) => {
      await route.fulfill({ status: 200, contentType: "text/html", body: "browser fallback" });
    });
    const webPage = await webContext.newPage();
    try {
      await webPage.goto(baseURL, { waitUntil: "networkidle" });
      const expected = "https://example.com/browser-fallback?q=knowlet#safe";
      await webPage.locator("body").evaluate((body, href) => {
        const anchor = document.createElement("a");
        anchor.href = href;
        anchor.textContent = "web fallback proof";
        anchor.dataset.testid = "web-fallback-link";
        body.append(anchor);
      }, expected);
      const link = webPage.locator('[data-testid="web-fallback-link"]');
      const urlBefore = webPage.url();
      const [popup] = await Promise.all([
        webPage.waitForEvent("popup", { timeout: 3000 }),
        link.click(),
      ]);
      await popup.waitForLoadState("domcontentloaded");

      assert(webPage.url() === urlBefore, "web fallback keeps Knowlet in place");
      assert(popup.url() === expected, `web fallback keeps the exact URL, got ${popup.url()}`);
      assert((await link.getAttribute("target")) === "_blank", "web fallback sets target=_blank");
      const rel = (await link.getAttribute("rel"))?.split(/\s+/) ?? [];
      assert(rel.includes("noopener") && rel.includes("noreferrer"), "web fallback hardens rel");
      await popup.close();
    } finally {
      await webContext.close();
    }
  });

  await runTest("rapid repeated activation hands the URL to the opener only once", async () => {
    await clickRow("doc");
    await clickMode("preview");
    await resetOpenerMock();
    const before = await workspaceSnapshot();
    const link = page
      .locator('[data-testid="markdown-preview"] a')
      .filter({ hasText: /^mouse external$/ })
      .first();
    await link.dblclick({ delay: 10 });
    await page.waitForTimeout(200);

    const calls = await openerCalls();
    assert(
      calls.length === 1,
      `rapid double activation is de-duplicated — got ${JSON.stringify(calls)}`,
    );
    await assertWorkspaceUnchanged(before, "rapid external-link activation");
  });

  await runTest("rapid activation stays de-duplicated after the anchor remounts", async () => {
    await clickRow("doc");
    await clickMode("preview");
    await resetOpenerMock();
    const link = page
      .locator('[data-testid="markdown-preview"] a')
      .filter({ hasText: /^mouse external$/ })
      .first();
    await link.click();
    const replacement = page.locator('[data-testid="remounted-external-link"]');
    await link.evaluate((element) => {
      const clone = element.cloneNode(true);
      clone.dataset.testid = "remounted-external-link";
      element.replaceWith(clone);
    });
    await replacement.click();
    await page.waitForTimeout(180);

    const calls = await openerCalls();
    assert(
      calls.length === 1,
      `same rapid URL is de-duplicated across anchor remounts, got ${calls.length}`,
    );
  });

  await runTest("a stale opener failure cannot clear a newer activation", async () => {
    await clickRow("doc");
    await clickMode("preview");
    await resetOpenerMock();
    await setOpenerResponses([
      { delayMs: 420, reject: true },
      { delayMs: 10, reject: false },
    ]);
    const link = page
      .locator('[data-testid="markdown-preview"] a')
      .filter({ hasText: /^mouse external$/ })
      .first();

    await link.click();
    await page.waitForTimeout(320);
    await link.click();
    await page.waitForTimeout(145);

    const error = page.locator('[data-testid="external-link-error"]');
    assert(
      !(await error.isVisible()),
      "a superseded opener rejection does not surface a false failure",
    );
    await link.click();
    await page.waitForTimeout(50);
    const calls = await openerCalls();
    assert(
      calls.length === 2,
      `stale failure keeps the newer cooldown intact, got ${calls.length} calls`,
    );
  });

  await runTest("opener rejection shows an error and the same link can retry", async () => {
    await clickRow("doc");
    await clickMode("preview");
    await resetOpenerMock({ rejectNext: true });
    const before = await workspaceSnapshot();
    const link = page
      .locator('[data-testid="markdown-preview"] a')
      .filter({ hasText: /^mouse external$/ })
      .first();
    await link.click();

    const error = page.locator('[data-testid="external-link-error"]');
    await error.waitFor({ state: "visible", timeout: 1500 });
    const errorFloor = await error.evaluate((element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      const hit = document.elementFromPoint(
        rect.left + rect.width / 2,
        rect.top + rect.height / 2,
      );
      return {
        backgroundColor: style.backgroundColor,
        hitTestId: hit?.closest('[data-testid="external-link-error"]')?.getAttribute(
          "data-testid",
        ),
      };
    });
    assert(
      errorFloor.backgroundColor !== "rgba(0, 0, 0, 0)",
      `external-link failure notice is opaque, got ${errorFloor.backgroundColor}`,
    );
    assert(
      errorFloor.hitTestId === "external-link-error",
      `failure notice center is hit-testable, got ${errorFloor.hitTestId}`,
    );
    assert(
      await link.evaluate((element) => document.activeElement === element),
      "rejected external link keeps keyboard focus on the activated anchor",
    );
    await assertWorkspaceUnchanged(before, "rejected external-link activation");
    let calls = await openerCalls();
    assert(calls.length === 1, `rejected handoff is attempted once — got ${calls.length}`);

    await link.click();
    await page.waitForFunction(
      () => window.__KNOWLET_OPENER_MOCK__.calls.length === 2,
      null,
      { timeout: 1500, polling: 30 },
    );
    await error.waitFor({ state: "hidden", timeout: 1500 });
    calls = await openerCalls();
    assert(calls.length === 2, "retry makes exactly one new opener request");
    await assertWorkspaceUnchanged(before, "external-link retry");
  });

  await runTest("internal, tag, empty, and unsafe links never call the opener", async () => {
    await clickRow("doc");
    await clickMode("preview");
    await resetOpenerMock();
    const preview = page.locator('[data-testid="markdown-preview"]');
    const backendBefore = await vaultNoteBodies();
    const mutations = captureBackendMutations();
    try {
      const urlBeforeBoundaryClicks = page.url();
      await preview.locator("a").filter({ hasText: /^empty$/ }).click();
      await preview.locator("a").filter({ hasText: /^unsafe$/ }).click();
      assert((await openerCalls()).length === 0, "empty and unsafe links skip the native opener");
      assert(
        page.url() === urlBeforeBoundaryClicks,
        "empty and unsafe links keep the current webview URL unchanged",
      );

      const heading = preview.locator("#big-heading");
      assert((await heading.count()) === 1, "heading target resolves to an existing DOM id");
      const headingLink = preview.locator("a").filter({ hasText: /^heading target$/ });
      const headingScrollBefore = await headingLink.evaluate((element) => {
        const container = element.closest('[data-testid="markdown-preview"]');
        if (!(container instanceof HTMLElement)) throw new Error("preview container missing");
        container.scrollTop = Math.max(0, element.offsetTop - 40);
        return container.scrollTop;
      });
      await headingLink.dispatchEvent("click", { button: 0 });
      const headingScrollAfter = await preview.evaluate((element) => element.scrollTop);
      assert(
        Math.abs(headingScrollAfter - headingScrollBefore) <= 1,
        "the existing heading-link no-op keeps preview scroll stable",
      );
      await preview.locator("a").filter({ hasText: /^relative$/ }).click();
      await preview.locator("a.kn-wikilink").filter({ hasText: /^missing target$/ }).click();
      assert(
        page.url() === urlBeforeBoundaryClicks,
        "heading, relative, and missing-note targets stay in the current webview",
      );
      assert(
        (await openerCalls()).length === 0,
        "heading, relative, and missing-note targets skip the native opener",
      );

      await preview.evaluate((root) => {
        const download = document.createElement("a");
        download.href = "data:text/plain,knowlet-download-boundary";
        download.download = "knowlet-boundary.txt";
        download.dataset.testid = "preview-download-boundary";
        download.textContent = "download boundary";
        root.append(download);
      });
      const [download] = await Promise.all([
        page.waitForEvent("download", { timeout: 3000 }),
        page.locator('[data-testid="preview-download-boundary"]').click(),
      ]);
      assert(
        download.suggestedFilename() === "knowlet-boundary.txt",
        `download keeps its filename, got ${download.suggestedFilename()}`,
      );
      assert((await download.path()) !== null, "download completes through the browser path");
      assert((await openerCalls()).length === 0, "downloads stay outside the native opener");

      await preview.locator("a.kn-wikilink").filter({ hasText: /^target$/ }).click();
      await page.locator('[data-testid="note-title"]').filter({ hasText: /^target$/ }).waitFor({
        state: "visible",
        timeout: 3000,
      });
      assert((await openerCalls()).length === 0, "wikilink navigation stays inside Knowlet");

      await clickRow("doc");
      await clickMode("preview");
      await page.locator('[data-testid="markdown-preview"] a.kn-inline-tag').click();
      await page.locator('[data-testid="activity-bar-tags"]').waitFor({
        state: "visible",
        timeout: 1500,
      });
      assert((await openerCalls()).length === 0, "inline tag navigation stays inside Knowlet");

      assert(
        JSON.stringify(await vaultNoteBodies()) === JSON.stringify(backendBefore),
        "boundary links leave every backend note unchanged",
      );
      assert(
        mutations.requests.length === 0,
        `boundary links send no backend mutation, got ${mutations.requests.join(", ")}`,
      );
    } finally {
      mutations.stop();
    }

    // Restore the Files rail for the remaining shared-page checks.
    await page.locator('[data-testid="activity-bar-notes"]').click();
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
