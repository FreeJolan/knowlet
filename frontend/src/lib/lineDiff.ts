/**
 * Phase 2 E Slice S5 — line-level diff for the merge editor.
 *
 * LCS-based 2-way diff. Given two strings, returns a sequence of
 * "hunks": runs of consecutive lines either equal on both sides or
 * differing. The merge UI iterates over hunks and lets the user
 * pick a side per differing hunk.
 *
 * Performance bounds: O(n × m) time and memory. Notes are typically
 * <2 000 lines so this is fine; the editor caps at 5 000 lines per
 * side and falls back to a "whole file" 2-pane choice past that
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

/** Standard LCS-table backtrack. Produces ops in source order.
 *
 * Uses non-null assertions liberally because the loop bounds make
 * every indexed read in-range; the TS compiler under
 * ``noUncheckedIndexedAccess`` can't prove that. */
function computeOps(a: string[], b: string[]): Op[] {
  const n = a.length;
  const m = b.length;
  // Flat row-major Int32Array — small constant factor vs nested
  // arrays at this scale, and avoids the GC pressure of N+1 arrays.
  const w = m + 1;
  const lcs = new Int32Array((n + 1) * w);
  for (let i = 1; i <= n; i++) {
    const ai = a[i - 1]!;
    for (let j = 1; j <= m; j++) {
      const bj = b[j - 1]!;
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
    const ai = a[i - 1]!;
    const bj = b[j - 1]!;
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
    ops.push({ kind: "mine", line: a[i - 1]! });
    i--;
  }
  while (j > 0) {
    ops.push({ kind: "theirs", line: b[j - 1]! });
    j--;
  }
  ops.reverse();
  return ops;
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
 * Equal hunks always pass through. ``null`` choice on a diff hunk
 * means "not yet chosen" — we emit nothing for that hunk so the
 * preview clearly shows the user still has work to do. */
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

export function countDiffHunks(hunks: LineHunk[]): number {
  return hunks.filter((h) => h.kind === "diff").length;
}
