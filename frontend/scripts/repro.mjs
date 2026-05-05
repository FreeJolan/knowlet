// Repro the three bugs the user reported, with video + per-step DOM
// dumps. Run headed=false to record, then watch the .webm.

import { setupTestEnv } from "./e2e/_fixture.mjs";

const env = await setupTestEnv({
  notes: [{ title: "alpha", folder: "lab" }],
  folders: ["lab", "other"],
  language: "en",
  headless: true,
});
const { page, browser, baseURL, teardown, errors } = env;

// Capture network traffic to see if create/rename POST/PUT actually fires
// and what the response is.
const requests = [];
page.on("request", (req) => {
  if (req.url().includes("/api/")) {
    requests.push(`>>> ${req.method()} ${req.url().split("/api/")[1]}`);
  }
});
page.on("response", async (resp) => {
  if (resp.url().includes("/api/")) {
    let body = "";
    try {
      body = (await resp.text()).slice(0, 200);
    } catch {
      // ignore
    }
    requests.push(`<<< ${resp.status()} ${resp.url().split("/api/")[1]} ${body}`);
  }
});
page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") {
    console.log(`[console.${m.type()}]`, m.text());
  }
});

await page.goto(baseURL, { waitUntil: "networkidle" });
await page.waitForTimeout(500);

async function snapshot(label) {
  const inputCount = await page.locator('input[data-rename-input="true"]').count();
  const rows = await page.locator(".group").allInnerTexts();
  const active = await page.evaluate(() => {
    const a = document.activeElement;
    return a
      ? `${a.tagName}${a.id ? "#" + a.id : ""}.${(a.className?.toString() ?? "").slice(0, 40)} value=${"value" in a ? a.value : ""}`
      : "<none>";
  });
  console.log(`\n--- ${label} ---`);
  console.log("active:", active);
  console.log("inputs visible:", inputCount);
  console.log(
    "rows (",
    rows.length,
    "):",
    rows.map((s) => s.replace(/\s+/g, " ").trim()).slice(0, 10).join(" | "),
  );
}

// =================== Bug A: new note disappears ===================
console.log("\n##### BUG A: new note → Enter → disappears");

await snapshot("A.0 baseline");
await page.click('button[aria-label="New note"]');
await page.waitForTimeout(80);
await snapshot("A.1 after click +");
await page.keyboard.type("note-a-1", { delay: 30 });
await snapshot("A.2 after typing");
await page.keyboard.press("Enter");
await page.waitForTimeout(50);
await snapshot("A.3 +50ms after Enter");
await page.waitForTimeout(150);
await snapshot("A.4 +200ms after Enter");
await page.waitForTimeout(800);
await snapshot("A.5 +1s after Enter");
await page.waitForTimeout(1500);
await snapshot("A.6 +2.5s after Enter (final)");

// =================== Bug B: caret invisible ===================
console.log("\n##### BUG B: caret not visible in input");

await page.click('button[aria-label="New note"]');
await page.waitForTimeout(200);
const inputStyles = await page.evaluate(() => {
  const i = document.querySelector('input[data-rename-input="true"]');
  if (!i) return null;
  const cs = getComputedStyle(i);
  return {
    color: cs.color,
    caretColor: cs.caretColor,
    background: cs.backgroundColor,
    selectionStart: i.selectionStart,
    selectionEnd: i.selectionEnd,
    valueLength: i.value.length,
    placeholder: i.placeholder,
    isActive: i === document.activeElement,
  };
});
console.log("input computed style + selection:", JSON.stringify(inputStyles, null, 2));
await page.keyboard.press("Escape");
await page.waitForTimeout(200);

// =================== Bug C: Rename loses focus immediately ===================
console.log("\n##### BUG C: Rename → focus disappears");

const alphaRow = page.locator(".group").filter({ hasText: "alpha" }).first();
await alphaRow.click({ button: "right" });
await page.waitForTimeout(200);
await snapshot("C.0 after right-click");
await page.getByRole("menuitem", { name: "Rename" }).click();
await page.waitForTimeout(20);
await snapshot("C.1 +20ms after Rename click");
await page.waitForTimeout(80);
await snapshot("C.2 +100ms after Rename click");
await page.waitForTimeout(400);
await snapshot("C.3 +500ms after Rename click");

console.log("\n##### NETWORK TRACE");
for (const r of requests) console.log(r);

console.log("\n##### CONSOLE ERRORS");
for (const e of errors) console.log(`[${e.type}]`, e.text);

await browser.close();
process.exit(0);
