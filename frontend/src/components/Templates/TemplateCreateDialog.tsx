import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { createTemplate } from "@/api/client";
import type { NoteFull, NoteKind } from "@/api/types";
import { KindChip } from "@/components/KindChip";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { imeSafeKeyHandler } from "@/lib/imeSafe";
import { QK } from "@/lib/queryClient";

interface TemplateCreateDialogProps {
  open: boolean;
  onClose: () => void;
  onCreated: (template: NoteFull) => void;
}

export function TemplateCreateDialog({
  open,
  onClose,
  onCreated,
}: TemplateCreateDialogProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<NoteKind>("knowledge");
  const [body, setBody] = useState("# {{title}}\n\n");
  const titleRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setTitle("");
    setKind("knowledge");
    setBody("# {{title}}\n\n");
  }, [open]);

  const createMut = useMutation({
    mutationFn: () =>
      createTemplate({
        title: title.trim(),
        kind,
        body,
      }),
    onSuccess: async (template) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: QK.templates }),
        qc.invalidateQueries({ queryKey: QK.tree }),
      ]);
      onCreated(template);
      onClose();
    },
  });

  const submit = () => {
    if (createMut.isPending || !title.trim()) return;
    createMut.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => (!v && !createMut.isPending ? onClose() : null)}
    >
      <DialogContent
        data-testid="template-create-dialog"
        showCloseButton={false}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          titleRef.current?.focus();
        }}
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
        <div
          className="flex items-center gap-3 px-5 pt-4 pb-3"
          style={{ borderBottom: "1px solid var(--line-soft)" }}
        >
          <DialogTitle asChild>
            <h2
              className="m-0 font-serif font-semibold"
              style={{ fontSize: 18, color: "var(--ink)", letterSpacing: 0 }}
            >
              {t("templates.createTitle")}
            </h2>
          </DialogTitle>
          <span className="flex-1" />
          <button
            type="button"
            onClick={onClose}
            disabled={createMut.isPending}
            aria-label={t("newDoc.close")}
            className="text-[color:var(--ink-mute)] hover:text-[color:var(--ink)] disabled:opacity-50"
          >
            <X size={14} />
          </button>
        </div>

        <div className="flex flex-col gap-3 px-5 py-4">
          <TemplateField label={t("templates.titleLabel")}>
            <input
              ref={titleRef}
              type="text"
              value={title}
              placeholder={t("templates.titlePlaceholder")}
              disabled={createMut.isPending}
              onChange={(e) => setTitle(e.target.value)}
              onKeyDown={imeSafeKeyHandler<HTMLInputElement>((e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  submit();
                }
              })}
              data-testid="template-title"
              className="outline-none"
              style={{
                height: 32,
                border: "1px solid var(--line)",
                borderRadius: 5,
                background: "var(--card)",
                padding: "0 10px",
                fontSize: 13,
                color: "var(--ink)",
              }}
            />
          </TemplateField>

          <TemplateField label={t("templates.kindLabel")}>
            <div className="flex gap-2">
              {(["knowledge", "reference"] as const).map((candidate) => (
                <button
                  key={candidate}
                  type="button"
                  disabled={createMut.isPending}
                  onClick={() => setKind(candidate)}
                  data-testid={`template-kind-${candidate}`}
                  className="inline-flex items-center rounded-md px-2 py-1 disabled:opacity-50"
                  style={{
                    border:
                      kind === candidate
                        ? "1px solid var(--accent)"
                        : "1px solid var(--line)",
                    background:
                      kind === candidate ? "var(--accent-tint)" : "var(--card)",
                  }}
                >
                  <KindChip kind={candidate} variant="chip-quiet" />
                </button>
              ))}
            </div>
          </TemplateField>

          <TemplateField
            label={t("templates.bodyLabel")}
            hint={t("templates.bodyHint")}
          >
            <textarea
              value={body}
              disabled={createMut.isPending}
              onChange={(e) => setBody(e.target.value)}
              data-testid="template-body"
              className="font-mono outline-none"
              style={{
                minHeight: 160,
                resize: "vertical",
                border: "1px solid var(--line)",
                borderRadius: 5,
                background: "var(--card)",
                padding: "10px 12px",
                fontSize: 12.5,
                lineHeight: 1.6,
                color: "var(--ink)",
              }}
            />
          </TemplateField>
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
            disabled={createMut.isPending}
            data-testid="template-create-cancel"
            className="rounded-md disabled:opacity-50"
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
            disabled={!title.trim() || createMut.isPending}
            aria-busy={createMut.isPending}
            data-busy={createMut.isPending ? "true" : undefined}
            data-testid="template-create-submit"
            className="inline-flex items-center gap-1.5 rounded-md disabled:opacity-50"
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
            {createMut.isPending ? (
              <Loader2
                size={11}
                strokeWidth={2.4}
                className="animate-spin"
                data-testid="template-create-submit-spinner"
              />
            ) : null}
            {createMut.isPending ? t("templates.creating") : t("templates.create")}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TemplateField({
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
        style={{ fontSize: 10.5, color: "var(--ink-mute)", letterSpacing: "0.04em" }}
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
