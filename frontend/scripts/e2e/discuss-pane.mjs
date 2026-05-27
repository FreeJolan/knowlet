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
  expectFocused,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    {
      title: "RAG Notes",
      body: "RAG retrieves relevant chunks, then generates an answer.",
    },
    {
      title: "Second Note",
      body: "This second note should keep its own chat state.",
    },
    {
      title: "Third Note",
      body: "A third note for accepting proposed edits.",
    },
    {
      title: "Fourth Note",
      body: "A fourth note for checking calibration reports.",
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

  await runTest("recommended question stays clickable and sends a fuller honest prompt", async () => {
    await page.route("**/api/chat/note/*/check", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          note_id: "x",
          summary: "No concrete issues found.",
          findings: [],
        }),
      }),
    );
    const chip = page.locator('[data-testid="discuss-suggestion-check"]');
    await chip.waitFor({ state: "visible", timeout: 3000 });
    const label = await chip.innerText();
    assert(
      !label.includes("查这篇") && !label.includes("改这篇"),
      `suggestion label should describe the action, got "${label}"`,
    );
    try {
      await page.setViewportSize({ width: 600, height: 900 });
      await page.waitForTimeout(300);
      const resizedChip = page.locator('[data-testid="discuss-suggestion-check"]');
      await resizedChip.waitFor({ state: "visible", timeout: 3000 });
      const geometry = await resizedChip.evaluate((el) => {
        const box = el.getBoundingClientRect();
        const pane = el.closest('[data-testid="discuss-pane"]')?.getBoundingClientRect();
        const top = document.elementFromPoint(
          box.left + box.width / 2,
          box.top + box.height / 2,
        );
        return {
          chipRight: box.right,
          paneRight: pane?.right ?? 0,
          paneWidth: pane?.width ?? 0,
          hit: top === el || el.contains(top),
        };
      });
      assert(
        geometry.paneWidth >= 176,
        `discuss pane should keep a usable narrow-width floor: ${JSON.stringify(geometry)}`,
      );
      assert(
        geometry.chipRight <= geometry.paneRight + 1,
        `suggestion chip should stay inside the pane at narrow width: ${JSON.stringify(geometry)}`,
      );
      assert(geometry.hit, "suggestion chip center should be clickable at narrow width");
      await resizedChip.click();
      const sent = page
        .locator('[data-testid="discuss-message-user"]')
        .filter({ hasText: "帮我看看这篇笔记是否有不对的地方" })
        .first();
      await sent.waitFor({ state: "visible", timeout: 3000 });
      await page
        .locator('[data-testid="discuss-message-assistant"]')
        .filter({ hasText: "No concrete issues found." })
        .first()
        .waitFor({ state: "visible", timeout: 3000 });
      await expectFocused(
        page,
        page.locator('[data-testid="discuss-input"]'),
        "input should regain focus after a suggested check finishes",
      );
    } finally {
      await page.setViewportSize({ width: 1400, height: 900 });
      await page.unroute("**/api/chat/note/*/check");
    }
  });

  await runTest("assistant messages render GitHub-flavored Markdown", async () => {
    await page.route("**/api/chat/note/*/stream", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"reply_chunk","text":"| 项 | 结论 |\\n| --- | --- |\\n| RAG | grounded |"}\n\n' +
          'data: {"type":"turn_done","final_text":"done"}\n\n',
      }),
    );
    const input = page.locator('[data-testid="discuss-input"]');
    await input.fill("return a table");
    await page.locator('[data-testid="discuss-send"]').click();
    await page
      .locator('[data-testid="discuss-message-assistant"] table')
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page.unroute("**/api/chat/note/*/stream");
  });

  await runTest("switching notes does not interrupt or cross-wire streaming", async () => {
    await page.route("**/api/chat/note/*/stream", async (route) => {
      const noteId = route.request().url().match(/\/note\/([^/]+)\/stream/)?.[1] ?? "";
      const body = await route.request().postDataJSON();
      if (body.text.includes("background stream")) {
        await new Promise((r) => setTimeout(r, 500));
        await route.fulfill({
          status: 200,
          contentType: "text/event-stream",
          body:
            'data: {"type":"reply_chunk","text":"A_BACKGROUND_DONE"}\n\n' +
            'data: {"type":"turn_done","final_text":"A_BACKGROUND_DONE"}\n\n',
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          `data: {"type":"reply_chunk","text":"reply for ${noteId}"}\n\n` +
          'data: {"type":"turn_done","final_text":"ok"}\n\n',
      });
    });
    await page.locator('[data-testid="discuss-input"]').fill("background stream");
    await page.locator('[data-testid="discuss-send"]').click();
    await page
      .locator(".group")
      .filter({ hasText: "Second Note" })
      .first()
      .click();
    await page.waitForTimeout(800);
    assert(
      (await page.locator('[data-testid="discuss-message-assistant"]').filter({ hasText: "A_BACKGROUND_DONE" }).count()) === 0,
      "Second Note should not receive Note A's streamed chunks",
    );
    await page
      .locator(".group")
      .filter({ hasText: "RAG Notes" })
      .first()
      .click();
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "A_BACKGROUND_DONE" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page.unroute("**/api/chat/note/*/stream");
  });

  await runTest("user scroll-up disables forced autoscroll during streaming", async () => {
    await page.route("**/api/chat/note/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: Array.from({ length: 60 }, (_, i) =>
          `data: {"type":"reply_chunk","text":"line ${i}\\n\\n"}\n\n`,
        ).join("") + 'data: {"type":"turn_done","final_text":"done"}\n\n',
      });
    });
    const input = page.locator('[data-testid="discuss-input"]');
    await input.fill("long answer please");
    await page.locator('[data-testid="discuss-send"]').click();
    const messages = page.locator('[data-testid="discuss-messages"]');
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "line 20" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await messages.evaluate((el) => {
      el.scrollTop = 0;
      el.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await page.waitForTimeout(250);
    const distanceFromBottom = await messages.evaluate(
      (el) => el.scrollHeight - el.scrollTop - el.clientHeight,
    );
    assert(
      distanceFromBottom > 40,
      `user scroll-up should keep the pane away from bottom, distance=${distanceFromBottom}`,
    );
    await page.unroute("**/api/chat/note/*/stream");
  });

  await runTest("sending echoes the user message immediately", async () => {
    const input = page.locator('[data-testid="discuss-input"]');
    await input.click();
    await page.keyboard.type("what is this note about?");
    await page.locator('[data-testid="discuss-send"]').click();
    const userMsg = page
      .locator('[data-testid="discuss-message-user"]')
      .filter({ hasText: "what is this note about?" })
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
    await page
      .locator(".group")
      .filter({ hasText: "Second Note" })
      .first()
      .click();
    await page.route("**/api/chat/note/*/propose-edit", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          note_id: "x",
          old_body: "This second note should keep its own chat state.",
          new_body:
            "This second note should keep its own chat state, with clearer wording.",
          changed: true,
          reason: "",
        }),
      }),
    );
    await page.locator('[data-testid="discuss-suggestion-propose"]').click();
    await page
      .locator('[data-testid="diff-review"]')
      .waitFor({ state: "visible", timeout: 4000 });
    await page
      .locator('[data-testid="discuss-message-user"]')
      .filter({ hasText: "请帮我基于这篇笔记提出一版更清晰" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
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
    const noteId = tree.notes.find((n) => n.title === "Second Note").id;
    const nf = await (
      await page.request.get(`${baseURL}/api/notes/${noteId}`)
    ).json();
    assert(
      !nf.body.includes("clearer wording"),
      `放弃 must not write to the note: body=${JSON.stringify(nf.body)}`,
    );
  });

  await runTest("P4: 应用 writes the accepted edit through the real save", async () => {
    await page
      .locator(".group")
      .filter({ hasText: "Third Note" })
      .first()
      .click();
    await page.locator('[data-testid="discuss-suggestion-propose"]').click();
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
    const noteId = tree.notes.find((n) => n.title === "Third Note").id;
    const nf = await (
      await page.request.get(`${baseURL}/api/notes/${noteId}`)
    ).json();
    assert(
      nf.body.includes("clearer wording"),
      `应用 must persist the accepted body: got ${JSON.stringify(nf.body)}`,
    );
  });

  await runTest("D1/D2: 查这篇 shows a report and fix enters diff review", async () => {
    await page
      .locator(".group")
      .filter({ hasText: "Fourth Note" })
      .first()
      .click();
    await page.route("**/api/chat/note/*/check", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          note_id: "x",
          summary: "One omission found.",
          findings: [
            {
              severity: "medium",
              paragraph: 1,
              quote: "RAG retrieves relevant chunks",
              finding: "The note omits reranking.",
              why: "The standard answer says reranking happens before generation.",
              suggestion: "Mention reranking before generation.",
              fix_instruction: "Add reranking between retrieval and generation.",
              confidence: 0.82,
            },
          ],
        }),
      }),
    );
    await page.route("**/api/chat/note/*/propose-edit", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          note_id: "x",
          old_body:
            "RAG retrieves relevant chunks, reranks them, then generates an answer.",
          new_body:
            "RAG retrieves relevant chunks, reranks them carefully, then generates an answer.",
          changed: true,
          reason: "",
        }),
      }),
    );
    await page.locator('[data-testid="discuss-suggestion-check"]').click();
    await page
      .locator('[data-testid="check-note-report"]')
      .waitFor({ state: "visible", timeout: 4000 });
    const reportText = await page.locator('[data-testid="check-note-report"]').innerText();
    assert(reportText.includes("omits reranking"), `report text: ${reportText}`);
    assert(reportText.includes("paragraph 1"), `report points to paragraph: ${reportText}`);

    await page.locator('[data-testid="check-note-fix-0"]').click();
    await page
      .locator('[data-testid="diff-review"]')
      .waitFor({ state: "visible", timeout: 4000 });
    await page.locator('[data-testid="diff-reject"]').click();
    await page.unroute("**/api/chat/note/*/check");
    await page.unroute("**/api/chat/note/*/propose-edit");
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
