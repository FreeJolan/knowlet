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
