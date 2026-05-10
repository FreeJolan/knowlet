/**
 * Phase 2 E Slice 5.D.2 — header sync badge (ADR-0027).
 *
 * Replaces the always-on top banner. Renders in the header next to
 * other utility icons. Shows a small `🔄 N` pill when N > 0; when
 * N = 0, the component returns null — single-device users without
 * conflicts never see it.
 *
 * Click → opens the Sync Conflicts Inbox dialog (passed in by the
 * parent via onOpen). Per ADR-0027 §UX, the inbox is the global
 * "where do I see ALL my pending conflicts" surface — distinct
 * from the per-note inline notice that appears next to the title
 * of a conflicted note (handled separately by NoteConflictNotice).
 *
 * Polling cadence is shared with NoteConflictNotice via the same
 * React Query key, so we don't double the API load.
 */

import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { listSyncNotifications } from "@/api/client";
import { Button } from "@/components/ui/button";
import { QK } from "@/lib/queryClient";

const POLL_MS = 10_000;

export function SyncBadge({ onOpen }: { onOpen: () => void }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: QK.syncNotifications,
    queryFn: listSyncNotifications,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: false,
  });
  const count = q.data?.notifications.length ?? 0;
  if (count === 0) return null;
  return (
    <Button
      variant="ghost"
      size="sm"
      data-testid="sync-badge"
      data-count={count}
      onClick={onOpen}
      title={t("sync.badgeTooltip", { count })}
      className="h-8 gap-1.5 px-2"
      style={{ color: "var(--warn-fg, #9a3412)" }}
    >
      <RefreshCw className="size-3.5" />
      <span className="font-mono text-[12px]">{count}</span>
    </Button>
  );
}
