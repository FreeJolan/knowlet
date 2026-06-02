// E2E: Chinese right-click delete must confirm after the context menu closes.

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

  await runTest("right-click delete triggers confirmation after menu closes", async () => {
    await page.evaluate(() => {
      window.__knowletConfirmCalls = [];
      window.confirm = (message) => {
        window.__knowletConfirmCalls.push({
          message,
          menuOpen: Boolean(
            document.querySelector('[data-slot="context-menu-content"]'),
          ),
        });
        return true;
      };
    });

    const row = await expectRow(page, "中文删除目标");
    const deleteResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "DELETE" &&
        response.url().includes("/api/notes/") &&
        response.status() < 400,
    );

    await row.click({ button: "right" });
    await page.getByRole("menuitem", { name: "删除", exact: true }).click();
    await deleteResponse;
    await page.waitForTimeout(300);

    const calls = await page.evaluate(() => window.__knowletConfirmCalls);
    assert(calls.length === 1, `expected one confirmation, got ${calls.length}`);
    assert(
      calls[0].message.includes("中文删除目标"),
      `confirmation should name the note, got ${JSON.stringify(calls[0].message)}`,
    );
    assert(
      calls[0].menuOpen === false,
      "delete confirmation should run after the context menu has closed",
    );
    assert(!(await hasRow(page, "中文删除目标")), "deleted note leaves the tree");
  });

  assertConsoleClean(env);
  console.log("✓ no console errors");
} finally {
  await teardown();
  exitAfter();
}
