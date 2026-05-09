/**
 * Phase 2 D Slice 2c.2-B' — Quick actions manager (per ADR-0025).
 *
 * Closes the CRUD loop that Slice 2c.1 left fragmented:
 *   - Browse all saved actions (list)
 *   - Run any action (⚡ button per row OR via Cmd+P palette)
 *   - Edit an action (rename / change folder / title template / shortcut / description)
 *   - Delete an action
 *   - Create a NEW action standalone (without going through NewDocDialog's
 *     "save as" piggyback flow — for the "I want to set this up for later"
 *     intent)
 *
 * Reachable via:
 *   - Header ⚡ icon (always visible)
 *   - Cmd+Shift+A keyboard shortcut
 *
 * The NewDocDialog's "保存为快捷操作" checkbox stays as a convenience side
 * path: "I just configured this and want to save it for next time."
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Pencil, Plus, Trash2, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createQuickAction,
  deleteQuickAction,
  listQuickActions,
  listTemplates,
  runQuickAction,
  updateQuickAction,
} from "@/api/client";
import type { TemplateSummary } from "@/api/client";
import type { NoteFull, QuickAction, QuickActionPayload } from "@/api/types";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { imeSafeKeyHandler } from "@/lib/imeSafe";
import { QK } from "@/lib/queryClient";

interface ManagerProps {
  open: boolean;
  onClose: () => void;
  /** When the user runs an action, the resulting note id flows up
   *  to AppShell so it can open in a tab. */
  onRan: (note: NoteFull) => void;
}

export function QuickActionsManager({ open, onClose, onRan }: ManagerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<QuickAction | null>(null);
  const [creating, setCreating] = useState<boolean>(false);

  // Reset transient editor state on each open so a previous unsaved
  // session doesn't bleed into the next.
  useEffect(() => {
    if (!open) {
      setEditing(null);
      setCreating(false);
    }
  }, [open]);

  const actionsQuery = useQuery<QuickAction[]>({
    queryKey: QK.quickActions,
    queryFn: listQuickActions,
    enabled: open,
    staleTime: 0,
  });

  const runMut = useMutation({
    mutationFn: (id: string) => runQuickAction(id),
    onSuccess: (note) => {
      void qc.invalidateQueries({ queryKey: QK.tree });
      onRan(note);
      onClose();
    },
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteQuickAction(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.quickActions });
    },
  });

  const list = actionsQuery.data ?? [];
  const editorOpen = creating || editing !== null;

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        if (!v) onClose();
      }}
    >
      <DialogContent
        data-testid="quick-actions-manager"
        showCloseButton={false}
        className="p-0"
        style={{
          width: 640,
          maxWidth: "94vw",
          background: "var(--bg)",
          border: "1px solid var(--line)",
          borderRadius: 8,
          overflow: "hidden",
        }}
      >
        <div
          className="flex items-center gap-3 px-5 pt-4 pb-3"
          style={{ borderBottom: "1px solid var(--line-soft)" }}
        >
          <DialogTitle asChild>
            <h2
              className="m-0 font-serif font-semibold"
              style={{
                fontSize: 18,
                color: "var(--ink)",
                letterSpacing: "-0.012em",
              }}
            >
              {t("quickActions.title")}
            </h2>
          </DialogTitle>
          <span className="flex-1" />
          <button
            type="button"
            data-testid="quick-actions-new"
            onClick={() => {
              setEditing(null);
              setCreating(true);
            }}
            className="inline-flex items-center gap-1.5 rounded-md font-medium"
            style={{
              height: 28,
              padding: "0 12px",
              fontSize: 12,
              background: "var(--accent)",
              color: "#faf7f0",
              border: "1px solid var(--accent)",
            }}
          >
            <Plus size={11} strokeWidth={2.4} />
            {t("quickActions.newAction")}
          </button>
        </div>

        {/* Body — list of actions or empty hint */}
        <div className="max-h-[60vh] overflow-y-auto">
          {actionsQuery.isLoading ? (
            <div
              className="px-5 py-6 text-xs"
              style={{ color: "var(--ink-mute)" }}
            >
              {t("quickActions.loading")}
            </div>
          ) : list.length === 0 ? (
            <div
              className="px-5 py-6 text-sm"
              style={{ color: "var(--ink-soft)" }}
              data-testid="quick-actions-empty"
            >
              <p style={{ marginTop: 0 }}>{t("quickActions.emptyTitle")}</p>
              <p
                className="mt-2"
                style={{ fontSize: 12, color: "var(--ink-mute)" }}
              >
                {t("quickActions.emptyHint")}
              </p>
            </div>
          ) : (
            <ul className="flex flex-col">
              {list.map((a) => (
                <li
                  key={a.id}
                  data-testid="quick-actions-row"
                  data-action-id={a.id}
                  className="flex items-center gap-2 px-4 py-2 transition-colors hover:bg-accent/15"
                  style={{ borderBottom: "1px solid var(--line-soft)" }}
                >
                  <Zap
                    size={14}
                    style={{ color: "var(--accent)", flexShrink: 0 }}
                  />
                  <div className="flex min-w-0 flex-1 flex-col">
                    <div className="flex items-baseline gap-2">
                      <span
                        className="truncate"
                        style={{
                          fontSize: 13,
                          color: "var(--ink)",
                          fontWeight: 500,
                        }}
                      >
                        {a.name}
                      </span>
                      {a.shortcut && (
                        <span
                          className="font-mono"
                          style={{
                            fontSize: 10.5,
                            color: "var(--ink-mute)",
                            padding: "1px 5px",
                            background: "var(--bg-1)",
                            borderRadius: 3,
                          }}
                        >
                          {a.shortcut}
                        </span>
                      )}
                    </div>
                    <span
                      className="truncate font-mono"
                      style={{ fontSize: 11, color: "var(--ink-mute)" }}
                    >
                      {a.params.kind === "create_note"
                        ? `${a.params.folder || "(root)"} / ${a.params.title_template}`
                        : a.params.kind}
                    </span>
                    {a.description && (
                      <span
                        className="mt-0.5 truncate italic"
                        style={{ fontSize: 11, color: "var(--ink-soft)" }}
                      >
                        {a.description}
                      </span>
                    )}
                  </div>
                  {/* Action buttons */}
                  <button
                    type="button"
                    onClick={() => runMut.mutate(a.id)}
                    aria-label={t("quickActions.run")}
                    title={t("quickActions.run")}
                    data-testid="quick-actions-run"
                    data-action-id={a.id}
                    className="flex size-7 items-center justify-center rounded-md transition-colors hover:bg-accent/30"
                    style={{ color: "var(--accent-2)" }}
                  >
                    <Zap size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setCreating(false);
                      setEditing(a);
                    }}
                    aria-label={t("quickActions.edit")}
                    title={t("quickActions.edit")}
                    data-testid="quick-actions-edit"
                    data-action-id={a.id}
                    className="flex size-7 items-center justify-center rounded-md transition-colors hover:bg-accent/30"
                    style={{ color: "var(--ink-mute)" }}
                  >
                    <Pencil size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (
                        window.confirm(
                          t("quickActions.deleteConfirm", { name: a.name }),
                        )
                      ) {
                        deleteMut.mutate(a.id);
                      }
                    }}
                    aria-label={t("quickActions.delete")}
                    title={t("quickActions.delete")}
                    data-testid="quick-actions-delete"
                    data-action-id={a.id}
                    className="flex size-7 items-center justify-center rounded-md transition-colors hover:bg-destructive/20"
                    style={{ color: "var(--ink-mute)" }}
                  >
                    <Trash2 size={13} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
      {editorOpen && (
        <QuickActionEditor
          mode={creating ? "create" : "edit"}
          initial={editing}
          onClose={() => {
            setEditing(null);
            setCreating(false);
          }}
        />
      )}
    </Dialog>
  );
}

interface EditorProps {
  mode: "create" | "edit";
  initial: QuickAction | null;
  onClose: () => void;
}

function QuickActionEditor({ mode, initial, onClose }: EditorProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [name, setName] = useState(initial?.name ?? "");
  const [folder, setFolder] = useState(
    initial?.params.kind === "create_note" ? initial.params.folder : "",
  );
  const [titleTemplate, setTitleTemplate] = useState(
    initial?.params.kind === "create_note"
      ? initial.params.title_template
      : "",
  );
  const [contentTemplateId, setContentTemplateId] = useState<string>(
    (initial?.params.kind === "create_note" &&
      initial.params.content_template_id) ||
      "",
  );
  const [shortcut, setShortcut] = useState(initial?.shortcut ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");

  const [templateMenuOpen, setTemplateMenuOpen] = useState(false);
  const templates = useQuery<TemplateSummary[]>({
    queryKey: QK.templates,
    queryFn: listTemplates,
    staleTime: 30_000,
  });

  const createMut = useMutation({
    mutationFn: (payload: QuickActionPayload) => createQuickAction(payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.quickActions });
      onClose();
    },
  });
  const updateMut = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: QuickActionPayload }) =>
      updateQuickAction(id, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.quickActions });
      onClose();
    },
  });
  const isPending = createMut.isPending || updateMut.isPending;

  const submit = () => {
    if (isPending) return;
    if (!name.trim()) return;
    const payload: QuickActionPayload = {
      name: name.trim(),
      description: description.trim() || null,
      shortcut: shortcut.trim() || null,
      params: {
        kind: "create_note",
        folder: folder.trim(),
        title_template: titleTemplate.trim(),
        content_template_id: contentTemplateId.trim() || null,
      },
    };
    if (mode === "create") {
      createMut.mutate(payload);
    } else if (initial) {
      updateMut.mutate({ id: initial.id, payload });
    }
  };

  return (
    <Dialog open={true} onOpenChange={(v) => (v ? null : onClose())}>
      <DialogContent
        data-testid="quick-actions-editor"
        showCloseButton={false}
        className="p-0"
        style={{
          width: 520,
          maxWidth: "92vw",
          background: "var(--bg)",
          border: "1px solid var(--line)",
          borderRadius: 8,
          overflow: "hidden",
        }}
      >
        <div
          className="px-5 pt-4 pb-3"
          style={{ borderBottom: "1px solid var(--line-soft)" }}
        >
          <DialogTitle asChild>
            <h2
              className="m-0 font-serif font-semibold"
              style={{
                fontSize: 17,
                color: "var(--ink)",
                letterSpacing: "-0.012em",
              }}
            >
              {mode === "create"
                ? t("quickActions.editorTitleNew")
                : t("quickActions.editorTitleEdit")}
            </h2>
          </DialogTitle>
        </div>

        <div className="flex flex-col gap-3 px-5 py-4">
          <Field label={t("newDoc.actionNameLabel")}>
            <input
              type="text"
              value={name}
              autoFocus
              placeholder={t("newDoc.actionNamePlaceholder")}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={imeSafeKeyHandler<HTMLInputElement>((e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  submit();
                }
              })}
              data-testid="editor-name"
              className="outline-none"
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
          <Field label={t("newDoc.folderLabel")}>
            <input
              type="text"
              value={folder}
              placeholder="weekly"
              onChange={(e) => setFolder(e.target.value)}
              data-testid="editor-folder"
              className="font-mono outline-none"
              style={{
                height: 30,
                border: "1px solid var(--line)",
                borderRadius: 5,
                background: "var(--card)",
                padding: "0 10px",
                fontSize: 12.5,
                color: "var(--ink)",
              }}
            />
          </Field>
          <Field
            label={t("newDoc.titleLabel")}
            hint={t("newDoc.titleHint")}
          >
            <input
              type="text"
              value={titleTemplate}
              placeholder="周报 {{week}}"
              onChange={(e) => setTitleTemplate(e.target.value)}
              data-testid="editor-title-template"
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
          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: "1fr 130px" }}
          >
            <Field label={t("newDoc.templateLabel")}>
              <TemplatePicker
                templates={templates.data ?? []}
                value={contentTemplateId || null}
                open={templateMenuOpen}
                onToggle={() => setTemplateMenuOpen((v) => !v)}
                onSelect={(id) => {
                  setContentTemplateId(id ?? "");
                  setTemplateMenuOpen(false);
                }}
                placeholder={t("newDoc.templateNone")}
              />
            </Field>
            <Field label={t("newDoc.actionShortcutLabel")}>
              <input
                type="text"
                value={shortcut}
                placeholder={t("newDoc.actionShortcutPlaceholder")}
                onChange={(e) => setShortcut(e.target.value)}
                data-testid="editor-shortcut"
                className="font-mono outline-none"
                style={{
                  height: 30,
                  border: "1px solid var(--line)",
                  borderRadius: 5,
                  background: "var(--card)",
                  padding: "0 10px",
                  fontSize: 11,
                  color: "var(--ink-soft)",
                }}
              />
            </Field>
          </div>
          <Field label={t("newDoc.actionDescriptionLabel")}>
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              data-testid="editor-description"
              className="outline-none"
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

        <div
          className="flex items-center gap-3 px-5 py-3"
          style={{
            borderTop: "1px solid var(--line-soft)",
            background: "var(--bg-1)",
          }}
        >
          <span className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            data-testid="editor-cancel"
            className="rounded-md"
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
            disabled={isPending || !name.trim()}
            data-testid="editor-save"
            className="inline-flex items-center gap-1.5 rounded-md disabled:opacity-50"
            style={{
              height: 28,
              padding: "0 14px",
              fontSize: 12,
              fontWeight: 500,
              background: "var(--accent)",
              color: "#faf7f0",
              border: "1px solid var(--accent)",
            }}
          >
            {mode === "create"
              ? t("quickActions.editorSaveNew")
              : t("quickActions.editorSaveEdit")}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Template picker — same UX as NewDocDialog's so users get the same
 *  affordance (pick by title, never expose ULIDs). 2026-05-10 dogfood
 *  fix: previous text input "模板 ID 可选模板笔记 id" leaked the
 *  internal id concept; user can't memorize ULIDs. */
function TemplatePicker({
  templates,
  value,
  open,
  onToggle,
  onSelect,
  placeholder,
}: {
  templates: TemplateSummary[];
  value: string | null;
  open: boolean;
  onToggle: () => void;
  onSelect: (id: string | null) => void;
  placeholder: string;
}) {
  const current = templates.find((t) => t.id === value);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        data-testid="editor-template-picker"
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
          <span style={{ color: "var(--ink)" }}>{current.title}</span>
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
          data-testid="editor-template-menu"
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
              data-testid="editor-template-option"
              data-template-id=""
              className="flex w-full items-center px-3 py-1.5 italic hover:bg-accent/30"
              style={{
                fontSize: 12,
                color: value === null ? "var(--accent-2)" : "var(--ink-mute)",
                background:
                  value === null ? "var(--accent-tint)" : "transparent",
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
                data-testid="editor-template-option"
                data-template-id={tpl.id}
                className="flex w-full items-center px-3 py-1.5 hover:bg-accent/30"
                style={{
                  fontSize: 12,
                  color: tpl.id === value ? "var(--accent-2)" : "var(--ink)",
                  background:
                    tpl.id === value ? "var(--accent-tint)" : "transparent",
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
