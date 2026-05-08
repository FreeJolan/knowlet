/**
 * Phase 1 C slice 1+2 polish — Tag chip strip in the NoteView header.
 *
 * Replaces the read-only tag display under the title with an editable
 * chip strip that lets users add / remove tags WITHOUT touching the
 * note's YAML frontmatter directly. Per dogfood feedback (2026-05-08):
 * "edit frontmatter to add a tag" was rated too geeky.
 *
 * - Existing tags render as chips with × button to remove
 * - "+ tag" pseudo-chip → inline input with autocomplete from
 *   QK.tags (existing tags across the vault)
 * - Enter / comma → commit the tag (validate empty + dedup); input stays
 *   open for the next tag
 * - Esc / blur (with no input) → close
 *
 * Frontmatter remains the canonical source — this is just an ergonomic
 * UI on top of `tags:` round-tripped through PUT /api/notes/{id}.
 */

import { useQuery } from "@tanstack/react-query";
import { Plus, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { listTags } from "@/api/client";
import type { TagSummary } from "@/api/types";
import { imeSafeKeyHandler } from "@/lib/imeSafe";
import { QK } from "@/lib/queryClient";

interface Props {
  tags: string[];
  onAdd: (tag: string) => void;
  onRemove: (tag: string) => void;
  /** When the note id changes, the chip strip's input gets reset. */
  noteId: string | null;
}

/** Sanitize one user-typed tag. Tags are case-sensitive identity strings;
 *  we only trim + lowercase the surrounding whitespace, never the tag
 *  itself. Reject `,` because the chip strip uses comma to commit. */
function sanitize(raw: string): string {
  return raw.trim().replace(/^#+/, "").replace(/,/g, "");
}

export function TagChipStrip({ tags, onAdd, onRemove, noteId }: Props) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset edit state when switching notes. The set-state-in-effect rule
  // is intentionally bent here: this is genuinely "external state changed
  // (note id), reset transient UI." There's no derived-from-render
  // alternative that doesn't make the parent's render path messier.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEditing(false);
    setDraft("");
  }, [noteId]);

  // Pull all tags across the vault for autocomplete suggestions.
  const allTags = useQuery<TagSummary[]>({
    queryKey: QK.tags,
    queryFn: listTags,
    staleTime: 10_000,
  });

  const suggestions = useMemo(() => {
    if (!editing || !allTags.data) return [];
    const term = draft.trim().toLowerCase();
    const have = new Set(tags.map((tg) => tg.toLowerCase()));
    return allTags.data
      .filter((row) => !have.has(row.tag.toLowerCase()))
      .filter((row) =>
        term ? row.tag.toLowerCase().includes(term) : true,
      )
      .slice(0, 8);
  }, [editing, allTags.data, draft, tags]);

  const commit = (raw: string) => {
    const value = sanitize(raw);
    if (!value) return;
    if (tags.includes(value)) return; // dedup
    onAdd(value);
    setDraft("");
    // Stay in edit mode for the next tag — common multi-tag flow.
    inputRef.current?.focus();
  };

  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      data-testid="tag-strip"
    >
      {tags.map((tag) => (
        <span
          key={tag}
          data-testid="tag-chip"
          data-tag={tag}
          className="inline-flex items-center gap-1 rounded-full px-2 text-[11.5px] font-medium"
          style={{
            height: 22,
            background: "var(--accent-tint, rgba(91, 122, 156, 0.18))",
            color: "var(--accent-2, #4d6a8a)",
          }}
        >
          <span>{tag}</span>
          <button
            type="button"
            onClick={() => onRemove(tag)}
            aria-label={t("noteTags.remove", { tag })}
            data-testid="tag-chip-remove"
            data-tag={tag}
            className="flex size-3.5 items-center justify-center rounded-full transition-colors hover:bg-accent/40"
            style={{ color: "var(--accent)", opacity: 0.6 }}
          >
            <X size={9} />
          </button>
        </span>
      ))}
      {editing ? (
        <div className="relative">
          <input
            ref={inputRef}
            type="text"
            autoFocus
            value={draft}
            placeholder={t("noteTags.placeholder")}
            data-testid="tag-add-input"
            onChange={(e) => setDraft(e.target.value)}
            // IME-safe: Enter / "," / Esc / Backspace handlers fire
            // only when no pinyin / IME composition is active. During
            // composition Enter means "confirm candidate" — committing
            // a half-typed tag would steal that keystroke.
            onKeyDown={imeSafeKeyHandler<HTMLInputElement>((e) => {
              if (e.key === "Enter" || e.key === ",") {
                e.preventDefault();
                commit(draft);
              } else if (e.key === "Escape") {
                e.preventDefault();
                setEditing(false);
                setDraft("");
              } else if (e.key === "Backspace" && !draft && tags.length > 0) {
                // Pop the last tag on backspace-into-empty (Bear / Notion style).
                onRemove(tags[tags.length - 1] as string);
              }
            })}
            onBlur={() => {
              // Defer so a click on a suggestion can register first.
              window.setTimeout(() => {
                if (draft.trim()) commit(draft);
                else setEditing(false);
              }, 150);
            }}
            className="rounded-full border px-2 text-[11.5px] outline-none focus:border-accent"
            style={{
              height: 22,
              borderColor: "var(--line)",
              background: "var(--card, #fbf8f1)",
              color: "var(--ink)",
              minWidth: 80,
            }}
          />
          {suggestions.length > 0 && (
            <div
              className="absolute left-0 top-full mt-1 max-h-48 overflow-y-auto rounded border shadow-md"
              style={{
                borderColor: "var(--line)",
                background: "var(--card, #fbf8f1)",
                minWidth: 140,
                zIndex: 30,
              }}
              data-testid="tag-add-suggestions"
            >
              {suggestions.map((s) => (
                <button
                  key={s.tag}
                  type="button"
                  data-testid="tag-suggestion"
                  data-tag={s.tag}
                  onMouseDown={(e) => {
                    // mousedown beats blur; use it to apply.
                    e.preventDefault();
                    commit(s.tag);
                  }}
                  className="flex w-full items-center justify-between gap-3 px-2 py-1 text-left text-xs transition-colors hover:bg-accent/30"
                  style={{ color: "var(--ink)" }}
                >
                  <span>{s.tag}</span>
                  <span
                    className="font-mono text-[10px]"
                    style={{ color: "var(--ink-mute)" }}
                  >
                    {s.count}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setEditing(true)}
          aria-label={t("noteTags.add")}
          data-testid="tag-add-button"
          className="inline-flex items-center gap-0.5 rounded-full px-2 text-[11px] transition-colors hover:text-[color:var(--ink)]"
          style={{
            height: 22,
            color: "var(--ink-mute)",
            border: "1px dashed var(--line)",
          }}
        >
          <Plus size={10} />
          <span>{t("noteTags.addShort")}</span>
        </button>
      )}
    </div>
  );
}
