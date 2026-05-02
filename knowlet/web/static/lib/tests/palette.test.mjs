// Tests for the Cmd+K palette query classifier + filters.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  classifyQuery,
  filterCommands,
  filterNotes,
} from "../palette.js";

// ---------------- classifyQuery

test("classifyQuery: empty / whitespace → browse", () => {
  assert.deepEqual(classifyQuery(""), { mode: "browse", text: "" });
  assert.deepEqual(classifyQuery("   "), { mode: "browse", text: "" });
  assert.deepEqual(classifyQuery(null), { mode: "browse", text: "" });
  assert.deepEqual(classifyQuery(undefined), { mode: "browse", text: "" });
});

test("classifyQuery: > prefix → ask AI", () => {
  assert.deepEqual(classifyQuery("> what is RAG?"), {
    mode: "ask",
    text: "what is RAG?",
  });
  assert.deepEqual(classifyQuery(">already-no-space"), {
    mode: "ask",
    text: "already-no-space",
  });
  // > with no text after is still "ask" mode (UI shows hint, button disabled)
  assert.deepEqual(classifyQuery(">"), { mode: "ask", text: "" });
  assert.deepEqual(classifyQuery(">  "), { mode: "ask", text: "" });
});

test("classifyQuery: + prefix → newnote", () => {
  assert.deepEqual(classifyQuery("+ My new note"), {
    mode: "newnote",
    text: "My new note",
  });
  assert.deepEqual(classifyQuery("+plain"), { mode: "newnote", text: "plain" });
  assert.deepEqual(classifyQuery("+"), { mode: "newnote", text: "" });
});

test("classifyQuery: bare text → fuzzy (lowercased)", () => {
  assert.deepEqual(classifyQuery("RAG"), { mode: "fuzzy", text: "rag" });
  assert.deepEqual(classifyQuery("Attention"), {
    mode: "fuzzy",
    text: "attention",
  });
  assert.deepEqual(classifyQuery("  spaced  "), {
    mode: "fuzzy",
    text: "spaced",
  });
});

test("classifyQuery: > inside the body (not a prefix) is fuzzy", () => {
  // Only the leading char qualifies. "rag>thing" is just a fuzzy query.
  assert.deepEqual(classifyQuery("rag>thing"), {
    mode: "fuzzy",
    text: "rag>thing",
  });
});

// ---------------- filterNotes

const NOTES = [
  { id: "1", title: "Attention paper notes", updated_at: "2026-05-01" },
  { id: "2", title: "RAG 检索策略", updated_at: "2026-05-02" },
  { id: "3", title: "RAG: another retrieval note", updated_at: "2026-05-02" },
  { id: "4", title: "TOEFL writing", updated_at: "2026-04-30" },
];

test("filterNotes: empty query returns first N preserving order", () => {
  assert.deepEqual(
    filterNotes(NOTES, "", 2).map((n) => n.id),
    ["1", "2"],
  );
});

test("filterNotes: matches case-insensitive substring", () => {
  const ids = filterNotes(NOTES, "rag", 8).map((n) => n.id);
  assert.deepEqual(ids, ["2", "3"]);
});

test("filterNotes: respects limit when many match", () => {
  const ids = filterNotes(NOTES, "rag", 1).map((n) => n.id);
  assert.deepEqual(ids, ["2"]);
});

test("filterNotes: handles malformed entries (no title)", () => {
  const messy = [...NOTES, { id: "X" }, null];
  const ids = filterNotes(messy, "rag", 8).map((n) => n.id);
  assert.deepEqual(ids, ["2", "3"]);
});

test("filterNotes: non-array notes returns []", () => {
  assert.deepEqual(filterNotes(null, "rag"), []);
  assert.deepEqual(filterNotes(undefined, "rag"), []);
});

// ---------------- filterCommands

const COMMANDS = [
  { id: "a", label: "Fetch all feeds now" },
  { id: "b", label: "Review inbox" },
  { id: "c", label: "Save chat as a note" },
  { id: "d", label: "Open profile" },
];

test("filterCommands: empty query returns all (copy)", () => {
  const out = filterCommands(COMMANDS, "");
  assert.equal(out.length, COMMANDS.length);
  assert.notEqual(out, COMMANDS, "should be a fresh array, not the same ref");
});

test("filterCommands: case-insensitive label substring", () => {
  const ids = filterCommands(COMMANDS, "review").map((c) => c.id);
  assert.deepEqual(ids, ["b"]);
});

test("filterCommands: tolerates malformed entries", () => {
  const messy = [...COMMANDS, { id: "X" }, null];
  const out = filterCommands(messy, "");
  // Empty query → return everything (including malformed); only filtering
  // skips bad entries.
  assert.equal(out.length, messy.length);
  const filtered = filterCommands(messy, "feeds").map((c) => c.id);
  assert.deepEqual(filtered, ["a"]);
});
