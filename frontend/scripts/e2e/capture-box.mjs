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

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [],
  folders: [],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function openCapture() {
  await page.keyboard.press("Meta+Shift+V");
  await page.locator('[data-testid="capture-box"]').waitFor({
    state: "visible",
    timeout: 5000,
  });
  await page.locator('[data-testid="capture-file-input"]').waitFor({
    state: "attached",
    timeout: 5000,
  });
}

async function waitForDecisionComplete() {
  await Promise.race([
    page.locator('[data-testid="capture-done"]').waitFor({
      state: "visible",
      timeout: 10000,
    }),
    page.locator('[data-testid="capture-box"]').waitFor({
      state: "hidden",
      timeout: 10000,
    }),
  ]);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("Cmd+Shift+V opens the CaptureBox modal", async () => {
    await openCapture();
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
    await openCapture();
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
    await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().endsWith("/api/capture/decide") &&
          r.request().method() === "POST" &&
          r.ok(),
        { timeout: 30000 },
      ),
      page.locator('[data-testid="capture-decide-reference"]').click(),
    ]);
    // The "done" state is intentionally brief, then the modal closes.
    await waitForDecisionComplete();
    await page.locator('[data-testid="capture-box"]').waitFor({
      state: "hidden",
      timeout: 5000,
    });
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
    await openCapture();
    const fileInput = page.locator('[data-testid="capture-file-input"]');
    await fileInput.setInputFiles({
      name: "later.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# Later Item\n\nDecide later.\n"),
    });
    await page
      .locator('[data-testid="capture-capsule"]')
      .waitFor({ state: "visible", timeout: 5000 });
    await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().endsWith("/api/capture/decide") &&
          r.request().method() === "POST" &&
          r.ok(),
        { timeout: 30000 },
      ),
      page.locator('[data-testid="capture-decide-defer"]').click(),
    ]);
    await waitForDecisionComplete();
    await page.locator('[data-testid="capture-box"]').waitFor({
      state: "hidden",
      timeout: 5000,
    });
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

  // ---------------- P1 cancel branch + P2 wrong-file branch ----

  await runTest("P1 branch: Esc before decision creates nothing", async () => {
    await openCapture();
    // Upload a file so we reach the capsule-ready state, then Esc
    // BEFORE any decision button click.
    await page.locator('[data-testid="capture-file-input"]').setInputFiles({
      name: "should-not-save.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# should not save\n\nbody\n"),
    });
    await page
      .locator('[data-testid="capture-capsule"]')
      .waitFor({ state: "visible", timeout: 5000 });
    await page.keyboard.press("Escape");
    await page.waitForTimeout(500);
    // No new Note, no new Draft.
    const tree = await (
      await page.request.get(`${baseURL}/api/tree`)
    ).json();
    const drafts = await (
      await page.request.get(`${baseURL}/api/drafts`)
    ).json();
    assert(
      !(tree.notes ?? []).map((n) => n.title).includes("should not save"),
      "Esc must not commit a Note",
    );
    assert(
      !drafts.map((d) => d.title).includes("should not save"),
      "Esc must not commit a Draft",
    );
  });

  await runTest("P2 branch: PDF upload shows error, not capsule", async () => {
    await openCapture();
    await page.locator('[data-testid="capture-file-input"]').setInputFiles({
      name: "doc.pdf",
      mimeType: "application/pdf",
      buffer: Buffer.from("%PDF-1.4 fake"),
    });
    // Backend returns 415; frontend surfaces error UI, not capsule.
    const err = page.locator('[data-testid="capture-error"]');
    await err.waitFor({ state: "visible", timeout: 3000 });
    const errText = await err.innerText();
    assert(
      errText.length > 0,
      "error message should be visible for unsupported file types",
    );
    // No capsule should have appeared.
    const capCount = await page
      .locator('[data-testid="capture-capsule"]')
      .count();
    assert(capCount === 0, "no capsule for rejected file type");
    await page.keyboard.press("Escape");
  });

  await runTest("no console errors during the suite", () => {
    // P2 / P3 negative tests trigger expected 415 / 502 responses;
    // the React client logs those as fetch failures via console.
    // Filter just those, keep everything else strict.
    assertConsoleClean(env, {
      allowMessages: [
        /415/,
        /Unsupported Media Type/i,
        /Failed to load resource/i,
      ],
    });
  });
} finally {
  await teardown();
}

exitAfter();
