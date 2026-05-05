/**
 * Trash UI (Phase 1 A, Slice 2.4).
 *
 * Wraps shadcn Dialog. Lists every entry in `notes/.trash/` with a one-
 * click restore + a confirm-required permanent purge. Empty-trash button
 * is gated by an explicit confirm because it's destructive.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import { emptyTrash, listTrash, purgeTrashed, restoreTrashed } from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { QK } from "@/lib/queryClient";

export function TrashPanel({
  open,
  onClose,
  onRestored,
}: {
  open: boolean;
  onClose: () => void;
  onRestored?: (noteId: string) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const trash = useQuery({
    queryKey: QK.trash,
    queryFn: listTrash,
    enabled: open,
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: QK.trash });
    qc.invalidateQueries({ queryKey: QK.tree });
  };

  const restoreM = useMutation({
    mutationFn: (name: string) => restoreTrashed(name),
    onSuccess: (note) => onRestored?.(note.id),
    onSettled: refresh,
  });
  const purgeM = useMutation({
    mutationFn: (name: string) => purgeTrashed(name),
    onSettled: refresh,
  });
  const emptyM = useMutation({
    mutationFn: () => emptyTrash(),
    onSettled: refresh,
  });

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("trash.title")}</DialogTitle>
        </DialogHeader>
        {trash.isLoading && (
          <div className="py-6 text-sm text-muted-foreground">{t("trash.loading")}</div>
        )}
        {trash.isError && (
          <div className="py-6 text-sm text-destructive">
            {t("trash.loadFailed", { error: String(trash.error) })}
          </div>
        )}
        {trash.data?.entries.length === 0 && (
          <div className="py-6 text-sm text-muted-foreground">
            {t("trash.empty")}
          </div>
        )}
        {(trash.data?.entries.length ?? 0) > 0 && (
          <ul
            className="max-h-[60vh] divide-y overflow-y-auto rounded border"
            style={{ borderColor: "var(--line-soft)" }}
          >
            {trash.data?.entries.map((e) => (
              <li
                key={e.name}
                className="flex items-center gap-3 px-3 py-2 hover:bg-secondary"
              >
                <div className="min-w-0 flex-1">
                  <div className="truncate font-medium">{e.title}</div>
                  <div className="font-mono text-xs text-muted-foreground">
                    {e.name} · {e.trashed_at.slice(0, 16).replace("T", " ")}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => restoreM.mutate(e.name)}
                  disabled={restoreM.isPending}
                >
                  <RotateCcw className="mr-1 size-3" />
                  {t("trash.restore")}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (window.confirm(t("trash.purgeConfirm", { title: e.title }))) {
                      purgeM.mutate(e.name);
                    }
                  }}
                  disabled={purgeM.isPending}
                  className="text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="mr-1 size-3" />
                  {t("trash.purge")}
                </Button>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("trash.close")}
          </Button>
          <Button
            variant="destructive"
            disabled={(trash.data?.entries.length ?? 0) === 0 || emptyM.isPending}
            onClick={() => {
              if (window.confirm(t("trash.emptyAllConfirm"))) {
                emptyM.mutate();
              }
            }}
          >
            {t("trash.emptyAll")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
