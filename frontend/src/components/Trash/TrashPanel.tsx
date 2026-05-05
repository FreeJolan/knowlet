/**
 * Trash UI (Phase 1 A, Slice 2.4).
 *
 * Wraps shadcn Dialog. Lists every entry in `notes/.trash/` with a one-
 * click restore + a confirm-required permanent purge. Empty-trash button
 * is gated by an explicit confirm because it's destructive.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RotateCcw, Trash2 } from "lucide-react";

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
          <DialogTitle>Trash</DialogTitle>
        </DialogHeader>
        {trash.isLoading && (
          <div className="py-6 text-sm text-muted-foreground">Loading…</div>
        )}
        {trash.isError && (
          <div className="py-6 text-sm text-destructive">
            Failed to load ({String(trash.error)}).
          </div>
        )}
        {trash.data?.entries.length === 0 && (
          <div className="py-6 text-sm text-muted-foreground">
            Trash is empty.
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
                  Restore
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    if (window.confirm(`Permanently delete ${e.title}?`)) {
                      purgeM.mutate(e.name);
                    }
                  }}
                  disabled={purgeM.isPending}
                  className="text-destructive hover:bg-destructive/10"
                >
                  <Trash2 className="mr-1 size-3" />
                  Purge
                </Button>
              </li>
            ))}
          </ul>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button
            variant="destructive"
            disabled={(trash.data?.entries.length ?? 0) === 0 || emptyM.isPending}
            onClick={() => {
              if (window.confirm("Empty the entire trash? This is permanent.")) {
                emptyM.mutate();
              }
            }}
          >
            Empty trash
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
