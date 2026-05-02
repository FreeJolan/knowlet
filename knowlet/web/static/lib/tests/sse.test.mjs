// Tests for the SSE parser. Node native test runner — no deps.
//
// Run via: scripts/test-frontend.sh
// Or directly: node --test knowlet/web/static/lib/tests/

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  parseEventBlock,
  parseSSEFromAsyncIterable,
} from "../sse.js";

// ---------------- parseEventBlock (pure)

test("parseEventBlock: single data line of valid JSON", () => {
  const ev = parseEventBlock(`data: {"type":"reply_chunk","text":"hi"}`);
  assert.deepEqual(ev, { type: "reply_chunk", text: "hi" });
});

test("parseEventBlock: multi-line data is concatenated", () => {
  const block = [
    `data: {"type":"reply_chunk",`,
    `data: "text":"hi"}`,
  ].join("\n");
  const ev = parseEventBlock(block);
  assert.deepEqual(ev, { type: "reply_chunk", text: "hi" });
});

test("parseEventBlock: empty block returns undefined", () => {
  assert.equal(parseEventBlock(""), undefined);
  assert.equal(parseEventBlock("\n"), undefined);
});

test("parseEventBlock: malformed JSON returns undefined (does not throw)", () => {
  // Silence the parser's console.error for this case.
  const origErr = console.error;
  console.error = () => {};
  try {
    assert.equal(parseEventBlock(`data: {not json`), undefined);
  } finally {
    console.error = origErr;
  }
});

test("parseEventBlock: ignores non-data lines (event:, id:, retry:)", () => {
  const block = [
    `event: tool_call`,
    `id: 42`,
    `retry: 100`,
    `data: {"type":"tool_call","name":"search_notes"}`,
  ].join("\n");
  assert.deepEqual(parseEventBlock(block), {
    type: "tool_call",
    name: "search_notes",
  });
});

// ---------------- parseSSEFromAsyncIterable (chunk-based)

async function collect(iter) {
  const out = [];
  for await (const ev of iter) out.push(ev);
  return out;
}

async function* yieldChunks(...chunks) {
  for (const c of chunks) yield typeof c === "string" ? c : c;
}

test("stream: one chunk with one complete event", async () => {
  const events = await collect(parseSSEFromAsyncIterable(yieldChunks(
    `data: {"type":"reply_chunk","text":"hello"}\n\n`,
  )));
  assert.equal(events.length, 1);
  assert.deepEqual(events[0], { type: "reply_chunk", text: "hello" });
});

test("stream: two events in one chunk", async () => {
  const events = await collect(parseSSEFromAsyncIterable(yieldChunks(
    [
      `data: {"type":"reply_chunk","text":"a"}`,
      ``,
      `data: {"type":"reply_chunk","text":"b"}`,
      ``,
    ].join("\n"),
  )));
  assert.deepEqual(events, [
    { type: "reply_chunk", text: "a" },
    { type: "reply_chunk", text: "b" },
  ]);
});

test("stream: event split across chunks (boundary mid-JSON)", async () => {
  // Server sends one event in two TCP frames; the boundary lands inside
  // the JSON payload. Parser must buffer until the trailing \n\n arrives.
  const events = await collect(parseSSEFromAsyncIterable(yieldChunks(
    `data: {"type":"reply_chunk","tex`,
    `t":"split"}\n\n`,
  )));
  assert.deepEqual(events, [{ type: "reply_chunk", text: "split" }]);
});

test("stream: event split across chunks (boundary mid-separator)", async () => {
  // The \n\n separator itself spans the chunk boundary.
  const events = await collect(parseSSEFromAsyncIterable(yieldChunks(
    `data: {"type":"reply_chunk","text":"x"}\n`,
    `\n`,
  )));
  assert.deepEqual(events, [{ type: "reply_chunk", text: "x" }]);
});

test("stream: malformed event in the middle does not break the stream", async () => {
  const origErr = console.error;
  console.error = () => {};
  try {
    const events = await collect(parseSSEFromAsyncIterable(yieldChunks(
      [
        `data: {"type":"reply_chunk","text":"a"}`, ``,
        `data: {bad json`, ``,
        `data: {"type":"reply_chunk","text":"c"}`, ``,
      ].join("\n"),
    )));
    assert.deepEqual(events, [
      { type: "reply_chunk", text: "a" },
      { type: "reply_chunk", text: "c" },
    ]);
  } finally {
    console.error = origErr;
  }
});

test("stream: trailing event without \\n\\n is flushed at end of stream", async () => {
  // Some servers don't append a final separator before closing the connection.
  // We should still surface the last event rather than dropping it.
  const events = await collect(parseSSEFromAsyncIterable(yieldChunks(
    `data: {"type":"turn_done","final_text":"end"}`,
  )));
  assert.deepEqual(events, [{ type: "turn_done", final_text: "end" }]);
});

test("stream: empty input yields no events", async () => {
  const events = await collect(parseSSEFromAsyncIterable(yieldChunks()));
  assert.deepEqual(events, []);
});

test("stream: Uint8Array chunks decode the same as strings", async () => {
  const enc = new TextEncoder();
  const events = await collect(parseSSEFromAsyncIterable(yieldChunks(
    enc.encode(`data: {"type":"reply_chunk","text":"中文"}\n\n`),
  )));
  assert.deepEqual(events, [{ type: "reply_chunk", text: "中文" }]);
});

test("stream: UTF-8 multi-byte char split across chunk boundary", async () => {
  // "中" is 0xE4 0xB8 0xAD. Slicing it mid-byte must not produce mojibake.
  const enc = new TextEncoder();
  const fullBytes = enc.encode(`data: {"type":"x","t":"中"}\n\n`);
  // Find the 中's bytes (E4 B8 AD) and split between B8 and AD.
  const idx = fullBytes.indexOf(0xE4);
  assert.ok(idx > 0, "expected to find E4 byte");
  const split = idx + 2; // after E4 B8, before AD
  const a = fullBytes.subarray(0, split);
  const b = fullBytes.subarray(split);
  const events = await collect(parseSSEFromAsyncIterable(yieldChunks(a, b)));
  assert.deepEqual(events, [{ type: "x", t: "中" }]);
});
