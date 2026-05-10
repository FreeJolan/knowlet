/**
 * Phase 2 E Slice 5.D.1 — in-app conflict resolution (ADR-0027).
 *
 * Closes the "knowlet sync resolve via CLI" loop from 5.D: banner
 * tells you remote moved, this dialog lets you act on it without
 * leaving the app. Three strategies, same semantics as the CLI:
 *
 * - mine    → force-overwrite remote with local. Drive's native
 *             version history (≈30 days) keeps the prior remote
 *             recoverable, so this is non-destructive in practice.
 * - remote  → overwrite local with remote bytes. Local's prior
 *             content goes into .knowlet/backups/note/ via the
 *             existing 4.E hook, also reversible.
 * - both    → write the remote bytes as a sibling conflict copy
 *             (filename suffixed with the device label + ts);
 *             local stays dirty so the next push retries pushing it.
 *             The user merges manually later.
 *
 * UI deliberately keeps the diff view as plain side-by-side
 * textareas. Markdown notes don't need monaco-grade diff for the
 * "I wrote a few sentences on each device" case that's 95% of
 * conflicts. We can layer on react-diff-viewer if dogfood asks.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";

import {
  type ConflictStrategy,
  getSyncConflict,
  resolveSyncConflict,
  type SyncConflictPayload,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { QK } from "@/lib/queryClient";

export function ConflictResolveDialog({
  noteId,
  open,
  onClose,
}: {
  noteId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const conflictQuery = useQuery<SyncConflictPayload>({
    queryKey: ["sync-conflict", noteId],
    queryFn: () => {
      if (!noteId) throw new Error("no note id");
      return getSyncConflict(noteId);
    },
    enabled: open && !!noteId,
    // The conflict snapshot can shift if Drive changes again
    // between open and click; refetch each open to stay fresh.
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

  const resolveMutation = useMutation({
    mutationFn: ({ strategy }: { strategy: ConflictStrategy }) => {
      if (!noteId) throw new Error("no note id");
      return resolveSyncConflict(noteId, strategy);
    },
    onSuccess: () => {
      // Banner clears (server pruned its pending dict) + the note's
      // body may have changed (remote / both branches), so refresh
      // both caches.
      void qc.invalidateQueries({ queryKey: QK.syncNotifications });
      void qc.invalidateQueries({ queryKey: QK.note(noteId ?? "") });
      void qc.invalidateQueries({ queryKey: QK.tree });
      onClose();
    },
  });

  const onResolve = (strategy: ConflictStrategy) =>
    resolveMutation.mutate({ strategy });

  const data = conflictQuery.data;
  const errMsg =
    conflictQuery.error instanceof Error
      ? conflictQuery.error.message
      : conflictQuery.isError
        ? "failed to load conflict"
        : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent
        data-testid="conflict-resolve-dialog"
        // Conflict review needs room: notes can be paragraphs, not
        // one-liners. Override the shadcn default `sm:max-w-sm`
        // (256px-ish) and pin top so the dialog doesn't bounce as
        // textareas grow.
        className="top-[5vh] left-1/2 w-[92vw] sm:max-w-[92vw] -translate-x-1/2 translate-y-0 max-h-[90vh]"
      >
        <DialogHeader>
          <DialogTitle>{t("conflict.title")}</DialogTitle>
          <DialogDescription>{t("conflict.description")}</DialogDescription>
        </DialogHeader>

        {conflictQuery.isLoading && (
          <div className="py-8 text-center text-sm text-muted-foreground">
            {t("conflict.loading")}
          </div>
        )}

        {errMsg && (
          <div
            className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-900"
            data-testid="conflict-error"
          >
            {errMsg}
          </div>
        )}

        {data && !data.conflict && (
          <div
            className="rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-900"
            data-testid="conflict-already-resolved"
          >
            {t("conflict.alreadyResolved")}
          </div>
        )}

        {data && data.conflict && (
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground">
                {t("conflict.localLabel")}
              </div>
              <textarea
                data-testid="conflict-local-text"
                readOnly
                value={data.local_text}
                className="h-[62vh] w-full resize-none rounded-md border bg-muted/30 p-3 font-mono text-[12px] leading-relaxed"
              />
            </div>
            <div className="flex flex-col gap-1">
              <div className="text-[11px] font-mono uppercase tracking-wider text-muted-foreground">
                {t("conflict.remoteLabel")}
              </div>
              <textarea
                data-testid="conflict-remote-text"
                readOnly
                value={data.remote_text}
                className="h-[62vh] w-full resize-none rounded-md border bg-muted/30 p-3 font-mono text-[12px] leading-relaxed"
              />
            </div>
          </div>
        )}

        <DialogFooter className="flex-col gap-2 sm:flex-row sm:justify-between">
          <Button
            variant="ghost"
            onClick={onClose}
            disabled={resolveMutation.isPending}
            data-testid="conflict-cancel"
          >
            {t("conflict.cancel")}
          </Button>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              onClick={() => onResolve("both")}
              disabled={
                !data?.conflict || resolveMutation.isPending
              }
              data-testid="conflict-keep-both"
              title={t("conflict.bothHint")}
            >
              {t("conflict.keepBoth")}
            </Button>
            <Button
              variant="outline"
              onClick={() => onResolve("remote")}
              disabled={
                !data?.conflict || resolveMutation.isPending
              }
              data-testid="conflict-use-remote"
              title={t("conflict.remoteHint")}
            >
              {t("conflict.useRemote")}
            </Button>
            <Button
              onClick={() => onResolve("mine")}
              disabled={
                !data?.conflict || resolveMutation.isPending
              }
              data-testid="conflict-use-mine"
              title={t("conflict.mineHint")}
            >
              {t("conflict.useMine")}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
