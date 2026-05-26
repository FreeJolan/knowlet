// E2E: Stage C2 — digest list UI.
//
// The digest view should show only drafts produced by digest sources,
// with an explicit today/week switch. Regular mining drafts must not
// leak into this intake surface.

import fs from "node:fs";
import path from "node:path";

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({ notes: [], language: "en" });
const { page, baseURL, vaultDir, teardown } = env;

function writeTask({ id, name, digest = false }) {
  const tasksDir = path.join(vaultDir, "tasks");
  fs.mkdirSync(tasksDir, { recursive: true });
  const now = new Date().toISOString();
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
  const front = [
    "---",
    "schema_version: 1",
    `id: ${id}`,
    `name: ${name}`,
    "enabled: true",
    "schedule:",
    "  every: 1d",
    "sources:",
    "  - rss: https://example.com/feed.xml",
    "prompt: digest prompt",
    `created_at: "${now}"`,
    `updated_at: "${now}"`,
    "---",
  ].join("\n");
  const body = digest
    ? "<!-- knowlet:digest-source/v1 -->\n\nDigest source"
    : "Regular mining source";
  fs.writeFileSync(path.join(tasksDir, `${id}-${slug}.md`), `${front}\n${body}\n`);
}

function writeDraft({ id, title, taskId, daysAgo = 0 }) {
  const draftsDir = path.join(vaultDir, "drafts");
  fs.mkdirSync(draftsDir, { recursive: true });
  const dt = new Date(Date.now() - daysAgo * 24 * 60 * 60 * 1000).toISOString();
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
  const front = [
    "---",
    "schema_version: 1",
    `id: ${id}`,
    `title: ${title}`,
    "tags: [digest]",
    "kind: reference",
    `task_id: ${taskId}`,
    "source: https://example.com/item",
    `created_at: ${dt}`,
    `updated_at: ${dt}`,
    "status: draft",
    "---",
  ].join("\n");
  fs.writeFileSync(path.join(draftsDir, `${id}-${slug}.md`), `${front}\n${title} body\n`);
}

try {
  writeTask({ id: "01DIGESTTASK01", name: "Digest feed", digest: true });
  writeTask({ id: "01REGULARTASK1", name: "Regular feed", digest: false });
  writeDraft({
    id: "01DIGESTTODAY1",
    title: "Digest today item",
    taskId: "01DIGESTTASK01",
    daysAgo: 0,
  });
  writeDraft({
    id: "01DIGESTWEEK01",
    title: "Digest week item",
    taskId: "01DIGESTTASK01",
    daysAgo: 3,
  });
  writeDraft({
    id: "01DIGESTOLD001",
    title: "Digest old item",
    taskId: "01DIGESTTASK01",
    daysAgo: 8,
  });
  writeDraft({
    id: "01REGULARTODAY",
    title: "Regular mining item",
    taskId: "01REGULARTASK1",
    daysAgo: 0,
  });

  await page.goto(baseURL, { waitUntil: "networkidle" });

  await runTest("digest button opens today's intake cards only", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-focus-mode"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-card-01DIGESTTODAY1"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-card-01DIGESTWEEK01"]').count()) === 0,
      "week-old digest item is hidden in Today",
    );
    assert(
      (await page.locator('[data-testid="digest-card-01REGULARTODAY"]').count()) === 0,
      "regular mining draft is not shown in digest",
    );
  });

  await runTest("week tab includes this week's digest cards", async () => {
    await page.locator('[data-testid="digest-period-week"]').click();
    await page.locator('[data-testid="digest-card-01DIGESTWEEK01"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-card-01DIGESTOLD001"]').count()) === 0,
      "older-than-week digest item is hidden in This week",
    );
  });

  await runTest("no console errors during the suite", () => {
    assertConsoleClean(env);
  });
} finally {
  await teardown();
}

exitAfter();
