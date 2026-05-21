// E2E: Stage 3 P11 — Mining task paused-by-backlog visibility.
//
// Seeds a MiningTask file with paused_reason=backlog + 5 drafts
// attached to that task_id, then verifies Settings → Advanced
// shows the right status badge + the "paused — review some to
// auto-resume" explanation (per ADR-0009 A2.3 visibility).

import fs from "node:fs";
import path from "node:path";

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({ notes: [], language: "en" });
const { page, baseURL, vaultDir, teardown } = env;

function writeMiningTask({ id, name, paused = false, maxPending = 5 }) {
  const tasksDir = path.join(vaultDir, "tasks");
  fs.mkdirSync(tasksDir, { recursive: true });
  const now = new Date().toISOString();
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
  const front = [
    "---",
    "schema_version: 1",
    `id: ${id}`,
    `name: ${name}`,
    `enabled: ${!paused}`,
    "schedule: {}",
    "sources: []",
    "prompt: stub prompt",
    `created_at: "${now}"`,
    `updated_at: "${now}"`,
    `max_pending_drafts: ${maxPending}`,
    ...(paused ? ["paused_reason: backlog"] : []),
    "---",
  ].join("\n");
  fs.writeFileSync(path.join(tasksDir, `${id}-${slug}.md`), `${front}\n`);
}

function writeDraftForTask({ id, title, taskId }) {
  const draftsDir = path.join(vaultDir, "drafts");
  fs.mkdirSync(draftsDir, { recursive: true });
  const now = new Date().toISOString();
  const slug = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
  const front = [
    "---",
    "schema_version: 1",
    `id: ${id}`,
    `title: ${title}`,
    "tags: []",
    "kind: reference",
    `task_id: ${taskId}`,
    `created_at: ${now}`,
    `updated_at: ${now}`,
    "status: draft",
    "---",
  ].join("\n");
  fs.writeFileSync(
    path.join(draftsDir, `${id}-${slug}.md`),
    `${front}\nbody\n`,
  );
}

try {
  // Seed: one paused task with 5 attached drafts (at the ceiling).
  writeMiningTask({
    id: "01TASKBACKLOG01",
    name: "Mining test feed",
    paused: true,
    maxPending: 5,
  });
  for (let i = 0; i < 5; i++) {
    writeDraftForTask({
      id: `01MTDR${String(i).padStart(5, "0")}`,
      title: `Mining draft ${i}`,
      taskId: "01TASKBACKLOG01",
    });
  }

  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest(
    "P11: Settings → Advanced shows paused-by-backlog badge + explanation",
    async () => {
      // The settings dialog is opened via a header gear or via a known
      // route. Easiest cross-version: dispatch the open-settings event.
      // Actually we use the keyboard / UI — but knowlet has no shortcut
      // for Settings. The header button is the entry point.
      const settingsBtn = page.getByRole("button", { name: /settings|设置/i }).first();
      await settingsBtn.click();
      await page.waitForTimeout(400);

      // Click Advanced tab.
      const advancedTab = page.locator('[data-testid="settings-tab-advanced"]');
      await advancedTab.click();
      await page.waitForTimeout(400);

      // Find the row for our task.
      const row = page.locator(
        '[data-testid="mining-task-row-01TASKBACKLOG01"]',
      );
      await row.waitFor({ state: "visible", timeout: 3000 });

      // Status badge text must include the paused-by-backlog string.
      const status = page.locator(
        '[data-testid="mining-task-status-01TASKBACKLOG01"]',
      );
      const statusText = await status.innerText();
      assert(
        /paused|暂停|backlog|积压/i.test(statusText),
        `paused-by-backlog status visible, got "${statusText}"`,
      );

      // Row content must mention 5/5 (pending count vs limit).
      const rowText = await row.innerText();
      assert(
        /5\s*\/\s*5/.test(rowText),
        `row shows '5/5 pending' count, got "${rowText.slice(0, 200)}"`,
      );

      // Row content must include explanation line (per A2.3 visibility).
      assert(
        /review|清理|清/i.test(rowText),
        `explanation tells user how to resume, got "${rowText.slice(0, 200)}"`,
      );
    },
  );
} finally {
  await teardown();
}

exitAfter();
