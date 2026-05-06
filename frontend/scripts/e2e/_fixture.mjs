/**
 * E2E fixture: spawns an isolated knowlet backend on a free port with a
 * seeded tmpdir vault, builds the frontend (once), and hands the test a
 * Playwright page pointed at it. Tear down kills the server + removes
 * the tmpdir so each test gets a clean slate.
 *
 * Cost per test file: ~3 s for FastAPI bootstrap + ~1 s for browser launch.
 * Tests within a file share the server. Group related cases in one file.
 */

import { execSync, spawn } from "node:child_process";
import { mkdtempSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");

/** Pick a free TCP port by asking the OS for one. */
async function freePort() {
  const net = await import("node:net");
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.unref();
    srv.on("error", reject);
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr ? addr.port : 0;
      srv.close(() => resolve(port));
    });
  });
}

/** Wait for `GET /api/health` on the given baseURL to return 200. */
async function waitForBackend(baseURL, timeoutMs = 15000) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    try {
      const r = await fetch(`${baseURL}/api/health`);
      if (r.ok) return;
    } catch {
      // Backend not up yet; retry.
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`backend did not become ready within ${timeoutMs} ms`);
}

/**
 * Seed a vault on disk via a Python one-liner. Lets us hit Vault.write_note
 * with explicit folder=... so the layout matches what the test expects.
 *
 * @param {string} vaultDir   Existing empty directory (already created).
 * @param {Array<{title: string, body?: string, folder?: string}>} notes
 * @param {string[]} folders  Folder paths to mkdir (forward-slash).
 * @param {"en" | "zh"} language
 */
function seedVault(vaultDir, { notes = [], folders = [], language = "en" } = {}) {
  // Build a Python script that does the seed in-process and writes config.toml.
  const lines = [
    "from pathlib import Path",
    "from knowlet.config import KnowletConfig, save_config",
    "from knowlet.core.note import Note, new_id",
    "from knowlet.core.vault import Vault",
    `v = Vault(Path(${JSON.stringify(vaultDir)}))`,
    "v.init_layout()",
    "cfg = KnowletConfig()",
    `cfg.general.language = ${JSON.stringify(language)}`,
    "cfg.embedding.backend = 'dummy'",
    "cfg.embedding.dim = 32",
    "cfg.llm.api_key = 'stub'",
    "save_config(v.root, cfg)",
  ];
  for (const f of folders) lines.push(`v.mkdir_folder(${JSON.stringify(f)})`);
  for (const n of notes) {
    const folder = n.folder ? `, folder=${JSON.stringify(n.folder)}` : "";
    const body = JSON.stringify(n.body ?? "body of " + n.title);
    lines.push(
      `v.write_note(Note(id=new_id(), title=${JSON.stringify(n.title)}, body=${body}, tags=[])${folder})`,
    );
  }
  const script = lines.join("\n");
  // Write to a temp file rather than -c, so multi-line newlines aren't
  // mangled by the shell.
  const scriptPath = join(vaultDir, "__seed.py");
  writeFileSync(scriptPath, script, "utf8");
  try {
    execSync(`uv run --directory ${REPO_ROOT} python ${scriptPath}`, { stdio: "pipe" });
  } finally {
    try {
      unlinkSync(scriptPath);
    } catch {
      // ignore
    }
  }
}

/**
 * Set up a fresh test environment. Returns { page, browser, baseURL,
 * vaultDir, teardown }. Caller must call teardown() in a finally block.
 *
 * @param {{
 *   notes?: Array<{title: string, body?: string, folder?: string}>,
 *   folders?: string[],
 *   language?: "en" | "zh",
 *   headless?: boolean,
 * }} opts
 */
export async function setupTestEnv(opts = {}) {
  const { notes = [], folders = [], language = "en", headless = true } = opts;

  // Make sure dist is built so FastAPI can serve the SPA.
  if (!process.env.SKIP_BUILD) {
    execSync("npm run build --silent", { cwd: join(REPO_ROOT, "frontend"), stdio: "pipe" });
  }

  const vaultDir = mkdtempSync(join(tmpdir(), "knowlet-e2e-"));
  seedVault(vaultDir, { notes, folders, language });

  const port = await freePort();
  const baseURL = `http://127.0.0.1:${port}`;

  // Spawn the backend in its OWN process group (`detached: true`).
  // `uv run knowlet web` is a 2-hop launch: uv spawns python, python
  // runs the FastAPI app. SIGKILL on the immediate child kills `uv`
  // but leaves the python grandchild reparented to launchd — which
  // then accumulates dozens of orphan backends on a busy dev day.
  // Putting the child in its own group lets us kill the whole group
  // in teardown via `process.kill(-pid, "SIGKILL")`.
  const backend = spawn(
    "uv",
    [
      "run",
      "--directory",
      REPO_ROOT,
      "knowlet",
      "web",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
    ],
    {
      env: { ...process.env, KNOWLET_VAULT: vaultDir },
      stdio: "pipe",
      detached: true,
    },
  );
  // Capture backend logs for debugging — only printed on failure.
  let backendLog = "";
  backend.stdout.on("data", (d) => (backendLog += d.toString()));
  backend.stderr.on("data", (d) => (backendLog += d.toString()));
  backend.on("error", (e) => {
    backendLog += `\nspawn error: ${String(e)}`;
  });

  try {
    await waitForBackend(baseURL);
  } catch (e) {
    backend.kill("SIGKILL");
    rmSync(vaultDir, { recursive: true, force: true });
    console.error("--- backend log ---\n" + backendLog);
    throw e;
  }

  const browser = await chromium.launch({ headless });
  const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
  const page = await context.newPage();

  const errors = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push({ type: m.type(), text: m.text() });
  });
  page.on("pageerror", (e) => errors.push({ type: "pageerror", text: String(e) }));

  return {
    page,
    browser,
    baseURL,
    vaultDir,
    errors,
    backendLog: () => backendLog,
    teardown: async () => {
      await browser.close().catch(() => {});
      // Detach stdio listeners + destroy streams; otherwise SIGKILL'd
      // backend's pipes can keep node's event loop alive after our test
      // logic finishes, leaving the process hanging until the parent
      // wrapper times out.
      backend.stdout.removeAllListeners();
      backend.stderr.removeAllListeners();
      backend.stdout.destroy();
      backend.stderr.destroy();
      // Kill the WHOLE process group, not just `uv`. The python
      // grandchild that actually serves FastAPI shares the group
      // (because we spawned with detached: true above). Negative PID
      // = "send signal to every process in this group". Without this
      // the python process gets reparented to launchd and lingers
      // until next reboot.
      try {
        if (typeof backend.pid === "number") {
          process.kill(-backend.pid, "SIGKILL");
        }
      } catch {
        // group may already be gone — ignore
      }
      // Also tag the immediate child for good measure.
      backend.kill("SIGKILL");
      try {
        rmSync(vaultDir, { recursive: true, force: true });
      } catch {
        // ignore
      }
    },
  };
}

/**
 * Tiny assertion helpers — keep e2e files terse without pulling a full
 * test runner. Each failing assert throws and prints the test file name.
 */
export function assert(cond, msg) {
  if (!cond) throw new Error(`assertion failed: ${msg}`);
}
export function assertEqual(actual, expected, msg) {
  if (actual !== expected) {
    throw new Error(
      `assertion failed: ${msg ?? ""} — expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
    );
  }
}

/** Wait until `selector` is visible AND its first element's text matches. */
export async function expectRow(page, text, timeoutMs = 3000) {
  const loc = page.locator(".group").filter({ hasText: text }).first();
  await loc.waitFor({ state: "visible", timeout: timeoutMs });
  return loc;
}

/** True if the tree contains a row with this exact text. */
export async function hasRow(page, text) {
  const count = await page.locator(".group").filter({ hasText: text }).count();
  return count > 0;
}

/**
 * Assert that `locator`'s first element is the active element in the
 * page's document. Critical for "did focus actually land?" — Playwright's
 * `.fill()` force-focuses the input it acts on, so plain visibility
 * checks don't catch focus regressions.
 */
export async function expectFocused(page, locator, msg = "expected element to be focused") {
  const isFocused = await locator.evaluate((el) => el === document.activeElement);
  if (!isFocused) {
    const active = await page.evaluate(() => {
      const a = document.activeElement;
      return a ? `${a.tagName}.${a.className?.toString().slice(0, 40)}` : "<none>";
    });
    throw new Error(`${msg}; activeElement=${active}`);
  }
}

/**
 * Type into a focused input the way a real user would: keystroke by
 * keystroke through Playwright's keyboard. Distinct from `input.fill()`
 * which sets `.value` directly and skips the keydown / input event chain.
 *
 * Use this whenever the test path cares about input handlers (IME
 * composition, keydown propagation, isComposing checks).
 */
export async function typeInto(page, locator, text, opts = {}) {
  await locator.click();
  await locator.evaluate((el) => {
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      el.value = "";
    }
  });
  await page.keyboard.type(text, { delay: opts.delay ?? 30 });
}

/**
 * Simulate a Chinese IME composition: composition events with
 * isComposing true, an Enter to confirm the candidate (which our input
 * must NOT treat as submit), then a final composition end + the resolved
 * characters. Mirrors what macOS pinyin / Sogou actually emits well
 * enough to catch the "Enter mid-IME submits the form" class of bug.
 */
export async function simulateIMEComposition(page, locator, finalText) {
  await locator.focus();
  // Open composition.
  await locator.evaluate((el, text) => {
    el.dispatchEvent(new CompositionEvent("compositionstart", { data: "" }));
    el.dispatchEvent(new CompositionEvent("compositionupdate", { data: text }));
  }, finalText);
  // The browser dispatches a keydown for Enter with isComposing=true
  // when the user accepts the IME candidate. Playwright doesn't expose
  // the isComposing flag directly, so dispatch a synthetic event with it.
  await locator.evaluate((el) => {
    const ev = new KeyboardEvent("keydown", {
      key: "Enter",
      code: "Enter",
      isComposing: true,
      bubbles: true,
      cancelable: true,
    });
    el.dispatchEvent(ev);
  });
  // End composition with the chosen text.
  await locator.evaluate((el, text) => {
    el.dispatchEvent(new CompositionEvent("compositionend", { data: text }));
    if (el instanceof HTMLInputElement) {
      el.value = text;
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }, finalText);
}

/** Run the body, print a green/red line, exit non-zero on failure. */
export async function runTest(name, fn) {
  const t0 = Date.now();
  try {
    await fn();
    const ms = Date.now() - t0;
    console.log(`✓ ${name} (${ms}ms)`);
  } catch (e) {
    console.log(`✗ ${name}`);
    console.error(e instanceof Error ? e.stack : String(e));
    process.exitCode = 1;
  }
}

/**
 * Force the process to exit after `delayMs`. Some test files trigger
 * react-dnd's HTML5 backend, which keeps timers alive even after browser
 * + backend are gone. Call this at the very end of each e2e file to
 * keep run-all.mjs moving instead of stalling on dangling handles.
 */
export function exitAfter(delayMs = 100) {
  setTimeout(() => process.exit(process.exitCode ?? 0), delayMs).unref();
}

void writeFileSync; // keep imported util available for follow-on tests
