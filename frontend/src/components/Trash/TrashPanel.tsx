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

import {
  emptyTrash,
  listTrash,
  purgeTrashed,
  restoreAllTrashed,
  restoreTrashed,
} from "@/api/client";
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
  const restoreAllM = useMutation({
    mutationFn: () => restoreAllTrashed(),
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
      {/* Trash is a *browse* surface — long folder paths + titles
       * shouldn't be truncated. shadcn's default is `sm:max-w-sm`
       * (384px); a non-prefixed `max-w-Xxl` doesn't override at the
       * sm+ breakpoint. Match the prefix to actually beat it.
       * 5xl ≈ 1024px gives plenty of room without dwarfing small
       * windows (shadcn's base `max-w-[calc(100%-2rem)]` still caps). */}
      <DialogContent className="sm:max-w-5xl">
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
                  <div className="truncate font-mono text-xs text-muted-foreground">
                    {/* Show the original folder if known — gives the user
                      * a hint about where this note will land on restore.
                      * The ULID + timestamp is debug-y; the folder is
                      * what they actually care about. */}
                    {e.original_folder ? `${e.original_folder}/` : ""}
                    {e.title}
                    <span className="opacity-60">
                      {" · "}
                      {e.trashed_at.slice(0, 16).replace("T", " ")}
                    </span>
                  </div>
                </div>
                {/* shrink-0 on every action button — without it, a long
                  * title pushes the button group off the row and the
                  * 还原 / 永久删除 labels overlap onto the ULID line
                  * (the dogfood report had a screenshot of this). */}
                <Button
                  variant="ghost"
                  size="sm"
                  className="shrink-0"
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
                  className="shrink-0 text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="mr-1 size-3" />
                  {t("trash.purge")}
                </Button>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter className="flex-wrap gap-2 sm:flex-nowrap">
          <Button
            variant="outline"
            className="mr-auto"
            disabled={(trash.data?.entries.length ?? 0) === 0 || restoreAllM.isPending}
            onClick={() => restoreAllM.mutate()}
          >
            <RotateCcw className="mr-1 size-3.5" />
            {t("trash.restoreAll")}
          </Button>
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
