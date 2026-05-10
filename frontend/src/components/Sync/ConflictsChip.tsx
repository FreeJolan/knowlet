/**
 * #107a — global "sync conflicts" chip + inline inbox.
 *
 * Mounted once at app-shell level (next to other top-bar status
 * affordances). Polls ``/api/sync/conflicts`` every 60s for the
 * cached preflight result. The first POST /preflight is fired
 * lazily on mount so a user landing on a fresh session gets a
 * scan within ~1s.
 *
 * Visibility rules:
 *   - hidden entirely when ``unauthenticated`` (Alice / new user)
 *   - hidden when the cached scan reports zero conflicts AND
 *     zero offline rows (clean vault — no chrome noise)
 *   - amber when there are real conflicts
 *   - muted gray when there are only "couldn't reach Drive" rows
 *     (transient — distinct from real conflicts so the user
 *     doesn't think they have work to do)
 *
 * Click → Popover with the inbox: each conflict row opens the
 * merge editor for that note. The merge editor lives in NoteView,
 * so we navigate to the note via TabStrip's open-note hook (the
 * NoteView's badge then auto-opens the dialog when the user clicks
 * "open merge editor" on the row, by setting the ``openMergeOnMount``
 * query-param sentinel — see NoteView's effect that reads it).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CloudOff, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getConflicts,
  getSyncMode,
  type PreflightConflict,
  type PreflightReport,
  runPreflight,
  type SyncModeResponse,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { QK } from "@/lib/queryClient";

const POLL_MS = 60_000;

export function ConflictsChip({
  onOpenNote,
}: {
  /** Called with a note id when the user clicks "open merge editor"
   *  for a row. The host is expected to (a) navigate to the note's
   *  view and (b) signal that the merge dialog should open on
   *  mount. */
  onOpenNote: (noteId: string) => void;
}): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);

  const conflicts = useQuery<PreflightReport>({
    queryKey: QK.syncConflicts,
    queryFn: getConflicts,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: false,
  });
  const mode = useQuery<SyncModeResponse>({
    queryKey: QK.syncMode,
    queryFn: getSyncMode,
    staleTime: 5 * 60_000,
  });

  // First-mount preflight: fire the scan once after we've seen the
  // initial cache GET come back. If the cache is empty (server has
  // never scanned) AND we're not already unauthenticated, kick a
  // scan so the chip lights up within a beat of app load.
  const refresh = useMutation({
    mutationFn: runPreflight,
    onSuccess: (report) => {
      qc.setQueryData(QK.syncConflicts, report);
    },
  });
  useEffect(() => {
    if (
      conflicts.data &&
      conflicts.data.ran_at === null &&
      !conflicts.data.unauthenticated &&
      !refresh.isPending
    ) {
      refresh.mutate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conflicts.data?.ran_at]);

  if (!conflicts.data) return null;
  if (conflicts.data.unauthenticated) return null;
  const conflictCount = conflicts.data.conflicts.length;
  const offlineCount = conflicts.data.offline.length;
  const effectiveMode = mode.data?.effective_mode ?? "auto";
  const isStrictBlocking = effectiveMode === "strict" && conflictCount > 0;

  if (conflictCount === 0 && offlineCount === 0) return null;

  const hasReal = conflictCount > 0;
  const Icon = hasReal ? AlertTriangle : CloudOff;
  const tone = hasReal
    ? "bg-amber-100 text-amber-900 ring-amber-300 dark:bg-amber-950/40 dark:text-amber-100"
    : "bg-muted text-muted-foreground ring-foreground/10";

  // Strict mode + at least one real conflict → render the blocking
  // modal instead of the Popover. The modal can't be dismissed
  // (showCloseButton={false}, no overlay-click escape) — once the
  // user resolves the last conflict the chip auto-hides because
  // ``conflictCount`` drops to zero on the next refetch.
  if (isStrictBlocking) {
    return (
      <BlockingConflictsModal
        report={conflicts.data}
        onOpenNote={onOpenNote}
        onRefresh={() => refresh.mutate()}
        refreshing={refresh.isPending}
      />
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="sync-conflicts-chip"
          data-count={conflictCount}
          className={[
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1",
            "hover:opacity-90 focus-visible:outline-none focus-visible:ring-2",
            tone,
          ].join(" ")}
        >
          <Icon className="size-3.5" />
          <span>
            {hasReal
              ? t("syncInbox.chipLabel", { count: conflictCount })
              : t("syncInbox.offline", { count: offlineCount })}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[420px] p-0"
        data-testid="sync-conflicts-inbox"
      >
        <InboxPanel
          report={conflicts.data}
          onOpenNote={(id) => {
            setOpen(false);
            onOpenNote(id);
          }}
          onRefresh={() => refresh.mutate()}
          refreshing={refresh.isPending}
        />
      </PopoverContent>
    </Popover>
  );
}


function InboxPanel({
  report,
  onOpenNote,
  onRefresh,
  refreshing,
}: {
  report: PreflightReport;
  onOpenNote: (noteId: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
}): React.ReactNode {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col">
      <div className="flex items-start justify-between gap-2 border-b px-3 py-2">
        <div className="min-w-0 flex-1">
          <div className="font-heading text-sm font-medium leading-none">
            {t("syncInbox.title")}
          </div>
          <div className="text-muted-foreground mt-1 text-xs">
            {t("syncInbox.subtitle")}
          </div>
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={onRefresh}
          disabled={refreshing}
          data-testid="sync-conflicts-refresh"
          aria-label={t("syncInbox.refresh")}
        >
          <RefreshCw
            className={`size-4 ${refreshing ? "animate-spin" : ""}`}
          />
        </Button>
      </div>

      {refreshing && report.conflicts.length === 0 && (
        <div className="text-muted-foreground px-3 py-4 text-sm">
          {t("syncInbox.scanning")}
        </div>
      )}

      {!refreshing &&
        report.conflicts.length === 0 &&
        report.offline.length === 0 && (
          <div className="text-muted-foreground px-3 py-6 text-center text-sm">
            {t("syncInbox.empty")}
          </div>
        )}

      {report.conflicts.length > 0 && (
        <ul
          data-testid="sync-conflicts-list"
          className="max-h-[60vh] overflow-y-auto"
        >
          {report.conflicts.map((c) => (
            <ConflictRow
              key={c.note_id}
              conflict={c}
              onOpenNote={onOpenNote}
            />
          ))}
        </ul>
      )}

      {report.offline.length > 0 && (
        <details className="border-t" data-testid="sync-conflicts-offline">
          <summary className="text-muted-foreground cursor-pointer px-3 py-2 text-xs">
            {t("syncInbox.offlineHeading")}{" "}
            {t("syncInbox.offline", { count: report.offline.length })}
          </summary>
          <ul className="px-3 pb-2">
            {report.offline.map((o) => (
              <li
                key={o.note_id}
                className="text-muted-foreground py-1 text-xs"
              >
                {o.note_title || t("syncInbox.untitledNote")}
                {o.detail && (
                  <span className="ml-2 opacity-70">— {o.detail}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}


function ConflictRow({
  conflict,
  onOpenNote,
}: {
  conflict: PreflightConflict;
  onOpenNote: (noteId: string) => void;
}): React.ReactNode {
  const { t } = useTranslation();
  const subtitle = formatRowSubtitle(conflict, t);
  return (
    <li>
      <button
        type="button"
        data-testid="sync-conflict-row"
        data-note-id={conflict.note_id}
        className="hover:bg-accent/30 flex w-full items-start gap-2 px-3 py-2 text-left"
        onClick={() => onOpenNote(conflict.note_id)}
      >
        <AlertTriangle className="text-warn-fg dark:text-warn-fg-dark mt-0.5 size-4 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium">
            {conflict.note_title || t("syncInbox.untitledNote")}
          </div>
          {subtitle && (
            <div className="text-muted-foreground mt-0.5 truncate text-xs">
              {subtitle}
            </div>
          )}
        </div>
      </button>
    </li>
  );
}


function formatRowSubtitle(
  c: PreflightConflict,
  t: (k: string, opts?: Record<string, unknown>) => string,
): string {
  const when = c.remote_modified_at
    ? formatRelative(c.remote_modified_at)
    : c.last_synced_at
      ? formatRelative(c.last_synced_at)
      : "";
  if (!when) return "";
  if (c.remote_modified_by) {
    return t("syncInbox.noteRowEditedByWho", {
      who: c.remote_modified_by,
      when,
    });
  }
  return t("syncInbox.noteRowEditedBy", { when });
}


function BlockingConflictsModal({
  report,
  onOpenNote,
  onRefresh,
  refreshing,
}: {
  report: PreflightReport;
  onOpenNote: (noteId: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
}): React.ReactNode {
  const { t } = useTranslation();
  const count = report.conflicts.length;
  // Always-open dialog with no close affordance: ``onOpenChange`` is
  // intentionally a no-op so users can't escape by ESC / overlay
  // click. The modal disappears only when ``conflictCount`` drops
  // to 0, at which point the parent ConflictsChip stops rendering it.
  return (
    <Dialog open onOpenChange={() => {}}>
      <DialogContent
        data-testid="strict-blocking-modal"
        showCloseButton={false}
        className="!flex flex-col top-[10vh] left-1/2 -translate-x-1/2 translate-y-0 w-[90vw] sm:max-w-lg max-h-[80vh] gap-3 overflow-hidden"
        onEscapeKeyDown={(e) => e.preventDefault()}
        onPointerDownOutside={(e) => e.preventDefault()}
      >
        <div className="flex shrink-0 items-start gap-3 border-b pb-3">
          <AlertTriangle className="text-warn-fg dark:text-warn-fg-dark mt-0.5 size-5 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="font-heading text-base font-medium leading-snug">
              {t("syncMode.blockingTitle")}
            </div>
            <div className="text-muted-foreground mt-1 text-xs">
              {t("syncMode.blockingSubtitle", {
                count,
                noun: t("syncMode.blockingNoun", { count }),
              })}
            </div>
            <div className="text-muted-foreground mt-1 text-xs">
              {t("syncMode.blockingHint")}
            </div>
          </div>
          <Button
            size="sm"
            variant="ghost"
            onClick={onRefresh}
            disabled={refreshing}
            aria-label={t("syncInbox.refresh")}
          >
            <RefreshCw
              className={`size-4 ${refreshing ? "animate-spin" : ""}`}
            />
          </Button>
        </div>
        <ul
          data-testid="strict-blocking-list"
          className="min-h-0 flex-1 overflow-y-auto"
        >
          {report.conflicts.map((c) => (
            <ConflictRow
              key={c.note_id}
              conflict={c}
              onOpenNote={onOpenNote}
            />
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}


function formatRelative(iso: string): string {
  try {
    const d = new Date(iso);
    const ms = Date.now() - d.getTime();
    const min = Math.floor(ms / 60000);
    if (min < 1) return "just now";
    if (min < 60) return `${min}m ago`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr}h ago`;
    const day = Math.floor(hr / 24);
    if (day < 7) return `${day}d ago`;
    return d.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}
