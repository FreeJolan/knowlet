/**
 * Regression suite for the frontend-feature audit batch (Sync / Discuss /
 * Digest / Drafts satellites).
 *
 * Covers:
 *   - conflict merge dialog refetches the bundle on every open and never
 *     shows (or saves) the previous conflict's text
 *   - realtime freshness gate: an unresolved conflict does not turn into a
 *     preflight → freshness → preflight loop
 *   - note chat: text streamed after a tool round is kept and rendered;
 *     the next request sends it as one assistant reply; streaming does not
 *     rewrite localStorage on every chunk
 *   - transcript keeps a user message that directly follows a tool trace
 *   - Drafts panel surfaces approve failures (and clears them on retry)
 *   - Digest review: edits still inside the autosave debounce are flushed
 *     on next / Esc-close; Esc inside the folder picker or discard confirm
 *     only closes that layer; commit side effects (list refresh + opening
 *     the note) survive closing the review during the transition
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import {
  assert,
  assertConsoleClean,
  exitAfter,
  runTest,
  setupTestEnv,
} from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "alpha", body: "alpha body" }],
  folders: ["library/final"],
  language: "en",
});
const { page, browser, baseURL, vaultDir, teardown } = env;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function until(cond, timeoutMs, msg) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (await cond()) return;
    await sleep(50);
  }
  throw new Error(`timed out after ${timeoutMs} ms: ${msg}`);
}

function sse(events) {
  return events.map((ev) => `data: ${JSON.stringify(ev)}\n\n`).join("");
}

// ------------------------------------------------------------ digest seed

const ITEM_A = "01C6AUDITRAWINFOAAAAA1";
const ITEM_B = "01C6AUDITRAWINFOBBBBB2";
const ITEM_C = "01C6AUDITRAWINFOCCCCC3";
const DRAFT_A = "01C8AUDITDRAFTAAAAAAA1";
const NOTE_FROM_A = "01C9AUDITNOTEFROMAAAA1";

function rawInfo(id, title, minutesAgo, extra = {}) {
  return {
    schema_version: 1,
    id,
    source_id: "01C6SRCAUDIT",
    source_name: "Audit Feed",
    source_kind: "rss",
    item_key: `rss:${id}`,
    title,
    url: `https://example.com/${id}`,
    published_at: null,
    fetched_at: new Date(Date.now() - minutesAgo * 60_000)
      .toISOString()
      .replace(/\.\d{3}Z$/, "Z"),
    summary: `${title} summary.`,
    key_points: ["one"],
    why_it_matters: "Regression coverage.",
    suggested_tags: ["audit"],
    confidence: "medium",
    content_excerpt: "Excerpt.",
    status: "unprocessed",
    note_draft_id: null,
    note_id: null,
    ...extra,
  };
}

{
  const root = join(vaultDir, ".knowlet", "digest", "items");
  mkdirSync(root, { recursive: true });
  const items = [
    rawInfo(ITEM_A, "Audit item A", 1, {
      status: "drafted",
      note_draft_id: DRAFT_A,
    }),
    rawInfo(ITEM_B, "Audit item B", 2),
    rawInfo(ITEM_C, "Audit item C", 3),
  ];
  for (const item of items) {
    writeFileSync(
      join(root, `${item.id}.json`),
      JSON.stringify(item, null, 2) + "\n",
      "utf8",
    );
  }
}

let serverDraftA = {
  id: DRAFT_A,
  title: "Draft A",
  body: "Draft A body.",
  source: `https://example.com/${ITEM_A}`,
  tags: ["audit"],
  kind: "knowledge",
  folder: "library/final",
  task_id: null,
  created_at: new Date().toISOString(),
  updated_at: new Date().toISOString(),
  age_days: 0,
  is_stale: false,
  is_warn_age: false,
};
const draftPuts = [];
let commitResponded = false;
let digestItemsGetsAfterCommit = 0;
let noteFromAFetches = 0;

await page.route(`**/api/drafts/${DRAFT_A}`, async (route) => {
  const method = route.request().method();
  if (method === "PUT") {
    const body = route.request().postDataJSON();
    draftPuts.push(body);
    serverDraftA = {
      ...serverDraftA,
      ...body,
      updated_at: new Date().toISOString(),
    };
  } else if (method !== "GET") {
    return route.fallback();
  }
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(serverDraftA),
  });
});

await page.route(`**/api/drafts/${DRAFT_A}/commit`, async (route) => {
  commitResponded = true;
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      note_id: NOTE_FROM_A,
      path: "/tmp/knowlet/notes/library/final/draft-a.md",
      title: serverDraftA.title,
      raw_info_id: ITEM_A,
    }),
  });
});

await page.route(`**/api/notes/${NOTE_FROM_A}`, async (route) => {
  noteFromAFetches += 1;
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      id: NOTE_FROM_A,
      title: serverDraftA.title,
      path: "/tmp/knowlet/notes/library/final/draft-a.md",
      folder: "library/final",
      tags: ["audit"],
      aliases: [],
      source: null,
      kind: "knowledge",
      body: serverDraftA.body,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      frontmatter_status: "valid",
      frontmatter_corruption: null,
    }),
  });
});

await page.route(`**/api/notes/${NOTE_FROM_A}/backlinks`, (route) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: "[]",
  }),
);

page.on("request", (req) => {
  if (
    commitResponded &&
    req.method() === "GET" &&
    new URL(req.url()).pathname === "/api/digest/items"
  ) {
    digestItemsGetsAfterCommit += 1;
  }
});

// Count localStorage writes of note-chat sessions.
await page.addInitScript(() => {
  const original = Storage.prototype.setItem;
  window.__chatWrites = 0;
  Storage.prototype.setItem = function (key, value) {
    if (String(key).startsWith("knowlet.discuss.")) window.__chatWrites += 1;
    return original.call(this, key, value);
  };
});

// ------------------------------------------------------------ conflict

const LOCAL_V1 = ["shared", "MINE v1", "tail"].join("\n");
const REMOTE_V1 = ["shared", "THEIRS v1", "tail"].join("\n");
const LOCAL_V2 = ["shared", "MINE v2", "tail"].join("\n");
const REMOTE_V2 = ["shared", "THEIRS v2", "tail"].join("\n");
let bundleCalls = 0;
let resolveBody = null;

await page.route("**/api/sync/note-status/**", (route) =>
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      state: "conflict",
      last_synced_at: "2026-11-01T12:00:00Z",
      drive_file_id: "DRIVE-FID",
      last_known_revision: "rev-OLD",
      current_drive_revision: "rev-NEW",
      detail: null,
    }),
  }),
);

await page.route("**/api/sync/conflict-bundle/**", async (route) => {
  bundleCalls += 1;
  const second = bundleCalls >= 2;
  if (second) await sleep(700);
  try {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        note_id: "alpha",
        drive_file_id: "DRIVE-FID",
        local_text: second ? LOCAL_V2 : LOCAL_V1,
        remote_text: second ? REMOTE_V2 : REMOTE_V1,
        current_drive_revision: second ? "rev-NEWER" : "rev-NEW",
        last_known_revision: "rev-OLD",
        local_modified_at: "2026-11-01T14:32:00Z",
        remote_modified_at: "2026-11-01T17:08:00Z",
        remote_modified_by: "alice@example.com",
      }),
    });
  } catch {
    // page torn down mid-delay
  }
});

await page.route("**/api/sync/resolve-merge/**", async (route) => {
  resolveBody = route.request().postDataJSON();
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ drive_file_id: "DRIVE-FID", new_revision: "rev-M" }),
  });
});

async function openAlpha() {
  await page.locator(".group").filter({ hasText: "alpha" }).first().click();
}

/** Fresh SPA state per section so one failing case cannot leave a modal
 *  up that cascades into the next (routes + counters survive reloads). */
async function reloadApp() {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(300);
}

page.setDefaultTimeout(5000);

try {
  await reloadApp();
  await openAlpha();

  await runTest("conflict dialog refetches the bundle on every open", async () => {
    const badge = page
      .locator('[data-testid="sync-status-badge"][data-state="conflict"]')
      .first();
    await badge.waitFor({ state: "visible", timeout: 5000 });
    await badge.click();
    const dialog = page.locator('[data-testid="conflict-merge-dialog"]');
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    const mine = page.locator('[data-testid="merge-hunk-mine-0"]');
    await mine.filter({ hasText: "MINE v1" }).waitFor({ timeout: 3000 });

    // Cancel branch: close without saving, a new conflict arrives remotely.
    await page.keyboard.press("Escape");
    await dialog.waitFor({ state: "detached", timeout: 3000 });
    await badge.click();
    await dialog.waitFor({ state: "visible", timeout: 3000 });
    // While the fresh bundle is loading the old one must not be shown.
    await sleep(250);
    const staleVisible = await page
      .locator('[data-testid="merge-hunk-mine-0"]')
      .filter({ hasText: "MINE v1" })
      .count();
    assert(staleVisible === 0, "reopened dialog must not show the old bundle");
    await mine.filter({ hasText: "MINE v2" }).waitFor({ timeout: 3000 });
    assert(bundleCalls === 2, `expected 2 bundle fetches, got ${bundleCalls}`);

    await page.locator('[data-testid="merge-all-mine"]').click();
    await page.locator('[data-testid="merge-save"]:not([disabled])').click();
    await dialog.waitFor({ state: "detached", timeout: 3000 });
    assert(
      resolveBody?.merged_text === LOCAL_V2,
      `save must merge the fresh text, got ${JSON.stringify(resolveBody)}`,
    );
  });

  await page.unroute("**/api/sync/note-status/**");

  // ------------------------------------------------------------ chat

  let lastHistory = null;
  let streamTurn = 0;
  const words = Array.from({ length: 40 }, (_, i) => `w${i} `);
  await page.route("**/api/chat/note/*/stream", async (route) => {
    streamTurn += 1;
    lastHistory = route.request().postDataJSON().history;
    let events;
    if (streamTurn === 1) {
      events = [
        { type: "reply_chunk", text: "Let me check. " },
        {
          type: "tool_call",
          id: "call_1",
          name: "search_notes",
          arguments: { query: "alpha" },
        },
        {
          type: "tool_result",
          id: "call_1",
          name: "search_notes",
          payload: { results: [{ title: "alpha", id: "n1" }] },
        },
        ...words.map((text) => ({ type: "reply_chunk", text })),
        { type: "turn_done", final_text: words.join("") },
      ];
    } else if (streamTurn === 2) {
      events = [
        {
          type: "tool_call",
          id: "call_2",
          name: "search_notes",
          arguments: { query: "beta" },
        },
        { type: "error", message: "upstream exploded" },
      ];
    } else {
      events = [
        { type: "reply_chunk", text: "third answer" },
        { type: "turn_done", final_text: "third answer" },
      ];
    }
    await route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sse(events),
    });
  });

  async function sendChat(text) {
    await page.locator('[data-testid="discuss-input"]').fill(text);
    await page.locator('[data-testid="discuss-send"]').click();
  }

  await reloadApp();
  await openAlpha();

  await runTest("answer streamed after a tool round is rendered", async () => {
    await page.locator('[data-testid="header-discuss-button"]').click();
    await page
      .locator('[data-testid="discuss-pane"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.evaluate(() => {
      window.__chatWrites = 0;
    });
    await sendChat("question one");
    await page
      .locator('[data-testid="discuss-answer"]')
      .filter({ hasText: "w39" })
      .waitFor({ timeout: 5000 });
    const answers = await page
      .locator('[data-testid="discuss-answer"]')
      .allInnerTexts();
    const all = answers.join("\n");
    assert(all.includes("Let me check."), `pre-tool text kept: ${all}`);
    assert(all.includes("w0") && all.includes("w39"), `final answer kept: ${all}`);
    // Trace panel sits between the two assistant texts.
    const order = await page.evaluate(() =>
      Array.from(
        document.querySelectorAll(
          '[data-testid="discuss-answer"], [data-testid="discuss-trace-panel"]',
        ),
      ).map((el) => el.getAttribute("data-testid")),
    );
    assert(
      order.join(">") === "discuss-answer>discuss-trace-panel>discuss-answer",
      `unexpected transcript order ${order.join(">")}`,
    );
  });

  await runTest("streaming does not rewrite localStorage per chunk", async () => {
    const writes = await page.evaluate(() => window.__chatWrites);
    assert(writes <= 4, `expected a handful of writes for 43 events, got ${writes}`);
    const stored = await page.evaluate(() => {
      const key = Object.keys(localStorage).find((k) =>
        k.startsWith("knowlet.discuss."),
      );
      return key ? localStorage.getItem(key) : null;
    });
    assert(stored && stored.includes("w39"), "final state persisted after the stream");
  });

  await runTest("next request sends the split reply as one assistant turn", async () => {
    await sendChat("question two");
    await page
      .locator('[data-testid="discuss-message-user"]')
      .nth(1)
      .waitFor({ timeout: 3000 });
    await until(() => streamTurn >= 2, 3000, "second stream request");
    assert(Array.isArray(lastHistory), "history sent");
    assert(
      lastHistory.length === 2,
      `expected [user, assistant], got ${JSON.stringify(lastHistory)}`,
    );
    const [u, a] = lastHistory;
    assert(u.role === "user" && u.content === "question one", "user turn");
    assert(
      a.role === "assistant" &&
        a.content.includes("Let me check.") &&
        a.content.includes("w39"),
      `assistant turn carries the whole reply: ${JSON.stringify(a)}`,
    );
  });

  await runTest("user message right after a failed tool turn stays visible", async () => {
    // Turn two errored after its tool call → history ends [.., user, tool].
    await page.waitForTimeout(300);
    await sendChat("question three");
    await page
      .locator('[data-testid="discuss-answer"]')
      .filter({ hasText: "third answer" })
      .waitFor({ timeout: 3000 });
    const bubbles = await page
      .locator('[data-testid="discuss-user-bubble"]')
      .allInnerTexts();
    assert(
      bubbles.length === 3 && bubbles[2].includes("question three"),
      `expected 3 user bubbles ending with question three, got ${JSON.stringify(bubbles)}`,
    );
  });

  await page.unroute("**/api/chat/note/*/stream");
  await reloadApp();

  // ------------------------------------------------------------ drafts

  await runTest("drafts panel surfaces approve failures", async () => {
    const r = await page.request.post(`${baseURL}/api/capture/decide`, {
      data: {
        capsule: { title: "Approve me", body: "body", source: null },
        decision: "defer",
        defer_kind: "reference",
      },
    });
    assert(r.ok(), `seed draft: ${r.status()}`);
    let failApprove = true;
    let approveCalls = 0;
    await page.route("**/api/drafts/*/approve", async (route) => {
      approveCalls += 1;
      if (failApprove) {
        await route.fulfill({
          status: 500,
          contentType: "application/json",
          body: JSON.stringify({ detail: "disk full" }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ note_id: "01C9APPROVED" }),
      });
    });

    await page.locator("body").click({ position: { x: 5, y: 5 } });
    await page.keyboard.press("Meta+I");
    const panel = page.locator('[data-testid="drafts-focus-mode"]');
    await panel.waitFor({ state: "visible", timeout: 3000 });
    const approve = page.locator('[data-testid^="draft-approve-"]').first();
    await approve.waitFor({ state: "visible", timeout: 3000 });
    await approve.click();
    const banner = page.locator('[data-testid="drafts-action-error"]');
    await banner.waitFor({ state: "visible", timeout: 3000 });
    const text = (await banner.textContent()) ?? "";
    assert(text.includes("disk full"), `error names the cause: ${text}`);
    assert(
      (await banner.getAttribute("role")) === "alert",
      "error is announced",
    );

    // Retry branch: a successful retry clears the error.
    failApprove = false;
    await approve.click();
    await banner.waitFor({ state: "detached", timeout: 3000 });
    assert(approveCalls === 2, `expected 2 approve calls, got ${approveCalls}`);
    await page.unroute("**/api/drafts/*/approve");
    await page.keyboard.press("Escape");
    await panel.waitFor({ state: "detached", timeout: 3000 });
  });

  // ------------------------------------------------------------ digest

  await reloadApp();
  const focusMode = page.locator('[data-testid="digest-focus-mode"]');
  const workspace = page.locator('[data-testid="digest-review-workspace"]');
  const currentTitle = page.locator('[data-testid="digest-review-current-title"]');

  async function openReviewOnA() {
    if (!(await focusMode.isVisible())) {
      await page.locator('[data-testid="header-digest-button"]').click();
      await focusMode.waitFor({ state: "visible", timeout: 3000 });
    }
    await page.locator(`[data-testid="digest-card-review-${ITEM_A}"]`).click();
    await workspace.waitFor({ state: "visible", timeout: 3000 });
    await currentTitle.filter({ hasText: "Audit item A" }).waitFor({ timeout: 3000 });
    await page
      .locator('[data-testid="digest-draft-title"]')
      .waitFor({ state: "visible", timeout: 3000 });
  }

  async function editDraftTitle(value) {
    await page.locator('[data-testid="digest-draft-title"]').click();
    const input = page.locator('[data-testid="digest-draft-title-input"]');
    await input.fill(value);
    await input.press("Enter");
  }

  await runTest("next flushes an edit still inside the autosave debounce", async () => {
    await openReviewOnA();
    await editDraftTitle("A edited");
    await page.locator('[data-testid="digest-review-next"]').click();
    await currentTitle.filter({ hasText: "Audit item B" }).waitFor({ timeout: 3000 });
    await until(
      () => draftPuts.some((b) => b.title === "A edited"),
      2000,
      "PUT with the debounced title edit",
    );
    // Back on A the editor shows the saved edit, not the stale cache.
    await page.locator('[data-testid="digest-review-prev"]').click();
    await currentTitle.filter({ hasText: "Audit item A" }).waitFor({ timeout: 3000 });
    await page
      .locator('[data-testid="digest-draft-title"]')
      .filter({ hasText: "A edited" })
      .waitFor({ timeout: 3000 });
  });

  await runTest("Esc closes only the review and flushes the pending edit", async () => {
    await reloadApp();
    await openReviewOnA();
    await editDraftTitle("A edited twice");
    await page.keyboard.press("Escape");
    await workspace.waitFor({ state: "detached", timeout: 3000 });
    assert(await focusMode.isVisible(), "Digest stays open after closing the review");
    await until(
      () => draftPuts.some((b) => b.title === "A edited twice"),
      2000,
      "PUT flushed on close",
    );
  });

  await runTest("Esc in the folder picker / discard confirm closes only that layer", async () => {
    await reloadApp();
    await openReviewOnA();
    await page
      .locator('[data-testid="digest-draft-commit"]:not([disabled])')
      .click({ timeout: 5000 });
    const folderDialog = page.locator('[data-testid="digest-folder-dialog"]');
    await folderDialog.waitFor({ state: "visible", timeout: 3000 });
    await page.keyboard.press("Escape");
    await folderDialog.waitFor({ state: "detached", timeout: 3000 });
    await page.waitForTimeout(200);
    assert(await workspace.isVisible(), "review survives Esc in the folder picker");
    assert(await focusMode.isVisible(), "Digest survives Esc in the folder picker");

    await page.locator('[data-testid="digest-review-discard"]').click();
    const popover = page.locator('[data-testid="digest-discard-confirm-popover"]');
    await popover.waitFor({ state: "visible", timeout: 3000 });
    // The hover tooltip of the discard button is the topmost layer and
    // takes the first Esc; each press peels one layer, never the review.
    for (let i = 0; i < 3 && (await popover.count()) > 0; i += 1) {
      await page.keyboard.press("Escape");
      await page.waitForTimeout(150);
      assert(await workspace.isVisible(), `review survives Esc #${i + 1}`);
    }
    await popover.waitFor({ state: "detached", timeout: 3000 });
    await page.waitForTimeout(200);
    assert(await workspace.isVisible(), "review survives Esc in the discard confirm");
  });

  await runTest("commit side effects survive closing the review mid-transition", async () => {
    await reloadApp();
    await openReviewOnA();
    await page
      .locator('[data-testid="digest-draft-commit"]:not([disabled])')
      .click({ timeout: 5000 });
    await page
      .locator('[data-testid="digest-folder-dialog"]')
      .waitFor({ state: "visible", timeout: 3000 });
    await page.locator('[data-testid="digest-folder-confirm"]').click();
    await page
      .locator('[data-testid="digest-review-transition"][data-kind="commit"]')
      .waitFor({ state: "visible", timeout: 3000 });
    // The transition overlay covers the header; Esc is the way out. A
    // focus-restored tooltip may absorb the first press.
    for (let i = 0; i < 3 && (await workspace.count()) > 0; i += 1) {
      await page.keyboard.press("Escape");
      await page.waitForTimeout(100);
    }
    await workspace.waitFor({ state: "detached", timeout: 1000 });
    // Well inside the 2 s animation the overlay would still have been up.
    await until(
      () => digestItemsGetsAfterCommit > 0 && noteFromAFetches > 0,
      1200,
      "digest list refetch + committed note opened",
    );
  });

  // ------------------------------------------------------------ sync loop

  await runTest("unresolved conflict does not loop freshness ↔ preflight", async () => {
    const context = await browser.newContext({ viewport: { width: 1200, height: 800 } });
    const p2 = await context.newPage();
    let freshnessCalls = 0;
    let preflightCalls = 0;
    const json = (body) => ({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    const conflictReport = {
      ran_at: Date.now() / 1000,
      scanned: 1,
      conflicts: [
        {
          note_id: "n-conflict",
          title: "Conflicted",
          drive_file_id: "F1",
          last_known_revision: "r1",
          current_drive_revision: "r2",
        },
      ],
      offline: [],
      auto_pulled_ids: [],
      synced_count: 0,
      dirty_count: 0,
      unauthenticated: false,
      alive_devices: [],
      cloned_from_drive_ids: [],
      trashed_for_drive_delete_ids: [],
      deleted_for_drive_delete_ids: [],
    };
    await p2.route("**/api/sync/auth-status", (r) =>
      r.fulfill(
        json({
          connected: true,
          user_email: "alice@example.com",
          user_display_name: "Alice",
          connecting: false,
          last_error: null,
        }),
      ),
    );
    await p2.route("**/api/sync/mode", (r) =>
      r.fulfill(json({ mode: "realtime", effective_mode: "realtime", device_count: 2 })),
    );
    await p2.route("**/api/sync/conflicts", (r) => r.fulfill(json(conflictReport)));
    await p2.route("**/api/sync/unpushed-status", (r) =>
      r.fulfill(json({ count: 0, authenticated: true })),
    );
    await p2.route("**/api/sync/overview", (r) =>
      r.fulfill(
        json({
          authenticated: true,
          state: "conflict",
          pending_count: 0,
          dirty_count: 0,
          deletion_pending_count: 0,
          unpushed_count: 0,
          failure_count: 0,
          last_synced_at: null,
          detail: null,
        }),
      ),
    );
    await p2.route("**/api/sync/push-errors", (r) => r.fulfill(json({ errors: [] })));
    await p2.route("**/api/sync/freshness", (r) => {
      freshnessCalls += 1;
      // The server stamps every probe with a new checked_at; the token
      // does not advance while the conflict is unresolved.
      return r.fulfill(
        json({
          mode: "realtime",
          state: "needs_sync",
          checked_at: new Date(Date.now() + freshnessCalls).toISOString(),
          requires_sync: true,
          reason: "remote_changes",
          changed_count: 1,
          next_start_page_token: "tok-2",
          detail: null,
        }),
      );
    });
    await p2.route("**/api/sync/preflight", (r) => {
      preflightCalls += 1;
      return r.fulfill(json(conflictReport));
    });
    try {
      await p2.goto(baseURL, { waitUntil: "domcontentloaded" });
      await until(() => preflightCalls >= 1, 5000, "first preflight");
      await sleep(2500);
      assert(
        preflightCalls === 1,
        `expected a single preflight for an unchanged remote state, got ${preflightCalls} (freshness ${freshnessCalls})`,
      );
      assert(freshnessCalls <= 3, `freshness should settle, got ${freshnessCalls}`);
      assert(
        (await p2.locator('[data-testid="sync-freshness-blocking-modal"]').count()) === 0,
        "conflict state does not leave the blocking modal up",
      );
    } finally {
      await context.close();
    }
  });

  assertConsoleClean(env, {
    allowMessages: [/status of 500/, /Failed to load resource/],
  });
  await teardown();
  exitAfter(0);
} catch (e) {
  console.error("audit-frontend-feature e2e failed:", e);
  await teardown();
  exitAfter(1);
}
