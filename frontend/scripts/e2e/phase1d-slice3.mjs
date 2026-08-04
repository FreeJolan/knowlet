/**
 * Phase 1 D slice 3 — Properties UI (D3, conservative version).
 *
 * Verifies:
 *   - Panel renders below tags strip on the open note.
 *   - Toggle expand / collapse round-trips through localStorage.
 *   - Aliases chip strip add → persisted to backend → survives reload.
 *   - Aliases chip strip remove → ✕ button drops the chip + PUT.
 *   - Empty input blur doesn't add a blank chip.
 *   - IME-Enter during compose doesn't commit a half-typed alias.
 *   - Created / Updated timestamps render in UTC long form.
 *   - Body autosave path doesn't clobber existing aliases (regression
 *     guard for the tri-state aliases=None semantics).
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const SOURCE_URL =
  "https://example.com/papers/attention?view=full&lang=en#section-2";
const INVALID_SOURCE = "not a valid source";

const env = await setupTestEnv({
  notes: [
    {
      title: "Attention Mechanism",
      body: "Self-attention from the Transformer paper.",
      source: SOURCE_URL,
    },
    {
      title: "Cooking pasta",
      body: "Boil water, add salt, drop pasta.",
      source: INVALID_SOURCE,
    },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

function openerCalls(calls) {
  return calls.filter((call) => call.cmd === "plugin:opener|open_url");
}

try {
  await page.addInitScript(() => {
    const calls = [];
    globalThis.isTauri = true;
    window.__KNOWLET_TAURI_CALLS__ = calls;
    window.__TAURI_INTERNALS__ = {
      invoke: async (cmd, args = {}) => {
        calls.push({ cmd, args });
        if (cmd === "plugin:event|listen") return calls.length;
        return null;
      },
      transformCallback: () => 0,
      unregisterCallback: () => {},
      runCallback: () => {},
      callbacks: new Map(),
      convertFileSrc: (filePath) => filePath,
    };
  });
  // Until the desktop handoff is implemented, target=_blank opens a popup.
  // Close it immediately so the red test cannot leak a real browser page.
  page.on("popup", (popup) => {
    void popup.close().catch(() => {});
  });
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  // Open the Attention note via the file tree.
  await page
    .locator('[role="treeitem"]', { hasText: "Attention Mechanism" })
    .first()
    .click();
  await page.waitForTimeout(400);

  await runTest("Properties toggle lives inline in the crumb row", async () => {
    // Post-2026-05-08 dogfood: the panel was its own card-shaped block
    // that read as too prominent. The toggle now sits as one segment
    // of the metadata crumb, peer to folder · id · updated.
    const toggle = page.locator('[data-testid="properties-toggle"]');
    await toggle.waitFor({ state: "visible", timeout: 3000 });
    // Toggle should be ABOVE the tag strip in DOM order (crumb is above tags).
    const order = await page.evaluate(() => {
      const tag = document.querySelector('[data-testid="tag-strip"]');
      const toggle = document.querySelector('[data-testid="properties-toggle"]');
      if (!tag || !toggle) return "missing";
      return tag.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_PRECEDING
        ? "toggle-above-tags"
        : "toggle-below-tags";
    });
    assert(
      order === "toggle-above-tags",
      `toggle should sit above tags (in the crumb), got: ${order}`,
    );
  });

  await runTest("Note source pill hands the exact URL to Tauri once", async () => {
    const source = page.locator('[data-testid="property-source-pill"]');
    await source.waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await source.getAttribute("href")) === SOURCE_URL,
      "source pill preserves the stored query string and fragment",
    );
    const urlBefore = page.url();
    const titleBefore = await page.locator('[data-testid="note-title"]').textContent();
    const propertiesBefore = await page
      .locator('[data-testid="properties-panel"]')
      .count();
    await page.evaluate(() => {
      window.__KNOWLET_TAURI_CALLS__.length = 0;
    });

    await source.click();
    await page.waitForTimeout(100);

    const calls = openerCalls(
      await page.evaluate(() => window.__KNOWLET_TAURI_CALLS__),
    );
    assert(calls.length === 1, `source pill invokes opener once, got ${calls.length}`);
    assert(
      calls[0]?.args?.url === SOURCE_URL,
      `source pill passes the exact URL, got ${JSON.stringify(calls[0]?.args)}`,
    );
    assert(page.url() === urlBefore, "source pill keeps the Knowlet URL unchanged");
    assert(
      (await page.locator('[data-testid="note-title"]').textContent()) === titleBefore,
      "source pill keeps the current note selected",
    );
    assert(
      (await page.locator('[data-testid="properties-panel"]').count()) ===
        propertiesBefore,
      "source pill keeps Properties collapsed",
    );
  });

  await runTest("Default collapsed — toggle reveals only created (+ source if any)", async () => {
    // Collapsed: no [data-testid="properties-panel"] in the DOM.
    const beforeCount = await page
      .locator('[data-testid="properties-panel"]')
      .count();
    assert(beforeCount === 0, `collapsed should hide content node, got ${beforeCount}`);
    await page.locator('[data-testid="properties-toggle"]').click();
    await page.waitForTimeout(150);
    const panel = page.locator('[data-testid="properties-panel"]');
    await panel.waitFor({ state: "visible", timeout: 1000 });
    // Per Claude-Design 2026-05-09 redesign: panel only carries
    // `created` and (optionally) `source` full URL. `updated` lives
    // in the kicker; `aliases` lives in row C; both must NOT
    // duplicate into the panel.
    const updatedExists = await page
      .locator('[data-testid="property-updated"]')
      .count();
    assert(updatedExists === 0, "updated MUST not be in panel (it's in kicker)");
    const aliasesInPanel = await page
      .locator('[data-testid="property-aliases"]')
      .count();
    assert(
      aliasesInPanel === 0,
      "aliases MUST not be in panel (they live in row C)",
    );
    const created = page.locator('[data-testid="property-created"]');
    await created.waitFor({ state: "visible", timeout: 1000 });
    const txt = (await created.textContent()) ?? "";
    assert(/UTC/.test(txt), `created should be UTC long form, got "${txt}"`);
  });

  await runTest("Expanded Note source hands the exact URL to Tauri once", async () => {
    await page.waitForTimeout(320);
    const source = page.locator('[data-testid="property-source"]');
    await source.waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await source.getAttribute("href")) === SOURCE_URL,
      "expanded source preserves the stored query string and fragment",
    );
    const urlBefore = page.url();
    const titleBefore = await page.locator('[data-testid="note-title"]').textContent();
    await page.evaluate(() => {
      window.__KNOWLET_TAURI_CALLS__.length = 0;
    });

    await source.click();
    await page.waitForTimeout(100);

    const calls = openerCalls(
      await page.evaluate(() => window.__KNOWLET_TAURI_CALLS__),
    );
    assert(calls.length === 1, `expanded source invokes opener once, got ${calls.length}`);
    assert(
      calls[0]?.args?.url === SOURCE_URL,
      `expanded source passes the exact URL, got ${JSON.stringify(calls[0]?.args)}`,
    );
    assert(page.url() === urlBefore, "expanded source keeps the Knowlet URL unchanged");
    assert(
      (await page.locator('[data-testid="note-title"]').textContent()) === titleBefore,
      "expanded source keeps the current note selected",
    );
    assert(
      await page.locator('[data-testid="properties-panel"]').isVisible(),
      "expanded source keeps Properties open",
    );
  });

  await runTest("Add alias 'Self-Attention' via chip strip", async () => {
    await page.locator('[data-testid="alias-add-button"]').click();
    const input = page.locator('[data-testid="alias-add-input"]');
    await input.waitFor({ state: "visible", timeout: 1000 });
    await input.fill("Self-Attention");
    await input.press("Enter");
    await page.waitForTimeout(400); // optimistic + network
    const chip = page
      .locator('[data-testid="alias-chip"][data-alias="Self-Attention"]')
      .first();
    await chip.waitFor({ state: "visible", timeout: 2000 });
  });

  await runTest("Add second alias '注意力' (Chinese)", async () => {
    // Input is still in edit mode after first commit (multi-add flow).
    const input = page.locator('[data-testid="alias-add-input"]');
    const visible = await input.isVisible();
    if (!visible) {
      await page.locator('[data-testid="alias-add-button"]').click();
      await input.waitFor({ state: "visible", timeout: 1000 });
    }
    await input.fill("注意力");
    await input.press("Enter");
    await page.waitForTimeout(400);
    const chip = page
      .locator('[data-testid="alias-chip"][data-alias="注意力"]')
      .first();
    await chip.waitFor({ state: "visible", timeout: 2000 });
  });

  await runTest("Aliases survive a full page reload", async () => {
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    await page
      .locator('[role="treeitem"]', { hasText: "Attention Mechanism" })
      .first()
      .click();
    await page.waitForTimeout(400);
    await page
      .locator('[data-testid="alias-chip"][data-alias="Self-Attention"]')
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
    await page
      .locator('[data-testid="alias-chip"][data-alias="注意力"]')
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("Remove alias via ✕ button", async () => {
    await page
      .locator('[data-testid="alias-chip-remove"][data-alias="注意力"]')
      .first()
      .click();
    await page.waitForTimeout(400);
    const remaining = await page
      .locator('[data-testid="alias-chip"][data-alias="注意力"]')
      .count();
    assert(remaining === 0, `chip should be gone, still ${remaining}`);
    // Self-Attention still there.
    await page
      .locator('[data-testid="alias-chip"][data-alias="Self-Attention"]')
      .first()
      .waitFor({ state: "visible", timeout: 1000 });
  });

  await runTest("Body autosave does NOT clobber aliases (regression)", async () => {
    // Edit body; autosave's PUT must keep aliases intact via tri-state
    // (frontend echoes current aliases; backend's None-means-preserve
    // is a second line of defense).
    const editor = page.locator(".cm-editor .cm-content").first();
    await editor.waitFor({ state: "visible", timeout: 2000 });
    await editor.click();
    await page.keyboard.press("End");
    await page.keyboard.type(" plus an extra sentence.");
    await page.waitForTimeout(1500); // wait for debounce + flush
    // Sanity: chip still present.
    await page
      .locator('[data-testid="alias-chip"][data-alias="Self-Attention"]')
      .first()
      .waitFor({ state: "visible", timeout: 2000 });
    // Reload + verify on disk.
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    await page
      .locator('[role="treeitem"]', { hasText: "Attention Mechanism" })
      .first()
      .click();
    await page.waitForTimeout(400);
    await page
      .locator('[data-testid="alias-chip"][data-alias="Self-Attention"]')
      .first()
      .waitFor({ state: "visible", timeout: 3000 });
  });

  await runTest("Toggle collapse hides rows; persists across reload", async () => {
    await page.locator('[data-testid="properties-toggle"]').click();
    await page.waitForTimeout(200);
    // Collapsed: content node is unmounted (returns null), not just hidden.
    const collapsedCount = await page
      .locator('[data-testid="properties-panel"]')
      .count();
    assert(collapsedCount === 0, `panel should be unmounted, got ${collapsedCount}`);
    // Reload and confirm collapse state survives.
    await page.reload({ waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    await page
      .locator('[role="treeitem"]', { hasText: "Attention Mechanism" })
      .first()
      .click();
    await page.waitForTimeout(400);
    const afterReload = await page
      .locator('[data-testid="properties-panel"]')
      .count();
    assert(afterReload === 0, `collapse state must persist post-reload, got ${afterReload}`);
    // Re-expand for next tests.
    await page.locator('[data-testid="properties-toggle"]').click();
    await page.waitForTimeout(200);
    await page
      .locator('[data-testid="properties-panel"]')
      .waitFor({ state: "visible", timeout: 1000 });
  });

  await runTest("IME compose Enter does NOT commit half-typed alias", async () => {
    await page.locator('[data-testid="alias-add-button"]').click();
    const input = page.locator('[data-testid="alias-add-input"]');
    await input.waitFor({ state: "visible", timeout: 1000 });
    await input.fill("zhuyili");
    const aliasChipsBefore = await page
      .locator('[data-testid="alias-chip"]')
      .count();
    // Simulate IME-Enter (keyCode=229 + isComposing).
    await page.evaluate(() => {
      const el = document.querySelector('[data-testid="alias-add-input"]');
      if (!(el instanceof HTMLInputElement)) return;
      el.dispatchEvent(new CompositionEvent("compositionstart"));
      const ev = new KeyboardEvent("keydown", {
        key: "Enter",
        code: "Enter",
        keyCode: 229,
        which: 229,
        bubbles: true,
        cancelable: true,
        composed: true,
      });
      Object.defineProperty(ev, "isComposing", { get: () => true });
      el.dispatchEvent(ev);
      el.dispatchEvent(new CompositionEvent("compositionend"));
    });
    await page.waitForTimeout(300);
    const aliasChipsAfter = await page
      .locator('[data-testid="alias-chip"]')
      .count();
    assert(
      aliasChipsAfter === aliasChipsBefore,
      `IME-Enter must not commit; before=${aliasChipsBefore} after=${aliasChipsAfter}`,
    );
    // Press Esc to clean up edit mode.
    await input.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("Invalid Note source is blocked in place with a visible failure", async () => {
    await page
      .locator('[role="treeitem"]', { hasText: "Cooking pasta" })
      .first()
      .click();
    await page.waitForTimeout(300);
    const source = page.locator('[data-testid="property-source-pill"]');
    await source.waitFor({ state: "visible", timeout: 3000 });
    const urlBefore = page.url();
    await page.evaluate(() => {
      window.__KNOWLET_TAURI_CALLS__.length = 0;
    });

    await source.click();
    await page.waitForTimeout(100);

    const calls = openerCalls(
      await page.evaluate(() => window.__KNOWLET_TAURI_CALLS__),
    );
    assert(calls.length === 0, "invalid source never reaches the native opener");
    assert(page.url() === urlBefore, "invalid source does not navigate the webview");
    assert(
      (await page.locator('[data-testid="note-title"]').textContent()) ===
        "Cooking pasta",
      "invalid source keeps the current note selected",
    );
    const failure = page.locator('[data-testid="external-link-error"]');
    await failure.waitFor({ state: "visible", timeout: 1500 });
    assert(Boolean((await failure.textContent())?.trim()), "failure notice explains the block");
  });

  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("phase1d-slice3 e2e failed:", e);
  await teardown();
  exitAfter(1);
}
