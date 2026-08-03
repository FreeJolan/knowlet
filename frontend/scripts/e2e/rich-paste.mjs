/**
 * Rich clipboard paste regression coverage. The editor stores Markdown, so
 * HTML clipboard payloads must be converted before CodeMirror falls back to
 * `text/plain` and loses formatting.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "paste-target", body: "" }],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function getTargetNote() {
  const treeResponse = await fetch(`${baseURL}/api/tree`);
  const tree = await treeResponse.json();
  const note = tree.notes.find((item) => item.title === "paste-target");
  if (!note) throw new Error("paste-target note missing from tree");
  const noteResponse = await fetch(
    `${baseURL}/api/notes/${encodeURIComponent(note.id)}`,
  );
  return noteResponse.json();
}

async function editorContent() {
  const content = page.locator(
    '[data-testid="markdown-editor"] .cm-content',
  );
  await content.waitFor({ state: "visible", timeout: 3000 });
  await content.click();
  return content;
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);
  await page
    .locator(".group")
    .filter({ hasText: /^paste-target$/ })
    .first()
    .click();

  await runTest("rich HTML paste preserves formatting as Markdown", async () => {
    const content = await editorContent();
    const notCancelled = await content.evaluate((element) => {
      const clipboardData = new DataTransfer();
      clipboardData.setData(
        "text/html",
        [
          "<h2>Pasted heading</h2>",
          "<p><strong>bold</strong> and <em>italic</em> and ",
          '<span style="font-weight: 700; font-style: italic">styled</span> ',
          '<a href="https://example.com/docs">link</a></p>',
          "<ul><li>first</li><li><del>removed</del></li></ul>",
          "<ol><li>ordered</li></ol>",
          "<table><thead><tr><th>Name</th><th>Value</th></tr></thead>",
          "<tbody><tr><td>alpha</td><td>1</td></tr></tbody></table>",
        ].join(""),
      );
      clipboardData.setData(
        "text/plain",
        "Pasted heading\nbold and italic and styled link\nfirst\nremoved\nordered\nName Value\nalpha 1",
      );
      return element.dispatchEvent(
        new ClipboardEvent("paste", {
          clipboardData,
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    assert(!notCancelled, "rich paste prevents the plain-text fallback");

    await page.waitForTimeout(1500);
    const { body } = await getTargetNote();
    assert(body.includes("## Pasted heading"), `heading preserved — got "${body}"`);
    assert(body.includes("**bold**"), `bold preserved — got "${body}"`);
    assert(body.includes("*italic*"), `italic preserved — got "${body}"`);
    assert(
      /\*{3}styled\*{3}/.test(body),
      `inline CSS emphasis preserved — got "${body}"`,
    );
    assert(
      body.includes("[link](https://example.com/docs)"),
      `link preserved — got "${body}"`,
    );
    assert(/^-\s+first$/m.test(body), `unordered list preserved — got "${body}"`);
    assert(body.includes("1.  ordered"), `ordered list preserved — got "${body}"`);
    assert(body.includes("~~removed~~"), `strikethrough preserved — got "${body}"`);
    assert(
      /\|\s*Name\s*\|\s*Value\s*\|/.test(body),
      `table preserved — got "${body}"`,
    );

    await page.locator('button[data-mode="preview"]').click();
    const preview = page.locator('[data-testid="markdown-preview"]');
    await preview.waitFor({ state: "visible", timeout: 3000 });
    assert(
      (await preview.locator("h2").innerText()) === "Pasted heading",
      "pasted heading renders as a heading",
    );
    assert((await preview.locator("strong").count()) >= 2, "bold styles render");
    assert((await preview.locator("em").count()) >= 2, "italic styles render");
    assert((await preview.locator("ul > li").count()) === 2, "list renders");
    assert((await preview.locator("table").count()) === 1, "table renders");
    await page.locator('button[data-mode="edit"]').click();
  });

  await runTest("plain-text paste remains literal", async () => {
    const content = await editorContent();
    await page.keyboard.press("Meta+A");
    await page.keyboard.press("Delete");
    await content.evaluate((element) => {
      const clipboardData = new DataTransfer();
      clipboardData.setData("text/plain", "<strong>literal</strong>");
      element.dispatchEvent(
        new ClipboardEvent("paste", {
          clipboardData,
          bubbles: true,
          cancelable: true,
        }),
      );
    });
    await page.waitForTimeout(1500);
    const { body } = await getTargetNote();
    assert(
      body === "<strong>literal</strong>",
      `plain text is unchanged — got "${body}"`,
    );
  });

  if (env.errors.length > 0) {
    console.log("✗ no console errors");
    for (const error of env.errors) console.log("  ", error.type, error.text);
    process.exitCode = 1;
  } else {
    console.log("✓ no console errors");
  }
} finally {
  await teardown();
  exitAfter();
}
