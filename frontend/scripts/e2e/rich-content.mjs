/**
 * Phase 1 B slices 5 + 6 — KaTeX math + Mermaid diagrams in the preview
 * pane. Edit-mode just stores the markdown source; only preview mode
 * renders.
 *
 * KaTeX renders synchronously via rehype-katex during the markdown
 * pipeline → the test asserts on `.katex` DOM nodes the moment preview
 * mode is entered.
 *
 * Mermaid lazy-loads (~500 KB) and renders async → poll for the SVG to
 * appear within 5 s. On render error MermaidBlock falls back to a
 * styled <pre> with `kn-mermaid-error` class — we use that as a signal
 * that mermaid loaded but the input was bad.
 */

import { assert, exitAfter, runTest, setupTestEnv } from "./_fixture.mjs";

const env = await setupTestEnv({
  notes: [
    {
      title: "math",
      body: [
        "Inline: $a^2 + b^2 = c^2$ in a sentence.",
        "",
        "Block:",
        "$$",
        "\\int_0^1 x^2 \\, dx = \\frac{1}{3}",
        "$$",
      ].join("\n"),
    },
    {
      title: "diagram",
      body: [
        "Flowchart:",
        "",
        "```mermaid",
        "graph TD",
        "  A[Start] --> B{Choice}",
        "  B -->|Yes| C[OK]",
        "  B -->|No| D[Fail]",
        "```",
      ].join("\n"),
    },
    {
      title: "broken-diagram",
      body: [
        "```mermaid",
        "this is not a valid diagram",
        "```",
      ].join("\n"),
    },
  ],
  language: "en",
});
const { page, baseURL, teardown } = env;

async function clickRow(title) {
  // Strict anchored regex match against trimmed text content. Naive
  // hasText substring matching picks "broken-diagram" when asked for
  // "diagram"; word-boundary regex still matched the prefix because
  // `-` is non-word. Anchor to start AND end with no escape hatch.
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const row = page
    .locator(".group")
    .filter({ hasText: new RegExp(`^${escaped}$`) })
    .first();
  await row.waitFor({ state: "visible", timeout: 3000 });
  await row.click();
}

async function clickPreview() {
  await page.locator('button[data-mode="preview"]').click();
  await page.waitForTimeout(120);
}

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.waitForTimeout(500);

  await runTest("inline + block math render via KaTeX", async () => {
    await clickRow("math");
    await clickPreview();
    const preview = page.locator('[data-testid="markdown-preview"]');
    await preview.waitFor({ state: "visible", timeout: 3000 });
    // KaTeX wraps every formula in a `.katex` span (or `.katex-display`
    // for block). At least one of each should be present.
    const inlineCount = await preview.locator(".katex").count();
    assert(inlineCount >= 2, `at least two .katex nodes (inline + block) — got ${inlineCount}`);
    const blockCount = await preview.locator(".katex-display").count();
    assert(blockCount >= 1, `at least one .katex-display — got ${blockCount}`);
    // Sanity: the rendered glyphs should include the integral symbol.
    const text = await preview.locator(".katex-display").innerText();
    assert(/∫/.test(text), `block formula renders ∫ — got "${text.slice(0, 80)}"`);
  });

  await runTest("mermaid block renders an SVG diagram", async () => {
    await clickRow("diagram");
    await clickPreview();
    const preview = page.locator('[data-testid="markdown-preview"]');
    // Mermaid lazy-loads. Wait for either the rendered SVG OR the
    // error fallback to land — both indicate the lib finished loading.
    await page.waitForFunction(
      () => {
        const root = document.querySelector('[data-testid="markdown-preview"]');
        if (!root) return false;
        return (
          root.querySelector(".kn-mermaid svg") !== null ||
          root.querySelector(".kn-mermaid-error") !== null
        );
      },
      null,
      { timeout: 8000, polling: 100 },
    );
    const svgCount = await preview.locator(".kn-mermaid svg").count();
    assert(svgCount === 1, `exactly one rendered SVG — got ${svgCount}`);
    // The diagram had nodes labeled Start / OK / Fail — confirm at least
    // one of those landed in the SVG text. SVGElement is not an
    // HTMLElement so .innerText doesn't work; use textContent.
    const svgText = await preview
      .locator(".kn-mermaid svg")
      .evaluate((el) => el.textContent ?? "");
    assert(
      /(Start|OK|Fail)/.test(svgText),
      `SVG includes node label — got "${svgText.slice(0, 120)}"`,
    );
  });

  await runTest(
    "split mode: wide preview content does NOT squeeze the editor pane",
    async () => {
      // Regression for "writing mermaid pushes the editor offscreen".
      // Without `min-w-0` on the flex children, a long mermaid error
      // line would expand the preview column past 50% and leave the
      // editor at 0 px width.
      await clickRow("broken-diagram");
      await page.locator('button[data-mode="split"]').click();
      await page.waitForTimeout(400);
      // Wait for the error fallback to land, ensuring the preview pane
      // has its widest possible content.
      await page.waitForFunction(
        () =>
          document.querySelector(
            '[data-testid="markdown-preview"] .kn-mermaid-error',
          ) !== null,
        null,
        { timeout: 8000, polling: 100 },
      );
      const editorBox = await page
        .locator('[data-testid="markdown-editor"]')
        .boundingBox();
      const previewBox = await page
        .locator('[data-testid="markdown-preview"]')
        .boundingBox();
      assert(
        editorBox !== null && editorBox.width > 100,
        `editor pane retains usable width — got ${editorBox?.width}px`,
      );
      assert(
        previewBox !== null && previewBox.width > 100,
        `preview pane retains usable width — got ${previewBox?.width}px`,
      );
      // The two panes should be roughly equal — within 50 px of each
      // other, since `flex-1` distributes evenly.
      const diff = Math.abs((editorBox?.width ?? 0) - (previewBox?.width ?? 0));
      assert(
        diff < 60,
        `split-mode panes roughly equal width — diff=${diff}px`,
      );
      await page.locator('button[data-mode="edit"]').click();
      await page.waitForTimeout(120);
    },
  );

  await runTest("broken mermaid input falls back to error pre", async () => {
    await clickRow("broken-diagram");
    await clickPreview();
    const preview = page.locator('[data-testid="markdown-preview"]');
    // Wait for either success SVG (unexpected) or fallback error.
    await page.waitForFunction(
      () => {
        const root = document.querySelector('[data-testid="markdown-preview"]');
        if (!root) return false;
        return (
          root.querySelector(".kn-mermaid svg") !== null ||
          root.querySelector(".kn-mermaid-error") !== null
        );
      },
      null,
      { timeout: 8000, polling: 100 },
    );
    const errorCount = await preview.locator(".kn-mermaid-error").count();
    assert(errorCount === 1, `error fallback pre rendered — got ${errorCount}`);
    // The fallback should display the original source verbatim.
    const errorText = await preview.locator(".kn-mermaid-error").innerText();
    assert(
      /this is not a valid diagram/.test(errorText),
      `fallback shows raw source — got "${errorText.slice(0, 100)}"`,
    );
    // Regression for the "bomb-icon SVG accumulates at bottom of page"
    // dogfood report: mermaid.render() on broken input leaks orphan
    // SVGs into <body>. We MUST validate with mermaid.parse() before
    // calling render to keep the DOM clean.
    const orphans = await page.evaluate(
      () =>
        document.querySelectorAll(
          'body > svg[id^="dmermaid-"], body > svg[id^="mmd-"]',
        ).length,
    );
    assert(
      orphans === 0,
      `no orphan mermaid bomb SVGs in body — found ${orphans}`,
    );
  });

  if (env.errors.length > 0) {
    // Mermaid can log debug warnings to the console even on success.
    // Filter those out — only fail on hard errors / pageerror.
    const real = env.errors.filter(
      (e) => e.type === "pageerror" || /TypeError|SyntaxError/.test(e.text),
    );
    if (real.length > 0) {
      console.log("✗ no console errors");
      for (const e of real) console.log("  ", e.type, e.text);
      process.exitCode = 1;
    } else {
      console.log("✓ no console errors (filtered mermaid noise)");
    }
  } else {
    console.log("✓ no console errors");
  }
} finally {
  await teardown();
  exitAfter();
}
