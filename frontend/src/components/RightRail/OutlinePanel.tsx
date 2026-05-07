/**
 * Phase 1 D slice 1 — Outline panel (3rd right-rail tab).
 *
 * Renders the current note's h1-h6 hierarchy. Click a heading → host
 * sets pendingHash on NoteView, which scrolls the preview to the
 * matching `id` (rehype-slug + github-slugger, same as wikilink
 * `[[Title#Heading]]` navigation already uses).
 *
 * Reuses `parseHeadings` from `Editor/wikilinkAutocomplete.ts` —
 * one parser for both autocomplete and outline = no drift.
 */

import { useQuery } from "@tanstack/react-query";
import GithubSlugger from "github-slugger";
import { Hash } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { getNote } from "@/api/client";
import type { NoteFull } from "@/api/types";
import { parseHeadings } from "@/components/Editor/wikilinkAutocomplete";
import { QK } from "@/lib/queryClient";

interface Props {
  noteId: string | null;
  /** Click a heading → host scrolls editor to its slugged anchor. */
  onJumpToHeading: (slug: string) => void;
}

interface OutlineEntry {
  level: number;
  text: string;
  slug: string;
}

export function OutlinePanel({ noteId, onJumpToHeading }: Props) {
  const { t } = useTranslation();

  const note = useQuery<NoteFull>({
    queryKey: noteId ? QK.note(noteId) : ["note", "_empty"],
    queryFn: () => getNote(noteId as string),
    enabled: !!noteId,
    staleTime: 10_000,
  });

  const entries: OutlineEntry[] = useMemo(() => {
    if (!note.data) return [];
    const slugger = new GithubSlugger();
    return parseHeadings(note.data.body).map((h) => ({
      level: h.level,
      text: h.text,
      // GithubSlugger handles duplicate headings by appending -1, -2, ...
      // matching rehype-slug behavior, so a doc with two `## Notes` still
      // produces stable distinct anchors.
      slug: slugger.slug(h.text),
    }));
  }, [note.data]);

  if (!noteId) {
    return (
      <Shell>
        <div
          className="px-3 py-4 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("rail.outline.noNote")}
        </div>
      </Shell>
    );
  }
  if (note.isLoading) {
    return (
      <Shell>
        <div
          className="px-3 py-3 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("rail.outline.loading")}
        </div>
      </Shell>
    );
  }
  if (entries.length === 0) {
    return (
      <Shell>
        <div
          className="px-3 py-4 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("rail.outline.empty")}
        </div>
      </Shell>
    );
  }

  // Normalize the smallest level we see to 1 so the indent doesn't
  // start at level-3 if a note's only headings are h3+. Visually
  // consistent across notes.
  const minLevel = Math.min(...entries.map((e) => e.level));

  return (
    <Shell>
      <ul className="flex-1 overflow-y-auto py-1" data-testid="outline-list">
        {entries.map((e, i) => {
          const indent = (e.level - minLevel) * 12;
          return (
            <li key={`${e.slug}-${i}`}>
              <button
                type="button"
                onClick={() => onJumpToHeading(e.slug)}
                data-testid="outline-row"
                data-level={e.level}
                data-slug={e.slug}
                className="flex w-full items-center gap-1.5 px-3 py-1 text-left text-[12px] transition-colors hover:bg-accent/30"
                style={{
                  color: "var(--ink, #2a2823)",
                  paddingLeft: 12 + indent,
                }}
              >
                {e.level === 1 && (
                  <Hash size={10} style={{ color: "var(--ink-mute)" }} />
                )}
                <span className="truncate" style={{ minWidth: 0 }}>
                  {e.text}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="flex h-full min-h-0 flex-col">{children}</div>;
}
