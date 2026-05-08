// Capture current NoteView header in all 3 view modes (light + dark)
// for Claude Design handoff. Saves PNGs into /tmp/knowlet-header/.
//
// Uses the e2e fixture (isolated backend + seeded vault) so the
// screenshots don't depend on whatever state the dev vault is in.
import { mkdirSync } from "node:fs";

import { setupTestEnv } from "./e2e/_fixture.mjs";

const OUT = "/tmp/knowlet-header";
mkdirSync(OUT, { recursive: true });

const env = await setupTestEnv({
  notes: [
    {
      title: "Attention Mechanism",
      // Long-ish body so the preview pane has something to fill
      // beneath the header.
      body: [
        "# Attention Mechanism",
        "",
        "Self-attention from the Transformer paper. Replaces RNN-style",
        "sequential processing with parallel pairwise weighted lookups.",
        "",
        "## Scaled Dot-Product",
        "",
        "Q · Kᵀ / √dₖ → softmax → V. The √dₖ scale keeps gradients stable",
        "as dimensionality grows.",
        "",
        "## Multi-Head",
        "",
        "Run h independent attention heads in parallel; concat + project.",
        "Each head can specialize (one for syntax, one for coreference, etc.).",
      ].join("\n"),
      tags: ["transformer", "deep-learning"],
    },
    { title: "another note", body: "filler" },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

try {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(600);

  // Pre-seed aliases + a fake source URL via PUT so the expanded
  // panel actually shows all 4 rows (aliases / source / created /
  // updated). The fixture doesn't carry source through seedVault,
  // so we patch the note frontmatter directly via the API.
  const tree = await page.evaluate(async () => {
    const r = await fetch("/api/tree");
    return r.json();
  });
  function* iter(node) {
    for (const n of node.notes ?? []) yield n;
    for (const f of node.folders ?? []) yield* iter(f);
  }
  let attentionId = null;
  for (const n of iter(tree)) if (n.title === "Attention Mechanism") attentionId = n.id;
  if (attentionId) {
    await page.evaluate(async (id) => {
      const cur = await (await fetch(`/api/notes/${id}`)).json();
      // Use the source field directly via writing the markdown — the
      // PUT path doesn't carry source; back-fill via a tiny extra
      // call by writing the note with frontmatter.source baked in.
      // Simpler hack: set aliases via PUT and hand-edit the disk
      // file's frontmatter for source. But we don't have FS access
      // from the browser; just leave source empty. The expanded
      // panel will show 3 rows instead of 4.
      await fetch(`/api/notes/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: cur.title,
          tags: cur.tags,
          body: cur.body,
          aliases: ["Self-Attention", "注意力"],
        }),
      });
    }, attentionId);
  }

  // Open the seeded note from the file tree.
  await page.locator('[role="treeitem"]', { hasText: "Attention Mechanism" }).first().click();
  await page.waitForTimeout(500);

  async function clickModeButton(mode) {
    const btn = page.locator(
      `[data-testid="view-mode-toggle"] button[data-mode="${mode}"]`,
    );
    await btn.click();
    await page.waitForTimeout(300);
  }

  async function shot(name) {
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      path: `${OUT}/${name}.png`,
      // Capture the top of the right pane only (the file tree on the
      // left isn't the subject).
      clip: { x: 280, y: 0, width: 1080, height: 360 },
    });
  }

  async function setTheme(theme) {
    await page.evaluate((t) => {
      document.documentElement.setAttribute("data-theme", t);
      try {
        window.localStorage.setItem("knowlet.theme.v1", t);
      } catch {}
    }, theme);
    await page.waitForTimeout(200);
  }

  async function setExpanded(expanded) {
    const cur = await page.evaluate(() =>
      window.localStorage.getItem("knowlet.properties.collapsed.v1"),
    );
    const wantFlag = expanded ? "0" : "1";
    if (cur === wantFlag) return;
    const toggle = page.locator('[data-testid="properties-toggle"]').first();
    if (await toggle.isVisible()) await toggle.click();
    await page.waitForTimeout(200);
  }

  for (const theme of ["light", "dark"]) {
    await setTheme(theme);
    for (const mode of ["edit", "split", "preview"]) {
      await clickModeButton(mode);
      await setExpanded(false);
      await shot(`${theme}-${mode}-collapsed`);
      await setExpanded(true);
      await shot(`${theme}-${mode}-expanded`);
    }
  }

  console.log("done — see " + OUT);
} finally {
  await teardown();
}
