/**
 * Phase 2 E Slice S1 — per-note sync status badge (ADR-0027).
 *
 * Lives next to the note title (placed by NoteHeader). Polls the
 * server every 10s for the active note. Five terminal states map to
 * one icon + color + label combo each. The badge is small + always
 * visible — never silent.
 *
 * Design choices that may want user input:
 * - Position: NoteHeader near the title kicker. Could move to a
 *   header status bar later if cluttered.
 * - Color palette: green / blue / orange / red / gray. Defaults
 *   chosen for low-noise neutrality; revisit after dogfood.
 * - Refresh cadence: 10s. Tight enough to feel live, loose enough
 *   not to spam Drive's quota.
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Check,
  CloudOff,
  Loader2,
  PencilLine,
} from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import {
  getNoteSyncStatus,
  type NoteSyncState,
  type NoteSyncStatus,
} from "@/api/client";
import { QK } from "@/lib/queryClient";

const POLL_MS = 10_000;

interface BadgeStyle {
  Icon: typeof Check;
  color: string;
  labelKey: string;
}

const BADGE: Record<NoteSyncState, BadgeStyle> = {
  synced: {
    Icon: Check,
    color: "var(--ok-fg, #166534)",
    labelKey: "syncStatus.synced",
  },
  dirty: {
    Icon: PencilLine,
    color: "var(--ink-mute)",
    labelKey: "syncStatus.dirty",
  },
  conflict: {
    Icon: AlertTriangle,
    color: "var(--warn-fg, #9a3412)",
    labelKey: "syncStatus.conflict",
  },
  offline: {
    Icon: CloudOff,
    color: "var(--ink-mute)",
    labelKey: "syncStatus.offline",
  },
  unauthenticated: {
    Icon: CloudOff,
    color: "var(--ink-mute)",
    labelKey: "syncStatus.unauthenticated",
  },
};

export function SyncStatusBadge({
  noteId,
  isSaving = false,
  hasUnsavedEdits = false,
  onConflictClick,
}: {
  noteId: string | null;
  /** Frontend overlay state: a save mutation is in flight. */
  isSaving?: boolean;
  /** Frontend overlay state: editor has unsaved changes (autosave
   *  hasn't fired yet). Surfaces as 'editing' over the base state. */
  hasUnsavedEdits?: boolean;
  /** Slice S5 — when state=conflict, the badge becomes clickable
   *  and fires this callback. The parent owns the merge dialog so
   *  it can stay mounted across re-renders without flicker. */
  onConflictClick?: () => void;
}): ReactNode {
  const { t } = useTranslation();
  const q = useQuery<NoteSyncStatus>({
    queryKey: QK.noteSyncStatus(noteId ?? ""),
    queryFn: () => {
      if (!noteId) throw new Error("no noteId");
      return getNoteSyncStatus(noteId);
    },
    enabled: !!noteId,
    refetchInterval: POLL_MS,
    refetchOnWindowFocus: false,
  });
  if (!noteId) return null;
  // Hide the badge entirely when sync isn't set up at all — single-
  // device users don't need to see "unauthenticated" rubbed in their
  // face on every note.
  if (q.data?.state === "unauthenticated") return null;

  // Frontend-only overlay states sit on top of the server's base
  // state. Order matters: in-flight save > unsaved-edit > server state.
  let displayState: NoteSyncState | "syncing" | "editing";
  let labelKey: string;
  let iconNode: ReactNode;
  let color: string;

  if (isSaving) {
    displayState = "syncing";
    labelKey = "syncStatus.syncing";
    iconNode = <Loader2 className="size-3 animate-spin" />;
    color = "var(--ink-mute)";
  } else if (hasUnsavedEdits) {
    displayState = "editing";
    labelKey = "syncStatus.editing";
    iconNode = <PencilLine className="size-3" />;
    color = "var(--ink-mute)";
  } else if (q.data) {
    const style = BADGE[q.data.state];
    displayState = q.data.state;
    labelKey = style.labelKey;
    iconNode = <style.Icon className="size-3" />;
    color = style.color;
  } else {
    return null;  // first load; show nothing rather than flicker
  }

  const tooltip = q.data?.detail
    ? `${t(labelKey)} · ${q.data.detail}`
    : t(labelKey);

  const baseClass =
    "inline-flex items-center gap-1 font-mono text-[11px] uppercase tracking-wider";
  const isConflict = displayState === "conflict";

  if (isConflict && onConflictClick) {
    // Click opens the merge editor. We use a real <button> so the
    // affordance is keyboard-reachable and screen readers announce
    // it as actionable.
    return (
      <button
        type="button"
        data-testid="sync-status-badge"
        data-state={displayState}
        title={tooltip}
        onClick={onConflictClick}
        className={`${baseClass} cursor-pointer underline-offset-2 hover:underline focus-visible:underline focus-visible:outline-none`}
        style={{ color }}
      >
        {iconNode}
        <span>{t(labelKey)}</span>
      </button>
    );
  }

  return (
    <span
      data-testid="sync-status-badge"
      data-state={displayState}
      title={tooltip}
      className={baseClass}
      style={{ color }}
    >
      {iconNode}
      <span>{t(labelKey)}</span>
    </span>
  );
}
