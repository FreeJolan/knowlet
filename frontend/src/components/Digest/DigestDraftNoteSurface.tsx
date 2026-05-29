import { ChevronRight, Columns2, Eye, Pen } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { DraftSummary } from "@/api/client";
import { InlineEditInput } from "@/components/InlineEdit/InlineEditInput";
import { KindChip } from "@/components/KindChip";
import { MarkdownEditor } from "@/components/Editor/MarkdownEditor";
import { MarkdownPreview } from "@/components/Editor/MarkdownPreview";
import { SourceKickerPill } from "@/components/NoteView/PropertiesPanel";
import { TagChipStrip } from "@/components/NoteView/TagChipStrip";

type DraftEdit = {
  title: string;
  tags: string;
  kind: "knowledge" | "reference";
  folder: string;
  body: string;
};

type ViewMode = "edit" | "split" | "preview";

interface Props {
  draft: DraftSummary;
  draftEdit: DraftEdit;
  editorRevision?: number;
  onDraftEditChange: (next: DraftEdit | ((current: DraftEdit) => DraftEdit)) => void;
  rationale?: string | null;
  footer?: React.ReactNode;
}

function parseTags(value: string): string[] {
  const seen = new Set<string>();
  const tags: string[] = [];
  for (const raw of value.split(",")) {
    const tag = raw.trim().replace(/^#/, "");
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    tags.push(tag);
  }
  return tags;
}

function serializeTags(tags: string[]): string {
  return tags.join(", ");
}

function loadInitialViewMode(): ViewMode {
  if (typeof window === "undefined") return "split";
  const value = window.localStorage.getItem("knowlet:digest-draft-view-mode");
  if (value === "edit" || value === "split" || value === "preview") return value;
  return "split";
}

function writeViewMode(value: ViewMode): void {
  try {
    window.localStorage.setItem("knowlet:digest-draft-view-mode", value);
  } catch {
    /* localStorage can be unavailable in private contexts. */
  }
}

export function DigestDraftNoteSurface({
  draft,
  draftEdit,
  editorRevision = 0,
  onDraftEditChange,
  rationale,
  footer,
}: Props): React.ReactNode {
  const { t } = useTranslation();
  const [editingTitle, setEditingTitle] = useState(false);
  const [propertiesOpen, setPropertiesOpen] = useState(false);
  const [viewMode, setViewMode] = useState<ViewMode>(() => loadInitialViewMode());
  const tags = parseTags(draftEdit.tags);

  const setDraftEdit = (
    next: DraftEdit | ((current: DraftEdit) => DraftEdit),
  ) => {
    onDraftEditChange(next);
  };

  const setTags = (nextTags: string[]) => {
    setDraftEdit((current) => ({
      ...current,
      tags: serializeTags(nextTags),
    }));
  };

  const setMode = (next: ViewMode) => {
    setViewMode(next);
    writeViewMode(next);
  };

  const source = draft.source ?? null;

  return (
    <div
      className="kn-paper flex min-h-0 flex-1 flex-col rounded-md border"
      style={{ borderColor: "var(--line)", background: "var(--bg)" }}
      data-testid="digest-draft-note-surface"
    >
      <header className="shrink-0 px-7 pt-5 pb-3">
        <div className="flex items-start justify-between gap-4">
          {editingTitle ? (
            <div className="min-w-0 flex-1">
              <InlineEditInput
                initial={draftEdit.title}
                placeholder={t("note.titlePlaceholder")}
                onSubmit={(value) => {
                  const next = value.trim();
                  if (next) {
                    setDraftEdit((current) => ({ ...current, title: next }));
                  }
                  setEditingTitle(false);
                }}
                onCancel={() => setEditingTitle(false)}
                dataTestId="digest-draft-title-input"
                className="block w-full rounded-sm border-0 border-b bg-transparent p-0 font-serif font-semibold outline-none ring-0 focus:border-b focus:outline-none"
                style={{
                  color: "var(--ink)",
                  fontSize: 28,
                  lineHeight: 1.18,
                  letterSpacing: 0,
                  borderBottomColor: "var(--ring)",
                  borderBottomWidth: 1,
                }}
              />
            </div>
          ) : (
            <h1
              className="min-w-0 cursor-text rounded-sm font-serif font-semibold transition-colors hover:bg-accent/40"
              style={{
                color: "var(--ink)",
                fontSize: 28,
                lineHeight: 1.18,
                letterSpacing: 0,
                wordBreak: "break-word",
              }}
              role="button"
              tabIndex={0}
              data-testid="digest-draft-title"
              title={t("note.editTitleHint")}
              onClick={() => setEditingTitle(true)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === "F2") {
                  e.preventDefault();
                  setEditingTitle(true);
                }
              }}
            >
              {draftEdit.title || t("digest.untitled")}
            </h1>
          )}
          <div className="flex shrink-0 items-center gap-3">
            <KindChip
              kind={draftEdit.kind}
              variant="chip"
              testId="digest-draft-kind-chip"
              onConfirmedToggle={(kind) =>
                setDraftEdit((current) => ({ ...current, kind }))
              }
            />
            <DraftViewModeToggle value={viewMode} onChange={setMode} />
          </div>
        </div>

        <div
          className="mt-1.5 flex flex-wrap items-center font-mono text-[11px] uppercase"
          style={{ color: "var(--ink-mute)" }}
        >
          <span>{draftEdit.folder || t("digest.rootFolder")}</span>
          <DraftKickerSep />
          <span>{draft.id.slice(0, 8)}</span>
          <DraftKickerSep />
          <span>
            {t("note.updatedPrefix")} {draft.updated_at.slice(0, 10)}
          </span>
          {source ? (
            <>
              <DraftKickerSep />
              <SourceKickerPill url={source} />
            </>
          ) : null}
          <span style={{ flex: 1 }} />
          <button
            type="button"
            onClick={() => setPropertiesOpen((value) => !value)}
            aria-expanded={propertiesOpen}
            aria-label={
              propertiesOpen ? t("noteProps.collapse") : t("noteProps.expand")
            }
            data-testid="digest-draft-properties-toggle"
            className="inline-flex items-center gap-1 rounded-sm font-mono text-[11px] uppercase transition-colors hover:text-[color:var(--ink)]"
            style={{ color: "var(--ink-mute)" }}
          >
            <ChevronRight
              size={11}
              className="transition-transform"
              style={{ transform: propertiesOpen ? "rotate(90deg)" : "rotate(0deg)" }}
            />
            <span>{t("noteProps.title")}</span>
          </button>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <TagChipStrip
            tags={tags}
            noteId={draft.id}
            onAdd={(tag) => setTags([...tags, tag])}
            onRemove={(tag) => setTags(tags.filter((current) => current !== tag))}
          />
        </div>

        {propertiesOpen && (
          <div
            className="mt-3 grid items-center pt-3"
            style={{
              borderTop: "1px dashed var(--line)",
              gridTemplateColumns: "minmax(64px, max-content) 1fr",
              rowGap: "8px",
              columnGap: "24px",
            }}
            data-testid="digest-draft-properties-panel"
          >
            <DraftPropertyLabel>{t("digest.draftFolder")}</DraftPropertyLabel>
            <input
              data-testid="digest-draft-folder-input"
              value={draftEdit.folder}
              onChange={(e) =>
                setDraftEdit((current) => ({ ...current, folder: e.target.value }))
              }
              placeholder={t("digest.rootFolder")}
              className="max-w-sm rounded-sm border bg-transparent px-2 py-1 text-sm outline-none"
              style={{ borderColor: "var(--line)", color: "var(--ink)" }}
            />

            <DraftPropertyLabel>{t("noteProps.createdLabel")}</DraftPropertyLabel>
            <div className="font-mono text-[12px]" style={{ color: "var(--ink-soft)" }}>
              {draft.created_at.slice(0, 16).replace("T", " ")}
            </div>

            {source && (
              <>
                <DraftPropertyLabel>{t("noteProps.sourceLabel")}</DraftPropertyLabel>
                <a
                  href={source}
                  target="_blank"
                  rel="noopener noreferrer"
                  data-testid="digest-draft-source"
                  className="truncate font-mono text-[12px]"
                  style={{
                    color: "var(--accent-2)",
                    borderBottom: "1px dashed var(--accent)",
                    width: "fit-content",
                    paddingBottom: 1,
                  }}
                >
                  {source}
                </a>
              </>
            )}

            {rationale && (
              <>
                <DraftPropertyLabel>{t("digest.draftRationale")}</DraftPropertyLabel>
                <div className="text-xs text-muted-foreground">{rationale}</div>
              </>
            )}
          </div>
        )}
      </header>

      <div className="flex min-h-0 flex-1 gap-6 px-7 pb-5">
        <div
          className={`min-h-0 min-w-0 flex-1 ${
            viewMode === "preview" ? "hidden" : ""
          }`}
          data-testid="digest-draft-editor"
          data-view-mode={viewMode}
        >
          <MarkdownEditor
            key={`${draft.id}:${editorRevision}`}
            initialValue={draftEdit.body ?? ""}
            onChange={(body) => setDraftEdit((current) => ({ ...current, body }))}
          />
        </div>
        {viewMode === "split" && (
          <div
            className="min-h-0 w-px shrink-0 self-stretch"
            style={{ background: "var(--accent-soft)" }}
          />
        )}
        <div
          className={`min-h-0 min-w-0 flex-1 overflow-y-auto ${
            viewMode === "edit" ? "hidden" : ""
          }`}
          data-testid="digest-draft-preview"
        >
          <MarkdownPreview value={draftEdit.body || t("digest.emptyDraftBody")} />
        </div>
      </div>

      {footer && (
        <div
          className="shrink-0 border-t px-7 py-3"
          style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
        >
          {footer}
        </div>
      )}
    </div>
  );
}

function DraftViewModeToggle({
  value,
  onChange,
}: {
  value: ViewMode;
  onChange: (next: ViewMode) => void;
}) {
  const { t } = useTranslation();
  const items: { mode: ViewMode; label: string; Icon: typeof Pen }[] = [
    { mode: "edit", label: t("note.viewEdit"), Icon: Pen },
    { mode: "split", label: t("note.viewSplit"), Icon: Columns2 },
    { mode: "preview", label: t("note.viewPreview"), Icon: Eye },
  ];
  return (
    <div
      className="flex items-center rounded-md border p-0.5"
      style={{ borderColor: "var(--accent-soft)", background: "var(--bg-1)" }}
      role="tablist"
      data-testid="digest-draft-view-mode-toggle"
    >
      {items.map(({ mode, label, Icon }) => {
        const active = value === mode;
        return (
          <button
            key={mode}
            type="button"
            role="tab"
            aria-selected={active}
            aria-label={label}
            title={label}
            data-mode={mode}
            data-active={active}
            onClick={() => onChange(mode)}
            className="flex size-7 items-center justify-center rounded-sm transition-colors"
            style={{
              background: active ? "var(--accent-tint-2)" : "transparent",
              color: active ? "var(--ink)" : "var(--ink-mute)",
            }}
          >
            <Icon className="size-3.5" />
          </button>
        );
      })}
    </div>
  );
}

function DraftKickerSep() {
  return (
    <span
      aria-hidden="true"
      style={{ color: "var(--ink-faint)", padding: "0 8px", userSelect: "none" }}
    >
      ·
    </span>
  );
}

function DraftPropertyLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex items-center font-mono text-[11px] uppercase"
      style={{ color: "var(--ink-mute)" }}
    >
      {children}
    </div>
  );
}
