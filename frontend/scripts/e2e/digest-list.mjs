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
    id: "01DIGESTSAVE01",
    title: "Save as reference item",
    taskId: "01DIGESTTASK01",
    daysAgo: 0,
  });
  writeDraft({
    id: "01DIGESTINTRNL",
    title: "Internalize item",
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

  await page.route("**/api/chat/draft/*/stream", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body:
        'data: {"type":"reply_chunk","text":"Grounded draft reply"}\n\n' +
        'data: {"type":"turn_done"}\n\n',
    });
  });
  await page.route("**/api/chat/draft/*/propose-internalize", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        note_id: "01DIGESTINTRNL",
        old_body: "Internalize item body\n",
        new_body: "# Internalized body\n\nThis is my reusable take.",
        changed: true,
        reason: "",
      }),
    });
  });

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

  await runTest("selected digest item can be read and discussed", async () => {
    await page.locator('[data-testid="digest-card-01DIGESTTODAY1"]').click();
    await page.locator('[data-testid="digest-detail"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-detail"]').textContent()).includes(
        "Digest today item body",
      ),
      "detail pane shows full draft body",
    );
    await page.locator('[data-testid="digest-chat-input"]').fill("What matters?");
    await page.locator('[data-testid="digest-chat-send"]').click();
    await page
      .locator('[data-testid="digest-message-assistant"]')
      .filter({ hasText: "Grounded draft reply" })
      .waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("skip removes only the selected digest draft", async () => {
    await page.locator('[data-testid="digest-action-skip"]').click();
    await page.locator('[data-testid="digest-card-01DIGESTTODAY1"]').waitFor({
      state: "detached",
      timeout: 3000,
    });
    const drafts = await (await page.request.get(`${baseURL}/api/digest/drafts?period=today`)).json();
    assert(!drafts.some((d) => d.id === "01DIGESTTODAY1"), "skipped draft is gone");
    assert(drafts.some((d) => d.id === "01DIGESTSAVE01"), "other digest drafts remain");
  });

  await runTest("save reference promotes the draft as a reference note", async () => {
    await page.locator('[data-testid="digest-card-01DIGESTSAVE01"]').click();
    await page.locator('[data-testid="digest-action-save-reference"]').click();
    await page.locator('[data-testid="digest-card-01DIGESTSAVE01"]').waitFor({
      state: "detached",
      timeout: 3000,
    });
    const notes = await (await page.request.get(`${baseURL}/api/notes`)).json();
    const note = notes.find((n) => n.id === "01DIGESTSAVE01");
    assert(note, "reference note was created");
    const full = await (await page.request.get(`${baseURL}/api/notes/01DIGESTSAVE01`)).json();
    assert(full.kind === "reference", "reference action preserves reference kind");
  });

  await runTest("internalize uses AI diff review before creating a knowledge note", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-card-01DIGESTINTRNL"]').click();
    await page.locator('[data-testid="digest-action-internalize"]').click();
    await page.locator('[data-testid="diff-review"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="diff-apply"]').click();
    await page.locator('[data-testid="digest-card-01DIGESTINTRNL"]').waitFor({
      state: "detached",
      timeout: 3000,
    });
    const notes = await (await page.request.get(`${baseURL}/api/notes`)).json();
    const note = notes.find((n) => n.id === "01DIGESTINTRNL");
    assert(note, "knowledge note was created after accepting diff");
    assert(note.kind === "knowledge", "internalize action creates a knowledge note");
    const full = await (await page.request.get(`${baseURL}/api/notes/01DIGESTINTRNL`)).json();
    assert(full.body.includes("Internalized body"), "accepted diff body was written");
  });

  await runTest("week tab includes this week's digest cards", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
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
