/**
 * DraftsFocusMode — Phase 3 Stage 3 §3.5
 *
 * Fullscreen Drafts (草稿) panel. ⌘I opens it; Esc closes.
 *
 * Per ADR-0009 amendment + ADR-0029 §4 原则 7, this is the "explicit-
 * defer" queue — items only land here when the user picks 暂存 in the
 * capture flow or chat URL-paste review. AI doesn't dump drafts here
 * silently.
 *
 * Anti-drift surface obligations (this component owns the UI side):
 *  - Soft-limit prompt when active_count > 20 (inline header)
 *  - Stale row muted at ≥7 days (age_days >= STALE_AGE_DAYS)
 *  - Warn-age inline strip at ≥30 days (one-line per row)
 *  - 90-day auto-archive happens server-side on every list fetch
 *
 * Empty state: a single line teaching the ⌘⇧V shortcut. New users
 * arrive here with zero drafts and need to know how to get one.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Trash2, X } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import {
  approveDraft,
  listDrafts,
  rejectDraft,
  type DraftSummary,
} from "@/api/client";
import { KindChip } from "@/components/KindChip";
import { QK } from "@/lib/queryClient";

interface Props {
  open: boolean;
  onClose: () => void;
  onOpenNote: (noteId: string) => void;
}

const SOFT_LIMIT = 20;

export function DraftsFocusMode({
  open,
  onClose,
  onOpenNote,
}: Props): React.ReactElement | null {
  const { t } = useTranslation();
  const qc = useQueryClient();

  // Esc closes.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Always refetch when the panel opens — user expects "what's
  // pending right now", not a snapshot from when they last looked.
  // Without refetchOnMount, a panel re-open within staleTime would
  // show a stale empty list even after the user just deferred
  // something via the CaptureBox.
  const drafts = useQuery({
    queryKey: ["drafts"],
    queryFn: listDrafts,
    enabled: open,
    refetchOnMount: "always",
    staleTime: 0,
  });

  const approveMut = useMutation({
    mutationFn: approveDraft,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["drafts"] });
      void qc.invalidateQueries({ queryKey: QK.tree });
    },
  });
  const rejectMut = useMutation({
    mutationFn: rejectDraft,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["drafts"] });
    },
  });

  if (!open) return null;

  const items = drafts.data ?? [];
  const showSoftLimit = items.length > SOFT_LIMIT;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{ background: "var(--bg, #f4f0e8)" }}
      data-testid="drafts-focus-mode"
    >
      <header
        className="flex items-center justify-between border-b px-6 py-3"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        <div className="flex items-baseline gap-3">
          <h2 className="font-serif text-xl font-semibold">
            {t("drafts.title")}
          </h2>
          <span className="text-[11px] text-muted-foreground">
            {items.length > 0
              ? t("drafts.count", { count: items.length })
              : ""}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("drafts.close")}
          className="rounded p-1 hover:bg-accent/30"
          data-testid="drafts-close"
        >
          <X className="size-4" />
        </button>
      </header>

      {showSoftLimit && (
        <div
          className="border-b px-6 py-2 text-[11px]"
          style={{
            borderColor: "var(--line)",
            background: "rgba(217,151,77,0.08)",
            color: "var(--ink-mute)",
          }}
          data-testid="drafts-soft-limit"
        >
          {t("drafts.softLimit", { count: items.length })}
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {drafts.isLoading && (
          <div className="p-6 text-sm text-muted-foreground">
            {t("drafts.loading")}
          </div>
        )}
        {drafts.data && items.length === 0 && (
          <div
            className="mx-auto mt-12 max-w-md rounded border p-6 text-center text-sm"
            style={{ borderColor: "var(--line)" }}
            data-testid="drafts-empty"
          >
            <div className="text-base font-serif mb-2">
              {t("drafts.emptyTitle")}
            </div>
            <div className="text-muted-foreground text-xs">
              {t("drafts.emptyHint")}
            </div>
          </div>
        )}
        <ul className="divide-y" style={{ borderColor: "var(--line)" }}>
          {items.map((d) => (
            <DraftRow
              key={d.id}
              draft={d}
              onOpen={() => onOpenNote(d.id)}
              onApprove={() => approveMut.mutate(d.id)}
              onReject={() => rejectMut.mutate(d.id)}
              isPending={
                approveMut.isPending || rejectMut.isPending
              }
              t={t}
            />
          ))}
        </ul>
      </div>
    </div>
  );
}

function DraftRow({
  draft,
  onOpen,
  onApprove,
  onReject,
  isPending,
  t,
}: {
  draft: DraftSummary;
  onOpen: () => void;
  onApprove: () => void;
  onReject: () => void;
  isPending: boolean;
  t: (key: string, vars?: Record<string, unknown>) => string;
}): React.ReactElement {
  const stale = !!draft.is_stale;
  const warnAge = !!draft.is_warn_age;
  return (
    <li
      className="px-6 py-3"
      style={{
        // Per ADR-0029 §4 原则 7: stale rows are muted. Not hidden,
        // not nagged — just visually de-emphasized so the eye drifts
        // to fresher items.
        opacity: stale ? 0.55 : 1,
      }}
      data-testid={`draft-row-${draft.id}`}
      data-stale={stale ? "true" : "false"}
    >
      <div className="flex items-start gap-3">
        <KindChip kind={draft.kind} variant="tag" />
        <button
          type="button"
          onClick={onOpen}
          className="flex-1 text-left text-sm hover:text-foreground"
          data-testid={`draft-title-${draft.id}`}
        >
          <div className="font-serif font-medium">{draft.title || t("drafts.untitled")}</div>
          {draft.source && (
            <div className="mt-0.5 text-[10.5px] text-muted-foreground truncate">
              {draft.source}
            </div>
          )}
        </button>
        <span className="text-[10.5px] text-muted-foreground font-mono whitespace-nowrap">
          {t("drafts.ageDays", { count: draft.age_days ?? 0 })}
        </span>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={onApprove}
            disabled={isPending}
            title={t("drafts.approve")}
            className="rounded p-1 hover:text-emerald-700"
            data-testid={`draft-approve-${draft.id}`}
          >
            <CheckCircle2 className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={onReject}
            disabled={isPending}
            title={t("drafts.reject")}
            className="rounded p-1 hover:text-rose-700"
            data-testid={`draft-reject-${draft.id}`}
          >
            <Trash2 className="size-3.5" />
          </button>
        </div>
      </div>
      {warnAge && (
        <div
          className="mt-1.5 rounded px-2 py-0.5 text-[10.5px]"
          style={{
            background: "rgba(217,151,77,0.12)",
            color: "var(--ink-mute)",
          }}
          data-testid={`draft-warn-age-${draft.id}`}
        >
          {t("drafts.warnAge", { days: draft.age_days ?? 30 })}
        </div>
      )}
    </li>
  );
}
