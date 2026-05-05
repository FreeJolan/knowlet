// Smoke test: open http://localhost:5173, wait for the tree to render, list
// what's visible. Used by the agent to *actually verify* a UI fix works
// before reporting "should be good now". No more white-screen ping-pong.

import { chromium } from "playwright";

const URL = process.env.URL ?? "http://localhost:5173";

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext();
const page = await ctx.newPage();

// Surface every console message + uncaught error so a render bug is loud,
// not silent.
const errors = [];
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") {
    errors.push({ type: m.type(), text: m.text() });
  }
});
page.on("pageerror", (e) => errors.push({ type: "pageerror", text: String(e) }));

const resp = await page.goto(URL, { waitUntil: "networkidle", timeout: 15000 });
console.log(`HTTP ${resp.status()} ${URL}`);

// Wait briefly for React to mount + first paint of the tree.
await page.waitForTimeout(1000);

const title = await page.title();
const headerText = (await page.locator("header").first().textContent()) ?? "";
const vaultText = (await page.locator('text=VAULT').first().isVisible()) ? "yes" : "no";

// Treat any visible row in the tree (folder or note) as proof of life.
const rowTexts = await page.locator(".group").allInnerTexts();

console.log("title:", title);
console.log("header:", headerText.trim());
console.log("vault label visible:", vaultText);
console.log("tree rows visible:", rowTexts.length);
for (const t of rowTexts.slice(0, 20)) console.log("  ·", t.replace(/\s+/g, " ").trim());

console.log("---");
console.log("console errors / warnings:", errors.length);
for (const e of errors) console.log(" ", e.type, e.text);

const bodyHtml = await page.locator("body").innerHTML();
console.log("---");
console.log("body length:", bodyHtml.length);

await browser.close();
process.exit(rowTexts.length === 0 || errors.some((e) => e.type === "pageerror") ? 1 : 0);
