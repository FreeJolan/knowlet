// E2E: Chinese right-click delete uses an app-owned confirmation dialog.

import {
  assert,
  assertConsoleClean,
  exitAfter,
  expectRow,
  hasRow,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    { title: "中文删除目标", body: "这条笔记用于右键删除回归测试。", folder: "测试" },
  ],
  folders: ["测试"],
  language: "zh",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("right-click delete confirms in-app without opening the note", async () => {
    await page.evaluate(() => {
      window.__knowletConfirmCalls = 0;
      window.confirm = () => {
        window.__knowletConfirmCalls += 1;
        throw new Error("File tree delete must not use window.confirm");
      };
    });

    const row = await expectRow(page, "中文删除目标");

    await row.click({ button: "right" });
    await page.getByRole("menuitem", { name: "删除", exact: true }).click();

    const dialog = page.locator('[data-testid="file-tree-delete-confirm"]');
    await dialog.waitFor({ state: "visible" });
    assert(
      await dialog.getByText("中文删除目标").isVisible(),
      "delete dialog should name the target note",
    );
    assert(
      (await page.getByRole("tab", { name: /中文删除目标/ }).count()) === 0,
      "opening the delete menu item must not activate the note row underneath",
    );
    assert(
      (await page.evaluate(() => window.__knowletConfirmCalls)) === 0,
      "delete path should not call native window.confirm",
    );

    await dialog.getByRole("button", { name: "取消" }).click();
    await dialog.waitFor({ state: "hidden" });
    assert(await hasRow(page, "中文删除目标"), "cancel keeps the note in the tree");

    await row.click({ button: "right" });
    await page.getByRole("menuitem", { name: "删除", exact: true }).click();
    await dialog.waitFor({ state: "visible" });

    const deleteResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "DELETE" &&
        response.url().includes("/api/notes/") &&
        response.status() < 400,
    );
    await dialog.getByRole("button", { name: "移到垃圾桶" }).click();
    await deleteResponse;
    await page.waitForTimeout(300);

    assert(!(await hasRow(page, "中文删除目标")), "deleted note leaves the tree");
  });

  assertConsoleClean(env);
  console.log("✓ no console errors");
} finally {
  await teardown();
  exitAfter();
}
