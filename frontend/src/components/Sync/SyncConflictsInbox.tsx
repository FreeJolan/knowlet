/**
 * Phase 2 E Slice 5.D.2 — pending-conflicts inbox (ADR-0027).
 *
 * Solves the "user has 10 conflicts but only learns about each one
 * when they happen to open that specific note" UX hole that the
 * banner-based design had: inbox is the **discovery** surface for
 * every pending conflict, sorted newest-first, click-through to
 * resolve.
 *
 * Reuses ConflictResolveDialog for the actual resolution; this
 * component just lists rows and drives the open/close state of
 * that dialog.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  dismissSyncNotification,
  listSyncNotifications,
  type SyncNotification,
} from "@/api/client";
import { ConflictResolveDialog } from "@/components/Sync/ConflictResolveDialog";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { QK } from "@/lib/queryClient";

export function SyncConflictsInbox({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: QK.syncNotifications,
    queryFn: listSyncNotifications,
    enabled: open,
    refetchOnWindowFocus: false,
  });
  const dismiss = useMutation({
    mutationFn: (noteId: string) => dismissSyncNotification(noteId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.syncNotifications });
    },
  });
  const [resolveOpenFor, setResolveOpenFor] = useState<string | null>(null);
  const notifications = q.data?.notifications ?? [];

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(o) => {
          if (!o) onClose();
        }}
      >
        <DialogContent
          data-testid="sync-conflicts-inbox"
          className="max-w-2xl"
        >
          <DialogHeader>
            <DialogTitle>{t("syncInbox.title")}</DialogTitle>
            <DialogDescription>
              {t("syncInbox.description")}
            </DialogDescription>
          </DialogHeader>
          {notifications.length === 0 ? (
            <div
              className="py-10 text-center text-sm text-muted-foreground"
              data-testid="sync-inbox-empty"
            >
              {t("syncInbox.empty")}
            </div>
          ) : (
            <ul className="divide-y border rounded-md max-h-[60vh] overflow-y-auto">
              {notifications.map((n: SyncNotification) => (
                <li
                  key={n.note_id}
                  data-testid="sync-inbox-row"
                  data-note-id={n.note_id}
                  className="flex items-center gap-3 px-3 py-2 transition-colors hover:bg-muted/40"
                >
                  <button
                    type="button"
                    onClick={() => setResolveOpenFor(n.note_id)}
                    data-testid="sync-inbox-row-resolve"
                    className="flex-1 min-w-0 text-left"
                  >
                    <div className="font-mono text-[12px] truncate">
                      {n.drive_file_name || n.note_id}
                    </div>
                    <div className="text-[11px] text-muted-foreground">
                      {n.removed
                        ? t("sync.removed")
                        : t("syncInbox.detectedAt", {
                            ts: n.detected_at,
                          })}
                    </div>
                  </button>
                  <button
                    type="button"
                    data-testid="sync-inbox-row-dismiss"
                    onClick={() => dismiss.mutate(n.note_id)}
                    aria-label={t("sync.dismissAria")}
                    className="flex size-6 items-center justify-center rounded-md transition-colors hover:bg-black/10"
                  >
                    <X className="size-3.5" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </DialogContent>
      </Dialog>
      <ConflictResolveDialog
        noteId={resolveOpenFor}
        open={resolveOpenFor !== null}
        onClose={() => setResolveOpenFor(null)}
      />
    </>
  );
}
