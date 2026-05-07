// Runs every e2e file with bounded parallelism. Each suite already gets
// its own backend (freePort + tmpdir vault + isolated Playwright), so
// they can't interfere — we just need to cap how many spawn at once
// to avoid swamping the dev box with 20 simultaneous Python backends.
//
// We build dist once at the top, then pass SKIP_BUILD=1 to children to
// save 5-10 s per file.
//
// Concurrency: defaults to `min(cpus, 6)`; override with E2E_CONCURRENCY
// (1 = effective serial; useful for debugging interleaving suspicions).
//
// Output policy: collect each child's stdout+stderr into a buffer and
// flush the whole block with a `=== file ===` header when the child
// exits. Prevents 6 suites' output from interleaving line-by-line.

import { execSync, spawn } from "node:child_process";
import { readdirSync } from "node:fs";
import { cpus } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");

const DEFAULT_CONCURRENCY = Math.max(2, Math.min(cpus().length, 6));
const concurrency = Math.max(
  1,
  parseInt(process.env.E2E_CONCURRENCY ?? "", 10) || DEFAULT_CONCURRENCY,
);

console.log("[run-all] build dist…");
execSync("npm run build --silent", { cwd: join(REPO_ROOT, "frontend"), stdio: "pipe" });

const files = readdirSync(HERE)
  .filter((f) => f.endsWith(".mjs") && !f.startsWith("_") && f !== "run-all.mjs")
  .sort();

console.log(
  `[run-all] running ${files.length} suite(s) with concurrency=${concurrency}`,
);

/** Spawn one suite. Resolves with `{file, code, output, durationMs}`. */
function runSuite(file) {
  const t0 = Date.now();
  return new Promise((resolve) => {
    const child = spawn("node", [join(HERE, file)], {
      env: { ...process.env, SKIP_BUILD: "1" },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let out = "";
    child.stdout.on("data", (d) => (out += d.toString()));
    child.stderr.on("data", (d) => (out += d.toString()));
    child.on("error", (e) => (out += `\nspawn error: ${String(e)}`));
    child.on("close", (code) => {
      resolve({ file, code: code ?? 1, output: out, durationMs: Date.now() - t0 });
    });
  });
}

/** Bounded parallel pool — runs at most `n` suites simultaneously. */
async function runPool(files, n) {
  const results = [];
  let next = 0;
  async function worker() {
    while (next < files.length) {
      const idx = next++;
      const file = files[idx];
      const r = await runSuite(file);
      // Print this suite's full output as a single block so concurrent
      // workers don't interleave their lines.
      const sec = (r.durationMs / 1000).toFixed(1);
      const banner =
        r.code === 0
          ? `[run-all] ✓ ${file}  (${sec}s)`
          : `[run-all] ✗ ${file}  (${sec}s)  exit=${r.code}`;
      console.log(`\n${banner}\n${r.output}`);
      results.push(r);
    }
  }
  await Promise.all(Array.from({ length: Math.min(n, files.length) }, worker));
  return results;
}

const startTotal = Date.now();
const results = await runPool(files, concurrency);
const totalSec = ((Date.now() - startTotal) / 1000).toFixed(1);
const failed = results.filter((r) => r.code !== 0).length;

// Summary table sorted by file name (matches the sequential-mode log
// order, makes diffs easier to read).
const sorted = [...results].sort((a, b) => a.file.localeCompare(b.file));
console.log("\n[run-all] summary:");
for (const r of sorted) {
  const sec = (r.durationMs / 1000).toFixed(1).padStart(5);
  const mark = r.code === 0 ? "✓" : "✗";
  console.log(`  ${mark}  ${sec}s  ${r.file}`);
}
console.log(
  `\n[run-all] done — ${files.length - failed}/${files.length} suites passed in ${totalSec}s (concurrency=${concurrency})`,
);
process.exit(failed === 0 ? 0 : 1);
