// E2E: Stage C v2 C6 — Raw Info digest inbox.
//
// Digest no longer shows today/week draft tabs. It is a Raw Info inbox:
// read-only cards, grouping by time/source, pull status, and overflow guard.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

let builtOnce = false;

async function setupDigestEnv(seed) {
  if (builtOnce) process.env.SKIP_BUILD = "1";
  const env = await setupTestEnv({ notes: [], language: "en" });
  builtOnce = true;
  process.env.SKIP_BUILD = "1";
  seed?.(env.vaultDir);
  await env.page.goto(env.baseURL, { waitUntil: "networkidle" });
  return env;
}

function isoDaysAgo(days) {
  return new Date(Date.now() - days * 24 * 60 * 60 * 1000)
    .toISOString()
    .replace(/\.\d{3}Z$/, "Z");
}

function rawInfo(overrides) {
  return {
    schema_version: 1,
    id: overrides.id,
    source_id: overrides.source_id ?? "01C6SRCRESEARCH",
    source_name: overrides.source_name ?? "Research Feed",
    source_kind: overrides.source_kind ?? "rss",
    item_key: overrides.item_key ?? `rss:${overrides.id}`,
    title: overrides.title,
    url: overrides.url ?? `https://example.com/${overrides.id}`,
    published_at: overrides.published_at ?? null,
    fetched_at: overrides.fetched_at ?? isoDaysAgo(0),
    summary: overrides.summary ?? "A concise raw information summary.",
    key_points: overrides.key_points ?? ["first signal", "second signal"],
    why_it_matters: overrides.why_it_matters ?? "Useful for deciding what to review.",
    suggested_tags: overrides.suggested_tags ?? ["ai"],
    confidence: overrides.confidence ?? "medium",
    content_excerpt: overrides.content_excerpt ?? "Excerpt from the original item.",
    status: overrides.status ?? "unprocessed",
    note_draft_id: null,
    note_id: null,
  };
}

function writeRawInfos(vaultDir, items) {
  const root = join(vaultDir, ".knowlet", "digest", "items");
  mkdirSync(root, { recursive: true });
  for (const item of items) {
    const slug = item.title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    writeFileSync(
      join(root, `${item.id}-${slug}.json`),
      JSON.stringify(item, null, 2) + "\n",
      "utf8",
    );
  }
}

function seedThreeItems(vaultDir) {
  writeRawInfos(vaultDir, [
    rawInfo({
      id: "01C6TODAYRAWINFO000001",
      title: "Agent trace design",
      url: "https://example.com/agent-trace",
      fetched_at: isoDaysAgo(0),
      summary: "A note about making tool traces visible without mixing them into final answers.",
      key_points: ["tool trace is separate", "answer remains readable"],
      status: "unprocessed",
    }),
    rawInfo({
      id: "01C6YDAYRAWINFO0000002",
      title: "RSS normalization caveat",
      fetched_at: isoDaysAgo(1),
      summary: "RSS feeds can be thin, so each entry needs normalization before review.",
      status: "viewed",
    }),
    rawInfo({
      id: "01C6PROMPTRAWINFO00003",
      source_id: "01C6SRCPROMPT",
      source_name: "Prompt Watch",
      source_kind: "prompt",
      title: "Prompt source candidate",
      url: "https://example.com/prompt-candidate",
      fetched_at: isoDaysAgo(8),
      summary: "A model-generated candidate with an original link.",
      status: "discussed",
      suggested_tags: ["agents", "prompt-source"],
    }),
  ]);
}

function seedOverflow(vaultDir) {
  writeRawInfos(
    vaultDir,
    Array.from({ length: 201 }, (_, i) =>
      rawInfo({
        id: `01C6OVERFLOW${String(i).padStart(12, "0")}`,
        title: `Overflow item ${i + 1}`,
        fetched_at: isoDaysAgo(0),
        summary: "Pending overflow item.",
      }),
    ),
  );
}

let env = await setupDigestEnv(seedThreeItems);
try {
  const { page } = env;

  await runTest("digest opens Raw Info inbox without today/week tabs", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-focus-mode"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-period-today"]').count()) === 0,
      "today tab removed",
    );
    assert(
      (await page.locator('[data-testid="digest-period-week"]').count()) === 0,
      "week tab removed",
    );
    await page.locator('[data-testid="digest-group-time-today"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-card-01C6TODAYRAWINFO000001"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const detailBg = await page
      .locator('[data-testid="digest-detail"]')
      .evaluate((el) => getComputedStyle(el).backgroundColor);
    assert(detailBg !== "rgba(0, 0, 0, 0)", "detail panel background is opaque");
    const hitCard = await page
      .locator('[data-testid="digest-card-01C6TODAYRAWINFO000001"]')
      .evaluate((el) => {
        const rect = el.getBoundingClientRect();
        const hit = document.elementFromPoint(
          rect.left + rect.width / 2,
          rect.top + rect.height / 2,
        );
        return hit?.closest('[data-testid="digest-card-01C6TODAYRAWINFO000001"]')
          ?.getAttribute("data-testid");
      });
    assert(
      hitCard === "digest-card-01C6TODAYRAWINFO000001",
      "card center resolves to the card",
    );
  });

  await runTest("digest can group Raw Info by source", async () => {
    await page.locator('[data-testid="digest-group-mode-source"]').click();
    await page.locator('[data-testid="digest-group-source-research-feed"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-group-source-prompt-watch"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
  });

  await runTest("selected Raw Info renders read-only details", async () => {
    await page.locator('[data-testid="digest-card-01C6TODAYRAWINFO000001"]').click();
    const detail = await page.locator('[data-testid="digest-detail"]').textContent();
    assert(detail.includes("Agent trace design"), "detail shows title");
    assert(detail.includes("tool traces visible"), "detail shows summary");
    assert(detail.includes("tool trace is separate"), "detail shows key points");
    assert(detail.includes("https://example.com/agent-trace"), "detail shows original link");
    assert(
      (await page.locator('[data-testid="digest-action-save-reference"]').count()) === 0,
      "old draft action is gone from raw info inbox",
    );
  });

  await runTest("review mode opens as a full-screen workspace and supports raw info chat", async () => {
    await page.route("**/api/chat/raw-info/*/stream", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body:
          'data: {"type":"reply_chunk","text":"Review reply grounded in Raw Info."}\n\n' +
          'data: {"type":"turn_done","final_text":"Review reply grounded in Raw Info."}\n\n',
      });
    });
    await page.locator('[data-testid="digest-start-review"]').click();
    await page.locator('[data-testid="digest-review-workspace"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-review-backdrop"]').count()) === 0,
      "review mode is not a windowed backdrop",
    );
    await page.locator('[data-testid="digest-review-stage-tab-raw"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-review-stage-tab-draft"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-review-stage-tab-raw"]').getAttribute("aria-selected")) === "true",
      "Raw Info tab is selected first",
    );
    assert(
      (await page.locator('[data-testid="digest-review-stage-tab-draft"]').getAttribute("aria-disabled")) === "true",
      "Draft tab is disabled before draft generation",
    );
    let title = await page.locator('[data-testid="digest-review-current-title"]').textContent();
    assert(title.includes("Agent trace design"), "review starts at selected item");

    await page.locator('[data-testid="digest-review-chat-input"]').fill("What matters?");
    await page.locator('[data-testid="digest-review-chat-send"]').click();
    await page.locator('[data-testid="digest-review-answer"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const answer = await page.locator('[data-testid="digest-review-answer"]').textContent();
    assert(answer.includes("Review reply grounded in Raw Info."), "review chat answer rendered");

    await page.locator('[data-testid="digest-review-next"]').click();
    title = await page.locator('[data-testid="digest-review-current-title"]').textContent();
    assert(title.includes("RSS normalization caveat"), "next changes review item");
    await page.locator('[data-testid="digest-review-close"]').click();
    await page.locator('[data-testid="digest-review-workspace"]').waitFor({
      state: "detached",
      timeout: 3000,
    });
  });

  await runTest("review mode can start from a specific card", async () => {
    await page.locator('[data-testid="digest-card-review-01C6PROMPTRAWINFO00003"]').click();
    await page.locator('[data-testid="digest-review-workspace"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const title = await page.locator('[data-testid="digest-review-current-title"]').textContent();
    assert(title.includes("Prompt source candidate"), "card action starts from that card");
    await page.locator('[data-testid="digest-review-close"]').click();
  });

  await runTest("review mode can settle Raw Info into a note draft", async () => {
    let rejectCalled = false;
    let acceptCalled = false;
    let commitCalled = false;
    let revisionCount = 0;
    await page.route("**/api/drafts/01C8DRAFTFROMRAWINFO", async (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      const body = route.request().postDataJSON();
      assert(body.title === "Tool Trace Notes", "draft metadata update sends title");
      assert(body.folder === "ai/notes", "draft metadata update sends folder");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "01C8DRAFTFROMRAWINFO",
          title: "Tool Trace Notes",
          body: "## Core\n\nTool traces should be visible but separate from the final answer.",
          source: "https://example.com/agent-trace",
          tags: ["agents", "notes"],
          kind: "knowledge",
          folder: "ai/notes",
          task_id: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          age_days: 0,
          is_stale: false,
          is_warn_age: false,
        }),
      });
    });
    await page.route("**/api/chat/raw-info/*/stream", async (route) => {
      revisionCount += 1;
      const newBody =
        revisionCount === 1
          ? "## Core\n\nTool traces should be visible but separate from the final answer."
          : "## Core\n\nTool traces should be visible, separate from the final answer, and easy to review.";
      const events = [
        {
          type: "tool_call",
          id: `draft_edit_${revisionCount}`,
          name: "propose_current_draft_edit",
          arguments: { instruction: "make the draft clearer" },
        },
        {
          type: "tool_result",
          id: `draft_edit_${revisionCount}`,
          name: "propose_current_draft_edit",
          payload: {
            kind: "draft_edit_proposal",
            draft_id: "01C8DRAFTFROMRAWINFO",
            title: "Tool Trace Notes",
            changed: true,
            old_body:
              "## Core\n\nTool traces should be visible but separate from the final answer.",
            new_body: newBody,
            summary: "Draft diff is ready for review.",
          },
        },
        {
          type: "reply_chunk",
          text: "I prepared a draft diff you can review.",
        },
        {
          type: "turn_done",
          final_text: "I prepared a draft diff you can review.",
        },
      ];
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join(""),
      });
    });
    await page.route("**/api/drafts/01C8DRAFTFROMRAWINFO/diff/reject", async (route) => {
      rejectCalled = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          draft: {
            id: "01C8DRAFTFROMRAWINFO",
            title: "Tool Trace Notes",
            body: "## Core\n\nTool traces should be visible but separate from the final answer.",
            source: "https://example.com/agent-trace",
            tags: ["agents", "notes"],
            kind: "knowledge",
            folder: "ai/notes",
            task_id: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            age_days: 0,
            is_stale: false,
            is_warn_age: false,
          },
          rejected: true,
        }),
      });
    });
    await page.route("**/api/drafts/01C8DRAFTFROMRAWINFO/diff/accept", async (route) => {
      acceptCalled = true;
      const body = route.request().postDataJSON();
      assert(
        body.final_body.includes("easy to review"),
        "accept sends the edited proposal body",
      );
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          draft: {
            id: "01C8DRAFTFROMRAWINFO",
            title: "Tool Trace Notes",
            body: body.final_body,
            source: "https://example.com/agent-trace",
            tags: ["agents", "notes"],
            kind: "knowledge",
            folder: "ai/notes",
            task_id: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            age_days: 0,
            is_stale: false,
            is_warn_age: false,
          },
          accepted: true,
        }),
      });
    });
    await page.route("**/api/drafts/01C8DRAFTFROMRAWINFO/commit", async (route) => {
      commitCalled = true;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          note_id: "01C9NOTEFROMDRAFT",
          path: "/tmp/knowlet/notes/ai/notes/tool-trace-notes.md",
          title: "Tool Trace Notes",
          raw_info_id: "01C6TODAYRAWINFO000001",
        }),
      });
    });
    await page.route("**/api/notes/01C9NOTEFROMDRAFT", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "01C9NOTEFROMDRAFT",
          title: "Tool Trace Notes",
          path: "/tmp/knowlet/notes/ai/notes/tool-trace-notes.md",
          folder: "ai/notes",
          tags: ["agents", "notes"],
          aliases: [],
          source: "https://example.com/agent-trace",
          kind: "knowledge",
          body: "## Core\n\nTool traces should be visible, separate from the final answer, and easy to review.",
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          frontmatter_status: "valid",
          frontmatter_corruption: null,
        }),
      });
    });
    await page.route("**/api/notes/01C9NOTEFROMDRAFT/backlinks", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify([]),
      });
    });
    await page.route("**/api/digest/items/*/draft", async (route) => {
      const request = route.request();
      const body = request.postDataJSON();
      assert(Array.isArray(body.history), "draft request forwards discussion history");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          raw_info: {
            ...rawInfo({
              id: "01C6TODAYRAWINFO000001",
              title: "Agent trace design",
              url: "https://example.com/agent-trace",
            }),
            status: "drafted",
            note_draft_id: "01C8DRAFTFROMRAWINFO",
          },
          draft: {
            id: "01C8DRAFTFROMRAWINFO",
            title: "Tool Trace Separation",
            body: "## Core\n\nTool traces should be visible but separate from the final answer.",
            source: "https://example.com/agent-trace",
            tags: ["agents", "tooling"],
            kind: "knowledge",
            folder: "ai/research",
            task_id: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            age_days: 0,
            is_stale: false,
            is_warn_age: false,
          },
          rationale: "The discussion turned this into durable knowledge.",
        }),
      });
    });
    await page.locator('[data-testid="digest-card-01C6TODAYRAWINFO000001"]').click();
    await page.locator('[data-testid="digest-start-review"]').click();
    await page.locator('[data-testid="digest-review-workspace"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-review-stage-tab-draft"]').getAttribute("aria-disabled")) === "true",
      "draft tab starts disabled",
    );
    await page.locator('[data-testid="digest-settle-draft"]').click();
    await page.locator('[data-testid="digest-draft-result"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-review-stage-tab-draft"]').getAttribute("aria-disabled")) === "false",
      "draft tab becomes enabled after draft generation",
    );
    assert(
      (await page.locator('[data-testid="digest-review-stage-tab-draft"]').getAttribute("aria-selected")) === "true",
      "draft tab is selected after draft generation",
    );
    await page.locator('[data-testid="digest-draft-editor"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const titleValue = await page.locator('[data-testid="digest-draft-title-input"]').inputValue();
    const result = await page.locator('[data-testid="digest-draft-result"]').textContent();
    assert(titleValue === "Tool Trace Separation", "created draft title is visible");
    assert(result.includes("knowledge"), "created draft kind is visible");
    assert(result.includes("ai/research"), "created draft folder is visible");
    await page.locator('[data-testid="digest-draft-title-input"]').fill("Tool Trace Notes");
    await page.locator('[data-testid="digest-draft-tags-input"]').fill("agents, notes");
    await page.locator('[data-testid="digest-draft-folder-input"]').fill("ai/notes");
    await page.locator('[data-testid="digest-draft-save"]').click();
    const updatedTitle = await page.locator('[data-testid="digest-draft-title-input"]').inputValue();
    const updatedFolder = await page.locator('[data-testid="digest-draft-folder-input"]').inputValue();
    const updated = await page.locator('[data-testid="digest-draft-result"]').textContent();
    assert(updatedTitle === "Tool Trace Notes", "updated draft title is visible");
    assert(updatedFolder === "ai/notes", "updated draft folder is visible");
    await page
      .locator('[data-testid="digest-review-chat-input"]')
      .fill("Please revise the draft so the final note is clearer.");
    await page.locator('[data-testid="digest-review-chat-send"]').click();
    await page.locator('[data-testid="diff-review"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="diff-reject"]').click();
    assert(rejectCalled, "reject diff endpoint is called");
    await page.locator('[data-testid="diff-review"]').waitFor({
      state: "detached",
      timeout: 3000,
    });

    await page
      .locator('[data-testid="digest-review-chat-input"]')
      .fill("Try one more draft revision and make it reviewable.");
    await page.locator('[data-testid="digest-review-chat-send"]').click();
    await page.locator('[data-testid="diff-review"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="diff-apply"]').click();
    assert(acceptCalled, "accept diff endpoint is called");
    await page
      .locator('[data-testid="digest-draft-body-preview"]')
      .filter({ hasText: "easy to review" })
      .waitFor({ state: "visible", timeout: 3000 });

    await page.locator('[data-testid="digest-draft-commit"]').click();
    assert(commitCalled, "commit endpoint is called");
    await page.locator('[data-testid="digest-draft-committed"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-review-close"]').click();
  });

  await runTest("no console errors during populated inbox suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await env.teardown();
}

env = await setupDigestEnv(seedOverflow);
try {
  const { page } = env;
  await runTest("digest shows pause banner when pending Raw Info exceeds 200", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-pause-banner"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const text = await page.locator('[data-testid="digest-pause-banner"]').textContent();
    assert(text.includes("200"), "pause banner names the threshold");
  });
  await runTest("no console errors during overflow suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await env.teardown();
}

env = await setupDigestEnv();
try {
  const { page } = env;
  await runTest("digest empty state renders for an empty Raw Info inbox", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-empty"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
  });
  await runTest("no console errors during empty suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await env.teardown();
}

exitAfter();
