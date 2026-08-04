// E2E: AI chat composer sizing, long-form mode, and Markdown-friendly input.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { assert, assertConsoleClean, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const RAW_INFO_ID = "01C6TODAYRAWINFO000001";
const DRAFT_ID = "01C8COMPOSERDRAFT000001";

const NOTE_USER_URL =
  "https://links.example.test/note/user?surface=discuss#question";
const NOTE_ASSISTANT_URL =
  "https://links.example.test/note/assistant?surface=discuss#answer";
const RAW_USER_URL =
  "https://links.example.test/raw-info/user?surface=review#question";
const RAW_ASSISTANT_URL =
  "https://links.example.test/raw-info/assistant?surface=review#answer";
const DRAFT_USER_URL =
  "https://links.example.test/draft/user?surface=review#question";
const DRAFT_ASSISTANT_URL =
  "https://links.example.test/draft/assistant?surface=review#answer";

function chatFiller(label) {
  return Array.from(
    { length: 40 },
    (_, index) => `${label} context line ${index + 1} keeps the transcript scrollable.`,
  ).join("\n\n");
}

const rawInfo = {
  schema_version: 1,
  id: RAW_INFO_ID,
  source_id: "01C6COMPOSERCHATSOURCE01",
  source_name: "Composer Chat Feed",
  source_kind: "rss",
  item_key: "rss:composer-chat-links",
  title: "Composer chat link coverage",
  url: "https://source.example.test/composer-chat",
  published_at: null,
  fetched_at: new Date().toISOString(),
  summary: "A Raw Info item used to exercise links in the review chat.",
  key_points: ["User and assistant Markdown both render through ChatTranscript."],
  why_it_matters: "Every reachable chat surface should preserve its workspace.",
  suggested_tags: ["chat", "links"],
  confidence: "high",
  content_excerpt: "Raw Info chat link fixture.",
  status: "unprocessed",
  note_draft_id: null,
  note_id: null,
};

const env = await setupTestEnv({
  notes: [
    {
      title: "Composer Note",
      body: "A note used to exercise the discussion composer.",
    },
  ],
  folders: [],
  language: "en",
});
const { page, teardown } = env;

const rawInfoRoot = join(env.vaultDir, ".knowlet", "digest", "items");
mkdirSync(rawInfoRoot, { recursive: true });
writeFileSync(
  join(rawInfoRoot, `${RAW_INFO_ID}-composer-chat-link-coverage.json`),
  `${JSON.stringify(rawInfo, null, 2)}\n`,
  "utf8",
);

await page.addInitScript(() => {
  const opener = { calls: [] };
  globalThis.isTauri = true;
  window.__KNOWLET_OPENER_MOCK__ = opener;
  window.__TAURI_INTERNALS__ = {
    invoke: async (cmd, args = {}) => {
      if (cmd === "plugin:opener|open_url") {
        opener.calls.push({ cmd, args });
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

page.on("popup", (popup) => {
  void popup.close().catch(() => {});
});

async function resetOpenerMock() {
  await page.evaluate(() => {
    window.__KNOWLET_OPENER_MOCK__.calls.length = 0;
  });
}

async function openerCalls() {
  return page.evaluate(() => [...window.__KNOWLET_OPENER_MOCK__.calls]);
}

async function noteContextSnapshot() {
  return {
    noteTitle: (
      await page.locator('[data-testid="note-title"]').innerText()
    ).trim(),
    anchorTitle: (
      await page.locator('[data-testid="discuss-anchor-title"]').innerText()
    ).trim(),
    paneVisible: await page.locator('[data-testid="discuss-pane"]').isVisible(),
  };
}

async function reviewContextSnapshot() {
  const draftTitle = page.locator('[data-testid="digest-draft-title"]');
  return {
    rawTitle: (
      await page.locator('[data-testid="digest-review-current-title"]').innerText()
    ).trim(),
    rawSelected: await page
      .locator('[data-testid="digest-review-stage-tab-raw"]')
      .getAttribute("aria-selected"),
    draftSelected: await page
      .locator('[data-testid="digest-review-stage-tab-draft"]')
      .getAttribute("aria-selected"),
    draftTitle:
      (await draftTitle.count()) > 0 ? (await draftTitle.innerText()).trim() : null,
    workspaceVisible: await page
      .locator('[data-testid="digest-review-workspace"]')
      .isVisible(),
  };
}

function samePageContext(actualURL, expectedURL) {
  const actual = new URL(actualURL);
  const expected = new URL(expectedURL);
  return (
    actual.origin === expected.origin &&
    actual.pathname === expected.pathname &&
    actual.search === expected.search
  );
}

async function activateChatLink({
  link,
  expectedURL,
  transcript,
  messages,
  contextSnapshot,
  opensExternally,
  label,
}) {
  await link.waitFor({ state: "visible", timeout: 3000 });
  await link.evaluate((element) => {
    element.scrollIntoView({ block: "center" });
  });
  await page.waitForTimeout(50);

  const before = {
    pageURL: page.url(),
    messageCount: await messages.count(),
    transcriptText: await transcript.innerText(),
    scroll: await transcript.evaluate((element) => ({
      scrollTop: element.scrollTop,
      scrollHeight: element.scrollHeight,
      clientHeight: element.clientHeight,
    })),
    context: await contextSnapshot(),
  };
  assert(
    before.scroll.scrollHeight > before.scroll.clientHeight && before.scroll.scrollTop > 0,
    `${label}: link is activated from a meaningful non-zero transcript scroll position`,
  );

  await resetOpenerMock();
  await link.click();
  if (opensExternally) {
    await page.waitForFunction(
      (url) =>
        window.__KNOWLET_OPENER_MOCK__.calls.some(
          (call) => call.args?.url === url,
        ),
      expectedURL,
      { timeout: 1500, polling: 25 },
    );
  } else {
    await page.waitForTimeout(100);
  }

  const calls = await openerCalls();
  if (opensExternally) {
    assert(calls.length === 1, `${label}: opener called once, got ${JSON.stringify(calls)}`);
    assert(
      calls[0]?.args?.url === expectedURL,
      `${label}: opener receives the exact URL, got ${JSON.stringify(calls[0]?.args)}`,
    );
    assert(page.url() === before.pageURL, `${label}: Knowlet URL remains ${before.pageURL}`);
  } else {
    assert(calls.length === 0, `${label}: internal link never reaches the opener`);
    assert(
      samePageContext(page.url(), before.pageURL),
      `${label}: internal link stays in the current Knowlet page`,
    );
  }

  assert(
    (await messages.count()) === before.messageCount,
    `${label}: message count stays ${before.messageCount}`,
  );
  assert(
    (await transcript.innerText()) === before.transcriptText,
    `${label}: transcript content is unchanged`,
  );
  const afterScrollTop = await transcript.evaluate((element) => element.scrollTop);
  assert(
    Math.abs(afterScrollTop - before.scroll.scrollTop) <= 1,
    `${label}: transcript scrollTop stays ${before.scroll.scrollTop}, got ${afterScrollTop}`,
  );
  assert(
    JSON.stringify(await contextSnapshot()) === JSON.stringify(before.context),
    `${label}: selected note/item and review stage stay unchanged`,
  );

  if (!opensExternally && page.url() !== before.pageURL) {
    await page.evaluate((url) => window.history.replaceState(null, "", url), before.pageURL);
  }
}

async function exerciseRenderedMessageLinks({
  message,
  stem,
  label,
  externalURL,
  internalHash,
  transcript,
  messages,
  contextSnapshot,
}) {
  await activateChatLink({
    link: message.locator("a").filter({ hasText: `${stem} external` }),
    expectedURL: externalURL,
    transcript,
    messages,
    contextSnapshot,
    opensExternally: true,
    label: `${label} external link`,
  });
  await activateChatLink({
    link: message.locator("a").filter({ hasText: `${stem} internal` }),
    expectedURL: internalHash,
    transcript,
    messages,
    contextSnapshot,
    opensExternally: false,
    label: `${label} internal link`,
  });
}

async function openDiscussPane() {
  await page.goto(env.baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  await page
    .locator(".group")
    .filter({ hasText: "Composer Note" })
    .first()
    .click();
  await page.locator('[data-testid="header-discuss-button"]').click();
  await page
    .locator('[data-testid="discuss-pane"]')
    .waitFor({ state: "visible", timeout: 3000 });
}

async function moveCaretToEnd(locator) {
  await locator.evaluate((el) => {
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  });
}

try {
  await openDiscussPane();

  await runTest("composer defaults to a roomier height", async () => {
    const height = await page
      .locator('[data-testid="discuss-input"]')
      .evaluate((el) => el.getBoundingClientRect().height);
    assert(height >= 92, `composer input should default to a roomier height, got ${height}`);
  });

  await runTest("normal composer continues ordered Markdown lists on Enter", async () => {
    const input = page.locator('[data-testid="discuss-input"]');
    await input.fill("1. first\n2. second\n3. third");
    await input.click();
    await page.keyboard.press("Enter");
    const value = await input.inputValue();
    assert(
      value === "1. first\n2. second\n3. third\n4. ",
      `Enter at the end of an ordered list should continue numbering, got ${JSON.stringify(value)}`,
    );
  });

  await runTest("composer height can be increased by dragging the resize handle", async () => {
    const shell = page.locator('[data-testid="discuss-composer-shell"]');
    const handle = page.locator('[data-testid="discuss-composer-resize-handle"]');
    const before = await shell.evaluate((el) => el.getBoundingClientRect().height);
    const box = await handle.boundingBox();
    assert(box, "resize handle should have a bounding box");
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2, box.y - 80, { steps: 6 });
    await page.mouse.up();
    const after = await shell.evaluate((el) => el.getBoundingClientRect().height);
    assert(after >= before + 50, `dragging up should increase composer height: ${before} -> ${after}`);
  });

  await runTest("long-form popout preserves text and treats Enter as newline", async () => {
    const input = page.locator('[data-testid="discuss-input"]');
    await input.fill("1. one");
    await page.locator('[data-testid="discuss-longform-open"]').click();
    const dialog = page.locator('[data-testid="discuss-longform-dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    const longInput = page.locator('[data-testid="discuss-longform-input"]');
    await moveCaretToEnd(longInput);
    await page.keyboard.press("Enter");
    let value = await longInput.inputValue();
    assert(value === "1. one\n2. ", `long-form Enter should continue the list, got ${JSON.stringify(value)}`);
    await moveCaretToEnd(longInput);
    await page.keyboard.type("two");
    await moveCaretToEnd(longInput);
    await page.keyboard.press("Enter");
    value = await longInput.inputValue();
    assert(
      value === "1. one\n2. two\n3. ",
      `long-form should keep Markdown continuation without sending, got ${JSON.stringify(value)}`,
    );
    assert(
      (await page.locator('[data-testid="discuss-message-user"]').count()) === 0,
      "pressing Enter in long-form mode should not send a message",
    );
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "hidden", timeout: 3000 });
    const smallValue = await input.inputValue();
    assert(
      smallValue === "1. one\n2. two\n3. ",
      `closing long-form should copy text back to the compact input, got ${JSON.stringify(smallValue)}`,
    );
  });

  await runTest("clicking outside the long-form popout closes and keeps edits", async () => {
    await page.locator('[data-testid="discuss-longform-open"]').click();
    await page
      .locator('[data-testid="discuss-longform-input"]')
      .fill("outside close\nkeeps content");
    await page.mouse.click(20, 20);
    await page
      .locator('[data-testid="discuss-longform-dialog"]')
      .waitFor({ state: "hidden", timeout: 3000 });
    const value = await page.locator('[data-testid="discuss-input"]').inputValue();
    assert(
      value === "outside close\nkeeps content",
      `outside click should preserve long-form edits, got ${JSON.stringify(value)}`,
    );
  });

  await runTest("Discuss Note user and assistant links preserve the transcript context", async () => {
    const assistantMarkdown = [
      "NOTE_ASSISTANT_LINKS",
      chatFiller("note assistant"),
      `Review the [note assistant external](${NOTE_ASSISTANT_URL})`,
      "and keep the [note assistant internal](#note-assistant-internal) in Knowlet.",
    ].join(" ");
    await page.route("**/api/chat/note/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          `data: ${JSON.stringify({ type: "reply_chunk", text: assistantMarkdown })}\n\n` +
          `data: ${JSON.stringify({ type: "turn_done", final_text: assistantMarkdown })}\n\n`,
      });
    });

    try {
      const userMarkdown = [
        "NOTE_USER_LINKS",
        chatFiller("note user"),
        `Open the [note user external](${NOTE_USER_URL})`,
        "but keep the [note user internal](#note-user-internal) in Knowlet.",
      ].join(" ");
      await page.locator('[data-testid="discuss-input"]').fill(userMarkdown);
      await page.locator('[data-testid="discuss-send"]').click();

      const userMessage = page
        .locator('[data-testid="discuss-message-user"]')
        .filter({ hasText: "NOTE_USER_LINKS" })
        .first();
      const assistantMessage = page
        .locator('[data-testid="discuss-message-assistant"]')
        .filter({ hasText: "NOTE_ASSISTANT_LINKS" })
        .first();
      await assistantMessage.waitFor({ state: "visible", timeout: 3000 });

      const transcript = page.locator('[data-testid="discuss-messages"]');
      const messages = page.locator(
        '[data-testid="discuss-message-user"], [data-testid="discuss-message-assistant"]',
      );
      await exerciseRenderedMessageLinks({
        message: userMessage,
        stem: "note user",
        label: "Discuss Note user",
        externalURL: NOTE_USER_URL,
        internalHash: "#note-user-internal",
        transcript,
        messages,
        contextSnapshot: noteContextSnapshot,
      });
      await exerciseRenderedMessageLinks({
        message: assistantMessage,
        stem: "note assistant",
        label: "Discuss Note assistant",
        externalURL: NOTE_ASSISTANT_URL,
        internalHash: "#note-assistant-internal",
        transcript,
        messages,
        contextSnapshot: noteContextSnapshot,
      });
    } finally {
      await page.unroute("**/api/chat/note/*/stream");
    }
  });

  await runTest("Raw Info and Draft stage chats preserve messages, scroll, and review context", async () => {
    await page.route("**/api/chat/raw-info/*/stream", async (route) => {
      const text = route.request().postDataJSON().text;
      const assistantMarkdown = text.includes("DRAFT_USER_LINKS")
        ? [
            "DRAFT_ASSISTANT_LINKS",
            chatFiller("draft assistant"),
            `Use the [draft assistant external](${DRAFT_ASSISTANT_URL})`,
            "and keep the [draft assistant internal](#draft-assistant-internal) local.",
          ].join(" ")
        : [
            "RAW_ASSISTANT_LINKS",
            chatFiller("raw assistant"),
            `Use the [raw assistant external](${RAW_ASSISTANT_URL})`,
            "and keep the [raw assistant internal](#raw-assistant-internal) local.",
          ].join(" ");
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          `data: ${JSON.stringify({ type: "reply_chunk", text: assistantMarkdown })}\n\n` +
          `data: ${JSON.stringify({ type: "turn_done", final_text: assistantMarkdown })}\n\n`,
      });
    });
    await page.route(`**/api/digest/items/${RAW_INFO_ID}/draft`, async (route) => {
      const now = new Date().toISOString();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          raw_info: {
            ...rawInfo,
            status: "drafted",
            note_draft_id: DRAFT_ID,
          },
          draft: {
            id: DRAFT_ID,
            title: "Composer Chat Draft",
            body: "## Draft\n\nA draft used to keep the review chat visible.",
            source: rawInfo.url,
            tags: ["chat", "links"],
            kind: "knowledge",
            folder: "research",
            task_id: null,
            created_at: now,
            updated_at: now,
            age_days: 0,
            is_stale: false,
            is_warn_age: false,
          },
          rationale: "The review conversation is ready for a draft.",
        }),
      });
    });

    try {
      await page.locator('[data-testid="discuss-close"]').click();
      await page.locator('[data-testid="header-digest-button"]').click();
      await page.locator('[data-testid="digest-focus-mode"]').waitFor({
        state: "visible",
        timeout: 3000,
      });
      await page.locator(`[data-testid="digest-card-${RAW_INFO_ID}"]`).click();
      await page.locator('[data-testid="digest-start-review"]').click();
      await page.locator('[data-testid="digest-review-workspace"]').waitFor({
        state: "visible",
        timeout: 3000,
      });
      assert(
        (await page
          .locator('[data-testid="digest-review-stage-tab-raw"]')
          .getAttribute("aria-selected")) === "true",
        "Raw Info stage starts selected",
      );

      const chatInput = page.locator('[data-testid="digest-review-chat-input"]');
      const transcript = page.locator('[data-testid="digest-review-chat"]');
      const messages = page.locator(
        '[data-testid="digest-review-message-user"], [data-testid="digest-review-message-assistant"]',
      );

      await chatInput.fill(
        [
          "RAW_USER_LINKS",
          chatFiller("raw user"),
          `Open the [raw user external](${RAW_USER_URL})`,
          "and keep the [raw user internal](#raw-user-internal) local.",
        ].join(" "),
      );
      await page.locator('[data-testid="digest-review-chat-send"]').click();
      const rawUserMessage = page
        .locator('[data-testid="digest-review-message-user"]')
        .filter({ hasText: "RAW_USER_LINKS" })
        .first();
      const rawAssistantMessage = page
        .locator('[data-testid="digest-review-message-assistant"]')
        .filter({ hasText: "RAW_ASSISTANT_LINKS" })
        .first();
      await rawAssistantMessage.waitFor({ state: "visible", timeout: 3000 });

      await exerciseRenderedMessageLinks({
        message: rawUserMessage,
        stem: "raw user",
        label: "Raw Info chat user",
        externalURL: RAW_USER_URL,
        internalHash: "#raw-user-internal",
        transcript,
        messages,
        contextSnapshot: reviewContextSnapshot,
      });
      await exerciseRenderedMessageLinks({
        message: rawAssistantMessage,
        stem: "raw assistant",
        label: "Raw Info chat assistant",
        externalURL: RAW_ASSISTANT_URL,
        internalHash: "#raw-assistant-internal",
        transcript,
        messages,
        contextSnapshot: reviewContextSnapshot,
      });

      await page.locator('[data-testid="digest-settle-draft"]').click();
      await page.locator('[data-testid="digest-draft-title"]').waitFor({
        state: "visible",
        timeout: 3000,
      });
      assert(
        (await page
          .locator('[data-testid="digest-review-stage-tab-draft"]')
          .getAttribute("aria-selected")) === "true",
        "Draft stage is selected after draft generation",
      );

      await chatInput.fill(
        [
          "DRAFT_USER_LINKS",
          chatFiller("draft user"),
          `Open the [draft user external](${DRAFT_USER_URL})`,
          "and keep the [draft user internal](#draft-user-internal) local.",
        ].join(" "),
      );
      await page.locator('[data-testid="digest-review-chat-send"]').click();
      const draftUserMessage = page
        .locator('[data-testid="digest-review-message-user"]')
        .filter({ hasText: "DRAFT_USER_LINKS" })
        .first();
      const draftAssistantMessage = page
        .locator('[data-testid="digest-review-message-assistant"]')
        .filter({ hasText: "DRAFT_ASSISTANT_LINKS" })
        .first();
      await draftAssistantMessage.waitFor({ state: "visible", timeout: 3000 });

      await exerciseRenderedMessageLinks({
        message: draftUserMessage,
        stem: "draft user",
        label: "Draft stage chat user",
        externalURL: DRAFT_USER_URL,
        internalHash: "#draft-user-internal",
        transcript,
        messages,
        contextSnapshot: reviewContextSnapshot,
      });
      await exerciseRenderedMessageLinks({
        message: draftAssistantMessage,
        stem: "draft assistant",
        label: "Draft stage chat assistant",
        externalURL: DRAFT_ASSISTANT_URL,
        internalHash: "#draft-assistant-internal",
        transcript,
        messages,
        contextSnapshot: reviewContextSnapshot,
      });
    } finally {
      await page.unroute("**/api/chat/raw-info/*/stream");
      await page.unroute(`**/api/digest/items/${RAW_INFO_ID}/draft`);
    }
  });

  await runTest("no unexpected console errors", () => {
    assertConsoleClean(env);
  });
} finally {
  await teardown();
}

exitAfter();
