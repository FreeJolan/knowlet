/**
 * Phase 1 D / D3 Properties UI — alias chip strip.
 *
 * Mirrors `TagChipStrip` UX (chips + "+ alias" pseudo-chip → inline
 * input → Enter / "," to commit, Esc to cancel, Backspace-into-empty
 * pops the last). Differences from tags:
 *   - No vault-wide autocomplete: aliases are per-note bespoke names,
 *     not a shared taxonomy. Suggesting other notes' aliases would
 *     leak across notes.
 *   - Comma is a separator, but aliases CAN contain spaces ("Self
 *     Attention"), so we keep the comma trick from tags.
 *   - Visually neutral chip (no tag tint) so users read the row as
 *     "alternate names" not "another taxonomy".
 *
 * Frontmatter `aliases:` round-trips through PUT /api/notes/{id} just
 * like tags do.
 */

import { Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { imeSafeKeyHandler } from "@/lib/imeSafe";

interface Props {
  aliases: string[];
  onAdd: (alias: string) => void;
  onRemove: (alias: string) => void;
  /** Resets the inline input when the user navigates to a new note. */
  noteId: string | null;
}

function sanitize(raw: string): string {
  return raw.trim().replace(/,/g, "");
}

export function AliasChipStrip({ aliases, onAdd, onRemove, noteId }: Props) {
  const { t } = useTranslation();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEditing(false);
    setDraft("");
  }, [noteId]);

  const commit = (raw: string) => {
    const value = sanitize(raw);
    if (!value) return;
    if (aliases.includes(value)) return;
    onAdd(value);
    setDraft("");
    inputRef.current?.focus();
  };

  return (
    <div
      className="flex flex-wrap items-center gap-1.5"
      data-testid="alias-strip"
    >
      {aliases.map((alias) => (
        <span
          key={alias}
          data-testid="alias-chip"
          data-alias={alias}
          className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs"
          style={{
            background: "var(--bg, #f5f1e8)",
            color: "var(--ink, #2a2823)",
            border: "1px solid var(--line)",
          }}
        >
          <span>{alias}</span>
          <button
            type="button"
            onClick={() => onRemove(alias)}
            aria-label={t("noteProps.aliasesRemove", { alias })}
            data-testid="alias-chip-remove"
            data-alias={alias}
            className="flex size-3.5 items-center justify-center rounded-full transition-colors hover:bg-accent/40"
            style={{ color: "var(--ink-mute)" }}
          >
            <X size={9} />
          </button>
        </span>
      ))}
      {editing ? (
        <input
          ref={inputRef}
          type="text"
          autoFocus
          value={draft}
          placeholder={t("noteProps.aliasesPlaceholder")}
          data-testid="alias-add-input"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={imeSafeKeyHandler<HTMLInputElement>((e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              commit(draft);
            } else if (e.key === "Escape") {
              e.preventDefault();
              setEditing(false);
              setDraft("");
            } else if (e.key === "Backspace" && !draft && aliases.length > 0) {
              onRemove(aliases[aliases.length - 1] as string);
            }
          })}
          onBlur={() => {
            window.setTimeout(() => {
              if (draft.trim()) commit(draft);
              else setEditing(false);
            }, 150);
          }}
          className="rounded-full border px-2 py-0.5 text-xs outline-none focus:border-accent"
          style={{
            borderColor: "var(--line)",
            background: "var(--card, #fbf8f1)",
            color: "var(--ink)",
            minWidth: 100,
          }}
        />
      ) : (
        <button
          type="button"
          onClick={() => setEditing(true)}
          aria-label={t("noteProps.aliasesAdd")}
          data-testid="alias-add-button"
          className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs transition-colors hover:bg-accent/30"
          style={{
            color: "var(--ink-mute)",
            border: "1px dashed var(--line)",
          }}
        >
          <Plus size={11} />
          <span>{t("noteProps.aliasesAdd")}</span>
        </button>
      )}
    </div>
  );
}
