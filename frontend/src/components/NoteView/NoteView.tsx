/**
 * Phase 1 A read-only note view. Phase 1 B replaces this with the
 * CodeMirror 6 editor + live preview; this is the placeholder so the
 * file tree click-through actually shows something.
 */

import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import { getNote } from "@/api/client";
import { QK } from "@/lib/queryClient";

export function NoteView({ noteId }: { noteId: string | null }) {
  const { t } = useTranslation();
  // Always provide a queryFn — TanStack Query v5 throws synchronously when
  // queryFn is undefined, even with enabled:false. The fn just never runs
  // when noteId is null because `enabled` gates execution.
  const note = useQuery({
    queryKey: noteId ? QK.note(noteId) : ["note", "_empty"],
    queryFn: () => {
      if (!noteId) throw new Error("noteId required");
      return getNote(noteId);
    },
    enabled: !!noteId,
  });

  if (!noteId) {
    return (
      <div className="kn-paper flex h-full items-center justify-center text-sm text-muted-foreground">
        {t("note.selectPrompt")}
      </div>
    );
  }
  if (note.isLoading) {
    return <div className="p-6 text-sm text-muted-foreground">{t("tree.loading")}</div>;
  }
  if (note.isError) {
    return (
      <div className="p-6 text-sm text-destructive">
        {t("note.loadFailed", { error: String(note.error) })}
      </div>
    );
  }
  if (!note.data) return null;

  return (
    <article className="kn-paper h-full overflow-y-auto px-10 py-8">
      <header className="mb-6">
        <h1 className="font-serif text-3xl" style={{ color: "var(--ink)" }}>
          {note.data.title}
        </h1>
        <div
          className="mt-2 font-mono text-xs uppercase tracking-wider"
          style={{ color: "var(--ink-mute)" }}
        >
          {note.data.folder || t("note.rootLabel")} · {note.data.id.slice(0, 8)} ·{" "}
          {t("note.updatedPrefix")} {note.data.updated_at.slice(0, 10)}
        </div>
        {note.data.tags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {note.data.tags.map((t) => (
              <span
                key={t}
                className="rounded-full px-2 py-0.5 text-xs"
                style={{
                  background: "var(--accent-tint)",
                  color: "var(--ink)",
                }}
              >
                {t}
              </span>
            ))}
          </div>
        )}
      </header>
      <pre
        className="whitespace-pre-wrap font-serif text-base leading-relaxed"
        style={{ color: "var(--ink)" }}
      >
        {note.data.body}
      </pre>
    </article>
  );
}
