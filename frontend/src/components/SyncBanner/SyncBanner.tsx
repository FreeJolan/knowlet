/**
 * Phase 2 E Slice 5.D — sync notifications banner (ADR-0027 §UX).
 *
 * Polls the backend every 10s for the list of remote-changed notes
 * detected by the SyncPoller. Renders a top-of-app banner only when
 * there's something to show — silent state when idle.
 *
 * Per ADR-0027 the user must be told "立即" when a remote write
 * lands during their edit session, not at save time. The poller
 * runs at ~30s; this hook adds another ~10s. Total worst case
 * notification latency: ~40s. Acceptable; can tighten later if
 * dogfood says it isn't.
 *
 * Slice 5.D scope: notification only. Acting on a notification
 * (apply remote / abort local / open conflict UI) is Slice 5.E+.
 * For now the banner offers a "dismiss" so the user can clear it
 * after they've handled the conflict via `knowlet sync resolve`.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import {
  dismissSyncNotification,
  listSyncNotifications,
  type SyncNotification,
} from "@/api/client";
import { QK } from "@/lib/queryClient";

const POLL_MS = 10_000;

export function SyncBanner({
  activeNoteId,
}: {
  /** Currently-open note id, used to make the banner more specific
   *  when the active note is one of the changed ones ("THIS note
   *  was modified on another device" vs. "X notes changed"). */
  activeNoteId: string | null;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: QK.syncNotifications,
    queryFn: listSyncNotifications,
    refetchInterval: POLL_MS,
    // No need to refetch on focus — the polling cadence is
    // deterministic and refetch-on-focus would burst on tab switch.
    refetchOnWindowFocus: false,
  });

  const dismiss = useMutation({
    mutationFn: (noteId: string) => dismissSyncNotification(noteId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.syncNotifications });
    },
  });

  const notifications = q.data?.notifications ?? [];
  if (notifications.length === 0) return null;

  // If the user is currently viewing one of the changed notes,
  // surface that one's banner specifically. Otherwise show a
  // collapsed summary that says "N notes changed".
  const forActive = activeNoteId
    ? notifications.find((n) => n.note_id === activeNoteId)
    : undefined;

  return (
    <div
      data-testid="sync-banner"
      className="flex shrink-0 items-center gap-3 px-4 py-2 text-[12px]"
      style={{
        background: "var(--warn-bg, #fff7ed)",
        color: "var(--warn-fg, #9a3412)",
        borderBottom: "1px solid var(--warn-border, #fed7aa)",
      }}
      role="status"
      aria-live="polite"
    >
      <AlertTriangle className="size-4 shrink-0" aria-hidden />
      <div className="flex-1 min-w-0">
        {forActive ? (
          <span>
            {forActive.removed
              ? t("sync.bannerRemoved")
              : t("sync.bannerCurrent")}
          </span>
        ) : (
          <span>
            {t("sync.bannerSummary", { count: notifications.length })}
            <ul className="mt-1 ml-4 list-disc">
              {notifications.slice(0, 5).map((n: SyncNotification) => (
                <li key={n.note_id}>
                  <span className="font-mono text-[11px]">
                    {n.drive_file_name || n.note_id}
                  </span>
                  {n.removed ? <span> · {t("sync.removed")}</span> : null}
                </li>
              ))}
              {notifications.length > 5 && (
                <li className="opacity-75">
                  {t("sync.bannerMore", {
                    count: notifications.length - 5,
                  })}
                </li>
              )}
            </ul>
          </span>
        )}
      </div>
      {forActive && (
        <button
          type="button"
          data-testid="sync-banner-dismiss"
          onClick={() => dismiss.mutate(forActive.note_id)}
          aria-label={t("sync.dismissAria")}
          className="flex size-6 items-center justify-center rounded-md transition-colors hover:bg-black/10"
        >
          <X className="size-3.5" />
        </button>
      )}
    </div>
  );
}
