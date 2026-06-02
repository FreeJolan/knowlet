// E2E: creation paths expose a visible loading state while the request is in flight.

import { assert, assertConsoleClean, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [],
  folders: [],
  language: "en",
});
const { page, baseURL, teardown } = env;

function delayNextPost(pathname) {
  let release;
  const ready = new Promise((resolve) => {
    release = resolve;
  });
  const handler = async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await ready;
    await route.continue();
    await page.unroute(`**${pathname}`, handler);
  };
  return page.route(`**${pathname}`, handler).then(() => release);
}

async function assertBusyButton(selector, spinnerSelector, expectedText) {
  const button = page.locator(selector);
  await button.waitFor({ state: "visible", timeout: 3000 });
  await page.waitForFunction(
    ([buttonSelector, spinner]) => {
      const el = document.querySelector(buttonSelector);
      const spin = document.querySelector(spinner);
      return (
        el instanceof HTMLButtonElement &&
        el.disabled &&
        el.getAttribute("aria-busy") === "true" &&
        el.getAttribute("data-busy") === "true" &&
        spin !== null
      );
    },
    [selector, spinnerSelector],
    { timeout: 3000, polling: 50 },
  );
  const text = ((await button.textContent()) ?? "").trim();
  assert(text.includes(expectedText), `${selector} should show "${expectedText}", got "${text}"`);
}

async function assertDisabled(selector, message) {
  const states = await page.locator(selector).evaluateAll((elements) => {
    return elements.map((el) => {
      return el instanceof HTMLButtonElement ||
        el instanceof HTMLInputElement ||
        el instanceof HTMLTextAreaElement
        ? el.disabled
        : el.getAttribute("aria-disabled") === "true";
    });
  });
  assert(states.length > 0, `${message}: no elements matched ${selector}`);
  assert(states.every(Boolean), message);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("New document submit shows loading while creating note", async () => {
    await page.locator('[data-testid="file-tree-empty-new-note"]').click();
    await page.locator('[data-testid="new-document-dialog"]').waitFor({ state: "visible" });
    await page.locator('[data-testid="new-document-title"]').fill("loading note");
    const release = await delayNextPost("/api/notes/new");
    try {
      await page.locator('[data-testid="new-document-submit"]').click();
      await assertBusyButton(
        '[data-testid="new-document-submit"]',
        '[data-testid="new-document-submit-spinner"]',
        "Creating",
      );
      await assertDisabled('[data-testid="new-document-cancel"]', "new document cancel should be disabled while creating");
      await assertDisabled('[data-testid="new-document-title"]', "new document title should be disabled while creating");
      await page.keyboard.press("Escape");
      await page.locator('[data-testid="new-document-dialog"]').waitFor({ state: "visible", timeout: 1000 });
    } finally {
      release();
    }
    await page.locator('[data-testid="new-document-dialog"]').waitFor({ state: "hidden" });
  });

  await runTest("Template creation submit shows loading while creating template", async () => {
    await page.locator('[data-testid="activity-bar-templates"]').click();
    await page.locator('[data-testid="template-tree-new-template"]').click();
    await page.locator('[data-testid="template-title"]').fill("loading template");
    const release = await delayNextPost("/api/templates");
    try {
      await page.locator('[data-testid="template-create-submit"]').click();
      await assertBusyButton(
        '[data-testid="template-create-submit"]',
        '[data-testid="template-create-submit-spinner"]',
        "Creating",
      );
      await assertDisabled('[data-testid="template-create-cancel"]', "template cancel should be disabled while creating");
      await assertDisabled('[data-testid="template-title"]', "template title should be disabled while creating");
      await assertDisabled('[data-testid="template-body"]', "template body should be disabled while creating");
      await page.keyboard.press("Escape");
      await page.locator('[data-testid="template-create-dialog"]').waitFor({ state: "visible", timeout: 1000 });
    } finally {
      release();
    }
    await page.locator('[data-testid="template-create-dialog"]').waitFor({ state: "hidden" });
  });

  await runTest("Quick action editor shows loading while saving", async () => {
    await page.locator('[data-testid="header-quick-actions-button"]').click();
    await page.locator('[data-testid="quick-actions-manager"]').waitFor({ state: "visible" });
    await page.locator('[data-testid="quick-actions-new"]').click();
    await page.locator('[data-testid="quick-actions-editor"]').waitFor({ state: "visible" });
    await page.locator('[data-testid="editor-name"]').fill("Loading action");
    await page.locator('[data-testid="editor-title-template"]').fill("loading action {{date}}");
    const release = await delayNextPost("/api/quick-actions");
    try {
      await page.locator('[data-testid="editor-save"]').click();
      await assertBusyButton(
        '[data-testid="editor-save"]',
        '[data-testid="editor-save-spinner"]',
        "Creating",
      );
      await assertDisabled('[data-testid="editor-cancel"]', "quick action editor cancel should be disabled while saving");
      await assertDisabled('[data-testid="editor-name"]', "quick action editor name should be disabled while saving");
      await page.keyboard.press("Escape");
      await page.locator('[data-testid="quick-actions-editor"]').waitFor({ state: "visible", timeout: 1000 });
    } finally {
      release();
    }
    await page.locator('[data-testid="quick-actions-editor"]').waitFor({ state: "hidden" });
  });

  await runTest("Quick action manager run button shows loading while creating note", async () => {
    const release = await delayNextPost("/api/quick-actions/**/run");
    const runButton = page.locator('[data-testid="quick-actions-run"]').first();
    try {
      await runButton.click();
      await page
        .locator('[data-testid="quick-actions-run"][data-busy="true"]')
        .waitFor({ state: "visible", timeout: 3000 });
      await page
        .locator('[data-testid="quick-actions-run-spinner"]')
        .waitFor({ state: "visible", timeout: 3000 });
      await assertDisabled('[data-testid="quick-actions-new"]', "new quick action should be disabled while an action is running");
      await assertDisabled('[data-testid="quick-actions-edit"]', "quick action edit should be disabled while an action is running");
      await assertDisabled('[data-testid="quick-actions-delete"]', "quick action delete should be disabled while an action is running");
    } finally {
      release();
    }
    await page.locator('[data-testid="quick-actions-manager"]').waitFor({ state: "hidden" });
  });

  await runTest("Command palette quick action row shows loading while running", async () => {
    await page.request.post(`${baseURL}/api/quick-actions`, {
      data: {
        name: "Palette loading action",
        description: "loading state regression",
        shortcut: null,
        params: {
          kind: "create_note",
          folder: "",
          title_template: "palette loading {{date}}",
          content_template_id: null,
        },
      },
    });
    const release = await delayNextPost("/api/quick-actions/**/run");
    await page.keyboard.press("Meta+Shift+P");
    await page.locator('[data-testid="palette-input"]').fill("Palette loading");
    const row = page.locator('[data-testid="palette-action-item"]').filter({
      hasText: "Palette loading action",
    });
    await row.waitFor({ state: "visible", timeout: 3000 });
    try {
      await row.click();
      await page
        .locator('[data-testid="palette-action-item"][data-busy="true"]')
        .waitFor({ state: "visible", timeout: 3000 });
      await page
        .locator('[data-testid="palette-action-spinner"]')
        .waitFor({ state: "visible", timeout: 3000 });
      await page.keyboard.press("Escape");
      await page.locator('[data-testid="palette-input"]').waitFor({ state: "visible", timeout: 1000 });
    } finally {
      release();
    }
    await page.locator('[data-testid="palette-input"]').waitFor({ state: "hidden" });
  });

  assertConsoleClean(env);
} catch (e) {
  console.error("creation-loading-states e2e failed:", e);
  process.exitCode = 1;
} finally {
  await teardown();
  exitAfter();
}
