// E2E: centered empty-state creation affordances for notes + templates.

import { assert, exitAfter, hasRow, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [],
  folders: [],
  language: "en",
});
const { page, baseURL, teardown } = env;

function countRegularNotes(folder) {
  let count = folder.notes?.length ?? 0;
  for (const sub of folder.folders ?? []) {
    if (sub.name === "_templates") continue;
    count += countRegularNotes(sub);
  }
  return count;
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("empty notes state opens and cancels New Document", async () => {
    await page
      .locator('[data-testid="file-tree-empty-state"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="file-tree-empty-new-note"]').click();
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="dialog-template-picker"]').click();
    await page
      .locator('[data-testid="new-doc-template-create"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="new-doc-template-create"]').click();
    await page
      .locator('[data-testid="template-create-dialog"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="template-create-cancel"]').click();
    await page
      .locator('[data-testid="new-document-dialog"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="new-document-cancel"]').click();
    await page
      .locator('[data-testid="file-tree-empty-state"]')
      .waitFor({ state: "visible", timeout: 3000 });
    const tree = await (await page.request.get(`${baseURL}/api/tree`)).json();
    assert(
      countRegularNotes(tree) === 0,
      `canceling New Document should not create notes — got ${JSON.stringify(tree)}`,
    );
  });

  await runTest("empty notes state creates a folder", async () => {
    await page.locator('[data-testid="file-tree-empty-new-folder"]').click();
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await input.fill("inbox");
    await input.press("Enter");
    await page.waitForTimeout(800);
    assert(await hasRow(page, "inbox"), "inbox folder appears from empty state");
  });

  await runTest("empty templates state cancels without writing", async () => {
    await page.locator('[data-testid="activity-bar-templates"]').click();
    await page
      .locator('[data-testid="templates-empty-state"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="template-empty-new-template"]').click();
    await page
      .locator('[data-testid="template-create-dialog"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="template-title"]').fill("ghost template");
    await page.locator('[data-testid="template-create-cancel"]').click();
    await page
      .locator('[data-testid="templates-empty-state"]')
      .waitFor({ state: "visible", timeout: 3000 });
    const templates = await (await page.request.get(`${baseURL}/api/templates`)).json();
    assert(
      templates.length === 0,
      `canceling template creation should not write templates — got ${JSON.stringify(templates)}`,
    );
  });

  await runTest("empty templates state creates a real template", async () => {
    await page.locator('[data-testid="template-empty-new-template"]').click();
    await page
      .locator('[data-testid="template-create-dialog"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="template-title"]').fill("meeting template");
    await page.locator('[data-testid="template-body"]').fill("# {{title}}\n\n## Notes\n");
    await page.locator('[data-testid="template-create-submit"]').click();
    await page.waitForTimeout(800);
    const templates = await (await page.request.get(`${baseURL}/api/templates`)).json();
    assert(
      templates.some((tpl) => tpl.title === "meeting template"),
      `meeting template should be created — got ${JSON.stringify(templates)}`,
    );
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll('[role="tree"] .group')).some(
          (el) => (el.textContent ?? "").trim() === "meeting template",
        ),
      null,
      { timeout: 4000, polling: 100 },
    );
  });

  if (env.errors.length > 0) {
    console.log("✗ no console errors");
    for (const e of env.errors) console.log("  ", e.type, e.text);
    process.exitCode = 1;
  } else {
    console.log("✓ no console errors");
  }
} finally {
  await teardown();
  exitAfter();
}
