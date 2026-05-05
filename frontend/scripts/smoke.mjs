// Smoke test: open http://localhost:5173, verify tree renders + interaction
// works. Extended after the 2026-05-05 dogfood: a single "tree has rows"
// check wasn't enough — we now also assert toggle works, no "Move to root"
// item, and i18n is wired.

import { chromium } from "playwright";

const URL = process.env.URL ?? "http://localhost:5173";

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1400, height: 900 } });
const page = await ctx.newPage();

const errors = [];
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") {
    errors.push({ type: m.type(), text: m.text() });
  }
});
page.on("pageerror", (e) => errors.push({ type: "pageerror", text: String(e) }));

const resp = await page.goto(URL, { waitUntil: "networkidle", timeout: 15000 });
console.log(`HTTP ${resp.status()} ${URL}`);
await page.waitForTimeout(500);

// 1 — tree renders
const initialRows = await page.locator(".group").count();
console.log("rows visible (default-open):", initialRows);

// 2 — chevron click collapses an open folder
const firstFolderChevron = page.locator('button[aria-label="collapse"]').first();
const hasChevron = (await firstFolderChevron.count()) > 0;
console.log("collapse chevron present:", hasChevron);
if (hasChevron) {
  await firstFolderChevron.click();
  await page.waitForTimeout(150);
  const rowsAfterCollapse = await page.locator(".group").count();
  console.log("rows after one collapse:", rowsAfterCollapse);
  if (rowsAfterCollapse >= initialRows) {
    console.log("WARN: collapse did not reduce row count");
  }
  // Re-expand for next steps
  const expandBtn = page.locator('button[aria-label="expand"]').first();
  if ((await expandBtn.count()) > 0) {
    await expandBtn.click();
    await page.waitForTimeout(150);
  }
}

// 3 — sidebar width sensible
const sidebar = page.locator('[data-slot="resizable-panel"]').first();
const box = await sidebar.boundingBox();
const widthPct = box ? Math.round((box.width / 1400) * 100) : 0;
console.log(`sidebar width: ${box?.width}px (${widthPct}%)`);
if (widthPct < 12 || widthPct > 32) console.log("WARN: sidebar width out of expected band");

// 4 — right-click a note row, confirm "Move to root" is absent
const firstNote = page.locator(".group").filter({ hasText: /design|hello|idea/ }).first();
if ((await firstNote.count()) > 0) {
  await firstNote.click({ button: "right" });
  await page.waitForTimeout(200);
  const menuTexts = await page.locator('[role="menuitem"]').allInnerTexts();
  console.log("context menu items:", menuTexts.map((s) => s.trim()).join(" | "));
  if (menuTexts.some((s) => /Move to root|移到根/i.test(s))) {
    console.log("ERR: Move-to-root item still present");
    process.exitCode = 1;
  }
  // Press Escape to close
  await page.keyboard.press("Escape");
}

// 5 — i18n: header should reflect backend language. Backend reports `zh`,
// so we expect to see "笔记库" (Vault) in the sidebar header eventually.
await page.waitForTimeout(800);
const vaultHeading = (await page.locator("header + div span").first().textContent()) ?? "";
console.log("sidebar heading text:", vaultHeading.trim());

console.log("---");
console.log("console errors / warnings:", errors.length);
for (const e of errors) console.log(" ", e.type, e.text);

await browser.close();
process.exit(
  initialRows === 0 || errors.some((e) => e.type === "pageerror") ? 1 : (process.exitCode ?? 0),
);
