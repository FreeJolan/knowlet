// Parse a Server-Sent Events response stream into a sequence of decoded
// JSON objects. Per ADR-0008 §"Update 2026-05-02", this lives in its own
// module so it can be tested in isolation — the bug class to catch is
// "the chunk boundary fell mid-event" / "one chunk had two events" /
// "data: line was malformed JSON" / etc.
//
// Two entry points:
//   parseSSE(response)       — for production use; reads response.body
//                              via the standard ReadableStream API.
//   parseSSEFromAsyncIterable(chunks)
//                            — for tests; takes any async iterable of
//                              Uint8Array | string chunks. Decoupled from
//                              fetch so we can simulate partial chunks.

const DECODER = new TextDecoder();

export async function* parseSSE(response) {
  if (!response || !response.body) {
    throw new TypeError("parseSSE: response.body is required");
  }
  const reader = response.body.getReader();
  yield* parseSSEFromReader(reader);
}

export async function* parseSSEFromReader(reader) {
  let buf = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += DECODER.decode(value, { stream: true });
    yield* drain(buf, (rest) => { buf = rest; });
  }
  // Flush any final event that didn't end with the canonical \n\n.
  yield* drain(buf + "\n\n", () => {});
}

export async function* parseSSEFromAsyncIterable(chunks) {
  let buf = "";
  for await (const chunk of chunks) {
    if (typeof chunk === "string") {
      buf += chunk;
    } else if (chunk instanceof Uint8Array) {
      buf += DECODER.decode(chunk, { stream: true });
    } else {
      throw new TypeError(
        `parseSSEFromAsyncIterable: chunks must yield Uint8Array | string, got ${typeof chunk}`
      );
    }
    yield* drain(buf, (rest) => { buf = rest; });
  }
  yield* drain(buf + "\n\n", () => {});
}

function* drain(buf, setRest) {
  let idx;
  while ((idx = buf.indexOf("\n\n")) >= 0) {
    const block = buf.slice(0, idx);
    buf = buf.slice(idx + 2);
    const event = parseEventBlock(block);
    if (event !== undefined) yield event;
  }
  setRest(buf);
}

// Take an SSE event block (text between two `\n\n` separators) and return
// its decoded JSON payload, or undefined if the block is empty / malformed.
// Malformed JSON is logged but does not throw — that matches what live
// SSE pipelines do (occasional bad lines shouldn't kill the stream).
export function parseEventBlock(block) {
  const dataLines = block
    .split("\n")
    .filter((l) => l.startsWith("data: "))
    .map((l) => l.slice(6));
  const json = dataLines.join("");
  if (!json) return undefined;
  try {
    return JSON.parse(json);
  } catch (err) {
    if (typeof console !== "undefined" && console.error) {
      console.error("SSE parse error", err, json);
    }
    return undefined;
  }
}
