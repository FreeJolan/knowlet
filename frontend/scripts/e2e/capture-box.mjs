// E2E: Phase 3 Stage 3 — CaptureBox.
//
// Tests the ⌘⇧V global shortcut, the modal mount, the three-button
// decide flow on a file-uploaded capsule (no network needed), and
// the resulting Note / Draft on disk. URL-fetch path is NOT tested
// here because it requires outbound network; that's covered by the
// backend integration tests (tests/test_web_capture_flow.py).
//
// The earlier "我按了快捷键没反应" dogfood report is the literal
// reason this file exists.

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [],
  folders: [],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Cmd+Shift+V opens the CaptureBox modal", async () => {
    await page.keyboard.press("Meta+Shift+V");
    await page.waitForTimeout(300);
    const modal = page.locator('[data-testid="capture-box"]');
    await modal.waitFor({ state: "visible", timeout: 3000 });
    // URL input is focused on open.
    const urlInput = page.locator('[data-testid="capture-url-input"]');
    await urlInput.waitFor({ state: "visible", timeout: 1000 });
  });

  await runTest("Escape closes the modal", async () => {
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    const modal = page.locator('[data-testid="capture-box"]');
    const count = await modal.count();
    // Either gone from the DOM or hidden — both acceptable.
    if (count > 0) {
      const visible = await modal.isVisible();
      assert(!visible, "modal hidden after Escape");
    }
  });

  await runTest("File upload renders capsule with three decision buttons", async () => {
    await page.keyboard.press("Meta+Shift+V");
    await page.waitForTimeout(300);
    // Drop a markdown file via the file input (more reliable than DnD).
    const fileInput = page.locator('[data-testid="capture-file-input"]');
    await fileInput.setInputFiles({
      name: "demo.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Hello E2E\n\nSome body content from a file.\n"),
    });
    // Wait for capsule preview.
    const capsule = page.locator('[data-testid="capture-capsule"]');
    await capsule.waitFor({ state: "visible", timeout: 5000 });
    // Title extracted from first heading.
    const text = await capsule.innerText();
    assert(text.includes("Hello E2E"), `capsule shows title: got "${text.slice(0, 120)}"`);
    // All three decision buttons visible.
    await page
      .locator('[data-testid="capture-decide-knowledge"]')
      .waitFor({ state: "visible", timeout: 1000 });
    await page
      .locator('[data-testid="capture-decide-reference"]')
      .waitFor({ state: "visible", timeout: 1000 });
    await page
      .locator('[data-testid="capture-decide-defer"]')
      .waitFor({ state: "visible", timeout: 1000 });
  });

  await runTest("Reference decision creates a Note kind=reference", async () => {
    // Capsule is still visible from previous test (modal stays open).
    await page.locator('[data-testid="capture-decide-reference"]').click();
    // "Done" state shown briefly then auto-close.
    const done = page.locator('[data-testid="capture-done"]');
    await done.waitFor({ state: "visible", timeout: 3000 });
    // Wait for the auto-close (900ms) plus a margin.
    await page.waitForTimeout(1400);
    // Verify the note was actually written by hitting the API.
    const r = await page.request.get(`${baseURL}/api/tree`);
    assert(r.ok(), "GET /api/tree ok");
    const tree = await r.json();
    // The capture should appear at root (no explicit folder).
    const titles = (tree.notes ?? []).map((n) => n.title);
    assert(
      titles.includes("Hello E2E"),
      `tree contains the captured note: got ${JSON.stringify(titles)}`,
    );
  });

  await runTest("Defer decision creates a Draft (not a Note)", async () => {
    await page.keyboard.press("Meta+Shift+V");
    await page.waitForTimeout(300);
    const fileInput = page.locator('[data-testid="capture-file-input"]');
    await fileInput.setInputFiles({
      name: "later.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Later Item\n\nDecide later.\n"),
    });
    await page
      .locator('[data-testid="capture-capsule"]')
      .waitFor({ state: "visible", timeout: 5000 });
    await page.locator('[data-testid="capture-decide-defer"]').click();
    await page
      .locator('[data-testid="capture-done"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.waitForTimeout(1400);
    // Should NOT appear in /api/tree (it's in drafts/, not notes/).
    const treeRes = await page.request.get(`${baseURL}/api/tree`);
    const tree = await treeRes.json();
    const titles = (tree.notes ?? []).map((n) => n.title);
    assert(
      !titles.includes("Later Item"),
      `defer should NOT write to notes: tree=${JSON.stringify(titles)}`,
    );
    // Should appear in /api/drafts.
    const draftsRes = await page.request.get(`${baseURL}/api/drafts`);
    const drafts = await draftsRes.json();
    const draftTitles = drafts.map((d) => d.title);
    assert(
      draftTitles.includes("Later Item"),
      `defer should write to drafts: got ${JSON.stringify(draftTitles)}`,
    );
  });
} finally {
  await teardown();
}

exitAfter();
