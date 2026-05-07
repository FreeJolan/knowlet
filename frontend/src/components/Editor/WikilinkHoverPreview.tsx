/**
 * Phase 1 D slice 1 — hover preview for `[[Title]]` wikilinks.
 *
 * On hover (400ms delay), looks up the target note in the tree cache,
 * fetches its body (cached via QK.note), and shows a small floating
 * card with title + first paragraph.
 *
 * Dangling targets (no note matches the title) get a muted "no note
 * with this title" hint instead of a fetch attempt.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { getNote } from "@/api/client";
import type { NoteFull, TreeFolder } from "@/api/types";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { QK } from "@/lib/queryClient";

interface Props {
  /** The wikilink target as written (may include `#heading` or pipe alias). */
  rawTarget: string;
  /** The clickable anchor (a link element). HoverCardTrigger wraps it. */
  children: React.ReactNode;
}

function normalizeTitle(s: string): string {
  return s.replace(/\s+/g, " ").trim().toLowerCase();
}

function findNoteIdByTitle(
  tree: TreeFolder | undefined,
  title: string,
): string | null {
  if (!tree) return null;
  const target = normalizeTitle(title);
  const stack: TreeFolder[] = [tree];
  while (stack.length) {
    const f = stack.pop();
    if (!f) continue;
    for (const n of f.notes) {
      if (normalizeTitle(n.title) === target) return n.id;
    }
    for (const sub of f.folders) stack.push(sub);
  }
  return null;
}

function firstParagraph(body: string, maxChars = 220): string {
  if (!body) return "";
  // Split on blank lines (markdown paragraph break).
  const paragraphs = body.split(/\n\s*\n/).map((p) => p.trim());
  for (const p of paragraphs) {
    if (!p) continue;
    // Skip frontmatter / heading-only paragraphs at the very top.
    if (/^---\s*$/.test(p) || /^#{1,6}\s+/.test(p)) continue;
    // Strip wikilinks / images / leading list markers for a cleaner
    // single-paragraph preview.
    const cleaned = p
      .replace(/\[\[([^[\]\n|]+?)(?:\|([^[\]\n]+?))?\]\]/g, (_, t1, t2) => t2 || t1)
      .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
      .replace(/^\s*[-*+]\s+/gm, "")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/\*\*([^*]+)\*\*/g, "$1")
      .replace(/\*([^*]+)\*/g, "$1")
      .trim();
    if (!cleaned) continue;
    return cleaned.length > maxChars ? cleaned.slice(0, maxChars - 1) + "…" : cleaned;
  }
  return "";
}

export function WikilinkHoverPreview({ rawTarget, children }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  // Strip heading anchor and pipe alias for note resolution; we still
  // show the target's note body, not its specific section.
  const title = useMemo(() => {
    const noPipe = rawTarget.split("|")[0] ?? rawTarget;
    return (noPipe.split("#")[0] ?? noPipe).trim();
  }, [rawTarget]);

  const tree = qc.getQueryData<TreeFolder>(QK.tree);
  const noteId = useMemo(() => findNoteIdByTitle(tree, title), [tree, title]);

  // Fetching key — only enabled when the user actually opens the
  // hover, so we don't pre-fetch every wikilink on the page.
  const note = useQuery<NoteFull>({
    queryKey: noteId ? QK.note(noteId) : ["note", "_hover_empty"],
    queryFn: () => getNote(noteId as string),
    enabled: !!noteId,
    staleTime: 30_000,
  });

  return (
    <HoverCard openDelay={400} closeDelay={120}>
      <HoverCardTrigger asChild>{children}</HoverCardTrigger>
      <HoverCardContent
        side="top"
        align="start"
        className="max-w-xs px-3 py-2"
        data-testid="wikilink-hover"
      >
        {!noteId ? (
          <div className="space-y-1">
            <div
              className="text-[12.5px] font-medium leading-tight"
              style={{
                fontFamily:
                  "var(--font-serif, Source Serif 4, Georgia, serif)",
                color: "var(--ink-mute)",
              }}
            >
              {title}
            </div>
            <div
              className="font-mono text-[10px]"
              style={{ color: "var(--ink-mute)" }}
            >
              {t("hover.broken")}
            </div>
          </div>
        ) : note.isLoading || !note.data ? (
          <div
            className="text-[12px]"
            style={{ color: "var(--ink-mute)" }}
          >
            {t("hover.loading")}
          </div>
        ) : (
          <div className="space-y-1.5">
            <div
              className="text-[13px] font-medium leading-tight"
              style={{
                fontFamily:
                  "var(--font-serif, Source Serif 4, Georgia, serif)",
                color: "var(--ink)",
              }}
            >
              {note.data.title}
            </div>
            <div
              className="text-[11.5px] leading-relaxed"
              style={{ color: "var(--ink-soft)" }}
            >
              {firstParagraph(note.data.body) || (
                <span style={{ color: "var(--ink-mute)" }}>
                  {t("hover.empty")}
                </span>
              )}
            </div>
            <div
              className="font-mono text-[10px]"
              style={{ color: "var(--ink-mute)" }}
            >
              {note.data.folder || "(root)"}
            </div>
          </div>
        )}
      </HoverCardContent>
    </HoverCard>
  );
}
