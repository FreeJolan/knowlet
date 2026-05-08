// E2E: inline edit paths that the earlier "happy-path fill+Enter" suites
// missed. The user's pinyin-input test session caught:
//   - input visually visible but not actually focused
//   - Enter during IME composition committing the half-typed name AND
//     bubbling to arborist's tree handler, which then enters edit mode
//     on a sibling row.
// We assert focus explicitly and use real keyboard events + composition
// events instead of `input.fill()`.

import {
  assert,
  exitAfter,
  expectFocused,
  hasRow,
  runTest,
  setupTestEnv,
  simulateIMEComposition,
  typeInto,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "alpha", folder: "lab" }],
  folders: ["lab", "other"],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("toolbar 'New note' input gets focus immediately", async () => {
    await page.click('button[aria-label="New note"]');
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await expectFocused(page, input, "new-note input is focused");
    // Cancel for cleanup.
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("right-click Rename input gets focus + KEEPS it through menu close", async () => {
    const row = page.locator(".group").filter({ hasText: "alpha" }).first();
    await row.click({ button: "right" });
    await page.getByRole("menuitem", { name: "Rename" }).click();
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    // Radix returns focus to its trigger ~80ms after menu close. Earlier
    // tests only checked at +20ms and missed the steal — assert at +200ms
    // and again at +500ms.
    await expectFocused(page, input, "rename input focused immediately");
    await page.waitForTimeout(200);
    await expectFocused(page, input, "rename input still focused after Radix close");
    await page.waitForTimeout(300);
    await expectFocused(page, input, "rename input still focused after 500 ms");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("inline-edit input has a visible caret-color (not text color)", async () => {
    await page.click('button[aria-label="New note"]');
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    const styles = await input.evaluate((el) => {
      const cs = getComputedStyle(el);
      return { color: cs.color, caretColor: cs.caretColor };
    });
    assert(
      styles.caretColor !== styles.color,
      `caret-color (${styles.caretColor}) must differ from text color (${styles.color}) so the cursor is visible`,
    );
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest(
    "real keystrokes type into new-note input + Enter commits exactly that text",
    async () => {
      await page.click('button[aria-label="New note"]');
      const input = page.locator('input[data-rename-input="true"]');
      await input.waitFor({ state: "visible", timeout: 3000 });
      await typeInto(page, input, "design");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(800);
      assert(await hasRow(page, "design"), "row exists with the typed name");
      // Critical: NO other row should have been pulled into edit mode.
      const inputCount = await page.locator('input[data-rename-input="true"]').count();
      assert(inputCount === 0, `no rogue rename input survived (got ${inputCount})`);
    },
  );

  await runTest(
    "new note stays visible across slow backend (no transient disappearance)",
    async () => {
      await page.click('button[aria-label="New note"]');
      const input = page.locator('input[data-rename-input="true"]');
      await input.waitFor({ state: "visible", timeout: 3000 });
      await typeInto(page, input, "persistent");
      // The placeholder row must stay visible while the backend POST is
      // in flight + during the tree refetch — no gap where neither the
      // placeholder nor the real note is on screen.
      await page.keyboard.press("Enter");
      // Sample at multiple timestamps. At every point, either the
      // placeholder row OR the real note must be in the tree. Never both
      // missing.
      for (const wait of [10, 30, 80, 150, 400, 800, 1500]) {
        await page.waitForTimeout(wait);
        const present = await hasRow(page, "persistent");
        assert(present, `'persistent' row must be in tree at +${wait}ms`);
      }
    },
  );

  await runTest(
    "IME composition: Enter during candidate confirm does NOT submit",
    async () => {
      await page.click('button[aria-label="New note"]');
      const input = page.locator('input[data-rename-input="true"]');
      await input.waitFor({ state: "visible", timeout: 3000 });
      // Simulate user typing pinyin for 设计 — composition starts,
      // Enter confirms the candidate. Our input must treat that Enter
      // as IME-only and stay in edit mode.
      await simulateIMEComposition(page, input, "设计");
      // After composition end, user presses Enter for real.
      await page.waitForTimeout(150);
      // The input should still be in edit mode after the IME Enter —
      // verify by checking the input is still in the DOM AND focused.
      const stillEditing = await page
        .locator('input[data-rename-input="true"]')
        .count();
      assert(stillEditing === 1, "input still mounted after IME Enter");
      await expectFocused(page, input, "input still focused after IME Enter");
      // Now press Enter for real (no composition) to commit.
      await page.keyboard.press("Enter");
      await page.waitForTimeout(800);
      assert(await hasRow(page, "设计"), "Chinese title committed correctly");
    },
  );

  await runTest(
    "Enter inside input does NOT bubble to tree (no rogue edit elsewhere)",
    async () => {
      // Pre-condition: select a different row so arborist has a focused
      // node that, if it received an Enter, would enter edit mode.
      const labRow = page.locator(".group").filter({ hasText: "lab" }).first();
      await labRow.click();
      await page.waitForTimeout(100);

      await page.click('button[aria-label="New note"]');
      const input = page.locator('input[data-rename-input="true"]');
      await input.waitFor({ state: "visible", timeout: 3000 });
      await typeInto(page, input, "isolated");
      await page.keyboard.press("Enter");
      await page.waitForTimeout(800);
      assert(await hasRow(page, "isolated"), "new note created");
      const remainingInputs = await page
        .locator('input[data-rename-input="true"]')
        .count();
      assert(
        remainingInputs === 0,
        `Enter must not have bubbled to a sibling row (got ${remainingInputs} stray inputs)`,
      );
    },
  );

  await runTest(
    "rename does NOT flash the old name between Enter and refetch",
    async () => {
      // The optimistic cache update should make the new title appear on
      // the same frame as Enter. Sample row text at multiple short
      // timestamps; the OLD title must not appear at any of them.
      // Earlier tests may have collapsed the `lab` folder — make sure
      // alpha is reachable before we right-click it.
      if (!(await hasRow(page, "alpha"))) {
        await page.locator(".group").filter({ hasText: "lab" }).first().click();
        await page.waitForTimeout(150);
      }
      const row = page.locator(".group").filter({ hasText: "alpha" }).first();
      await row.click({ button: "right" });
      await page.getByRole("menuitem", { name: "Rename" }).click();
      const input = page.locator('input[data-rename-input="true"]');
      await input.waitFor({ state: "visible", timeout: 3000 });
      await typeInto(page, input, "alpha-renamed");
      await page.keyboard.press("Enter");
      // Sample at progressively-later checkpoints. At every one the
      // tree must show "alpha-renamed" (optimistic), never plain
      // "alpha" alone (would be the flash).
      for (const wait of [0, 30, 80, 150, 400, 800]) {
        await page.waitForTimeout(wait);
        const hasNew = await hasRow(page, "alpha-renamed");
        assert(hasNew, `'alpha-renamed' must be present at +${wait}ms`);
      }
    },
  );

  await runTest("F2 on focused row enters rename mode", async () => {
    if (!(await hasRow(page, "alpha"))) {
      await page.locator(".group").filter({ hasText: "lab" }).first().click();
      await page.waitForTimeout(150);
    }
    // Click alpha to focus it (in arborist's terms).
    await page.locator(".group").filter({ hasText: "alpha" }).first().click();
    await page.waitForTimeout(150);
    await page.keyboard.press("F2");
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 2000 });
    await expectFocused(page, input, "F2 input is focused");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("F2 inside an existing input does NOT cascade", async () => {
    // While the user is typing in the rename input, F2 must do nothing.
    await page.click('button[aria-label="New note"]');
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 2000 });
    await page.keyboard.press("F2");
    await page.waitForTimeout(150);
    const stillOne = await page.locator('input[data-rename-input="true"]').count();
    assert(stillOne === 1, `F2 inside input must not open a second editor (got ${stillOne})`);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(200);
  });

  await runTest("Esc cancels without committing", async () => {
    await page.click('button[aria-label="New note"]');
    const input = page.locator('input[data-rename-input="true"]');
    await input.waitFor({ state: "visible", timeout: 3000 });
    await typeInto(page, input, "phantom");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(400);
    assert(!(await hasRow(page, "phantom")), "phantom row not in tree");
    const inputs = await page.locator('input[data-rename-input="true"]').count();
    assert(inputs === 0, "input dismissed");
  });

  await runTest(
    "tree rename of currently-open note: NoteView h1 updates immediately (regression)",
    async () => {
      // 2026-05-09 dogfood: renaming the open note via the file tree
      // updated the tree row but NoT the right-pane <h1> until the
      // user clicked away. Root cause: FileTree's renameNoteM only
      // patched QK.tree, not QK.note(id) — NoteView's useQuery served
      // the stale cached note. Fix: optimistic patch on both caches.
      // Open lab/alpha first.
      if (!(await hasRow(page, "alpha"))) {
        await page.locator(".group").filter({ hasText: "lab" }).first().click();
        await page.waitForTimeout(150);
      }
      await page.locator(".group").filter({ hasText: "alpha" }).first().click();
      await page.waitForTimeout(300);
      const titleH1 = page.locator('[data-testid="note-title"]').first();
      await titleH1.waitFor({ state: "visible", timeout: 2000 });
      const before = (await titleH1.textContent()) ?? "";
      assert(/alpha/.test(before), `setup: h1 should show alpha, got "${before}"`);
      // Rename via right-click → Rename.
      await page.locator(".group").filter({ hasText: "alpha" }).first().click({ button: "right" });
      await page.getByRole("menuitem", { name: "Rename" }).click();
      const input = page.locator('input[data-rename-input="true"]');
      await input.waitFor({ state: "visible", timeout: 2000 });
      await typeInto(page, input, "alpha-renamed-from-tree");
      await page.keyboard.press("Enter");
      // The NoteView h1 must reflect the new title within the next
      // few frames — same render cycle as the optimistic patch, no
      // refetch needed.
      await page.waitForFunction(
        () => {
          const h1 = document.querySelector('[data-testid="note-title"]');
          return h1 && /alpha-renamed-from-tree/.test(h1.textContent ?? "");
        },
        null,
        { timeout: 1500, polling: 50 },
      );
      const after = (await titleH1.textContent()) ?? "";
      assert(
        /alpha-renamed-from-tree/.test(after),
        `h1 must show new title without page click — got "${after}"`,
      );
    },
  );

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
