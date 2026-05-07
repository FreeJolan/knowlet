/**
 * Phase 1 C slice 2 — Tag browser, peer of FileTree on the left rail.
 *
 * Two-pane layout (single column at the left rail width budget):
 *   - top: vertical list of all tags + counts (scrollable)
 *   - bottom: when a tag is selected, the notes carrying that tag
 *
 * Per ADR-0013 §3 Layer B — no taxonomy enforcement. We surface what
 * the user typed, nothing more. Click a tag → see notes; click a note
 * → opens it in the editor (host wires the callback).
 */

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, FileText, Hash } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { listNotesByTag, listTags } from "@/api/client";
import type { NoteSummary, TagSummary } from "@/api/types";
import { QK } from "@/lib/queryClient";

interface Props {
  onSelectNote: (id: string) => void;
  /** When AppShell is asked to open a specific tag (e.g. via a #tag
   *  click in preview), the host sets this and TagBrowser drills in. */
  pendingTag?: string | null;
  onPendingTagConsumed?: () => void;
}

export function TagBrowser({
  onSelectNote,
  pendingTag,
  onPendingTagConsumed,
}: Props) {
  const { t } = useTranslation();
  const [activeTag, setActiveTag] = useState<string | null>(null);

  useEffect(() => {
    if (pendingTag && pendingTag !== activeTag) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveTag(pendingTag);
      onPendingTagConsumed?.();
    }
  }, [pendingTag, activeTag, onPendingTagConsumed]);

  const tagsQuery = useQuery<TagSummary[]>({
    queryKey: QK.tags,
    queryFn: listTags,
    staleTime: 10_000,
  });

  if (activeTag) {
    return (
      <TagDetail
        tag={activeTag}
        onBack={() => setActiveTag(null)}
        onSelectNote={onSelectNote}
      />
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {tagsQuery.isLoading && (
        <div
          className="px-3 py-3 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("tags.loading")}
        </div>
      )}
      {tagsQuery.isError && (
        <div
          className="px-3 py-3 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("tags.loadFailed", {
            error:
              (tagsQuery.error as { detail?: string })?.detail ?? "unknown",
          })}
        </div>
      )}
      {tagsQuery.data && tagsQuery.data.length === 0 && (
        <div
          className="px-3 py-4 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("tags.empty")}
        </div>
      )}
      <ul className="flex-1 overflow-y-auto" data-testid="tags-list">
        {tagsQuery.data?.map((row) => (
          <li key={row.tag}>
            <button
              type="button"
              onClick={() => setActiveTag(row.tag)}
              data-testid="tag-row"
              data-tag={row.tag}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent/30"
              style={{
                color: "var(--ink, #2a2823)",
                borderBottom: "1px solid var(--line-soft, #e2dac9)",
              }}
            >
              <Hash size={12} style={{ color: "var(--ink-soft)" }} />
              <span className="flex-1 truncate">{row.tag}</span>
              <span
                className="font-mono text-[10.5px]"
                style={{ color: "var(--ink-mute)" }}
              >
                {row.count}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

interface DetailProps {
  tag: string;
  onBack: () => void;
  onSelectNote: (id: string) => void;
}

function TagDetail({ tag, onBack, onSelectNote }: DetailProps) {
  const { t } = useTranslation();
  const notesQuery = useQuery<NoteSummary[]>({
    queryKey: QK.tagNotes(tag),
    queryFn: () => listNotesByTag(tag),
    staleTime: 10_000,
  });

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div
        className="flex shrink-0 items-center gap-2 px-3 py-2"
        style={{ borderBottom: "1px solid var(--line, #d8cfb9)" }}
      >
        <button
          type="button"
          onClick={onBack}
          aria-label={t("tags.back")}
          data-testid="tag-detail-back"
          className="flex size-6 items-center justify-center rounded transition-colors hover:bg-accent/40"
          style={{ color: "var(--ink-soft)" }}
        >
          <ChevronLeft size={14} />
        </button>
        <Hash size={12} style={{ color: "var(--ink-soft)" }} />
        <span className="text-xs font-medium">{tag}</span>
        {notesQuery.data && (
          <span
            className="font-mono text-[10.5px]"
            style={{ color: "var(--ink-mute)" }}
          >
            ·{" "}
            {t("tags.noteCount", { count: notesQuery.data.length })}
          </span>
        )}
      </div>
      {notesQuery.isLoading && (
        <div
          className="px-3 py-3 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("tags.loading")}
        </div>
      )}
      {notesQuery.data && notesQuery.data.length === 0 && (
        <div
          className="px-3 py-4 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          {t("tags.noNotesForTag")}
        </div>
      )}
      <ul className="flex-1 overflow-y-auto" data-testid="tag-notes-list">
        {notesQuery.data?.map((n) => (
          <li key={n.id}>
            <button
              type="button"
              onClick={() => onSelectNote(n.id)}
              data-testid="tag-note-row"
              data-note-id={n.id}
              className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm transition-colors hover:bg-accent/30"
              style={{
                color: "var(--ink, #2a2823)",
                borderBottom: "1px solid var(--line-soft, #e2dac9)",
              }}
            >
              <FileText size={12} style={{ color: "var(--ink-soft)" }} />
              <span className="flex-1 truncate">{n.title}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
