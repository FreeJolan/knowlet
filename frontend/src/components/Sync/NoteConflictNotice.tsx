/**
 * Phase 2 E Slice 5.D.2 — per-note inline conflict notice (ADR-0027).
 *
 * Replaces the global banner's "this active note has a conflict"
 * branch. Lives next to NoteHeader so its scope is unambiguous: it's
 * about THIS note. Clicking [Review] opens the resolution dialog
 * scoped to this note.
 *
 * Returns null when there's no conflict for the active note —
 * doesn't take vertical real estate when it's not load-bearing.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { listSyncNotifications } from "@/api/client";
import { ConflictResolveDialog } from "@/components/Sync/ConflictResolveDialog";
import { Button } from "@/components/ui/button";
import { QK } from "@/lib/queryClient";

const POLL_MS = 10_000;

export function NoteConflictNotice({ noteId }: { noteId: string | null }) {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: QK.syncNotifications,
    queryFn: listSyncNotifications,
    // We share the queryKey with SyncBadge so React Query dedupes
    // the polling — there's only one request every POLL_MS no matter
    // how many subscribers are mounted.
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: false,
  });
  const [resolveOpen, setResolveOpen] = useState(false);
  if (!noteId) return null;
  const found = q.data?.notifications.find((n) => n.note_id === noteId);
  if (!found) return null;
  return (
    <>
      <div
        data-testid="note-conflict-notice"
        data-note-id={noteId}
        className="flex items-center gap-2 px-4 py-2 text-[12px]"
        style={{
          background: "var(--warn-bg, #fff7ed)",
          color: "var(--warn-fg, #9a3412)",
          borderTop: "1px solid var(--warn-border, #fed7aa)",
          borderBottom: "1px solid var(--warn-border, #fed7aa)",
        }}
      >
        <AlertTriangle className="size-4 shrink-0" aria-hidden />
        <span className="flex-1 min-w-0 truncate">
          {found.removed
            ? t("sync.bannerRemoved")
            : t("sync.bannerCurrent")}
        </span>
        <Button
          size="sm"
          variant="outline"
          data-testid="note-conflict-resolve"
          onClick={() => setResolveOpen(true)}
          className="h-7"
        >
          {found.removed
            ? t("sync.bannerReviewRemoved")
            : t("sync.bannerResolve")}
        </Button>
      </div>
      <ConflictResolveDialog
        noteId={resolveOpen ? noteId : null}
        open={resolveOpen}
        onClose={() => setResolveOpen(false)}
      />
    </>
  );
}
