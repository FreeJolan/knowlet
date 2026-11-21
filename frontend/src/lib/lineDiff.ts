/**
 * Phase 2 E Slice S5 — line-level diff for the merge editor.
 *
 * LCS-based 2-way diff. Given two strings, returns a sequence of
 * "hunks": runs of consecutive lines either equal on both sides or
 * differing. The merge UI iterates over hunks and lets the user
 * pick a side per differing hunk.
 *
 * Performance bounds: the common prefix / suffix is matched in linear
 * time, so only the changed middle is diffed. That middle costs O(n × m)
 * time; memory stays bounded — a full LCS table is used only up to
 * ``TABLE_CELL_LIMIT`` cells (8 MB), larger middles are split with
 * Hirschberg's linear-space recursion. The editor caps at 5 000 lines
 * per side and falls back to a "whole file" 2-pane choice past that
 * (see ``MAX_DIFFABLE_LINES``).
 */

export type LineHunkKind = "equal" | "diff";

export interface LineHunk {
  kind: LineHunkKind;
  mine: string[];
  theirs: string[];
}

export const MAX_DIFFABLE_LINES = 5000;

export class TooLargeForDiffError extends Error {
  readonly mineLineCount: number;
  readonly theirsLineCount: number;
  constructor(mineLineCount: number, theirsLineCount: number) {
    super(
      `note exceeds ${MAX_DIFFABLE_LINES}-line diff cap ` +
        `(mine=${mineLineCount}, theirs=${theirsLineCount})`,
    );
    this.mineLineCount = mineLineCount;
    this.theirsLineCount = theirsLineCount;
  }
}

export function splitLines(s: string): string[] {
  // We split on \n and keep "" trailing entries to round-trip
  // newline-terminated content. join("\n") is the inverse.
  if (s === "") return [];
  return s.split("\n");
}

export function joinLines(lines: string[]): string {
  return lines.join("\n");
}

export function diffLines(mine: string, theirs: string): LineHunk[] {
  const a = splitLines(mine);
  const b = splitLines(theirs);
  if (a.length > MAX_DIFFABLE_LINES || b.length > MAX_DIFFABLE_LINES) {
    throw new TooLargeForDiffError(a.length, b.length);
  }
  const ops = computeOps(a, b);
  return groupHunks(ops);
}

type Op =
  | { kind: "equal"; line: string }
  | { kind: "mine"; line: string }
  | { kind: "theirs"; line: string };

/** Largest LCS table (n × m cells) built in one piece: 8 MB as Uint16. */
const TABLE_CELL_LIMIT = 4_000_000;

/** Line ops in source order: shared prefix + diff of the middle + shared
 * suffix.
 *
 * Uses non-null assertions liberally because the loop bounds make
 * every indexed read in-range; the TS compiler under
 * ``noUncheckedIndexedAccess`` can't prove that. */
function computeOps(a: string[], b: string[]): Op[] {
  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) {
    start++;
  }
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }
  const ops: Op[] = [];
  for (let i = 0; i < start; i++) ops.push({ kind: "equal", line: a[i]! });
  diffRange(a, start, endA, b, start, endB, ops);
  for (let i = endA; i < a.length; i++) {
    ops.push({ kind: "equal", line: a[i]! });
  }
  return ops;
}

/** Append the ops turning a[aLo, aHi) into b[bLo, bHi). */
function diffRange(
  a: string[],
  aLo: number,
  aHi: number,
  b: string[],
  bLo: number,
  bHi: number,
  out: Op[],
): void {
  const n = aHi - aLo;
  const m = bHi - bLo;
  if (n === 0) {
    for (let j = bLo; j < bHi; j++) out.push({ kind: "theirs", line: b[j]! });
    return;
  }
  if (m === 0) {
    for (let i = aLo; i < aHi; i++) out.push({ kind: "mine", line: a[i]! });
    return;
  }
  if (n * m <= TABLE_CELL_LIMIT || n === 1) {
    tableOps(a, aLo, aHi, b, bLo, bHi, out);
    return;
  }
  // Hirschberg: split a in half, find where an optimal alignment crosses
  // that row using two O(m) LCS-length rows, recurse on both quadrants.
  const aMid = aLo + (n >> 1);
  const fwd = forwardLcsRow(a, aLo, aMid, b, bLo, bHi);
  const bwd = backwardLcsRow(a, aMid, aHi, b, bLo, bHi);
  let best = -1;
  let split = 0;
  for (let j = 0; j <= m; j++) {
    const v = fwd[j]! + bwd[j]!;
    if (v > best) {
      best = v;
      split = j;
    }
  }
  diffRange(a, aLo, aMid, b, bLo, bLo + split, out);
  diffRange(a, aMid, aHi, b, bLo + split, bHi, out);
}

/** row[j] = LCS length of a[aLo, aHi) and b[bLo, bLo + j). */
function forwardLcsRow(
  a: string[],
  aLo: number,
  aHi: number,
  b: string[],
  bLo: number,
  bHi: number,
): Int32Array {
  const m = bHi - bLo;
  let prev = new Int32Array(m + 1);
  let cur = new Int32Array(m + 1);
  for (let i = aLo; i < aHi; i++) {
    const ai = a[i]!;
    cur[0] = 0;
    for (let j = 1; j <= m; j++) {
      if (ai === b[bLo + j - 1]) cur[j] = prev[j - 1]! + 1;
      else {
        const up = prev[j]!;
        const left = cur[j - 1]!;
        cur[j] = up >= left ? up : left;
      }
    }
    [prev, cur] = [cur, prev];
  }
  return prev;
}

/** row[j] = LCS length of a[aLo, aHi) and b[bLo + j, bHi). */
function backwardLcsRow(
  a: string[],
  aLo: number,
  aHi: number,
  b: string[],
  bLo: number,
  bHi: number,
): Int32Array {
  const m = bHi - bLo;
  let prev = new Int32Array(m + 1);
  let cur = new Int32Array(m + 1);
  for (let i = aHi - 1; i >= aLo; i--) {
    const ai = a[i]!;
    cur[m] = 0;
    for (let j = m - 1; j >= 0; j--) {
      if (ai === b[bLo + j]) cur[j] = prev[j + 1]! + 1;
      else {
        const down = prev[j]!;
        const right = cur[j + 1]!;
        cur[j] = down >= right ? down : right;
      }
    }
    [prev, cur] = [cur, prev];
  }
  return prev;
}

/** Standard LCS-table backtrack over a[aLo, aHi) × b[bLo, bHi); appends
 * ops in source order. */
function tableOps(
  a: string[],
  aLo: number,
  aHi: number,
  b: string[],
  bLo: number,
  bHi: number,
  out: Op[],
): void {
  const n = aHi - aLo;
  const m = bHi - bLo;
  // Flat row-major typed array — small constant factor vs nested arrays
  // and no GC pressure from N+1 arrays. LCS values never exceed
  // min(n, m), so 16 bits suffice below 65 536 lines.
  const w = m + 1;
  const lcs =
    Math.min(n, m) < 0xffff
      ? new Uint16Array((n + 1) * w)
      : new Int32Array((n + 1) * w);
  for (let i = 1; i <= n; i++) {
    const ai = a[aLo + i - 1]!;
    for (let j = 1; j <= m; j++) {
      const bj = b[bLo + j - 1]!;
      if (ai === bj) {
        lcs[i * w + j] = lcs[(i - 1) * w + (j - 1)]! + 1;
      } else {
        const up = lcs[(i - 1) * w + j]!;
        const left = lcs[i * w + (j - 1)]!;
        lcs[i * w + j] = up >= left ? up : left;
      }
    }
  }
  const ops: Op[] = [];
  let i = n;
  let j = m;
  while (i > 0 && j > 0) {
    const ai = a[aLo + i - 1]!;
    const bj = b[bLo + j - 1]!;
    if (ai === bj) {
      ops.push({ kind: "equal", line: ai });
      i--;
      j--;
    } else if (lcs[(i - 1) * w + j]! >= lcs[i * w + (j - 1)]!) {
      ops.push({ kind: "mine", line: ai });
      i--;
    } else {
      ops.push({ kind: "theirs", line: bj });
      j--;
    }
  }
  while (i > 0) {
    ops.push({ kind: "mine", line: a[aLo + i - 1]! });
    i--;
  }
  while (j > 0) {
    ops.push({ kind: "theirs", line: b[bLo + j - 1]! });
    j--;
  }
  for (let k = ops.length - 1; k >= 0; k--) out.push(ops[k]!);
}

/** Coalesce a sequence of ops into hunks. Equal lines collapse into
 * one ``equal`` hunk (mine and theirs identical); mine + theirs runs
 * collapse into one ``diff`` hunk that records both sides. */
function groupHunks(ops: Op[]): LineHunk[] {
  const out: LineHunk[] = [];
  let cur: LineHunk | null = null;
  const flush = () => {
    if (cur) {
      out.push(cur);
      cur = null;
    }
  };
  for (const op of ops) {
    if (op.kind === "equal") {
      if (cur && cur.kind === "equal") {
        cur.mine.push(op.line);
        cur.theirs.push(op.line);
      } else {
        flush();
        cur = { kind: "equal", mine: [op.line], theirs: [op.line] };
      }
    } else {
      if (cur && cur.kind === "diff") {
        if (op.kind === "mine") cur.mine.push(op.line);
        else cur.theirs.push(op.line);
      } else {
        flush();
        cur = {
          kind: "diff",
          mine: op.kind === "mine" ? [op.line] : [],
          theirs: op.kind === "theirs" ? [op.line] : [],
        };
      }
    }
  }
  flush();
  return out;
}

export type HunkChoice = "mine" | "theirs" | "both" | null;

/** Build the merged text from the hunks and per-diff choices.
 *
 * Equal hunks always pass through. For an unresolved diff hunk
 * (``choice === null``), the **saved** text omits it (the user
 * isn't allowed to save while any choice is null — see the
 * dialog's save-disabled gate). The **preview** version uses
 * ``buildPreviewText`` instead, which renders an inline placeholder
 * so the user can see exactly where they still owe a decision. */
export function buildMergedText(
  hunks: LineHunk[],
  choices: HunkChoice[],
): string {
  const lines: string[] = [];
  let diffIndex = 0;
  for (const h of hunks) {
    if (h.kind === "equal") {
      lines.push(...h.mine);
      continue;
    }
    const choice = choices[diffIndex];
    diffIndex++;
    if (choice === "mine") lines.push(...h.mine);
    else if (choice === "theirs") lines.push(...h.theirs);
    else if (choice === "both") {
      lines.push(...h.mine, ...h.theirs);
    }
    // null → emit nothing, the user hasn't chosen yet.
  }
  return joinLines(lines);
}

/** Identical to ``buildMergedText`` but for unresolved hunks emits a
 * single placeholder line containing ``placeholder``. The merge
 * editor passes a localized "⟨waiting for choice⟩" string. */
export function buildPreviewText(
  hunks: LineHunk[],
  choices: HunkChoice[],
  placeholder: string,
): string {
  const lines: string[] = [];
  let diffIndex = 0;
  for (const h of hunks) {
    if (h.kind === "equal") {
      lines.push(...h.mine);
      continue;
    }
    const choice = choices[diffIndex];
    diffIndex++;
    if (choice === "mine") lines.push(...h.mine);
    else if (choice === "theirs") lines.push(...h.theirs);
    else if (choice === "both") {
      lines.push(...h.mine, ...h.theirs);
    } else {
      lines.push(placeholder);
    }
  }
  return joinLines(lines);
}

export function countDiffHunks(hunks: LineHunk[]): number {
  return hunks.filter((h) => h.kind === "diff").length;
}
