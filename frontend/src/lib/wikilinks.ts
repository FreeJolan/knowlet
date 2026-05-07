/**
 * Phase 1 C slice 1 polish — pure helpers for parsing `[[Title]]` /
 * `[[Title#Heading]]` / `[[Title|Alias]]` wikilinks out of note body.
 *
 * The right-rail Outbound section uses these to derive forward links
 * client-side (no new backend endpoint — every note is already cached
 * via NoteView's `getNote` query, so reading body is free).
 */

import type { TreeFolder } from "@/api/types";

const WIKILINK_RE = /\[\[([^[\]\n|]+?)(?:\|([^[\]\n]+?))?\]\]/g;

export interface OutboundLink {
  /** First-occurrence target, in the form the user wrote (case + spacing
   *  may differ from the canonical title). For deduplication we use
   *  `targetKey` below. */
  target: string;
  /** Lower-cased + whitespace-collapsed key for resolution / dedup. */
  targetKey: string;
  /** 1-based line number of the FIRST occurrence (subsequent matches
   *  for the same target are folded into the same row). */
  line: number;
  /** Sentence preview (the line containing the first occurrence,
   *  trimmed; contains the literal `[[…]]` syntax for highlighting). */
  sentence: string;
  /** How many times this target appears in the body. */
  count: number;
  /** True when no Note in the vault matches this target (case-insensitive
   *  title match). The panel renders these in a "broken link" style. */
  dangling: boolean;
  /** When `dangling=false`, the resolved target Note's id; for click
   *  navigation. */
  resolvedNoteId: string | null;
}

const PREVIEW_MAX = 240;

function normalize(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

function trimAroundMatch(line: string, matchStart: number, matchLen: number): string {
  const trimmed = line.trim();
  if (trimmed.length <= PREVIEW_MAX) return trimmed;
  // Window around the match
  const half = Math.floor(PREVIEW_MAX / 2);
  const start = Math.max(0, matchStart - half);
  const end = Math.min(line.length, matchStart + matchLen + half);
  let snippet = line.slice(start, end);
  if (start > 0) snippet = "…" + snippet;
  if (end < line.length) snippet = snippet + "…";
  return snippet;
}

/**
 * Walk a TreeFolder snapshot and build a `normalize(title) → noteId` map
 * once, so resolution is O(1) per outbound link instead of O(notes) per.
 */
export function buildTitleIndex(tree: TreeFolder | undefined): Map<string, string> {
  const out = new Map<string, string>();
  if (!tree) return out;
  const stack: TreeFolder[] = [tree];
  while (stack.length) {
    const f = stack.pop();
    if (!f) continue;
    for (const n of f.notes) out.set(normalize(n.title), n.id);
    for (const sub of f.folders) stack.push(sub);
  }
  return out;
}

/**
 * Extract outbound `[[Title]]` references from a note body, deduplicated
 * by case-insensitive target. Returns rows in document-order (first
 * occurrence wins).
 *
 * Per the design intent for the panel:
 * - Pipe aliases (`[[Title|alias]]`) → take the part before `|` as target
 * - Heading anchors (`[[Title#section]]`) → keep as part of target so
 *   click-navigation jumps to the heading
 * - Inside code blocks the regex still matches; we tolerate this for v1
 *   (rare in practice), since walking the AST would mean parsing
 *   markdown twice. Document and revisit if dogfood signals false hits.
 */
export function extractOutboundLinks(
  body: string,
  titleIndex: Map<string, string>,
  excludeNoteId: string | null = null,
): OutboundLink[] {
  const byKey = new Map<string, OutboundLink>();
  if (!body) return [];
  const lines = body.split("\n");
  for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
    const line = lines[lineIdx];
    if (!line) continue;
    WIKILINK_RE.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = WIKILINK_RE.exec(line)) !== null) {
      const raw = m[1]?.trim() ?? "";
      if (!raw) continue;
      // For resolution we only care about the title portion (before `#`).
      const hashIdx = raw.indexOf("#");
      const titleOnly = (hashIdx === -1 ? raw : raw.slice(0, hashIdx)).trim();
      const key = normalize(titleOnly);
      if (!key) continue;
      const resolved = titleIndex.get(key) ?? null;
      // Don't show self-references in the outbound panel.
      if (resolved && excludeNoteId && resolved === excludeNoteId) continue;
      const existing = byKey.get(key);
      if (existing) {
        existing.count += 1;
        continue;
      }
      byKey.set(key, {
        target: raw,
        targetKey: key,
        line: lineIdx + 1,
        sentence: trimAroundMatch(line, m.index, m[0].length),
        count: 1,
        dangling: resolved === null,
        resolvedNoteId: resolved,
      });
    }
  }
  return Array.from(byKey.values());
}
