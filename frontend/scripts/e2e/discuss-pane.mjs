// E2E: Phase 3 Stage 4 P1 — note-anchored discussion pane.
//
// The pane is the Cursor-style "chat about this note": opens beside the
// NoteView, anchored to the note you're looking at. The happy LLM
// answer needs a real model, so it's covered by pytest with a stub
// (tests/test_web_note_chat.py); this suite covers the deterministic
// surface — pane opens beside the note, shows the anchored title, input
// works, the user message echoes — plus the failure branch: with the
// fixture's stub api_key the LLM call fails, so the pane must surface an
// informed error (or a streamed reply), never a silent stall.

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    {
      title: "RAG Notes",
      body: "RAG retrieves relevant chunks, then generates an answer.",
    },
  ],
  folders: [],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("opening a note enables the discuss button", async () => {
    // Select the seeded note from the file tree.
    await page
      .locator(".group")
      .filter({ hasText: "RAG Notes" })
      .first()
      .click();
    // The header discuss button is disabled until a note is selected.
    const btn = page.locator('[data-testid="header-discuss-button"]');
    await btn.waitFor({ state: "visible", timeout: 3000 });
    // Auto-waits for enabled; throws if it never enables.
    await btn.click();
  });

  await runTest("pane opens beside the note, anchored to its title", async () => {
    const pane = page.locator('[data-testid="discuss-pane"]');
    await pane.waitFor({ state: "visible", timeout: 3000 });
    const anchor = page.locator('[data-testid="discuss-anchor-title"]');
    const anchorText = await anchor.innerText();
    assert(
      anchorText.includes("RAG Notes"),
      `pane anchored to the note title: got "${anchorText}"`,
    );
    // Composer present.
    await page
      .locator('[data-testid="discuss-input"]')
      .waitFor({ state: "visible", timeout: 1000 });
  });

  await runTest("sending echoes the user message immediately", async () => {
    const input = page.locator('[data-testid="discuss-input"]');
    await input.click();
    await page.keyboard.type("what is this note about?");
    await page.locator('[data-testid="discuss-send"]').click();
    const userMsg = page
      .locator('[data-testid="discuss-message-user"]')
      .first();
    await userMsg.waitFor({ state: "visible", timeout: 3000 });
    const txt = await userMsg.innerText();
    assert(
      txt.includes("what is this note about?"),
      `user message echoed: got "${txt}"`,
    );
  });

  await runTest("pane responds — reply or informed error, no silent stall", async () => {
    // Fixture uses a stub api_key, so the real LLM call fails; the pane
    // must surface an error event. Accept a streamed reply too in case
    // the env ever has a working model.
    await Promise.race([
      page
        .locator('[data-testid="discuss-message-assistant"]')
        .waitFor({ state: "visible", timeout: 12000 }),
      page
        .locator('[data-testid="discuss-error"]')
        .waitFor({ state: "visible", timeout: 12000 }),
    ]).catch(() => {});
    const replied = await page
      .locator('[data-testid="discuss-message-assistant"]')
      .count();
    const errored = await page
      .locator('[data-testid="discuss-error"]')
      .count();
    assert(
      replied + errored > 0,
      "pane must show a reply or an error (no silent stall)",
    );
  });

  await runTest("A5: stop button aborts an in-flight stream", async () => {
    // Hold the stream open so the streaming state is observable, then
    // stop it. (route stays pending until we abort client-side.)
    await page.route("**/api/chat/note/*/stream", async (route) => {
      await new Promise((r) => setTimeout(r, 8000));
      try {
        await route.fulfill({ status: 200, body: "" });
      } catch {
        /* request already aborted by the stop button — expected */
      }
    });
    const input = page.locator('[data-testid="discuss-input"]');
    await input.click();
    await page.keyboard.type("a held question");
    await page.locator('[data-testid="discuss-send"]').click();
    // While the request hangs, the send button becomes a stop control.
    const stop = page.locator('[data-testid="discuss-stop"]');
    await stop.waitFor({ state: "visible", timeout: 3000 });
    await stop.click();
    // After abort: back to idle — stop gone, send usable again.
    await page
      .locator('[data-testid="discuss-send"]')
      .waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await stop.count()) === 0,
      "stop control gone after aborting the stream",
    );
    await page.unroute("**/api/chat/note/*/stream");
  });

  // ---------- P3 / P4: AI proposes a diff → review → accept/reject ----
  // The proposal needs the LLM, so we mock /propose-edit at the network
  // boundary for a deterministic diff. The ACCEPT write goes to the
  // REAL backend (PUT /api/notes), so this exercises the actual atomic
  // save end-to-end.

  await runTest("P3/P4: 改这篇 shows a diff; 放弃 leaves the note unchanged", async () => {
    await page.route("**/api/chat/note/*/propose-edit", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          note_id: "x",
          old_body: "RAG retrieves relevant chunks, then generates an answer.",
          new_body:
            "RAG retrieves relevant chunks, reranks them, then generates an answer.",
          changed: true,
          reason: "",
        }),
      }),
    );
    const input = page.locator('[data-testid="discuss-input"]');
    await input.click();
    await page.keyboard.type("note that it reranks");
    await page.locator('[data-testid="discuss-propose"]').click();
    await page
      .locator('[data-testid="diff-review"]')
      .waitFor({ state: "visible", timeout: 4000 });
    await page
      .locator('button[aria-label="接受这一块改动"]')
      .first()
      .waitFor({ state: "visible", timeout: 1000 });
    const diffText = await page.locator('[data-testid="diff-review"]').innerText();
    assert(
      !diffText.includes("Accept") && !diffText.includes("Reject"),
      `chunk controls should not leak English labels: got "${diffText}"`,
    );
    // 放弃 → diff dismissed, note untouched.
    await page.locator('[data-testid="diff-reject"]').click();
    await page.waitForTimeout(300);
    assert(
      (await page.locator('[data-testid="diff-review"]').count()) === 0,
      "diff dismissed after 放弃",
    );
    const tree = await (await page.request.get(`${baseURL}/api/tree`)).json();
    const noteId = tree.notes[0].id;
    const nf = await (
      await page.request.get(`${baseURL}/api/notes/${noteId}`)
    ).json();
    assert(
      !nf.body.includes("reranks"),
      `放弃 must not write to the note: body=${JSON.stringify(nf.body)}`,
    );
  });

  await runTest("P4: 应用 writes the accepted edit through the real save", async () => {
    const input = page.locator('[data-testid="discuss-input"]');
    await input.click();
    await page.keyboard.type("note that it reranks");
    await page.locator('[data-testid="discuss-propose"]').click();
    await page
      .locator('[data-testid="diff-review"]')
      .waitFor({ state: "visible", timeout: 4000 });
    await page.locator('[data-testid="diff-apply"]').click();
    await page
      .locator('[data-testid="diff-review"]')
      .waitFor({ state: "detached", timeout: 4000 })
      .catch(() => {});
    await page.waitForTimeout(500);
    const tree = await (await page.request.get(`${baseURL}/api/tree`)).json();
    const noteId = tree.notes[0].id;
    const nf = await (
      await page.request.get(`${baseURL}/api/notes/${noteId}`)
    ).json();
    assert(
      nf.body.includes("reranks"),
      `应用 must persist the accepted body: got ${JSON.stringify(nf.body)}`,
    );
  });

  await runTest("A6: conversation persists across pane close/reopen", async () => {
    await page.route("**/api/chat/note/*/stream", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"reply_chunk","text":"PERSIST_REPLY_X"}\n\n' +
          'data: {"type":"turn_done","final_text":"PERSIST_REPLY_X"}\n\n',
      }),
    );
    const input = page.locator('[data-testid="discuss-input"]');
    await input.click();
    await page.keyboard.type("记住这个标记");
    await page.locator('[data-testid="discuss-send"]').click();
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "PERSIST_REPLY_X" })
      .first()
      .waitFor({ state: "visible", timeout: 4000 });
    // Close the pane …
    await page.locator('[data-testid="discuss-close"]').click();
    await page.waitForTimeout(200);
    assert(
      (await page.locator('[data-testid="discuss-pane"]').count()) === 0,
      "pane closed",
    );
    // … reopen on the same note → conversation restored from localStorage.
    await page.locator('[data-testid="header-discuss-button"]').click();
    await page
      .locator('[data-testid="discuss-pane"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="discuss-message-user"]')
      .filter({ hasText: "记住这个标记" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "PERSIST_REPLY_X" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page.unroute("**/api/chat/note/*/stream");
  });

  await runTest("close button dismisses the pane, leaving the note", async () => {
    await page.locator('[data-testid="discuss-close"]').click();
    await page.waitForTimeout(300);
    const count = await page.locator('[data-testid="discuss-pane"]').count();
    assert(count === 0, "pane removed from the DOM after close");
    // NoteView still mounted (we didn't tear down the note column).
    const editor = await page.locator(".cm-editor").count();
    assert(editor > 0, "NoteView editor still present after closing pane");
  });

  await runTest("no unexpected console errors", () => {
    // The stub-key LLM failure travels in-stream (200 response), so it
    // should not produce console errors. Keep this strict.
    assertConsoleClean(env);
  });
} finally {
  await teardown();
}

exitAfter();
