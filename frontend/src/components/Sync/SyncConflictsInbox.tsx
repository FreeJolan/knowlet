/**
 * Phase 2 E Slice 5.D.3.A — pending-conflicts inbox with multi-select
 * + bulk apply (ADR-0027).
 *
 * Discovery surface for every pending conflict. Solves three holes
 * the earlier (5.D / 5.D.2) inbox had:
 *
 * 1. "I have 30 conflicts; resolving each one in a separate dialog
 *    is unusable." → multi-select rows + a toolbar that applies a
 *    strategy across all selected ids in one round trip.
 * 2. "Dismiss = forever silenced" → dismiss is now a 24h snooze
 *    (the underlying endpoint stamps file_state.dismissed_until,
 *    state-reconciliation poller filters by it, conflict re-surfaces
 *    automatically after expiry). The button copy reflects this.
 * 3. "I want to permanently accept divergence without moving data"
 *    → new "Accept as in-sync" action advances last_known_etag to
 *    Drive's current revision; not a snooze, not a data move.
 *
 * The single-row resolution path (open ConflictResolveDialog) is
 * unchanged and reused for the "I want to actually look at this one"
 * cases. Bulk is the escape hatch for mass conflicts.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import {
  acceptCurrentAsSynced,
  type BulkResolveStrategy,
  bulkResolveSyncConflicts,
  dismissSyncNotification,
  listSyncNotifications,
  type SyncNotification,
} from "@/api/client";
import { ConflictResolveDialog } from "@/components/Sync/ConflictResolveDialog";
import { Button } from "@/components/ui/button";
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
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: QK.syncNotifications });

  const snoozeOne = useMutation({
    mutationFn: (noteId: string) => dismissSyncNotification(noteId),
    onSuccess: () => void invalidate(),
  });
  const acceptOne = useMutation({
    mutationFn: (noteId: string) => acceptCurrentAsSynced(noteId),
    onSuccess: () => void invalidate(),
  });
  const bulk = useMutation({
    mutationFn: ({
      ids,
      strategy,
    }: {
      ids: string[];
      strategy: BulkResolveStrategy;
    }) => bulkResolveSyncConflicts(ids, strategy),
    onSuccess: () => {
      void invalidate();
      setSelected({});
    },
  });

  const [resolveOpenFor, setResolveOpenFor] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const notifications = q.data?.notifications ?? [];
  const selectedIds = notifications
    .filter((n) => selected[n.note_id])
    .map((n) => n.note_id);

  const toggleAll = (checked: boolean) => {
    if (!checked) {
      setSelected({});
      return;
    }
    const next: Record<string, boolean> = {};
    for (const n of notifications) next[n.note_id] = true;
    setSelected(next);
  };

  const allSelected =
    notifications.length > 0 &&
    notifications.every((n) => selected[n.note_id]);

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
          className="max-w-3xl"
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
            <>
              {/* Bulk toolbar — one row of actions that apply to
                  every selected id in one round trip. Always
                  visible (even at 0 selected) so the affordances
                  are discoverable; buttons disable until something's
                  selected. */}
              <div
                data-testid="sync-inbox-toolbar"
                className="flex flex-wrap items-center gap-2 border rounded-md bg-muted/30 px-3 py-2"
              >
                <label className="flex items-center gap-2 text-[12px] cursor-pointer">
                  <input
                    type="checkbox"
                    data-testid="sync-inbox-select-all"
                    checked={allSelected}
                    onChange={(e) => toggleAll(e.target.checked)}
                  />
                  <span>
                    {selectedIds.length > 0
                      ? t("syncInbox.selectedCount", {
                          count: selectedIds.length,
                        })
                      : t("syncInbox.selectAll")}
                  </span>
                </label>
                <div className="ml-auto flex flex-wrap gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={selectedIds.length === 0 || bulk.isPending}
                    data-testid="sync-inbox-bulk-mine"
                    onClick={() =>
                      bulk.mutate({ ids: selectedIds, strategy: "mine" })
                    }
                    title={t("conflict.mineHint")}
                  >
                    {t("syncInbox.bulkMine")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={selectedIds.length === 0 || bulk.isPending}
                    data-testid="sync-inbox-bulk-remote"
                    onClick={() =>
                      bulk.mutate({
                        ids: selectedIds,
                        strategy: "remote",
                      })
                    }
                    title={t("conflict.remoteHint")}
                  >
                    {t("syncInbox.bulkRemote")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={selectedIds.length === 0 || bulk.isPending}
                    data-testid="sync-inbox-bulk-accept"
                    onClick={() =>
                      bulk.mutate({
                        ids: selectedIds,
                        strategy: "accept-current",
                      })
                    }
                    title={t("syncInbox.bulkAcceptHint")}
                  >
                    {t("syncInbox.bulkAccept")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={selectedIds.length === 0 || bulk.isPending}
                    data-testid="sync-inbox-bulk-snooze"
                    onClick={() =>
                      bulk.mutate({
                        ids: selectedIds,
                        strategy: "snooze",
                      })
                    }
                  >
                    {t("syncInbox.bulkSnooze")}
                  </Button>
                </div>
              </div>

              <ul className="divide-y border rounded-md max-h-[55vh] overflow-y-auto">
                {notifications.map((n: SyncNotification) => (
                  <li
                    key={n.note_id}
                    data-testid="sync-inbox-row"
                    data-note-id={n.note_id}
                    className="flex items-center gap-3 px-3 py-2 transition-colors hover:bg-muted/40"
                  >
                    <input
                      type="checkbox"
                      data-testid="sync-inbox-row-checkbox"
                      checked={!!selected[n.note_id]}
                      onChange={(e) =>
                        setSelected((prev) => ({
                          ...prev,
                          [n.note_id]: e.target.checked,
                        }))
                      }
                    />
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
                    <Button
                      size="sm"
                      variant="ghost"
                      data-testid="sync-inbox-row-accept"
                      onClick={() => acceptOne.mutate(n.note_id)}
                      disabled={acceptOne.isPending}
                      title={t("syncInbox.bulkAcceptHint")}
                    >
                      {t("syncInbox.rowAccept")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      data-testid="sync-inbox-row-snooze"
                      onClick={() => snoozeOne.mutate(n.note_id)}
                      disabled={snoozeOne.isPending}
                      title={t("syncInbox.snoozeHint")}
                    >
                      {t("syncInbox.rowSnooze")}
                    </Button>
                  </li>
                ))}
              </ul>
            </>
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
