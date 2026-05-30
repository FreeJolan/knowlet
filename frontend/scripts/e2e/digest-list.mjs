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

function digestSource(overrides) {
  return {
    schema_version: 1,
    id: overrides.id,
    name: overrides.name ?? "Paused historical source",
    kind: overrides.kind ?? "rss",
    enabled: overrides.enabled ?? false,
    url: overrides.url ?? "https://example.com/feed.xml",
    prompt: overrides.prompt ?? null,
    created_at: overrides.created_at ?? isoDaysAgo(1),
    updated_at: overrides.updated_at ?? isoDaysAgo(0),
    last_pull_at: overrides.last_pull_at ?? isoDaysAgo(0),
    last_success_at: overrides.last_success_at ?? null,
    last_error: overrides.last_error ?? "pending raw info reached 200",
    pull_status: overrides.pull_status ?? "paused",
  };
}

function writeDigestSources(vaultDir, sources) {
  const root = join(vaultDir, ".knowlet", "digest", "sources");
  mkdirSync(root, { recursive: true });
  for (const source of sources) {
    const slug = source.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    writeFileSync(
      join(root, `${source.id}-${slug}.json`),
      JSON.stringify(source, null, 2) + "\n",
      "utf8",
    );
  }
}

async function waitForDraftAutosave(page, state) {
  await page.locator(`[data-testid="digest-draft-autosave-state"][data-state="${state}"]`).waitFor({
    state: "visible",
    timeout: 5000,
  });
}

async function replaceDraftBody(page, body) {
  await page
    .locator('[data-testid="digest-draft-view-mode-toggle"] button[data-mode="edit"]')
    .click();
  const editor = page.locator('[data-testid="digest-draft-editor"] .cm-content');
  await editor.waitFor({ state: "visible", timeout: 3000 });
  await editor.click();
  await page.keyboard.press("Meta+A");
  await page.keyboard.press("Delete");
  await page.keyboard.type(body, { delay: 5 });
}

function seedThreeItems(vaultDir) {
  mkdirSync(join(vaultDir, "notes", "ai", "notes"), { recursive: true });
  mkdirSync(join(vaultDir, "notes", "library", "final"), { recursive: true });
  writeDigestSources(vaultDir, [
    digestSource({
      id: "01C6SRCRESEARCH",
      name: "Research Feed",
      enabled: true,
      pull_status: "ok",
      last_error: null,
      last_success_at: isoDaysAgo(0),
    }),
    digestSource({
      id: "01C6SRCPROMPT",
      name: "Prompt Watch",
      kind: "prompt",
      enabled: true,
      url: null,
      prompt: "Find important AI agent updates.",
      pull_status: "ok",
      last_error: null,
      last_success_at: isoDaysAgo(0),
    }),
  ]);
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
    rawInfo({
      id: "01C6INCLUDEDMIXED0001",
      title: "Already processed library item",
      url: "https://example.com/processed-library-item",
      fetched_at: isoDaysAgo(0),
      summary: "This item has already been saved and should not remain in the review inbox.",
      status: "included",
    }),
  ]);
}

function seedOneItem(vaultDir) {
  writeRawInfos(vaultDir, [
    rawInfo({
      id: "01C6ONLYRAWINFO000001",
      title: "Only review item",
      url: "https://example.com/only",
      fetched_at: isoDaysAgo(0),
      summary: "A single item for empty queue behavior.",
      status: "unprocessed",
    }),
  ]);
}

function seedProcessedItems(vaultDir) {
  writeDigestSources(vaultDir, [
    digestSource({
      id: "01C6PAUSEDSOURCE0001",
      name: "Paused stale source",
      pull_status: "paused",
    }),
  ]);
  writeRawInfos(vaultDir, [
    rawInfo({
      id: "01C6INCLUDEDRAWINFO01",
      title: "Already included item",
      url: "https://example.com/included",
      status: "included",
    }),
    rawInfo({
      id: "01C6DISCARDEDRAWINFO1",
      title: "Already discarded item",
      url: "https://example.com/discarded",
      status: "discarded",
    }),
  ]);
}

function seedSourceCoverage(vaultDir) {
  writeDigestSources(vaultDir, [
    digestSource({
      id: "01C6SRCWITHITEMS",
      name: "Research Feed",
      enabled: true,
      pull_status: "ok",
      last_error: null,
      last_success_at: isoDaysAgo(0),
    }),
    digestSource({
      id: "01C6SRCWITHOUTITEMS",
      name: "Prompt Watch",
      kind: "prompt",
      enabled: true,
      url: null,
      prompt: "Find important AI agent updates.",
      pull_status: "ok",
      last_error: null,
      last_success_at: isoDaysAgo(0),
    }),
  ]);
  writeRawInfos(vaultDir, [
    rawInfo({
      id: "01C6SINGLECOVERAGE01",
      source_id: "01C6SRCWITHITEMS",
      source_name: "Research Feed",
      title: "Single sourced item",
      fetched_at: isoDaysAgo(0),
      summary: "One source produced a pending item.",
      status: "unprocessed",
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
    await page.locator('[data-testid="digest-today-pull-copy"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const todayPullCopy = await page
      .locator('[data-testid="digest-today-pull-copy"]')
      .textContent();
    assert(
      /today.*complete/i.test(todayPullCopy),
      `Digest list explains today's pull is complete, got ${JSON.stringify(todayPullCopy)}`,
    );
    assert(
      /2 enabled sources/i.test(todayPullCopy),
      `Digest list names the enabled source coverage, got ${JSON.stringify(todayPullCopy)}`,
    );
    const statusPlacement = await page
      .locator('[data-testid="digest-pull-status"]')
      .evaluate((el) => {
        const style = getComputedStyle(el);
        return {
          parent: el.closest('[data-testid="digest-list-status-row"]')?.getAttribute("data-testid"),
          borderWidth: style.borderTopWidth,
          borderStyle: style.borderTopStyle,
        };
      });
    assert(
      statusPlacement.parent === "digest-list-status-row",
      "pull status sits in the left status row instead of the right action cluster",
    );
    assert(
      statusPlacement.borderWidth === "0px" || statusPlacement.borderStyle === "none",
      `pull status reads as passive status, got border ${statusPlacement.borderWidth} ${statusPlacement.borderStyle}`,
    );
    assert(
      (await page.locator('[data-testid="digest-card-01C6INCLUDEDMIXED0001"]').count()) === 0,
      "processed Raw Info is hidden from the review inbox",
    );
    await page.locator('[data-testid="digest-list-pane"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const detailBg = await page
      .locator('[data-testid="digest-detail"]')
      .evaluate((el) => getComputedStyle(el).backgroundColor);
    assert(detailBg !== "rgba(0, 0, 0, 0)", "detail panel background is opaque");
    const listDetailVisuals = await page.evaluate(() => {
      const list = document.querySelector('[data-testid="digest-list-pane"]');
      const detail = document.querySelector('[data-testid="digest-detail"]');
      const listStyle = list ? getComputedStyle(list) : null;
      const detailStyle = detail ? getComputedStyle(detail) : null;
      return {
        listBg: listStyle?.backgroundColor,
        detailBg: detailStyle?.backgroundColor,
        listBorder: listStyle?.borderTopColor,
      };
    });
    assert(
      listDetailVisuals.listBg !== listDetailVisuals.detailBg,
      `list and detail panes need distinct backgrounds, got ${JSON.stringify(listDetailVisuals)}`,
    );
    assert(
      listDetailVisuals.listBorder !== "rgba(0, 0, 0, 0)",
      "left list pane has a visible boundary",
    );
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
    const researchToggle = page.locator('[data-testid="digest-group-toggle-source-research-feed"]');
    assert(
      (await researchToggle.getAttribute("aria-expanded")) === "true",
      "source group starts expanded",
    );
    await researchToggle.click();
    assert(
      (await researchToggle.getAttribute("aria-expanded")) === "false",
      "source group can collapse",
    );
    await page.locator('[data-testid="digest-card-01C6TODAYRAWINFO000001"]').waitFor({
      state: "hidden",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-card-01C6PROMPTRAWINFO00003"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await researchToggle.click();
    await page.locator('[data-testid="digest-card-01C6TODAYRAWINFO000001"]').waitFor({
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
    const footerOrder = await page
      .locator('[data-testid="digest-review-footer"]')
      .evaluate((footer) =>
        Array.from(
          footer.querySelectorAll(
            '[data-testid="digest-review-prev"], [data-testid="digest-review-discard"], [data-testid="digest-draft-commit"], [data-testid="digest-review-next"]',
          ),
        ).map((el) => el.getAttribute("data-testid")),
      );
    assert(
      footerOrder.join(" > ") ===
        "digest-review-prev > digest-review-discard > digest-draft-commit > digest-review-next",
      `review actions keep discard/commit immediately before next, got ${footerOrder.join(" > ")}`,
    );
    assert(
      await page.locator('[data-testid="digest-draft-commit"]').isDisabled(),
      "commit action is present but disabled before a draft exists",
    );
    await page.locator('[data-testid="digest-draft-commit-tooltip-trigger"]').hover();
    await page.locator('[data-testid="digest-draft-commit-tooltip"]').filter({
      hasText: "Create a note draft first",
    }).waitFor({ state: "visible", timeout: 3000 });
    const paneRatio = await page.locator('[data-testid="digest-review-workspace"]').evaluate(() => {
      const left = document.querySelector('[data-testid="digest-review-left-pane"]');
      const right = document.querySelector('[data-testid="digest-review-chat-pane"]');
      const lw = left?.getBoundingClientRect().width ?? 0;
      const rw = right?.getBoundingClientRect().width ?? 0;
      return lw / (lw + rw);
    });
    assert(paneRatio > 0.58 && paneRatio < 0.62, `review layout starts near 6:4, got ${paneRatio}`);
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

  await runTest("draft autosave status appears only after a save and clears on item switch", async () => {
    await page.route("**/api/digest/items/01C6TODAYRAWINFO000001/draft", async (route) => {
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
            note_draft_id: "01C8AUTOSAVESCOPE",
          },
          draft: {
            id: "01C8AUTOSAVESCOPE",
            title: "Autosave Scope",
            body: "## Core\n\nAutosave status should be scoped to the active review item.",
            source: "https://example.com/agent-trace",
            tags: ["agents"],
            kind: "knowledge",
            folder: "ai/research",
            task_id: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
            age_days: 0,
            is_stale: false,
            is_warn_age: false,
          },
          rationale: "A small draft for autosave status scoping.",
        }),
      });
    });
    await page.route("**/api/drafts/01C8AUTOSAVESCOPE", async (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      const body = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "01C8AUTOSAVESCOPE",
          title: body.title,
          body: body.body,
          source: "https://example.com/agent-trace",
          tags: body.tags,
          kind: body.kind,
          folder: body.folder,
          task_id: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          age_days: 0,
          is_stale: false,
          is_warn_age: false,
        }),
      });
    });

    await page.locator('[data-testid="digest-card-01C6TODAYRAWINFO000001"]').click();
    await page.locator('[data-testid="digest-start-review"]').click();
    await page.locator('[data-testid="digest-settle-draft"]').click();
    await page.locator('[data-testid="digest-draft-editor"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-draft-autosave-state"]').count()) === 0,
      "autosave status is hidden before the user triggers a save",
    );

    await page.locator('[data-testid="digest-draft-title"]').click();
    await page.locator('[data-testid="digest-draft-title-input"]').fill("Autosave Scope Updated");
    await page.locator('[data-testid="digest-draft-title-input"]').press("Enter");
    await waitForDraftAutosave(page, "saved");
    await page
      .locator(
        '[data-testid="digest-review-footer"] [data-testid="digest-draft-autosave-state"][data-state="saved"]',
      )
      .waitFor({ state: "visible", timeout: 3000 });
    const footerOrder = await page
      .locator('[data-testid="digest-review-footer"]')
      .evaluate((footer) =>
        Array.from(
          footer.querySelectorAll(
            '[data-testid="digest-draft-autosave-state"], [data-testid="digest-review-discard"]',
          ),
        ).map((el) => el.getAttribute("data-testid")),
      );
    assert(
      footerOrder.join(" > ") === "digest-draft-autosave-state > digest-review-discard",
      `autosave status sits immediately before discard, got ${footerOrder.join(" > ")}`,
    );

    await page.locator('[data-testid="digest-review-next"]').click();
    await page
      .locator('[data-testid="digest-review-current-title"]')
      .filter({ hasText: "RSS normalization caveat" })
      .waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await page.locator('[data-testid="digest-draft-autosave-state"]').count()) === 0,
      "autosave status is hidden after switching to another Raw Info item",
    );
    await page.locator('[data-testid="digest-review-close"]').click();
  });

  await runTest("review mode can settle Raw Info into a note draft", async () => {
    let rejectCalled = false;
    let acceptCalled = false;
    let commitCalled = false;
    let revisionCount = 0;
    let failNextDraftSave = false;
    const draftSaveBodies = [];
    await page.route("**/api/drafts/01C8DRAFTFROMRAWINFO", async (route) => {
      if (route.request().method() !== "PUT") return route.fallback();
      const body = route.request().postDataJSON();
      draftSaveBodies.push(body);
      if (failNextDraftSave) {
        failNextDraftSave = false;
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ error: "save failed" }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "01C8DRAFTFROMRAWINFO",
          title: body.title,
          body: body.body,
          source: "https://example.com/agent-trace",
          tags: body.tags,
          kind: body.kind,
          folder: body.folder,
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
            kind: "reference",
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
            kind: "reference",
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
      const body = route.request().postDataJSON();
      assert(body.folder === "library/final", `commit sends selected folder, got ${body.folder}`);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          note_id: "01C9NOTEFROMDRAFT",
          path: "/tmp/knowlet/notes/library/final/tool-trace-notes.md",
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
    await page.locator('[data-testid="digest-draft-note-surface"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const titleText = await page.locator('[data-testid="digest-draft-title"]').textContent();
    const result = await page.locator('[data-testid="digest-draft-result"]').textContent();
    assert(titleText === "Tool Trace Separation", "created draft title is visible as note title");
    assert(result.includes("ai/research"), "created draft folder is visible");
    assert(
      (await page.locator('[data-testid="digest-draft-kind-chip"]').getAttribute("data-kind")) === "knowledge",
      "created draft kind chip is visible",
    );
    assert(
      (await page.locator('[data-testid="digest-draft-view-mode-toggle"]').count()) === 1,
      "draft has note-style view mode toggle",
    );
    assert(
      (await page.locator('[data-testid="tag-chip"][data-tag="tooling"]').count()) === 1,
      "draft tags render as chips",
    );
    await page.locator('[data-testid="digest-review-stage-tab-raw"]').click();
    await page.locator('[data-testid="digest-existing-draft-notice"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-settle-draft"]').count()) === 0,
      "raw info with a draft does not offer duplicate draft generation",
    );
    await page.locator('[data-testid="digest-review-stage-tab-draft"]').click();
    assert(
      (await page.locator('[data-testid="digest-draft-autosave-state"]').count()) === 0,
      "newly generated draft does not show saved status before a real autosave",
    );
    assert(
      (await page.locator('[data-testid="digest-draft-revert-session"]').count()) === 0,
      "draft footer does not expose a session revert button",
    );
    assert(
      (await page.locator('[data-testid="digest-draft-save"]').count()) === 0,
      "draft footer does not expose a manual save button",
    );
    assert(
      (await page.locator('[data-testid="digest-review-skip"]').count()) === 0,
      "review footer does not expose the old skip button",
    );
    await page.locator('[data-testid="digest-review-discard"]').waitFor({
      state: "visible",
      timeout: 3000,
    });

    failNextDraftSave = true;
    await page.locator('[data-testid="digest-draft-title"]').click();
    await page.locator('[data-testid="digest-draft-title-input"]').fill("Tool Trace Notes");
    await page.locator('[data-testid="digest-draft-title-input"]').press("Enter");
    await waitForDraftAutosave(page, "error");
    assert(
      await page.locator('[data-testid="digest-draft-commit"]').isDisabled(),
      "commit stays blocked while autosave is failed",
    );

    await page.locator('[data-testid="tag-add-button"]').click();
    await page.locator('[data-testid="tag-add-input"]').fill("notes");
    await page.locator('[data-testid="tag-add-input"]').press("Enter");
    await page.locator('[data-testid="tag-chip-remove"][data-tag="tooling"]').click();
    await page.locator('[data-testid="digest-draft-kind-chip-button"]').click();
    await page.locator('[data-testid="kind-chip-demote-confirm"]').click();
    assert(
      (await page.locator('[data-testid="digest-draft-kind-chip"]').getAttribute("data-kind")) === "reference",
      "draft kind chip demotes to reference",
    );
    await page.locator('[data-testid="digest-draft-properties-toggle"]').click();
    await page.locator('[data-testid="digest-draft-folder-input"]').fill("ai/notes");
    await replaceDraftBody(
      page,
      "## Core\n\nTool traces should be visible, separate from the final answer, and pleasant to review.",
    );
    await waitForDraftAutosave(page, "saved");
    await page
      .locator(
        '[data-testid="digest-review-footer"] [data-testid="digest-draft-autosave-state"][data-state="saved"]',
      )
      .waitFor({ state: "visible", timeout: 3000 });
    assert(
      draftSaveBodies.some(
        (body) =>
          body.title === "Tool Trace Notes" &&
          body.folder === "ai/notes" &&
          body.kind === "reference" &&
          body.tags.join(",") === "agents,notes" &&
          body.body.includes("pleasant to review"),
      ),
      `autosave persists the edited draft body and metadata — got ${JSON.stringify(draftSaveBodies)}`,
    );

    await replaceDraftBody(
      page,
      "## Core\n\nTool traces should be visible but separate from the final answer.",
    );
    await waitForDraftAutosave(page, "saved");
    await page
      .locator('[data-testid="digest-draft-view-mode-toggle"] button[data-mode="preview"]')
      .click();
    await page
      .locator('[data-testid="digest-draft-preview"]')
      .filter({ hasText: "Tool traces should be visible" })
      .waitFor({ state: "visible", timeout: 3000 });
    const updatedTitle = await page.locator('[data-testid="digest-draft-title"]').textContent();
    const updatedFolder = await page.locator('[data-testid="digest-draft-folder-input"]').inputValue();
    assert(updatedTitle === "Tool Trace Notes", "updated draft title is visible");
    assert(updatedFolder === "ai/notes", "updated draft folder is visible");
    assert(
      (await page.locator('[data-testid="digest-draft-kind-chip"]').getAttribute("data-kind")) === "reference",
      "updated draft kind is visible",
    );
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
      .locator('[data-testid="digest-draft-view-mode-toggle"] button[data-mode="preview"]')
      .click();
    await page
      .locator('[data-testid="digest-draft-preview"]')
      .filter({ hasText: "easy to review" })
      .waitFor({ state: "visible", timeout: 3000 });

    await page.locator('[data-testid="digest-draft-commit"]').click();
    await page.locator('[data-testid="digest-folder-dialog"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(!commitCalled, "opening the folder dialog does not commit");
    await page.locator('[data-testid="digest-folder-cancel"]').click();
    await page.locator('[data-testid="digest-folder-dialog"]').waitFor({
      state: "detached",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-draft-commit"]').click();
    await page.locator('[data-testid="digest-folder-dialog"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-folder-option-library-final"]').click();
    await page.locator('[data-testid="digest-folder-confirm"]').click();
    assert(commitCalled, "commit endpoint is called");
    const commitTransition = page.locator(
      '[data-testid="digest-review-transition"][data-kind="commit"][data-target="library"][data-duration-ms="2000"][data-motion="shrink-then-horizontal"][data-distance="compact"][data-scale="large"]',
    );
    await commitTransition.waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-review-transition-snapshot"]').getAttribute("data-scale-lock")) === "true",
      "snapshot locks its final size before horizontal travel",
    );
    assert(
      (await page.locator('[data-testid="digest-review-transition-target"]').getAttribute("data-position")) === "center-right",
      "target icon is pulled toward the center",
    );
    await page.waitForTimeout(1000);
    assert(
      await commitTransition.isVisible(),
      "commit transition stays visible long enough to communicate the destination",
    );
    await page.locator('[data-testid="digest-review-transition-complete"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-review-current-title"]').filter({
      hasText: "RSS normalization caveat",
    }).waitFor({
      state: "visible",
      timeout: 5000,
    });
    assert(
      (await page.locator('[data-testid="digest-review-stage-tab-raw"]').getAttribute("aria-selected")) === "true",
      "after commit the next item without a draft opens Raw Info",
    );
    await page.locator('[data-testid="digest-review-close"]').click();
  });

  await runTest("no console errors during populated inbox suite", () => {
    assertConsoleClean(env, {
      allowMessages: ["Failed to load resource: the server responded with a status of 500"],
    });
  });
} finally {
  await env.teardown();
}

env = await setupDigestEnv(seedThreeItems);
try {
  const { page, baseURL } = env;
  await runTest("Digest list can clear all pending Raw Info items", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-clear-pending"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-clear-pending"]').click();
    await page.locator('[data-testid="digest-clear-confirm-popover"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-clear-cancel"]').click();
    await page.locator('[data-testid="digest-clear-confirm-popover"]').waitFor({
      state: "detached",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-clear-pending"]').click();
    await page.locator('[data-testid="digest-clear-confirm"]').click();
    await page.locator('[data-testid="digest-empty"]').waitFor({
      state: "visible",
      timeout: 5000,
    });
    const items = await (await page.request.get(`${baseURL}/api/digest/items`)).json();
    const pending = items.filter((item) => !["discarded", "included"].includes(item.status));
    assert(pending.length === 0, `all pending Raw Info items are discarded, got ${JSON.stringify(pending)}`);
  });
  await runTest("no console errors during clear-pending suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await env.teardown();
}

env = await setupDigestEnv(seedOneItem);
try {
  const { page } = env;
  await runTest("review queue shows an empty state after discarding the last item", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-start-review"]').click();
    await page.locator('[data-testid="digest-review-workspace"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-review-skip"]').count()) === 0,
      "skip button is removed from review mode",
    );
    await page.locator('[data-testid="digest-review-discard"]').click();
    await page.locator('[data-testid="digest-discard-confirm-popover"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-review-transition"]').count()) === 0,
      "first discard click only opens confirmation",
    );
    await page.locator('[data-testid="digest-discard-cancel"]').click();
    await page.locator('[data-testid="digest-discard-confirm-popover"]').waitFor({
      state: "detached",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-review-discard"]').click();
    await page.locator('[data-testid="digest-discard-confirm"]').click();
    const discardTransition = page.locator(
      '[data-testid="digest-review-transition"][data-kind="discard"][data-target="discard"][data-duration-ms="2000"][data-motion="shrink-then-horizontal"][data-distance="compact"][data-scale="large"]',
    );
    await discardTransition.waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.waitForTimeout(1000);
    assert(
      await discardTransition.isVisible(),
      "discard transition stays visible long enough to communicate the destination",
    );
    assert(
      (await page.locator('[data-testid="digest-review-transition-complete"]').count()) === 0,
      "discard transition avoids a green completion badge",
    );
    await page.locator('[data-testid="digest-review-transition-burst"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-review-empty-state"]').waitFor({
      state: "visible",
      timeout: 5000,
    });
    assert(
      (await page.locator('[data-testid="digest-review-left-pane"]').count()) === 0,
      "empty review queue replaces the split panes",
    );
    await page.locator('[data-testid="digest-review-close"]').click();
  });
  await runTest("no console errors during single-item discard suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await env.teardown();
}

env = await setupDigestEnv(seedProcessedItems);
try {
  const { page } = env;
  await runTest("review entry is disabled when every Raw Info item is already processed", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-focus-mode"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      await page.locator('[data-testid="digest-start-review"]').isDisabled(),
      "top-level review entry is disabled with no pending items",
    );
    assert(
      (await page.locator('[data-testid="digest-pause-banner"]').count()) === 0,
      "stale paused source status does not show the backlog pause banner",
    );
    const pullStatus = await page.locator('[data-testid="digest-pull-status"]').textContent();
    assert(
      !pullStatus.includes("paused") && !pullStatus.includes("Paused"),
      `stale paused source status does not mark the whole Digest as paused — got ${pullStatus}`,
    );
    assert(
      (await page.locator('[data-testid="digest-card-01C6INCLUDEDRAWINFO01"]').count()) === 0,
      "included item is hidden from the review inbox",
    );
    assert(
      (await page.locator('[data-testid="digest-card-01C6DISCARDEDRAWINFO1"]').count()) === 0,
      "discarded item is hidden from the review inbox",
    );
    assert(
      (await page.locator('[data-testid="digest-review-workspace"]').count()) === 0,
      "disabled review entries do not open the empty review workspace",
    );
  });
  await runTest("no console errors during processed-only suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await env.teardown();
}

env = await setupDigestEnv(seedSourceCoverage);
try {
  const { page } = env;
  await runTest("source grouping shows enabled sources with no pending items", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-focus-mode"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const todayPullCopy = await page
      .locator('[data-testid="digest-today-pull-copy"]')
      .textContent();
    assert(
      /2 enabled sources/i.test(todayPullCopy),
      `source coverage copy includes empty enabled sources, got ${JSON.stringify(todayPullCopy)}`,
    );
    await page.locator('[data-testid="digest-group-mode-source"]').click();
    await page.locator('[data-testid="digest-group-source-research-feed"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-group-source-prompt-watch"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const emptyGroup = await page
      .locator('[data-testid="digest-group-empty-source-prompt-watch"]')
      .textContent();
    assert(
      emptyGroup.includes("no pending items"),
      `empty source group explains why no cards appear, got ${JSON.stringify(emptyGroup)}`,
    );
  });
  await runTest("no console errors during source coverage suite", () => {
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
    assert(
      (await page.getByText("Select raw information to read it.").count()) === 0,
      "empty inbox does not also show the select-a-row placeholder",
    );
  });
  await runTest("no console errors during empty suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await env.teardown();
}

env = await setupTestEnv({ notes: [], language: "en" });
try {
  const { page, baseURL } = env;
  await runTest("main Digest icon animates while sources are pulling", async () => {
    await page.route("**/api/digest/status", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "running",
          pending_count: 0,
          last_report: null,
          last_error: null,
          sources: [],
        }),
      });
    });
    await page.goto(baseURL, { waitUntil: "networkidle" });
    const digestButton = page.locator('[data-testid="header-digest-button"]');
    await digestButton.waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="header-digest-pulling-indicator"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await digestButton.getAttribute("data-pull-state")) === "running",
      "main Digest button exposes the running pull state",
    );
  });
  await runTest("no console errors during header pull indicator suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await env.teardown();
}

exitAfter();
