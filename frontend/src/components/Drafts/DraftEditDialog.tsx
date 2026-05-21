/**
 * DraftEditDialog — Phase 3 Stage 3 §3.5 (added 2026-05-22 dogfood)
 *
 * Edit a draft's title + body in place before approving. Per
 * ADR-0029 §4 原则 1 ("user is the last-byte channel"), the user
 * frequently wants to refine an AI-extracted summary before
 * committing it as a Note. This dialog is the explicit path.
 *
 * Three actions:
 *   - Save: write back to draft (kind / source unchanged).
 *   - Save & Approve: write to draft THEN convert to Note.
 *   - Cancel: discard pending edits.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { approveDraft, listDrafts, updateDraft } from "@/api/client";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { QK } from "@/lib/queryClient";

interface Props {
  draftId: string;
  open: boolean;
  onClose: () => void;
}

export function DraftEditDialog({
  draftId,
  open,
  onClose,
}: Props): React.ReactElement {
  const { t } = useTranslation();
  const qc = useQueryClient();
  // Pull the draft from the cached drafts list — the list already
  // carries body since Phase 3 Stage 3 (2026-05-22 dogfood fix). No
  // separate fetch needed; if missing from the list (race), the form
  // renders empty and the user can still save.
  const drafts = useQuery({
    queryKey: ["drafts"],
    queryFn: listDrafts,
    staleTime: 0,
  });
  const draft = drafts.data?.find((d) => d.id === draftId);

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (draft) {
      setTitle(draft.title);
      setBody(draft.body ?? "");
      setDirty(false);
    }
  }, [draft]);

  const saveMut = useMutation({
    mutationFn: () => updateDraft(draftId, { title, body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["drafts"] });
      setDirty(false);
      onClose();
    },
  });

  const approveMut = useMutation({
    mutationFn: async () => {
      if (dirty) {
        await updateDraft(draftId, { title, body });
      }
      return approveDraft(draftId);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["drafts"] });
      void qc.invalidateQueries({ queryKey: QK.tree });
      onClose();
    },
  });

  const busy = saveMut.isPending || approveMut.isPending;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        className="sm:max-w-2xl"
        data-testid="draft-edit-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("drafts.editTitle")}</DialogTitle>
          <DialogDescription>{t("drafts.editSubtitle")}</DialogDescription>
        </DialogHeader>

        <label className="block text-xs">
          <div className="text-muted-foreground mb-1">
            {t("drafts.titleLabel")}
          </div>
          <input
            type="text"
            value={title}
            onChange={(e) => {
              setTitle(e.target.value);
              setDirty(true);
            }}
            data-testid="draft-edit-title"
            className="w-full rounded border px-2 py-1.5 text-sm"
            style={{
              borderColor: "var(--line)",
              background: "var(--bg-1)",
            }}
          />
        </label>

        <label className="block text-xs">
          <div className="text-muted-foreground mb-1">
            {t("drafts.bodyLabel")}
          </div>
          <textarea
            value={body}
            onChange={(e) => {
              setBody(e.target.value);
              setDirty(true);
            }}
            data-testid="draft-edit-body"
            rows={12}
            className="w-full rounded border px-2 py-1.5 text-xs font-mono"
            style={{
              borderColor: "var(--line)",
              background: "var(--bg-1)",
              resize: "vertical",
            }}
          />
        </label>

        <div className="flex flex-wrap justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded border px-3 py-1.5 text-xs"
            style={{ borderColor: "var(--line)" }}
            data-testid="draft-edit-cancel"
          >
            {t("drafts.editCancel")}
          </button>
          <button
            type="button"
            onClick={() => saveMut.mutate()}
            disabled={busy || !dirty}
            className="rounded border px-3 py-1.5 text-xs disabled:opacity-50"
            style={{ borderColor: "var(--line)" }}
            data-testid="draft-edit-save"
          >
            {saveMut.isPending && (
              <Loader2 className="inline size-3 animate-spin mr-1" />
            )}
            {t("drafts.editSave")}
          </button>
          <button
            type="button"
            onClick={() => approveMut.mutate()}
            disabled={busy || !title.trim()}
            className="rounded border px-3 py-1.5 text-xs"
            style={{
              background: "var(--accent-soft, rgba(91,122,156,0.18))",
              borderColor: "var(--accent, #5b7a9c)",
              color: "var(--accent-2, #34495e)",
            }}
            data-testid="draft-edit-save-approve"
          >
            {approveMut.isPending && (
              <Loader2 className="inline size-3 animate-spin mr-1" />
            )}
            {t("drafts.editSaveApprove")}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
