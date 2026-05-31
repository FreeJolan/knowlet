// E2E: desktop vault launcher deletion UX with mocked Tauri IPC.

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const initialRecent = [
  {
    name: "Research Vault",
    parent: "/Users/jolan/Documents",
    path: "/Users/jolan/Documents/Research Vault",
  },
  {
    name: "Archive Vault",
    parent: "/Users/jolan/Documents",
    path: "/Users/jolan/Documents/Archive Vault",
  },
];

const env = await setupTestEnv({ notes: [], language: "en" });
const { page, baseURL, teardown } = env;

try {
  await page.addInitScript((recentVaults) => {
    const recent = [...recentVaults];
    const calls = [];
    globalThis.isTauri = true;
    window.__KNOWLET_TAURI_CALLS__ = calls;
    window.__TAURI_INTERNALS__ = {
      invoke: async (cmd, args = {}) => {
        calls.push({ cmd, args });
        if (cmd === "desktop_recent_vaults") return [...recent];
        if (cmd === "desktop_delete_vault") {
          const idx = recent.findIndex((v) => v.path === args.path);
          if (idx >= 0) recent.splice(idx, 1);
          return {
            forgotten: idx >= 0,
            deleted_local_files: Boolean(args.deleteLocalFiles),
          };
        }
        if (cmd === "desktop_preview_new_vault") {
          return {
            status: "ready",
            name: String(args.name ?? ""),
            parent: String(args.parent ?? ""),
            target: `${args.parent}/${args.name}`,
            can_create: true,
            requires_empty_dir_confirmation: false,
            message: "Ready to create.",
            suggested_name: null,
          };
        }
        return null;
      },
      transformCallback: () => 0,
      unregisterCallback: () => {},
      runCallback: () => {},
      callbacks: new Map(),
      convertFileSrc: (filePath) => filePath,
    };
  }, initialRecent);

  await page.goto(`${baseURL}/?desktop-launcher=1`, { waitUntil: "networkidle" });

  await runTest("recent vault delete opens a clear default-safe dialog", async () => {
    await page.getByText("Research Vault").waitFor({ state: "visible", timeout: 3000 });
    await page.getByLabel("Remove Research Vault").click();

    const dialog = page.locator('[data-testid="desktop-delete-vault-dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    const text = await dialog.textContent();
    assert(
      text?.includes("only forgets this vault on this device"),
      `dialog explains default behavior — got ${JSON.stringify(text)}`,
    );
    assert(
      text?.includes("Cloud sync data is kept"),
      `dialog explains cloud data is kept — got ${JSON.stringify(text)}`,
    );
    const confirm = page.locator('[data-testid="desktop-delete-vault-confirm"]');
    assert((await confirm.textContent())?.includes("Remove from List"), "default action forgets only");
  });

  await runTest("confirming without checkbox forgets the vault only", async () => {
    await page.locator('[data-testid="desktop-delete-vault-confirm"]').click();
    await page.locator('[data-testid="desktop-delete-vault-dialog"]').waitFor({
      state: "hidden",
      timeout: 3000,
    });
    assert(
      (await page.getByText("Research Vault").count()) === 0,
      "deleted recent vault row disappears",
    );
    assert(
      (await page.getByText("Archive Vault").count()) === 1,
      "other recent vault remains",
    );
    const calls = await page.evaluate(() => window.__KNOWLET_TAURI_CALLS__);
    const lastDelete = calls.filter((c) => c.cmd === "desktop_delete_vault").at(-1);
    assert(lastDelete?.args?.path === initialRecent[0].path, "delete command receives vault path");
    assert(lastDelete?.args?.deleteLocalFiles === false, "default does not delete local files");
  });

  await runTest("checkbox switches confirmation to move local folder to Trash", async () => {
    await page.getByLabel("Remove Archive Vault").click();
    await page.locator('[data-testid="desktop-delete-local-files"]').check();
    const confirm = page.locator('[data-testid="desktop-delete-vault-confirm"]');
    assert((await confirm.textContent())?.includes("Move to Trash"), "checked action changes label");
    await confirm.click();
    await page.locator('[data-testid="desktop-delete-vault-dialog"]').waitFor({
      state: "hidden",
      timeout: 3000,
    });

    const calls = await page.evaluate(() => window.__KNOWLET_TAURI_CALLS__);
    const lastDelete = calls.filter((c) => c.cmd === "desktop_delete_vault").at(-1);
    assert(lastDelete?.args?.path === initialRecent[1].path, "trash command receives vault path");
    assert(lastDelete?.args?.deleteLocalFiles === true, "checked action requests local trash");
    await page.getByText("No recent vaults yet.").waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("launcher panel is opaque and hit-testable", async () => {
    const panel = page.locator('[data-testid="desktop-recent-vaults-panel"]');
    const background = await panel.evaluate((el) => getComputedStyle(el).backgroundColor);
    assert(background !== "rgba(0, 0, 0, 0)", `panel has opaque background: ${background}`);

    const box = await panel.boundingBox();
    assert(Boolean(box), "recent panel has a layout box");
    const hit = await page.evaluate(({ x, y }) => {
      const el = document.elementFromPoint(x, y);
      return el?.closest('[data-testid="desktop-recent-vaults-panel"]')?.getAttribute("data-testid");
    }, {
      x: box.x + box.width / 2,
      y: box.y + box.height / 2,
    });
    assert(hit === "desktop-recent-vaults-panel", `elementFromPoint hits panel — got ${hit}`);
  });

  assertConsoleClean(env);
  console.log("✓ no console errors");
} finally {
  await teardown();
  exitAfter();
}
