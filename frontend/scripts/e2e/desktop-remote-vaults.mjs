// E2E: desktop launcher restores an existing remote Drive Vault with mocked Tauri IPC.

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const remoteVaults = [
  {
    vault_id: "01REMOTEVAULTID000000000000",
    name: "Research Vault",
    updated_at: "2026-06-03T08:00:00Z",
    last_device_label: "MacBook",
    item_count: 12,
    source: "registry",
  },
];

const env = await setupTestEnv({ notes: [], language: "en" });
const { page, baseURL, teardown } = env;

try {
  await page.addInitScript((vaults) => {
    const calls = [];
    globalThis.isTauri = true;
    window.__KNOWLET_TAURI_CALLS__ = calls;
    window.__TAURI_INTERNALS__ = {
      invoke: async (cmd, args = {}) => {
        calls.push({ cmd, args });
        if (cmd === "desktop_recent_vaults") return [];
        if (cmd === "desktop_drive_account_status") {
          return {
            connected: true,
            user_email: "meowcassiel@gmail.com",
            user_display_name: "Jolan",
          };
        }
        if (cmd === "desktop_remote_vaults") return [...vaults];
        if (cmd === "desktop_choose_vault_parent") return "/Users/jolan/Documents";
        if (cmd === "desktop_restore_remote_vault") {
          await new Promise((resolve) => setTimeout(resolve, 400));
          return {
            backend_url: "http://127.0.0.1:9999",
            vault: `${args.parent}/${args.name}`,
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
            message: "Ready to restore.",
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
  }, remoteVaults);

  await page.goto(`${baseURL}/?desktop-launcher=1`, { waitUntil: "networkidle" });

  await runTest("remote Drive vaults are discoverable from the launcher", async () => {
    await page.getByText("Restore from Drive").waitFor({ state: "visible", timeout: 3000 });
    await page.getByText("Connected as meowcassiel@gmail.com").waitFor({
      state: "visible",
      timeout: 3000,
    });
    await page.getByText("Research Vault").waitFor({ state: "visible", timeout: 3000 });
    await page.getByText("12 synced items").waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("restoring a remote vault asks for a local folder and opens it", async () => {
    await page.getByRole("button", { name: "Restore Research Vault" }).click();
    const dialog = page.locator('[data-testid="desktop-restore-vault-dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    await page.getByRole("button", { name: "Choose Location" }).click();
    await page.getByRole("button", { name: "Restore and Open" }).click();

    const overlay = page.locator('[data-testid="desktop-vault-switch-overlay"]');
    await overlay.waitFor({ state: "visible", timeout: 1000 });
    const overlayText = await overlay.textContent();
    assert(
      overlayText?.includes("Restoring Research Vault"),
      `restore overlay names the remote vault — got ${JSON.stringify(overlayText)}`,
    );
    await overlay.waitFor({ state: "hidden", timeout: 3000 });

    const calls = await page.evaluate(() => window.__KNOWLET_TAURI_CALLS__);
    const restore = calls.filter((c) => c.cmd === "desktop_restore_remote_vault").at(-1);
    assert(
      restore?.args?.vaultId === "01REMOTEVAULTID000000000000",
      "restore command receives remote vault id",
    );
    assert(restore?.args?.parent === "/Users/jolan/Documents", "restore command receives parent");
    assert(restore?.args?.name === "Research Vault", "restore command defaults local name");
  });

  await runTest("remote vault panel is opaque and hit-testable", async () => {
    const panel = page.locator('[data-testid="desktop-remote-vaults-panel"]');
    const background = await panel.evaluate((el) => getComputedStyle(el).backgroundColor);
    assert(background !== "rgba(0, 0, 0, 0)", `panel has opaque background: ${background}`);

    const box = await panel.boundingBox();
    assert(Boolean(box), "remote vault panel has a layout box");
    const hit = await page.evaluate(({ x, y }) => {
      const el = document.elementFromPoint(x, y);
      return el
        ?.closest('[data-testid="desktop-remote-vaults-panel"]')
        ?.getAttribute("data-testid");
    }, {
      x: box.x + box.width / 2,
      y: box.y + box.height / 2,
    });
    assert(hit === "desktop-remote-vaults-panel", `elementFromPoint hits panel — got ${hit}`);
  });

  assertConsoleClean(env);
  console.log("✓ no console errors");
} finally {
  await teardown();
  exitAfter();
}
