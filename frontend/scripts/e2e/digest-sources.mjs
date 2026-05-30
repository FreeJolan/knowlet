// E2E: Stage C v2 C10 — Digest source configuration inside Digest.
//
// Users configure information sources from the Digest workbench itself.
// C10 keeps RSS Source and Prompt Source as the only supported source kinds;
// website URL subscriptions are not a product surface.

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({ notes: [], language: "en" });
const { page, baseURL, teardown, vaultDir } = env;

function sourceFileName(source) {
  const slug = source.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `${source.id}-${slug}.json`;
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });

  await runTest("General settings no longer owns Digest source configuration", async () => {
    await page.locator('[data-testid="header-settings-button"]').click();
    await page.locator('[data-testid="settings-dialog"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="settings-tab-digest"]').count()) === 0,
      "Digest source configuration is not in general settings",
    );
    await page.locator('[data-testid="settings-dialog"]').press("Escape");
    await page.locator('[data-testid="settings-dialog"]').waitFor({
      state: "detached",
      timeout: 3000,
    });
  });

  await runTest("Digest workbench add RSS and Prompt sources", async () => {
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-focus-mode"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-config-toggle"]').click();
    await page.locator('[data-testid="digest-source-config-dialog"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-source-panel"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    assert(
      (await page.locator('[data-testid="digest-source-config"]').count()) === 0,
      "source configuration opens as a centered dialog, not an inline page section",
    );
    await page.locator('[data-testid="digest-source-schedule-hint"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const scheduleHint = await page
      .locator('[data-testid="digest-source-schedule-hint"]')
      .textContent();
    assert(
      /first time.*online|new day|Pull now/i.test(scheduleHint),
      `source configuration explains the automatic pull timing, got ${JSON.stringify(scheduleHint)}`,
    );
    await page.locator('[data-testid="digest-source-config-dialog"]').press("Escape");
    await page.locator('[data-testid="digest-source-config-dialog"]').waitFor({
      state: "detached",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-focus-mode"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.locator('[data-testid="digest-config-toggle"]').click();
    await page.locator('[data-testid="digest-source-config-dialog"]').waitFor({
      state: "visible",
      timeout: 3000,
    });

    await page.locator('[data-testid="digest-source-name"]').fill("Daily AI");
    await page
      .locator('[data-testid="digest-source-rss-url"]')
      .fill("https://example.com/feed.xml");
    await page.locator('[data-testid="digest-source-add"]').click();
    await page.locator('[data-testid^="digest-source-row-"]').filter({
      hasText: "Daily AI",
    }).waitFor({ state: "visible", timeout: 3000 });
    const dailyRow = page.locator('[data-testid^="digest-source-row-"]').filter({
      hasText: "Daily AI",
    });
    const dailyToggle = dailyRow.locator('[data-testid^="digest-source-toggle-"]');
    assert(
      (await dailyToggle.getAttribute("role")) === "switch",
      "source enabled state is represented by a switch",
    );
    assert(
      (await dailyToggle.getAttribute("aria-checked")) === "true",
      "newly-created source switch starts on",
    );
    const dailyRowText = await dailyRow.textContent();
    assert(
      !/\benabled\b|\bdisabled\b/i.test(dailyRowText),
      `source row should not duplicate switch state as text — got ${JSON.stringify(dailyRowText)}`,
    );

    await page.locator('[data-testid="digest-source-kind-prompt"]').click();
    await page.locator('[data-testid="digest-source-name"]').fill("Agent watch");
    await page
      .locator('[data-testid="digest-source-prompt"]')
      .fill("Find important AI agent updates.");
    await page.locator('[data-testid="digest-source-add"]').click();
    await page.locator('[data-testid^="digest-source-row-"]').filter({
      hasText: "Agent watch",
    }).waitFor({ state: "visible", timeout: 3000 });

    const apiSources = await (await page.request.get(`${baseURL}/api/digest/sources`)).json();
    assert(apiSources.length === 2, "two sources persisted");
    assert(
      apiSources.map((s) => s.kind).join(",") === "rss,prompt",
      "source kinds persisted in order",
    );
  });

  await runTest("Digest source modal renders human pull status copy", async () => {
    const sources = await (await page.request.get(`${baseURL}/api/digest/sources`)).json();
    const daily = sources.find((s) => s.name === "Daily AI");
    assert(daily, "Daily AI source exists");
    const root = join(vaultDir, ".knowlet", "digest", "sources");
    mkdirSync(root, { recursive: true });
    writeFileSync(
      join(root, sourceFileName(daily)),
      JSON.stringify(
        {
          ...daily,
          last_pull_at: new Date().toISOString(),
          last_success_at: new Date().toISOString(),
          pull_status: "ok",
        },
        null,
        2,
      ) + "\n",
      "utf8",
    );
    await page.reload({ waitUntil: "networkidle" });
    await page.locator('[data-testid="header-digest-button"]').click();
    await page.locator('[data-testid="digest-config-toggle"]').click();
    await page.locator(`[data-testid="digest-source-row-${daily.id}"]`).waitFor({
      state: "visible",
      timeout: 3000,
    });
    const dailyRowText = await page.locator(`[data-testid="digest-source-row-${daily.id}"]`).textContent();
    assert(
      /Last pull completed/i.test(dailyRowText),
      `source row should explain a completed pull, got ${JSON.stringify(dailyRowText)}`,
    );
    assert(
      !/\bok\b|\bpass\b/i.test(dailyRowText),
      `source row should not expose raw backend status words, got ${JSON.stringify(dailyRowText)}`,
    );
  });

  await runTest("Digest workbench rejects invalid RSS URL", async () => {
    await page.locator('[data-testid="digest-source-kind-rss"]').click();
    await page.locator('[data-testid="digest-source-name"]').fill("Broken feed");
    await page
      .locator('[data-testid="digest-source-rss-url"]')
      .fill("not-a-url");
    await page.locator('[data-testid="digest-source-add"]').click();
    await page.locator('[data-testid="digest-source-error"]').waitFor({
      state: "visible",
      timeout: 3000,
    });
    const apiSources = await (await page.request.get(`${baseURL}/api/digest/sources`)).json();
    assert(apiSources.length === 2, "invalid website source was not persisted");
  });

  await runTest("Digest workbench toggles and removes sources", async () => {
    const sources = await (await page.request.get(`${baseURL}/api/digest/sources`)).json();
    const daily = sources.find((s) => s.name === "Daily AI");
    const prompt = sources.find((s) => s.name === "Agent watch");
    assert(daily && prompt, "expected sources exist before toggle/remove");

    await page.locator(`[data-testid="digest-source-toggle-${daily.id}"]`).click();
    await page.waitForFunction(
      async ([url, id]) => {
        const items = await (await fetch(url)).json();
        return items.find((s) => s.id === id)?.enabled === false;
      },
      [`${baseURL}/api/digest/sources`, daily.id],
    );
    let afterToggle = await (await page.request.get(`${baseURL}/api/digest/sources`)).json();
    assert(
      afterToggle.find((s) => s.id === daily.id)?.enabled === false,
      "RSS source disabled",
    );
    assert(
      (await page.locator(`[data-testid="digest-source-toggle-${daily.id}"]`).getAttribute("aria-checked")) === "false",
      "source switch reflects the disabled state",
    );

    await page.locator(`[data-testid="digest-source-remove-${prompt.id}"]`).click();
    await page.locator(`[data-testid="digest-source-row-${prompt.id}"]`).waitFor({
      state: "detached",
      timeout: 3000,
    });
    afterToggle = await (await page.request.get(`${baseURL}/api/digest/sources`)).json();
    assert(
      afterToggle.map((s) => s.name).join(",") === "Daily AI",
      "prompt source removed",
    );
  });

  await runTest("no console errors during the suite", () => {
    assertConsoleClean(env, { allowMessages: ["400 (Bad Request)"] });
  });
} finally {
  await teardown();
}

exitAfter();
