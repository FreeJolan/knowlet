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
    let checkCalled = false;
    let proposeCalled = false;
    let streamedPrompt = "";
    await page.route("**/api/chat/note/*/check", (route) => {
      checkCalled = true;
      return route.fulfill({ status: 500, body: "check endpoint should not be used" });
    });
    await page.route("**/api/chat/note/*/propose-edit", (route) => {
      proposeCalled = true;
      return route.fulfill({ status: 500, body: "propose endpoint should not be used" });
    });
    await page.route("**/api/chat/note/*/stream", async (route) => {
      const body = await route.request().postDataJSON();
      streamedPrompt = body.text;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"reply_chunk","text":"SUGGESTED_STREAM_REPLY"}\n\n' +
          'data: {"type":"turn_done","final_text":"SUGGESTED_STREAM_REPLY"}\n\n',
      });
    });
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
        .filter({ hasText: "SUGGESTED_STREAM_REPLY" })
        .first()
        .waitFor({ state: "visible", timeout: 3000 });
      assert(
        streamedPrompt.includes("帮我看看这篇笔记是否有不对的地方"),
        `suggestion should send the full prompt through the chat stream: ${streamedPrompt}`,
      );
      assert(!checkCalled, "suggestion should not call the check-note endpoint");
      assert(!proposeCalled, "suggestion should not call the propose-edit endpoint");
      await expectFocused(
        page,
        page.locator('[data-testid="discuss-input"]'),
        "input should regain focus after a suggested check finishes",
      );
    } finally {
      await page.setViewportSize({ width: 1400, height: 900 });
      await page.unroute("**/api/chat/note/*/check");
      await page.unroute("**/api/chat/note/*/propose-edit");
      await page.unroute("**/api/chat/note/*/stream");
    }
  });

  await runTest("reset starts a fresh conversation for the current note only", async () => {
    const reset = page.locator('[data-testid="discuss-reset"]');
    await reset.waitFor({ state: "visible", timeout: 3000 });
    await reset.click();
    assert(
      (await page
        .locator('[data-testid="discuss-message-user"]')
        .filter({ hasText: "帮我看看这篇笔记是否有不对的地方" })
        .count()) === 0,
      "reset clears the current note's visible chat history",
    );
    await page
      .locator('[data-testid="discuss-suggestion-check"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="discuss-close"]').click();
    await page.locator('[data-testid="header-discuss-button"]').click();
    await page
      .locator('[data-testid="discuss-suggestion-check"]')
      .waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await page
        .locator('[data-testid="discuss-message-user"]')
        .filter({ hasText: "帮我看看这篇笔记是否有不对的地方" })
        .count()) === 0,
      "reset removes persisted chat history for this note",
    );

    await page.route("**/api/chat/note/*/stream", async (route) => {
      const body = await route.request().postDataJSON();
      const text = body.text.includes("second keep")
        ? "SECOND_KEEP"
        : "RAG_THROWAWAY";
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          `data: {"type":"reply_chunk","text":"${text}"}\n\n` +
          `data: {"type":"turn_done","final_text":"${text}"}\n\n`,
      });
    });
    await page
      .locator(".group")
      .filter({ hasText: "Second Note" })
      .first()
      .click();
    await page.locator('[data-testid="discuss-input"]').fill("second keep");
    await page.locator('[data-testid="discuss-send"]').click();
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "SECOND_KEEP" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });

    await page
      .locator(".group")
      .filter({ hasText: "RAG Notes" })
      .first()
      .click();
    await page.locator('[data-testid="discuss-input"]').fill("rag throwaway");
    await page.locator('[data-testid="discuss-send"]').click();
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "RAG_THROWAWAY" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="discuss-reset"]').click();

    await page
      .locator(".group")
      .filter({ hasText: "Second Note" })
      .first()
      .click();
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "SECOND_KEEP" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="discuss-reset"]').click();
    await page
      .locator('[data-testid="discuss-suggestion-check"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator(".group")
      .filter({ hasText: "RAG Notes" })
      .first()
      .click();
    await page.unroute("**/api/chat/note/*/stream");
  });

  await runTest("chat uses right-side markdown user bubbles and left-side assistant turns", async () => {
    const reset = page.locator('[data-testid="discuss-reset"]');
    if (await reset.isEnabled()) await reset.click();
    await page.route("**/api/chat/note/*/stream", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          {
            type: "tool_call",
            id: "call_layout",
            name: "search_notes",
            arguments: { query: "RAG", limit: 1 },
          },
          {
            type: "tool_result",
            id: "call_layout",
            name: "search_notes",
            payload: { results: [{ title: "RAG Notes", id: "n1" }] },
          },
          {
            type: "reply_chunk",
            text: "**Found** one useful note.\n\n| Note | Why |\n| --- | --- |\n| RAG | grounded |",
          },
          { type: "turn_done", final_text: "done" },
        ]
          .map((event) => `data: ${JSON.stringify(event)}\n\n`)
          .join(""),
      }),
    );
    await page
      .locator('[data-testid="discuss-input"]')
      .fill("**User asks**\n\n- with markdown");
    await page.locator('[data-testid="discuss-send"]').click();

    const userBubble = page
      .locator('[data-testid="discuss-user-bubble"]')
      .filter({ hasText: "User asks" })
      .first();
    await userBubble.waitFor({ state: "visible", timeout: 3000 });
    await userBubble.locator("strong").filter({ hasText: "User asks" }).waitFor({
      state: "visible",
      timeout: 3000,
    });
    await userBubble.locator("li").filter({ hasText: "with markdown" }).waitFor({
      state: "visible",
      timeout: 3000,
    });

    const assistant = page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "Found" })
      .first();
    await assistant.locator("strong").filter({ hasText: "Found" }).waitFor({
      state: "visible",
      timeout: 3000,
    });
    await assistant.locator("table").waitFor({ state: "visible", timeout: 3000 });

    const tracePanel = page.locator('[data-testid="discuss-trace-panel"]').first();
    await tracePanel.waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await tracePanel.evaluate((el) => !el.open)) === true,
      "completed tool trace should auto-collapse once the final answer is visible",
    );
    await page.locator('[data-testid="discuss-trace-toggle"]').first().click();
    await page
      .locator('[data-testid="tool-trace-search_notes"]')
      .first()
      .waitFor({ state: "visible", timeout: 3000 });

    const assistantText = (await assistant.innerText()).trim();
    assert(
      !assistantText.startsWith("AI"),
      `assistant turn should not need a visible AI label: "${assistantText}"`,
    );
    const userText = (
      await page.locator('[data-testid="discuss-message-user"]').first().innerText()
    ).trim();
    assert(
      !userText.startsWith("你"),
      `user turn should rely on right-side bubble layout, not a visible label: "${userText}"`,
    );

    const geometry = await page.evaluate(() => {
      const messages = document.querySelector('[data-testid="discuss-messages"]');
      const user = document.querySelector('[data-testid="discuss-user-bubble"]');
      const assistantTurn = document.querySelector(
        '[data-testid="discuss-message-assistant"]',
      );
      const trace = document.querySelector('[data-testid="discuss-trace-panel"]');
      const box = (el) => el?.getBoundingClientRect();
      const mb = box(messages);
      const ub = box(user);
      const ab = box(assistantTurn);
      const tb = box(trace);
      return {
        messageRight: mb?.right ?? 0,
        userLeft: ub?.left ?? 0,
        userRight: ub?.right ?? 0,
        assistantLeft: ab?.left ?? 0,
        traceLeft: tb?.left ?? 0,
      };
    });
    assert(
      geometry.userLeft > geometry.assistantLeft + 40,
      `user bubble should sit to the right of assistant turns: ${JSON.stringify(geometry)}`,
    );
    assert(
      geometry.messageRight - geometry.userRight < 24,
      `user bubble should align to the right edge: ${JSON.stringify(geometry)}`,
    );
    assert(
      geometry.traceLeft < geometry.userLeft,
      `tool trace should stay in the assistant/left lane: ${JSON.stringify(geometry)}`,
    );

    await page.locator('[data-testid="discuss-reset"]').click();
    await page.unroute("**/api/chat/note/*/stream");
  });

  await runTest("tool calls and results render as visible trace items", async () => {
    let requestCount = 0;
    const histories = [];
    await page.route("**/api/chat/note/*/stream", async (route) => {
      requestCount += 1;
      const body = await route.request().postDataJSON();
      histories.push(body.history ?? []);
      if (requestCount === 1) {
        return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"tool_call","id":"call_1","name":"search_notes","arguments":{"query":"RAG","limit":1}}\n\n' +
          'data: {"type":"tool_result","id":"call_1","name":"search_notes","payload":{"results":[{"title":"RAG Notes","id":"n1"}]}}\n\n' +
          'data: {"type":"reply_chunk","text":"工具查完了。"}\n\n' +
          'data: {"type":"turn_done","final_text":"工具查完了。"}\n\n',
        });
      }
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"reply_chunk","text":"SECOND_AFTER_TOOL"}\n\n' +
          'data: {"type":"turn_done","final_text":"SECOND_AFTER_TOOL"}\n\n',
      });
    });
    await page.locator('[data-testid="discuss-input"]').fill("use tool trace");
    await page.locator('[data-testid="discuss-send"]').click();
    const tracePanel = page.locator('[data-testid="discuss-trace-panel"]').first();
    await tracePanel.waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await tracePanel.innerText()).includes("已完成 1 个工具"),
      "completed tool trace should summarize the hidden process",
    );
    await page.locator('[data-testid="discuss-trace-toggle"]').first().click();
    const trace = page.locator('[data-testid="tool-trace-search_notes"]').first();
    await trace.waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await trace.innerText()).includes("search_notes"),
      "tool trace should show the tool name",
    );
    assert(
      (await trace.innerText()).includes("RAG Notes"),
      "tool trace should summarize the tool result",
    );
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "工具查完了" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="discuss-input"]').fill("after tool trace");
    await page.locator('[data-testid="discuss-send"]').click();
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "SECOND_AFTER_TOOL" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    assert(
      histories[1].every((m) => m.role === "user" || m.role === "assistant"),
      `follow-up history must not send tool trace messages: ${JSON.stringify(histories[1])}`,
    );
    await page.locator('[data-testid="discuss-reset"]').click();
    await page.unroute("**/api/chat/note/*/stream");
  });

  await runTest("natural check request can show current-note calibration trace", async () => {
    await page.route("**/api/chat/note/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"tool_call","id":"check_1","name":"check_current_note","arguments":{"instruction":"检查错漏"}}\n\n' +
          'data: {"type":"tool_result","id":"check_1","name":"check_current_note","payload":{"note_id":"n1","title":"RAG Notes","summary":"发现一处高风险事实错误。","count":1,"findings":[{"severity":"high","paragraph":1,"finding":"RAG 不是把全部笔记塞进 prompt。"}]}}\n\n' +
          'data: {"type":"reply_chunk","text":"我检查完了，主要问题是 RAG 的定义写反了。"}\n\n' +
          'data: {"type":"turn_done","final_text":"我检查完了，主要问题是 RAG 的定义写反了。"}\n\n',
      });
    });
    await page.locator('[data-testid="discuss-input"]').fill("帮我检查这篇有没有错漏");
    await page.locator('[data-testid="discuss-send"]').click();
    const tracePanel = page.locator('[data-testid="discuss-trace-panel"]').first();
    await tracePanel.waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="discuss-trace-toggle"]').first().click();
    const trace = page.locator('[data-testid="tool-trace-check_current_note"]').first();
    await trace.waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await trace.innerText()).includes("check_current_note"),
      "calibration should be rendered as a tool trace",
    );
    assert(
      (await trace.innerText()).includes("1 个发现"),
      "calibration trace should summarize findings instead of raw JSON",
    );
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "RAG 的定义写反了" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="discuss-reset"]').click();
    await page.unroute("**/api/chat/note/*/stream");
  });

  await runTest("current-note edit proposal tool opens the diff review", async () => {
    await page
      .locator(".group")
      .filter({ hasText: "RAG Notes" })
      .first()
      .click();
    const reset = page.locator('[data-testid="discuss-reset"]');
    if (await reset.isEnabled()) await reset.click();
    await page.route("**/api/chat/note/*/stream", async (route) => {
      const noteId = new URL(route.request().url()).pathname.match(
        /\/api\/chat\/note\/([^/]+)\/stream$/,
      )?.[1];
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"tool_call","id":"edit_1","name":"propose_current_note_edit","arguments":{"instruction":"最小改写"}}\n\n' +
          `data: {"type":"tool_result","id":"edit_1","name":"propose_current_note_edit","payload":{"kind":"note_edit_proposal","note_id":"${noteId}","title":"RAG Notes","changed":true,"summary":"已生成可审阅的修改提案。","old_body":"RAG retrieves relevant chunks, then generates an answer.","new_body":"RAG retrieves relevant chunks, reranks them, then generates an answer."}}\n\n` +
          'data: {"type":"reply_chunk","text":"我准备好了一版可审阅的修改提案。"}\n\n' +
          'data: {"type":"turn_done","final_text":"我准备好了一版可审阅的修改提案。"}\n\n',
      });
    });
    await page
      .locator('[data-testid="discuss-input"]')
      .fill("请给这篇笔记提出一版可审阅的最小改写");
    await page.locator('[data-testid="discuss-send"]').click();
    await page
      .locator('[data-testid="diff-review"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="diff-label-original"]')
      .filter({ hasText: "当前正文" })
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="diff-label-proposal"]')
      .filter({ hasText: "AI 提案" })
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="diff-editor"]')
      .filter({ hasText: "reranks" })
      .waitFor({ state: "visible", timeout: 3000 });
    const diffLayout = await page
      .locator('[data-testid="diff-review"]')
      .evaluate((root) => {
        const editors = Array.from(root.querySelectorAll(".cm-mergeViewEditor")).map(
          (el) => {
            const rect = el.getBoundingClientRect();
            return {
              left: rect.left,
              right: rect.right,
              top: rect.top,
              width: rect.width,
            };
          },
        );
        return {
          count: editors.length,
          sameRow:
            editors.length === 2 && Math.abs(editors[0].top - editors[1].top) < 4,
          separated:
            editors.length === 2 && editors[0].right <= editors[1].left + 32,
          balanced:
            editors.length === 2 &&
            Math.abs(editors[0].width - editors[1].width) < 80,
        };
      });
    assert(
      diffLayout.count === 2 && diffLayout.sameRow && diffLayout.separated && diffLayout.balanced,
      `diff review should render two side-by-side panes: ${JSON.stringify(diffLayout)}`,
    );
    await page
      .locator('[data-testid="tool-trace-propose_current_note_edit"]')
      .first()
      .waitFor({ state: "attached", timeout: 3000 });
    await page.locator('[data-testid="diff-reject"]').click();
    await page
      .locator('[data-testid="markdown-editor"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="discuss-reset"]').click();
    await page.unroute("**/api/chat/note/*/stream");
  });

  await runTest("structured stream errors render as text instead of crashing", async () => {
    await page.route("**/api/chat/note/*/stream", (route) =>
      route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          "data: " +
          JSON.stringify({
            type: "error",
            message: {
              type: "literal_error",
              loc: ["body", "history", 0, "role"],
              msg: "Input should be 'user' or 'assistant'",
              input: "tool",
              ctx: { expected: "'user' or 'assistant'" },
            },
          }) +
          "\n\n",
      }),
    );
    await page.locator('[data-testid="discuss-input"]').fill("structured error");
    await page.locator('[data-testid="discuss-send"]').click();
    await page
      .locator('[data-testid="discuss-error"]')
      .filter({ hasText: "Input should be 'user' or 'assistant'" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="discuss-reset"]').click();
    await page.unroute("**/api/chat/note/*/stream");
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

  await runTest("sending shows a clear AI generation indicator before chunks arrive", async () => {
    await page.route("**/api/chat/note/*/stream", async (route) => {
      await new Promise((r) => setTimeout(r, 700));
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"reply_chunk","text":"INDICATOR_DONE"}\n\n' +
          'data: {"type":"turn_done","final_text":"INDICATOR_DONE"}\n\n',
      });
    });
    const input = page.locator('[data-testid="discuss-input"]');
    await input.fill("show me that generation started");
    await page.locator('[data-testid="discuss-send"]').click();
    const indicator = page.locator('[data-testid="discuss-generating"]').first();
    await indicator.waitFor({ state: "visible", timeout: 1000 });
    const label = await indicator.innerText();
    assert(
      label.includes("正在生成"),
      `generation indicator should explain the in-flight state, got "${label}"`,
    );
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "INDICATOR_DONE" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await page.locator('[data-testid="discuss-generating"]').count()) === 0,
      "generation indicator should disappear once the assistant has content",
    );
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

  await runTest("proposal recommendation also follows the normal chat stream", async () => {
    await page
      .locator(".group")
      .filter({ hasText: "Second Note" })
      .first()
      .click();
    let proposeEditCalled = false;
    let streamedPrompt = "";
    await page.route("**/api/chat/note/*/propose-edit", (route) => {
      proposeEditCalled = true;
      return route.fulfill({ status: 500, body: "propose endpoint should not be used" });
    });
    await page.route("**/api/chat/note/*/stream", async (route) => {
      const body = await route.request().postDataJSON();
      streamedPrompt = body.text;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"reply_chunk","text":"PROPOSE_SUGGESTION_REPLY"}\n\n' +
          'data: {"type":"turn_done","final_text":"PROPOSE_SUGGESTION_REPLY"}\n\n',
      });
    });
    const resetBeforeProposal = page.locator('[data-testid="discuss-reset"]');
    if (await resetBeforeProposal.isEnabled()) await resetBeforeProposal.click();
    await page
      .locator('[data-testid="discuss-suggestion-propose"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="discuss-suggestion-propose"]').click();
    await page
      .locator('[data-testid="discuss-message-user"]')
      .filter({ hasText: "请为这篇笔记生成一个可在 diff 中审阅的最小改写提案" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="discuss-message-assistant"]')
      .filter({ hasText: "PROPOSE_SUGGESTION_REPLY" })
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    assert(
      streamedPrompt.includes("请为这篇笔记生成一个可在 diff 中审阅的最小改写提案"),
      `proposal suggestion should send the full prompt through the chat stream: ${streamedPrompt}`,
    );
    assert(!proposeEditCalled, "proposal suggestion should not call propose-edit");
    await page.unroute("**/api/chat/note/*/propose-edit");
    await page.unroute("**/api/chat/note/*/stream");
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
