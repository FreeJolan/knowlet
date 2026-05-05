// Runs every e2e file sequentially. Each gets its own backend + vault, so
// they can't interfere. We build the dist once at the top, then pass
// SKIP_BUILD=1 to children to save 5-10 s per file.

import { execSync, spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, "..", "..", "..");

console.log("[run-all] build dist…");
execSync("npm run build --silent", { cwd: join(REPO_ROOT, "frontend"), stdio: "pipe" });

const files = readdirSync(HERE)
  .filter((f) => f.endsWith(".mjs") && !f.startsWith("_") && f !== "run-all.mjs")
  .sort();

let failed = 0;
for (const f of files) {
  console.log(`\n[run-all] === ${f} ===`);
  const r = spawnSync("node", [join(HERE, f)], {
    stdio: "inherit",
    env: { ...process.env, SKIP_BUILD: "1" },
  });
  if (r.status !== 0) failed += 1;
}

console.log(`\n[run-all] done — ${files.length - failed}/${files.length} suites passed`);
process.exit(failed === 0 ? 0 : 1);
