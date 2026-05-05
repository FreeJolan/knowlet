import { chromium } from "playwright";
const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1400, height: 900 } })).newPage();
await page.goto("http://localhost:5173", { waitUntil: "networkidle" });
await page.waitForTimeout(800);

console.log("--- before click ---");
const before = await page.locator(".group").allInnerTexts();
for (const [i, t] of before.entries()) console.log(i, JSON.stringify(t));

// Find the row whose text equals "archive" (with whitespace)
const archiveRow = page.locator(".group").filter({ hasText: "archive" }).first();
console.log("archive row count:", await archiveRow.count());
console.log("archive row html:", (await archiveRow.innerHTML()).slice(0, 200));

// Click the inner pill (the one with onClick)
await archiveRow.locator(".rounded-md").first().click();
await page.waitForTimeout(300);
console.log("--- after click on archive's pill ---");
const after = await page.locator(".group").allInnerTexts();
for (const [i, t] of after.entries()) console.log(i, JSON.stringify(t));

await browser.close();
