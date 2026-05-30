#!/usr/bin/env node
import fs from "node:fs";

const args = new Map();
for (let index = 2; index < process.argv.length; index += 2) {
  const key = process.argv[index];
  const value = process.argv[index + 1];
  if (!key?.startsWith("--") || value === undefined) {
    throw new Error(`Invalid argument near ${key ?? "<empty>"}`);
  }
  args.set(key.slice(2), value);
}

for (const key of ["version", "notes-file", "pub-date", "url", "signature-file", "out"]) {
  if (!args.has(key)) {
    throw new Error(`Missing required --${key}`);
  }
}

const version = args.get("version");
const notes = fs.readFileSync(args.get("notes-file"), "utf8").trim();
const signature = fs.readFileSync(args.get("signature-file"), "utf8").trim();
const url = args.get("url");

if (!signature) {
  throw new Error("Updater signature is empty");
}
if (!url) {
  throw new Error("Updater URL is empty");
}

const manifest = {
  version,
  notes,
  pub_date: args.get("pub-date"),
  platforms: {
    "darwin-aarch64": { signature, url },
    "darwin-x86_64": { signature, url },
  },
};

fs.writeFileSync(args.get("out"), `${JSON.stringify(manifest, null, 2)}\n`);
