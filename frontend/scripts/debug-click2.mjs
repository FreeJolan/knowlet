import { chromium } from "playwright";
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
page.on("console", m => {
  const t = m.text();
  if (t.includes("knowlet") || t.includes("toggle")) console.log("[browser]", m.type(), t);
});
await page.goto("http://localhost:5173", { waitUntil: "networkidle" });
await page.waitForTimeout(800);

const before = (await page.locator(".group").allInnerTexts()).length;
console.log("BEFORE:", before, "rows");
await page.locator(".group").filter({ hasText: "archive" }).first().click();
await page.waitForTimeout(500);
const after = (await page.locator(".group").allInnerTexts()).length;
console.log("AFTER:", after, "rows");

await browser.close();
