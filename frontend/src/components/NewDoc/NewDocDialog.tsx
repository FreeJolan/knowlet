/**
 * Phase 2 D Slice 2a — 新建文档 dialog (NewDocDialog).
 *
 * Per Claude Design 2026-05-09 (v2). The single create-document entry
 * for the app, replacing the awkward "click LayoutTemplate icon →
 * surprise note in root" flow:
 *
 *   - 位置 (folder): default = `seedFolder` prop (current tree
 *     selection at open time). User can change via picker.
 *   - 模板 (template): optional. Pulls from /api/templates. Selecting
 *     a template fills the preview pane below.
 *   - 标题 (title): plain input; supports {{date}} {{week}} {{month}}
 *     placeholders rendered at create-time.
 *   - 5 inspiration chips: clicking fills folder + title (NOT a
 *     pre-shipped action — just form prefill).
 *   - "保存为快捷操作" checkbox: Slice 2c will wire to backend; here
 *     it's marked as preview / disabled with a tooltip.
 *
 * Esc / × / clicking outside cancels. Enter while focused on title
 * commits (IME-safe).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ExternalLink, FolderOpen, Plus, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createBlankNote,
  createFolder,
  getNote,
  getTree,
  listTemplates,
} from "@/api/client";
import type { TemplateSummary } from "@/api/client";
import type { NoteFull, TreeFolder } from "@/api/types";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { imeSafeKeyHandler } from "@/lib/imeSafe";
import { renderPlaceholders } from "@/lib/placeholders";
import { QK } from "@/lib/queryClient";

import { INSPIRATIONS } from "./inspirations";

interface Props {
  open: boolean;
  onClose: () => void;
  /** Folder to default-select when the dialog opens. The caller (AppShell)
   *  computes this from the current tree selection or the right-clicked
   *  folder in the context menu. Empty = vault root. */
  seedFolder?: string;
  /** Called with the new note's id after a successful create — caller
   *  opens it in a tab via tabsApi.openNote. */
  onCreated: (note: NoteFull) => void;
}

function listFoldersFlat(root: TreeFolder | undefined): string[] {
  if (!root) return [];
  const out: string[] = [""];
  const walk = (f: TreeFolder, prefix: string) => {
    for (const sub of f.folders) {
      const path = prefix ? `${prefix}/${sub.name}` : sub.name;
      // Skip dotfolders (.trash) and the templates folder — they're
      // not valid create-document targets.
      if (sub.name.startsWith(".") || sub.name === "_templates") continue;
      out.push(path);
      walk(sub, path);
    }
  };
  walk(root, "");
  return out;
}

export function NewDocDialog({ open, onClose, seedFolder, onCreated }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const [folder, setFolder] = useState<string>(seedFolder ?? "");
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [titleTemplate, setTitleTemplate] = useState<string>("");
  const [folderMenuOpen, setFolderMenuOpen] = useState(false);
  const [templateMenuOpen, setTemplateMenuOpen] = useState(false);

  // Reset the form ONLY on a closed→open transition. If we keyed off
  // `seedFolder` changes too, the bubble-up effect (window event →
  // AppShell sets seedFolder → reset fires → state cleared) would
  // erase the user's just-clicked title/template. Use a ref to track
  // the previous `open` value so the reset is gated on the actual
  // edge.
  const prevOpenRef = useRef<boolean>(false);
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setFolder(seedFolder ?? "");
      setTemplateId(null);
      setTitleTemplate("");
    }
    prevOpenRef.current = open;
  }, [open, seedFolder]);

  // Phase 2 D Slice 2b — bubble folder changes via a window event
  // for the tree's ghost selection to follow. Deferring via
  // setTimeout(0) breaks the synchronous render chain that triggered
  // a React #185 cascade with arborist's tree (the cycle was:
  // openNewDocDialog setStates → dialog mounts → useState init runs
  // → Reset effect "redundantly" sets folder → Folder-change effect
  // dispatches synchronously → AppShell setNewDocSeedFolder → arborist
  // re-renders during the same commit → schedule loop).
  const lastDispatchedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!open) {
      lastDispatchedRef.current = null;
      return;
    }
    if (lastDispatchedRef.current === folder) return;
    lastDispatchedRef.current = folder;
    const handle = window.setTimeout(() => {
      window.dispatchEvent(
        new CustomEvent("knowlet:new-doc-folder-change", { detail: folder }),
      );
    }, 0);
    return () => window.clearTimeout(handle);
  }, [folder, open]);

  const tree = useQuery<TreeFolder>({ queryKey: QK.tree, queryFn: getTree });
  const folders = useMemo(() => listFoldersFlat(tree.data), [tree.data]);

  const templates = useQuery<TemplateSummary[]>({
    queryKey: QK.templates,
    queryFn: listTemplates,
    staleTime: 30_000,
  });

  const previewQuery = useQuery<NoteFull>({
    queryKey: templateId ? QK.note(templateId) : ["new-doc-preview-empty"],
    queryFn: () => getNote(templateId as string),
    enabled: !!templateId,
    staleTime: 30_000,
  });

  // Live-rendered title (placeholders → values).
  const renderedTitle = useMemo(
    () => renderPlaceholders(titleTemplate),
    [titleTemplate],
  );

  const titleInputRef = useRef<HTMLInputElement>(null);
  // Auto-focus the title field on open so the user can type immediately
  // (most-common path: seed folder is right + just type a title).
  useEffect(() => {
    if (open) {
      const t = window.setTimeout(() => titleInputRef.current?.focus(), 60);
      return () => window.clearTimeout(t);
    }
    return undefined;
  }, [open]);

  const createMutation = useMutation({
    mutationFn: async () => {
      // Make sure the folder exists before creating the note.
      // createFolder is idempotent on the backend (409 == already-exists,
      // which is fine). Empty folder == root, no mkdir needed.
      if (folder) {
        try {
          await createFolder(folder);
        } catch (err) {
          const status = (err as { status?: number }).status;
          if (status !== 409) throw err;
        }
      }
      const finalTitle = renderedTitle.trim() || t("newDoc.defaultTitle");
      const fresh = await createBlankNote({
        title: finalTitle,
        folder: folder || undefined,
        templateId: templateId ?? undefined,
      });
      return fresh;
    },
    onSuccess: (fresh) => {
      void qc.invalidateQueries({ queryKey: QK.tree });
      onCreated(fresh);
      onClose();
    },
  });

  const submit = () => {
    if (createMutation.isPending) return;
    createMutation.mutate();
  };

  const previewBody = previewQuery.data?.body ?? "";

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <DialogContent
        data-testid="new-document-dialog"
        className="p-0"
        style={{
          width: 560,
          maxWidth: "94vw",
          background: "var(--bg)",
          border: "1px solid var(--line)",
          borderRadius: 8,
          overflow: "hidden",
        }}
      >
        {/* Header */}
        <div
          className="px-5 pt-4 pb-3"
          style={{ borderBottom: "1px solid var(--line-soft)" }}
        >
          <div className="flex items-center gap-3">
            <DialogTitle asChild>
              <h2
                className="m-0 font-serif font-semibold"
                style={{
                  fontSize: 18,
                  color: "var(--ink)",
                  letterSpacing: "-0.012em",
                }}
              >
                {t("newDoc.title")}
              </h2>
            </DialogTitle>
            <span className="flex-1" />
            <span
              className="font-mono"
              style={{
                fontSize: 10.5,
                color: "var(--ink-mute)",
                padding: "2px 6px",
                background: "var(--bg-1)",
                borderRadius: 3,
              }}
            >
              ESC
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label={t("newDoc.close")}
              className="text-[color:var(--ink-mute)] hover:text-[color:var(--ink)]"
            >
              <X size={14} />
            </button>
          </div>
          <ConceptLine />
        </div>

        {/* Inspiration chips */}
        <div
          className="flex flex-wrap items-center gap-1.5 px-5 pt-3 pb-2.5"
          style={{ borderBottom: "1px solid var(--line-soft)" }}
        >
          <span
            className="mr-1 self-center font-mono uppercase tracking-wider"
            style={{
              fontSize: 10,
              color: "var(--ink-mute)",
              letterSpacing: "0.04em",
            }}
          >
            {t("newDoc.try")}
          </span>
          {INSPIRATIONS.map((preset) => {
            const active =
              folder === preset.folder && titleTemplate === preset.titleTemplate;
            return (
              <button
                key={preset.id}
                type="button"
                data-testid={`inspiration-${preset.id}`}
                onClick={() => {
                  setFolder(preset.folder);
                  setTitleTemplate(preset.titleTemplate);
                }}
                className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 transition-colors"
                style={{
                  fontSize: 11.5,
                  background: active ? "var(--accent-soft)" : "transparent",
                  border: active
                    ? "1px solid var(--accent)"
                    : "1px solid var(--line)",
                  color: active ? "var(--accent-2)" : "var(--ink-soft)",
                }}
              >
                <span style={{ fontSize: 12 }}>{preset.icon}</span>
                {preset.label}
              </button>
            );
          })}
        </div>

        {/* Form body */}
        <div className="flex flex-col gap-3 px-5 pt-4 pb-3">
          {/* 位置 */}
          <Field label={t("newDoc.folderLabel")}>
            <FolderPickerButton
              folder={folder}
              folders={folders}
              open={folderMenuOpen}
              onToggle={() => {
                setFolderMenuOpen((v) => !v);
                setTemplateMenuOpen(false);
              }}
              onSelect={(f) => {
                setFolder(f);
                setFolderMenuOpen(false);
              }}
            />
          </Field>

          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: "1fr 1fr" }}
          >
            <Field label={t("newDoc.templateLabel")}>
              <TemplateSelectButton
                templateId={templateId}
                templates={templates.data ?? []}
                open={templateMenuOpen}
                onToggle={() => {
                  setTemplateMenuOpen((v) => !v);
                  setFolderMenuOpen(false);
                }}
                onSelect={(id) => {
                  setTemplateId(id);
                  setTemplateMenuOpen(false);
                }}
                placeholder={t("newDoc.templateNone")}
              />
            </Field>
            <Field
              label={t("newDoc.titleLabel")}
              hint={t("newDoc.titleHint")}
            >
              <input
                ref={titleInputRef}
                type="text"
                value={titleTemplate}
                placeholder={t("newDoc.titlePlaceholder")}
                onChange={(e) => setTitleTemplate(e.target.value)}
                onKeyDown={imeSafeKeyHandler<HTMLInputElement>((e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    submit();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    onClose();
                  }
                })}
                data-testid="new-document-title"
                className="font-mono outline-none"
                style={{
                  height: 30,
                  border: "1px solid var(--line)",
                  borderRadius: 5,
                  background: "var(--card)",
                  padding: "0 10px",
                  fontSize: 13,
                  color: "var(--ink)",
                }}
              />
            </Field>
          </div>

          {/* Preview when template selected */}
          {templateId ? (
            <Field label={t("newDoc.previewLabel")}>
              <div
                data-testid="new-document-preview"
                className="relative font-mono"
                style={{
                  border: "1px dashed var(--line)",
                  borderRadius: 5,
                  background: "var(--bg-1)",
                  padding: "10px 12px",
                  fontSize: 11.5,
                  color: "var(--ink-soft)",
                  lineHeight: 1.7,
                  maxHeight: 132,
                  overflow: "hidden",
                  whiteSpace: "pre-wrap",
                }}
              >
                {previewBody.split("\n").slice(0, 12).join("\n")}
                <span
                  aria-hidden="true"
                  className="pointer-events-none absolute bottom-0 left-0 right-0"
                  style={{
                    height: 28,
                    background:
                      "linear-gradient(to bottom, transparent, var(--bg-1))",
                  }}
                />
              </div>
            </Field>
          ) : null}

          {/* Save-as-quick-action — placeholder until Slice 2c */}
          <button
            type="button"
            disabled
            title={t("newDoc.saveAsActionComingSoon")}
            data-testid="save-as-quick-action"
            className="flex cursor-not-allowed items-start gap-2.5 rounded-md px-3 py-2.5 opacity-60"
            style={{
              border: "1px dashed var(--line)",
              background: "var(--card)",
            }}
          >
            <span
              className="flex size-3.5 shrink-0 items-center justify-center rounded-sm"
              style={{
                border: "1.5px solid var(--ink-mute)",
                marginTop: 1,
              }}
            />
            <span className="flex flex-col items-start gap-0.5 text-left">
              <span
                style={{
                  fontSize: 12.5,
                  color: "var(--ink)",
                  fontWeight: 500,
                }}
              >
                {t("newDoc.saveAsAction")}
              </span>
              <span style={{ fontSize: 11, color: "var(--ink-soft)" }}>
                {t("newDoc.saveAsActionComingSoon")}
              </span>
            </span>
          </button>
        </div>

        {/* Footer */}
        <div
          className="flex items-center gap-3 px-5 py-3"
          style={{
            borderTop: "1px solid var(--line-soft)",
            background: "var(--bg-1)",
          }}
        >
          <span
            className="font-mono"
            style={{ fontSize: 11, color: "var(--ink-mute)" }}
          >
            {t("newDoc.manageTemplatesPrefix")}{" "}
            <button
              type="button"
              data-testid="open-templates-manager"
              onClick={() => {
                onClose();
                window.dispatchEvent(new CustomEvent("knowlet:open-templates"));
              }}
              className="underline decoration-dotted underline-offset-2"
              style={{ color: "var(--accent-2)" }}
            >
              {t("newDoc.manageTemplatesLink")}
              <ExternalLink size={9} className="ml-0.5 inline" />
            </button>
          </span>
          <span className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            data-testid="new-document-cancel"
            className="rounded-md transition-colors"
            style={{
              height: 28,
              padding: "0 14px",
              fontSize: 12,
              color: "var(--ink-soft)",
              background: "transparent",
              border: "1px solid var(--line)",
            }}
          >
            {t("newDoc.cancel")}
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={createMutation.isPending}
            data-testid="new-document-submit"
            className="inline-flex items-center gap-1.5 rounded-md transition-colors disabled:opacity-50"
            style={{
              height: 28,
              padding: "0 14px",
              fontSize: 12,
              fontWeight: 500,
              color: "#faf7f0",
              background: "var(--accent)",
              border: "1px solid var(--accent)",
            }}
          >
            <Plus size={11} strokeWidth={2.4} />
            {createMutation.isPending ? t("newDoc.creating") : t("newDoc.create")}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ConceptLine() {
  const { t } = useTranslation();
  return (
    <div
      className="mt-2.5 flex items-center gap-1"
      style={{ fontSize: 11.5, color: "var(--ink-soft)", lineHeight: 1.5 }}
    >
      <em
        style={{ color: "var(--accent-2)", fontStyle: "italic" }}
      >
        {t("newDoc.conceptAction")}
      </em>
      <span style={{ color: "var(--ink-faint)" }}>=</span>
      <span>{t("newDoc.conceptFolder")}</span>
      <span style={{ color: "var(--ink-faint)" }}>+</span>
      <span>{t("newDoc.conceptTemplate")}</span>
      <span style={{ color: "var(--ink-faint)" }}>=</span>
      <em style={{ color: "var(--ink)", fontStyle: "italic" }}>
        {t("newDoc.conceptDoc")}
      </em>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label
        className="font-mono uppercase tracking-wider"
        style={{
          fontSize: 10.5,
          color: "var(--ink-mute)",
          letterSpacing: "0.04em",
        }}
      >
        {label}
        {hint ? (
          <span
            className="ml-2 italic"
            style={{
              textTransform: "none",
              letterSpacing: 0,
              fontFamily: "var(--font-sans)",
              color: "var(--ink-faint)",
            }}
          >
            {hint}
          </span>
        ) : null}
      </label>
      {children}
    </div>
  );
}

function FolderPickerButton({
  folder,
  folders,
  open,
  onToggle,
  onSelect,
}: {
  folder: string;
  folders: string[];
  open: boolean;
  onToggle: () => void;
  onSelect: (f: string) => void;
}) {
  const segs = folder ? folder.split("/") : ["root"];
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        data-testid="dialog-folder-picker"
        className="flex w-full items-center gap-1.5 font-mono"
        style={{
          height: 30,
          border: "1px solid var(--line)",
          borderRadius: 5,
          background: "var(--card)",
          padding: "0 8px 0 10px",
          fontSize: 12.5,
          color: "var(--ink)",
        }}
      >
        <FolderOpen size={12} className="shrink-0" />
        <span style={{ color: "var(--ink-soft)" }}>
          {segs.map((s, i) => (
            <span key={i}>
              {i > 0 ? (
                <span style={{ color: "var(--ink-faint)", padding: "0 4px" }}>
                  /
                </span>
              ) : null}
              <span
                style={{
                  color:
                    i === segs.length - 1 ? "var(--accent-2)" : "var(--ink-soft)",
                  fontWeight: i === segs.length - 1 ? 500 : 400,
                }}
              >
                {s}
              </span>
            </span>
          ))}
        </span>
        <span className="flex-1" />
        <ChevronDown size={11} />
      </button>
      {open ? (
        <ul
          data-testid="dialog-folder-menu"
          className="absolute z-50 mt-1 max-h-56 overflow-y-auto"
          style={{
            left: 0,
            right: 0,
            background: "var(--card)",
            border: "1px solid var(--line)",
            borderRadius: 5,
            boxShadow: "0 8px 22px rgba(40,30,20,.18)",
          }}
        >
          {folders.map((f) => (
            <li key={f || "__root"}>
              <button
                type="button"
                onClick={() => onSelect(f)}
                data-testid="dialog-folder-option"
                data-folder={f}
                className="flex w-full items-center gap-2 px-3 py-1.5 font-mono hover:bg-accent/30"
                style={{
                  fontSize: 12,
                  color: f === folder ? "var(--accent-2)" : "var(--ink)",
                  background: f === folder ? "var(--accent-tint)" : "transparent",
                  textAlign: "left",
                }}
              >
                <FolderOpen size={11} />
                {f || "(root)"}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function TemplateSelectButton({
  templateId,
  templates,
  open,
  onToggle,
  onSelect,
  placeholder,
}: {
  templateId: string | null;
  templates: TemplateSummary[];
  open: boolean;
  onToggle: () => void;
  onSelect: (id: string | null) => void;
  placeholder: string;
}) {
  const current = templates.find((t) => t.id === templateId);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        data-testid="dialog-template-picker"
        className="flex w-full items-center gap-2"
        style={{
          height: 30,
          border: "1px solid var(--line)",
          borderRadius: 5,
          background: "var(--card)",
          padding: "0 10px",
          fontSize: 12.5,
        }}
      >
        {current ? (
          <>
            <span
              className="inline-flex size-4 items-center justify-center rounded-sm"
              style={{
                background: "var(--accent-tint)",
                color: "var(--accent-2)",
                fontSize: 10,
              }}
            >
              ▤
            </span>
            <span style={{ color: "var(--ink)" }}>{current.title}</span>
          </>
        ) : (
          <span className="italic" style={{ color: "var(--ink-mute)" }}>
            {placeholder}
          </span>
        )}
        <span className="flex-1" />
        <ChevronDown size={11} style={{ color: "var(--ink-mute)" }} />
      </button>
      {open ? (
        <ul
          data-testid="dialog-template-menu"
          className="absolute z-50 mt-1 max-h-56 overflow-y-auto"
          style={{
            left: 0,
            right: 0,
            background: "var(--card)",
            border: "1px solid var(--line)",
            borderRadius: 5,
            boxShadow: "0 8px 22px rgba(40,30,20,.18)",
          }}
        >
          <li>
            <button
              type="button"
              onClick={() => onSelect(null)}
              data-testid="dialog-template-option"
              data-template-id=""
              className="flex w-full items-center gap-2 px-3 py-1.5 italic hover:bg-accent/30"
              style={{
                fontSize: 12,
                color: templateId === null ? "var(--accent-2)" : "var(--ink-mute)",
                background:
                  templateId === null ? "var(--accent-tint)" : "transparent",
                textAlign: "left",
              }}
            >
              {placeholder}
            </button>
          </li>
          {templates.map((tpl) => (
            <li key={tpl.id}>
              <button
                type="button"
                onClick={() => onSelect(tpl.id)}
                data-testid="dialog-template-option"
                data-template-id={tpl.id}
                className="flex w-full items-center gap-2 px-3 py-1.5 hover:bg-accent/30"
                style={{
                  fontSize: 12,
                  color: tpl.id === templateId ? "var(--accent-2)" : "var(--ink)",
                  background:
                    tpl.id === templateId ? "var(--accent-tint)" : "transparent",
                  textAlign: "left",
                }}
              >
                {tpl.title}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
