/**
 * Phase 1 B slice 8 v2 — Templates management + use dialog.
 *
 * Design intent: users should not need to know `notes/templates/` is
 * the on-disk storage. This dialog is the only first-class entry to
 * "the Templates feature". Click a template to use it (creates a new
 * note from it); the per-row Edit / Delete affordances cover
 * management without exposing the folder in the regular file tree.
 *
 * Inline insertion of a template into an *already-open* note is
 * handled by the editor's `/` slash command (see templateSlash.ts).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createBlankNote,
  deleteNote,
  listTemplates,
  type TemplateSummary,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { QK } from "@/lib/queryClient";

// Storage convention: templates are notes under `notes/_templates/`.
// The leading underscore matches `_attachments/` — both are reserved
// system folders the file tree hides. End-users only meet the
// "Templates" concept; the on-disk name is opaque unless they go to
// Finder.
const TEMPLATE_FOLDER = "_templates";
const NEW_TEMPLATE_PLACEHOLDER = "Untitled template";

export function TemplatesDialog({
  open,
  onClose,
  onUseTemplate,
  onEditTemplate,
}: {
  open: boolean;
  onClose: () => void;
  /** User clicked "Use" on a template — start the new-note flow with
   *  this template id. null means "Blank note from no template". */
  onUseTemplate: (templateId: string | null) => void;
  /** User clicked "Edit" on a template — open it in the main editor. */
  onEditTemplate: (templateId: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const templates = useQuery({
    queryKey: QK.templates,
    queryFn: listTemplates,
    enabled: open,
  });
  const [filter, setFilter] = useState("");
  useEffect(() => {
    if (!open) setFilter("");
  }, [open]);

  const newTemplateM = useMutation({
    mutationFn: () =>
      createBlankNote({
        title: NEW_TEMPLATE_PLACEHOLDER,
        folder: TEMPLATE_FOLDER,
      }),
    onSuccess: async (note) => {
      await qc.invalidateQueries({ queryKey: QK.templates });
      await qc.invalidateQueries({ queryKey: QK.tree });
      onEditTemplate(note.id);
      onClose();
    },
  });

  const deleteTemplateM = useMutation({
    mutationFn: (id: string) => deleteNote(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.templates });
      void qc.invalidateQueries({ queryKey: QK.tree });
    },
  });

  const filtered = filterTemplates(templates.data ?? [], filter);

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent className="gap-0 p-0 sm:max-w-4xl">
        <DialogHeader className="border-b px-4 py-3" style={{ borderColor: "var(--line)" }}>
          <DialogTitle className="text-sm font-semibold">
            {t("templates.dialogTitle")}
          </DialogTitle>
          {/* sr-only description satisfies Radix' a11y rule (without
            * one or `aria-describedby={undefined}`, the dev console
            * spams "Missing Description for DialogContent"). */}
          <DialogDescription className="sr-only">
            {t("templates.dialogDescription")}
          </DialogDescription>
        </DialogHeader>
        <div className="px-3 pt-3 pb-2">
          <Input
            value={filter}
            placeholder={t("templates.filterPlaceholder")}
            onChange={(e) => setFilter(e.target.value)}
            data-testid="templates-filter"
            autoFocus
          />
        </div>
        <div
          className="max-h-80 min-h-32 overflow-y-auto"
          data-testid="templates-list"
        >
          {templates.isLoading && (
            <div className="px-4 py-3 text-xs text-muted-foreground">
              {t("tree.loading")}
            </div>
          )}
          {/* Distinguish "backend can't be reached" (e.g. dev server
            * not restarted after a code change) from "no templates
            * yet". Same UI either way is misleading; the user can't
            * tell why the dialog is empty. */}
          {!templates.isLoading && templates.isError && (
            <div
              className="px-4 py-6 text-xs"
              style={{ color: "var(--danger, #b8554d)" }}
              data-testid="templates-error-hint"
            >
              {t("templates.fetchError")}
            </div>
          )}
          {!templates.isLoading &&
            !templates.isError &&
            filtered.length === 0 && (
              <div
                className="px-4 py-6 text-xs"
                style={{ color: "var(--ink-mute)" }}
                data-testid="templates-empty-hint"
              >
                {t("templates.empty")}
              </div>
            )}
          <ul className="py-1">
            {filtered.map((tpl) => (
              <li
                key={tpl.id}
                className="group flex items-center gap-2 px-3 py-1.5 hover:bg-accent/40"
              >
                <button
                  type="button"
                  className="flex-1 truncate text-left text-sm"
                  style={{ color: "var(--ink)" }}
                  onClick={() => {
                    onUseTemplate(tpl.id);
                    onClose();
                  }}
                  data-testid="template-use"
                >
                  {tpl.title}
                </button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 opacity-0 group-hover:opacity-100"
                  aria-label={t("templates.editAction")}
                  onClick={() => {
                    onEditTemplate(tpl.id);
                    onClose();
                  }}
                  data-testid="template-edit"
                >
                  <Pencil className="size-3.5" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-7 opacity-0 group-hover:opacity-100"
                  aria-label={t("templates.deleteAction")}
                  onClick={() => {
                    if (
                      window.confirm(
                        t("templates.deleteConfirm", { name: tpl.title }),
                      )
                    ) {
                      deleteTemplateM.mutate(tpl.id);
                    }
                  }}
                  data-testid="template-delete"
                >
                  <Trash2 className="size-3.5" />
                </Button>
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center justify-between border-t px-3 py-2" style={{ borderColor: "var(--line)" }}>
          <span className="text-[11px]" style={{ color: "var(--ink-mute)" }}>
            {t("templates.locationHint")}
          </span>
          <Button
            variant="default"
            size="sm"
            onClick={() => newTemplateM.mutate()}
            disabled={newTemplateM.isPending}
            data-testid="templates-new"
          >
            <Plus className="mr-1 size-3.5" />
            {t("templates.newAction")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Cheap fuzzy: substring match on lowercased label, case-insensitive. */
function filterTemplates(all: TemplateSummary[], q: string): TemplateSummary[] {
  if (!q.trim()) return all;
  const lower = q.trim().toLowerCase();
  return all.filter((t) => t.title.toLowerCase().includes(lower));
}
