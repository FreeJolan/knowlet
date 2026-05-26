/**
 * DigestFocusMode — Stage C2.
 *
 * Read-only intake list for drafts produced by digest sources. C3 adds
 * decisions (skip / save reference / internalize); this view only makes
 * today's and this week's fetched items visible as cards.
 */

import { useQuery } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  listDigestDrafts,
  type DigestPeriod,
  type DraftSummary,
} from "@/api/client";

interface Props {
  open: boolean;
  onClose: () => void;
}

export function DigestFocusMode({
  open,
  onClose,
}: Props): React.ReactElement | null {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<DigestPeriod>("today");

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

  const drafts = useQuery({
    queryKey: ["digest-drafts", period],
    queryFn: () => listDigestDrafts(period),
    enabled: open,
    refetchOnMount: "always",
    staleTime: 0,
  });

  if (!open) return null;

  const items = drafts.data ?? [];

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{ background: "var(--bg, #f4f0e8)" }}
      data-testid="digest-focus-mode"
    >
      <header
        className="flex items-center justify-between border-b px-6 py-3"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        <div className="flex items-baseline gap-3">
          <h2 className="font-serif text-xl font-semibold">
            {t("digest.title")}
          </h2>
          <span className="text-[11px] text-muted-foreground">
            {items.length > 0
              ? t("digest.count", { count: items.length })
              : ""}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("digest.close")}
          className="rounded p-1 hover:bg-accent/30"
          data-testid="digest-close"
        >
          <X className="size-4" />
        </button>
      </header>

      <div
        className="flex items-center gap-2 border-b px-6 py-2"
        style={{ borderColor: "var(--line)" }}
      >
        <PeriodButton
          id="today"
          active={period === "today"}
          label={t("digest.today")}
          onClick={() => setPeriod("today")}
        />
        <PeriodButton
          id="week"
          active={period === "week"}
          label={t("digest.week")}
          onClick={() => setPeriod("week")}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
        {drafts.isLoading && (
          <div className="text-sm text-muted-foreground">
            {t("digest.loading")}
          </div>
        )}
        {drafts.data && items.length === 0 && (
          <div
            className="mx-auto mt-12 max-w-md rounded border p-6 text-center text-sm"
            style={{ borderColor: "var(--line)" }}
            data-testid="digest-empty"
          >
            <div className="font-serif text-base mb-2">
              {t("digest.emptyTitle")}
            </div>
            <div className="text-xs text-muted-foreground">
              {t("digest.emptyHint")}
            </div>
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map((draft) => (
            <DigestCard key={draft.id} draft={draft} />
          ))}
        </div>
      </div>
    </div>
  );
}

function PeriodButton({
  id,
  active,
  label,
  onClick,
}: {
  id: "today" | "week";
  active: boolean;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded border px-2.5 py-1 text-xs"
      style={{
        borderColor: active ? "var(--accent)" : "var(--line)",
        background: active ? "var(--accent-tint-2)" : "transparent",
        color: "var(--ink)",
      }}
      data-testid={`digest-period-${id}`}
      aria-pressed={active}
    >
      {label}
    </button>
  );
}

function DigestCard({ draft }: { draft: DraftSummary }) {
  const { t } = useTranslation();
  const preview = (draft.body ?? "").trim();
  return (
    <article
      className="min-h-[150px] rounded-md border p-4"
      style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      data-testid={`digest-card-${draft.id}`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="font-serif text-base font-medium leading-snug">
          {draft.title || t("digest.untitled")}
        </h3>
        <span className="font-mono text-[10px] text-muted-foreground">
          {t("digest.ageDays", { count: draft.age_days ?? 0 })}
        </span>
      </div>
      {draft.source && (
        <a
          href={draft.source}
          target="_blank"
          rel="noreferrer"
          className="mb-3 flex items-center gap-1 truncate text-[11px] text-muted-foreground hover:text-foreground"
        >
          <ExternalLink className="size-3" />
          {draft.source}
        </a>
      )}
      <p
        className="whitespace-pre-wrap text-sm leading-relaxed text-muted-foreground"
        style={{
          display: "-webkit-box",
          WebkitLineClamp: 8,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {preview || t("digest.bodyMissing")}
      </p>
    </article>
  );
}
