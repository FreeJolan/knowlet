/**
 * #107a + #113 + #114 — unified sync chip in the app header.
 *
 * Single chip surface covering both kinds of "sync needs your
 * attention" state:
 *
 * - **Conflicts** (real merge required): amber, click → inbox row
 *   per note → merge editor.
 * - **Unpushed** (notes created before Drive auth / outside knowlet):
 *   blue, click → "Push all" button in the inbox.
 * - **Offline** (preflight couldn't reach Drive for some rows):
 *   collapsible section, informational.
 *
 * Visibility rule: chip hidden iff no creds AND nothing in any
 * bucket. Strict mode's blocking modal triggers ONLY on conflicts;
 * unpushed notes don't block the app, they just nag via the chip.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpFromLine,
  CloudOff,
  RefreshCw,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getConflicts,
  getSyncMode,
  getUnpushedStatus,
  type PreflightConflict,
  type PreflightReport,
  pushAllUnpushed,
  runPreflight,
  type SyncModeResponse,
  type UnpushedStatus,
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

export function SyncChip({
  onOpenNote,
}: {
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
  const unpushed = useQuery<UnpushedStatus>({
    queryKey: QK.syncUnpushed,
    queryFn: getUnpushedStatus,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: false,
  });
  const mode = useQuery<SyncModeResponse>({
    queryKey: QK.syncMode,
    queryFn: getSyncMode,
    staleTime: 5 * 60_000,
  });

  const refresh = useMutation({
    mutationFn: runPreflight,
    onSuccess: (report) => {
      qc.setQueryData(QK.syncConflicts, report);
      void qc.invalidateQueries({ queryKey: QK.syncUnpushed });
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
  const unpushedCount = unpushed.data?.count ?? 0;
  const effectiveMode = mode.data?.effective_mode ?? "auto";

  if (conflictCount === 0 && offlineCount === 0 && unpushedCount === 0) {
    return null;
  }

  // Strict mode blocks ONLY on real conflicts. Unpushed notes are
  // chrome, not work — never blocking.
  const isStrictBlocking = effectiveMode === "strict" && conflictCount > 0;
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

  // Chip palette + label: conflicts dominate when present (amber);
  // unpushed-only is blue (action available, no urgency); offline-only
  // is muted (informational).
  const hasConflict = conflictCount > 0;
  const hasUnpushed = unpushedCount > 0;
  const Icon = hasConflict
    ? AlertTriangle
    : hasUnpushed
      ? ArrowUpFromLine
      : CloudOff;
  const tone = hasConflict
    ? "bg-amber-100 text-amber-900 ring-amber-300 dark:bg-amber-950/40 dark:text-amber-100"
    : hasUnpushed
      ? "bg-blue-100 text-blue-900 ring-blue-300 dark:bg-blue-950/40 dark:text-blue-100"
      : "bg-muted text-muted-foreground ring-foreground/10";
  const label =
    hasConflict && hasUnpushed
      ? t("syncInbox.chipBoth", {
          conflicts: conflictCount,
          unpushed: unpushedCount,
        })
      : hasConflict
        ? t("syncInbox.chipConflicts", { count: conflictCount })
        : hasUnpushed
          ? t("syncInbox.chipUnpushed", { count: unpushedCount })
          : t("syncInbox.offline", { count: offlineCount });

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          data-testid="sync-chip"
          data-conflicts={conflictCount}
          data-unpushed={unpushedCount}
          className={[
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1",
            "hover:opacity-90 focus-visible:outline-none focus-visible:ring-2",
            tone,
          ].join(" ")}
        >
          <Icon className="size-3.5" />
          <span>{label}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="end"
        className="w-[420px] p-0"
        data-testid="sync-inbox"
      >
        <InboxPanel
          report={conflicts.data}
          unpushedCount={unpushedCount}
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
  unpushedCount,
  onOpenNote,
  onRefresh,
  refreshing,
}: {
  report: PreflightReport;
  unpushedCount: number;
  onOpenNote: (noteId: string) => void;
  onRefresh: () => void;
  refreshing: boolean;
}): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const pushAll = useMutation({
    mutationFn: pushAllUnpushed,
    onSuccess: () => {
      // Drainer takes over from here. The count won't drop instantly
      // (push happens on the drainer's 5s tick) — invalidate so the
      // panel re-fetches and starts trending toward zero.
      void qc.invalidateQueries({ queryKey: QK.syncUnpushed });
    },
  });

  const hasConflicts = report.conflicts.length > 0;
  const hasOffline = report.offline.length > 0;
  const hasUnpushed = unpushedCount > 0;
  const isEmpty =
    !hasConflicts && !hasOffline && !hasUnpushed && !refreshing;

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
          data-testid="sync-inbox-refresh"
          aria-label={t("syncInbox.refresh")}
        >
          <RefreshCw
            className={`size-4 ${refreshing ? "animate-spin" : ""}`}
          />
        </Button>
      </div>

      {refreshing && !hasConflicts && !hasUnpushed && (
        <div className="text-muted-foreground px-3 py-4 text-sm">
          {t("syncInbox.scanning")}
        </div>
      )}

      {isEmpty && (
        <div className="text-muted-foreground px-3 py-6 text-center text-sm">
          {t("syncInbox.empty")}
        </div>
      )}

      {hasConflicts && (
        <section
          data-testid="sync-inbox-conflicts"
          className="border-b"
        >
          <header className="text-muted-foreground px-3 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wide">
            {t("syncInbox.conflictsHeading")}
          </header>
          <ul className="max-h-[40vh] overflow-y-auto">
            {report.conflicts.map((c) => (
              <ConflictRow
                key={c.note_id}
                conflict={c}
                onOpenNote={onOpenNote}
              />
            ))}
          </ul>
        </section>
      )}

      {hasUnpushed && (
        <section
          data-testid="sync-inbox-unpushed"
          className="border-b"
        >
          <header className="text-muted-foreground px-3 pt-2 pb-1 text-[10px] font-medium uppercase tracking-wide">
            {t("syncInbox.unpushedHeading")}
          </header>
          <div className="flex items-center justify-between gap-3 px-3 pb-3 pt-1">
            <div className="text-muted-foreground min-w-0 flex-1 text-xs">
              {t("syncInbox.unpushedSummary", { count: unpushedCount })}
            </div>
            <Button
              size="sm"
              data-testid="sync-inbox-push-all"
              onClick={() => pushAll.mutate()}
              disabled={pushAll.isPending}
            >
              {pushAll.isPending
                ? t("syncInbox.unpushedQueuing")
                : t("syncInbox.unpushedPushAll")}
            </Button>
          </div>
          {pushAll.isSuccess && pushAll.data && (
            <div className="text-muted-foreground px-3 pb-2 text-[10px]">
              {t("syncInbox.unpushedQueued", { count: pushAll.data.queued })}
            </div>
          )}
        </section>
      )}

      {hasOffline && (
        <details
          className="border-t"
          data-testid="sync-inbox-offline"
        >
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
