/**
 * DigestFocusMode — Stage C v2 C6.
 *
 * Raw Info inbox. Items are read-only here; review conversation and draft
 * settlement return in the next slice.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  Clock,
  ExternalLink,
  RefreshCw,
  Rss,
  Send,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  createRawInfoDraft,
  getDigestStatus,
  listRawInfoItems,
  pullDigestSources,
  updateDraft,
  type DigestStatus,
  type RawInfoDraftResult,
  type RawInfoSummary,
} from "@/api/client";
import { ChatTranscript, chatHistoryForRequest } from "@/components/Discuss";

import { useRawInfoChat } from "./useRawInfoChat";

interface Props {
  open: boolean;
  onClose: () => void;
  onOpenNote?: (noteId: string, opts?: { discuss?: boolean }) => void;
}

type GroupMode = "time" | "source";

interface DigestGroup {
  id: string;
  label: string;
  items: RawInfoSummary[];
}

export function DigestFocusMode({
  open,
  onClose,
}: Props): React.ReactElement | null {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [groupMode, setGroupMode] = useState<GroupMode>("time");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reviewId, setReviewId] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setSelectedId(null);
      setReviewId(null);
      setGroupMode("time");
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const rawInfo = useQuery({
    queryKey: ["digest-items"],
    queryFn: listRawInfoItems,
    enabled: open,
    refetchOnMount: "always",
    staleTime: 0,
  });

  const status = useQuery({
    queryKey: ["digest-status"],
    queryFn: getDigestStatus,
    enabled: open,
    refetchInterval: open ? 5000 : false,
  });

  const pullMut = useMutation({
    mutationFn: pullDigestSources,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["digest-items"] });
      void qc.invalidateQueries({ queryKey: ["digest-status"] });
    },
  });

  const items = useMemo(
    () => sortRawInfo(rawInfo.data ?? []),
    [rawInfo.data],
  );
  const selected = useMemo(
    () => items.find((item) => item.id === selectedId) ?? null,
    [items, selectedId],
  );
  const groups = useMemo(
    () => groupRawInfo(items, groupMode, t),
    [items, groupMode, t],
  );

  useEffect(() => {
    if (!open || !rawInfo.data) return;
    if (items.length === 0) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !items.some((item) => item.id === selectedId)) {
      const first = items[0];
      if (first) setSelectedId(first.id);
    }
  }, [items, open, rawInfo.data, selectedId]);

  if (!open) return null;

  const pendingCount =
    status.data?.pending_count ?? items.filter((item) => isPending(item)).length;
  const paused =
    pendingCount > 200 ||
    status.data?.status === "paused" ||
    (status.data?.sources ?? []).some((source) => source.pull_status === "paused");

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{ background: "var(--bg, #f4f0e8)" }}
      data-testid="digest-focus-mode"
    >
      <header
        className="flex items-center justify-between gap-4 border-b px-6 py-3"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        <div className="min-w-0">
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
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <PullStatusBadge
            status={status.data}
            pending={pullMut.isPending || status.isFetching}
            fallbackPaused={paused}
          />
          <button
            type="button"
            onClick={() => pullMut.mutate()}
            disabled={pullMut.isPending}
            className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs disabled:opacity-50"
            style={{ borderColor: "var(--line)", color: "var(--ink)" }}
            data-testid="digest-pull-now"
            title={t("digest.pullNow")}
          >
            <RefreshCw className={pullMut.isPending ? "size-3 animate-spin" : "size-3"} />
            {t("digest.pullNow")}
          </button>
          <button
            type="button"
            onClick={() => setReviewId(selected?.id ?? items[0]?.id ?? null)}
            disabled={items.length === 0}
            className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs disabled:opacity-50"
            style={{ borderColor: "var(--accent)", color: "var(--ink)" }}
            data-testid="digest-start-review"
          >
            {t("digest.startReview")}
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label={t("digest.close")}
            className="rounded p-1 hover:bg-accent/30"
            data-testid="digest-close"
          >
            <X className="size-4" />
          </button>
        </div>
      </header>

      <div
        className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-2"
        style={{ borderColor: "var(--line)" }}
      >
        <div className="flex items-center gap-2">
          <GroupButton
            mode="time"
            active={groupMode === "time"}
            label={t("digest.groupTime")}
            onClick={() => setGroupMode("time")}
          />
          <GroupButton
            mode="source"
            active={groupMode === "source"}
            label={t("digest.groupSource")}
            onClick={() => setGroupMode("source")}
          />
        </div>
        {paused && (
          <div
            className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs"
            style={{
              borderColor: "var(--warning, #b7791f)",
              background: "var(--bg-1)",
              color: "var(--ink)",
            }}
            data-testid="digest-pause-banner"
          >
            <AlertTriangle className="size-3.5" />
            {t("digest.pauseBanner")}
          </div>
        )}
      </div>

      <div className="grid min-h-0 flex-1 gap-4 px-6 py-4 lg:grid-cols-[minmax(0,1fr)_430px]">
        <main className="min-h-0 overflow-y-auto">
          {rawInfo.isLoading && (
            <div className="text-sm text-muted-foreground">
              {t("digest.loading")}
            </div>
          )}
          {rawInfo.data && items.length === 0 && (
            <div
              className="mx-auto mt-12 max-w-md rounded border p-6 text-center text-sm"
              style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
              data-testid="digest-empty"
            >
              <div className="mb-2 font-serif text-base">
                {t("digest.emptyTitle")}
              </div>
              <div className="text-xs text-muted-foreground">
                {t("digest.emptyHint")}
              </div>
            </div>
          )}

          <div className="space-y-5">
            {groups.map((group) => (
              <section
                key={group.id}
                data-testid={`digest-group-${groupMode}-${slugId(group.id)}`}
              >
                <div className="mb-2 flex items-center justify-between">
                  <h3 className="font-mono text-[11px] uppercase text-muted-foreground">
                    {group.label}
                  </h3>
                  <span className="text-[11px] text-muted-foreground">
                    {t("digest.count", { count: group.items.length })}
                  </span>
                </div>
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {group.items.map((item) => (
                    <DigestCard
                      key={item.id}
                      item={item}
                      selected={item.id === selectedId}
                      onSelect={() => setSelectedId(item.id)}
                      onReview={() => setReviewId(item.id)}
                    />
                  ))}
                </div>
              </section>
            ))}
          </div>
        </main>

        <aside className="min-h-0">
          {selected ? (
            <DigestDetail item={selected} />
          ) : (
            <div
              className="rounded-md border p-4 text-sm text-muted-foreground"
              style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
            >
              {t("digest.selectHint")}
            </div>
          )}
        </aside>
      </div>
      {reviewId && (
        <ReviewOverlay
          items={items}
          activeId={reviewId}
          onChangeItem={setReviewId}
          onClose={() => setReviewId(null)}
        />
      )}
    </div>
  );
}

function PullStatusBadge({
  status,
  pending,
  fallbackPaused,
}: {
  status?: DigestStatus;
  pending: boolean;
  fallbackPaused: boolean;
}) {
  const { t } = useTranslation();
  const state = pending ? "running" : fallbackPaused ? "paused" : status?.status ?? "idle";
  const label =
    state === "running"
      ? t("digest.pullRunning")
      : state === "paused"
        ? t("digest.pullPaused")
        : state === "error"
          ? t("digest.pullError")
          : state === "ok"
            ? t("digest.pullOk")
            : t("digest.pullIdle");
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs"
      style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      data-testid="digest-pull-status"
    >
      <Clock className="size-3.5" />
      {label}
    </span>
  );
}

function GroupButton({
  mode,
  active,
  label,
  onClick,
}: {
  mode: GroupMode;
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
      data-testid={`digest-group-mode-${mode}`}
      aria-pressed={active}
    >
      {label}
    </button>
  );
}

function DigestCard({
  item,
  selected,
  onSelect,
  onReview,
}: {
  item: RawInfoSummary;
  selected: boolean;
  onSelect: () => void;
  onReview: () => void;
}) {
  const { t } = useTranslation();
  return (
    <article
      className="min-h-[172px] cursor-pointer rounded-md border p-4 outline-none"
      style={{
        borderColor: selected ? "var(--accent)" : "var(--line)",
        background: selected ? "var(--accent-tint-2)" : "var(--bg-1)",
      }}
      data-testid={`digest-card-${item.id}`}
      data-selected={selected ? "true" : "false"}
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <h3 className="font-serif text-base font-medium leading-snug">
          {item.title || t("digest.untitled")}
        </h3>
        <SourceKind kind={item.source_kind} />
      </div>
      <div className="mb-2 flex items-center gap-2 text-[11px] text-muted-foreground">
        <span className="truncate">{item.source_name}</span>
        <span>{statusLabel(item.status)}</span>
      </div>
      <a
        href={item.url}
        target="_blank"
        rel="noreferrer"
        className="mb-3 flex items-center gap-1 truncate text-[11px] text-muted-foreground hover:text-foreground"
        onClick={(e) => e.stopPropagation()}
      >
        <ExternalLink className="size-3" />
        {item.url}
      </a>
      <p
        className="text-sm leading-relaxed text-muted-foreground"
        style={{
          display: "-webkit-box",
          WebkitLineClamp: 5,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
        }}
      >
        {item.summary || t("digest.bodyMissing")}
      </p>
      <div className="mt-3 text-[11px] text-muted-foreground">
        {formatDate(item.fetched_at)}
      </div>
      <button
        type="button"
        className="mt-3 rounded border px-2 py-1 text-[11px]"
        style={{ borderColor: "var(--line)", color: "var(--ink)" }}
        data-testid={`digest-card-review-${item.id}`}
        onClick={(e) => {
          e.stopPropagation();
          onReview();
        }}
      >
        {t("digest.startHere")}
      </button>
    </article>
  );
}

function DigestDetail({ item }: { item: RawInfoSummary }) {
  const { t } = useTranslation();
  return (
    <div
      className="flex h-full min-h-[520px] flex-col overflow-hidden rounded-md border"
      style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      data-testid="digest-detail"
    >
      <div className="border-b p-4" style={{ borderColor: "var(--line)" }}>
        <div className="mb-1 text-[10px] font-mono uppercase text-muted-foreground">
          {t("digest.detail")}
        </div>
        <h3 className="font-serif text-lg font-medium">
          {item.title || t("digest.untitled")}
        </h3>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
          <SourceKind kind={item.source_kind} />
          <span>{item.source_name}</span>
          <span>{statusLabel(item.status)}</span>
          <span>{t("digest.confidenceLabel", { confidence: item.confidence })}</span>
        </div>
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 flex items-center gap-1 truncate text-[11px] text-muted-foreground hover:text-foreground"
        >
          <ExternalLink className="size-3" />
          {item.url}
        </a>
      </div>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 text-sm leading-relaxed">
        <DetailBlock label={t("digest.summary")} value={item.summary} />
        {item.key_points.length > 0 && (
          <section>
            <h4 className="mb-1 text-[11px] font-mono uppercase text-muted-foreground">
              {t("digest.keyPoints")}
            </h4>
            <ul className="list-disc space-y-1 pl-5">
              {item.key_points.map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </section>
        )}
        <DetailBlock label={t("digest.whyItMatters")} value={item.why_it_matters} />
        {item.suggested_tags.length > 0 && (
          <section>
            <h4 className="mb-1 text-[11px] font-mono uppercase text-muted-foreground">
              {t("digest.tags")}
            </h4>
            <div className="flex flex-wrap gap-1.5">
              {item.suggested_tags.map((tag) => (
                <span
                  key={tag}
                  className="rounded border px-1.5 py-0.5 text-[11px]"
                  style={{ borderColor: "var(--line)" }}
                >
                  {tag}
                </span>
              ))}
            </div>
          </section>
        )}
        <DetailBlock label={t("digest.excerpt")} value={item.content_excerpt} />
        <div className="text-[11px] text-muted-foreground">
          {t("digest.fetchedAt", { date: formatDate(item.fetched_at) })}
        </div>
      </div>
    </div>
  );
}

function DetailBlock({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <section>
      <h4 className="mb-1 text-[11px] font-mono uppercase text-muted-foreground">
        {label}
      </h4>
      <p className="whitespace-pre-wrap">{value}</p>
    </section>
  );
}

function SourceKind({ kind }: { kind: RawInfoSummary["source_kind"] }) {
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[10px]"
      style={{ background: "var(--accent-tint-2)" }}
    >
      {kind === "rss" ? <Rss className="size-3" /> : <Sparkles className="size-3" />}
      {kind}
    </span>
  );
}

function ReviewOverlay({
  items,
  activeId,
  onChangeItem,
  onClose,
}: {
  items: RawInfoSummary[];
  activeId: string;
  onChangeItem: (id: string) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const index = Math.max(
    0,
    items.findIndex((item) => item.id === activeId),
  );
  const item = items[index] ?? null;
  const previous = index > 0 ? items[index - 1] : null;
  const next = index >= 0 && index < items.length - 1 ? items[index + 1] : null;
  const { messages, status, error, send, stop } = useRawInfoChat(item?.id ?? null);
  const [input, setInput] = useState("");
  const [draftResult, setDraftResult] = useState<RawInfoDraftResult | null>(null);
  const [draftEdit, setDraftEdit] = useState({
    title: "",
    tags: "",
    kind: "reference" as "knowledge" | "reference",
    folder: "",
  });
  const [draftError, setDraftError] = useState<string | null>(null);

  const draftMut = useMutation({
    mutationFn: async () => {
      if (!item) throw new Error("No Raw Info item selected");
      return createRawInfoDraft(item.id, {
        history: chatHistoryForRequest(messages),
      });
    },
    onSuccess: (result) => {
      setDraftResult(result);
      setDraftEdit({
        title: result.draft.title,
        tags: result.draft.tags.join(", "),
        kind: result.draft.kind,
        folder: result.draft.folder ?? "",
      });
      setDraftError(null);
      void qc.invalidateQueries({ queryKey: ["digest-items"] });
      void qc.invalidateQueries({ queryKey: ["digest-status"] });
    },
    onError: (err) => {
      setDraftError(err instanceof Error ? err.message : t("digest.draftFailed"));
    },
  });

  const saveDraftMut = useMutation({
    mutationFn: async () => {
      if (!draftResult) throw new Error("No draft to save");
      return updateDraft(draftResult.draft.id, {
        title: draftEdit.title,
        tags: draftEdit.tags
          .split(",")
          .map((tag) => tag.trim().replace(/^#/, ""))
          .filter(Boolean),
        kind: draftEdit.kind,
        folder: draftEdit.folder,
      });
    },
    onSuccess: (draft) => {
      setDraftResult((current) => (current ? { ...current, draft } : current));
      setDraftEdit({
        title: draft.title,
        tags: draft.tags.join(", "),
        kind: draft.kind,
        folder: draft.folder ?? "",
      });
      setDraftError(null);
    },
    onError: (err) => {
      setDraftError(err instanceof Error ? err.message : t("digest.draftSaveFailed"));
    },
  });

  useEffect(() => {
    setInput("");
    setDraftResult(null);
    setDraftEdit({ title: "", tags: "", kind: "reference", folder: "" });
    setDraftError(null);
  }, [item?.id]);

  if (!item) return null;

  const draftChanged =
    draftResult !== null &&
    (draftEdit.title.trim() !== draftResult.draft.title ||
      draftEdit.tags.trim() !== draftResult.draft.tags.join(", ") ||
      draftEdit.kind !== draftResult.draft.kind ||
      draftEdit.folder.trim() !== (draftResult.draft.folder ?? ""));

  const submit = () => {
    if (input.trim() && status !== "streaming") {
      send(input);
      setInput("");
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-6"
      style={{ background: "rgba(22, 18, 12, 0.28)" }}
      data-testid="digest-review-backdrop"
    >
      <div
        className="grid h-full w-full max-w-[1320px] overflow-hidden rounded-md border shadow-2xl lg:grid-cols-[minmax(360px,0.9fr)_minmax(480px,1.1fr)]"
        style={{ borderColor: "var(--line)", background: "var(--bg)" }}
        data-testid="digest-review-overlay"
      >
        <section
          className="min-h-0 overflow-y-auto border-r"
          style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
        >
          <div className="flex items-center justify-between border-b p-4" style={{ borderColor: "var(--line)" }}>
            <div className="text-[11px] font-mono uppercase text-muted-foreground">
              {t("digest.reviewPosition", { current: index + 1, total: items.length })}
            </div>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 hover:bg-accent/30"
              data-testid="digest-review-close"
              aria-label={t("digest.close")}
            >
              <X className="size-4" />
            </button>
          </div>
          <div className="space-y-4 p-4">
            <div>
              <h3
                className="font-serif text-xl font-medium"
                data-testid="digest-review-current-title"
              >
                {item.title || t("digest.untitled")}
              </h3>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                <SourceKind kind={item.source_kind} />
                <span>{item.source_name}</span>
                <span>{statusLabel(item.status)}</span>
              </div>
              <a
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 flex items-center gap-1 truncate text-[11px] text-muted-foreground hover:text-foreground"
              >
                <ExternalLink className="size-3" />
                {item.url}
              </a>
            </div>
            <DetailBlock label={t("digest.summary")} value={item.summary} />
            {item.key_points.length > 0 && (
              <section>
                <h4 className="mb-1 text-[11px] font-mono uppercase text-muted-foreground">
                  {t("digest.keyPoints")}
                </h4>
                <ul className="list-disc space-y-1 pl-5 text-sm">
                  {item.key_points.map((point) => (
                    <li key={point}>{point}</li>
                  ))}
                </ul>
              </section>
            )}
            <DetailBlock label={t("digest.whyItMatters")} value={item.why_it_matters} />
            <DetailBlock label={t("digest.excerpt")} value={item.content_excerpt} />
            <button
              type="button"
              disabled={draftMut.isPending || status === "streaming"}
              onClick={() => draftMut.mutate()}
              className="inline-flex items-center gap-1.5 rounded border px-3 py-2 text-xs disabled:opacity-50"
              style={{ borderColor: "var(--accent)", color: "var(--ink)" }}
              data-testid="digest-settle-draft"
            >
              <Sparkles className="size-3.5" />
              {draftMut.isPending ? t("digest.creatingDraft") : t("digest.settleDraft")}
            </button>
            {draftResult && (
              <div
                className="rounded-md border p-3 text-sm"
                style={{ borderColor: "var(--line)", background: "var(--bg)" }}
                data-testid="digest-draft-result"
              >
                <div className="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
                  <CheckCircle2 className="size-3.5" />
                  {t("digest.draftCreated")}
                </div>
                <div className="space-y-2" data-testid="digest-draft-metadata">
                  <label className="block text-[11px] text-muted-foreground">
                    {t("digest.draftTitle")}
                    <input
                      data-testid="digest-draft-title-input"
                      value={draftEdit.title}
                      onChange={(e) =>
                        setDraftEdit((current) => ({ ...current, title: e.target.value }))
                      }
                      className="mt-1 w-full rounded border bg-transparent px-2 py-1 text-sm text-foreground"
                      style={{ borderColor: "var(--line)" }}
                    />
                  </label>
                  <label className="block text-[11px] text-muted-foreground">
                    {t("digest.draftTags")}
                    <input
                      data-testid="digest-draft-tags-input"
                      value={draftEdit.tags}
                      onChange={(e) =>
                        setDraftEdit((current) => ({ ...current, tags: e.target.value }))
                      }
                      className="mt-1 w-full rounded border bg-transparent px-2 py-1 text-sm text-foreground"
                      style={{ borderColor: "var(--line)" }}
                    />
                  </label>
                  <div className="grid grid-cols-2 gap-2">
                    <label className="block text-[11px] text-muted-foreground">
                      {t("digest.draftKind")}
                      <select
                        data-testid="digest-draft-kind-select"
                        value={draftEdit.kind}
                        onChange={(e) =>
                          setDraftEdit((current) => ({
                            ...current,
                            kind: e.target.value as "knowledge" | "reference",
                          }))
                        }
                        className="mt-1 w-full rounded border bg-transparent px-2 py-1 text-sm text-foreground"
                        style={{ borderColor: "var(--line)" }}
                      >
                        <option value="knowledge">knowledge</option>
                        <option value="reference">reference</option>
                      </select>
                    </label>
                    <label className="block text-[11px] text-muted-foreground">
                      {t("digest.draftFolder")}
                      <input
                        data-testid="digest-draft-folder-input"
                        value={draftEdit.folder}
                        onChange={(e) =>
                          setDraftEdit((current) => ({ ...current, folder: e.target.value }))
                        }
                        placeholder={t("digest.rootFolder")}
                        className="mt-1 w-full rounded border bg-transparent px-2 py-1 text-sm text-foreground"
                        style={{ borderColor: "var(--line)" }}
                      />
                    </label>
                  </div>
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  {draftResult.draft.kind} · {draftResult.draft.folder || t("digest.rootFolder")}
                </div>
                {draftResult.rationale && (
                  <div className="mt-2 text-xs text-muted-foreground">
                    {draftResult.rationale}
                  </div>
                )}
                <button
                  type="button"
                  disabled={!draftChanged || saveDraftMut.isPending}
                  onClick={() => saveDraftMut.mutate()}
                  className="mt-3 rounded border px-2 py-1 text-xs disabled:opacity-50"
                  style={{ borderColor: "var(--line)" }}
                  data-testid="digest-draft-save"
                >
                  {saveDraftMut.isPending ? t("digest.savingDraft") : t("digest.saveDraft")}
                </button>
              </div>
            )}
            {draftError && (
              <div className="text-xs" style={{ color: "var(--danger, #c0392b)" }}>
                {draftError}
              </div>
            )}
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t p-4" style={{ borderColor: "var(--line)" }}>
            <button
              type="button"
              disabled={!previous || status === "streaming"}
              onClick={() => previous && onChangeItem(previous.id)}
              className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs disabled:opacity-50"
              style={{ borderColor: "var(--line)" }}
              data-testid="digest-review-prev"
            >
              <ArrowLeft className="size-3.5" />
              {t("digest.previous")}
            </button>
            <button
              type="button"
              disabled={!next || status === "streaming"}
              onClick={() => next && onChangeItem(next.id)}
              className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs disabled:opacity-50"
              style={{ borderColor: "var(--line)" }}
              data-testid="digest-review-next"
            >
              {t("digest.next")}
              <ArrowRight className="size-3.5" />
            </button>
          </div>
        </section>

        <section className="flex min-h-0 flex-col" style={{ background: "var(--bg)" }}>
          <div className="border-b p-4" style={{ borderColor: "var(--line)" }}>
            <h3 className="font-serif text-lg font-medium">{t("digest.reviewChat")}</h3>
          </div>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4" data-testid="digest-review-chat">
            {messages.length === 0 && !error && (
              <div className="text-sm text-muted-foreground">
                {t("digest.reviewChatEmpty")}
              </div>
            )}
            <ChatTranscript
              messages={messages}
              status={status}
              testPrefix="digest-review"
              generatingLabel={t("digest.working")}
            />
            {error && (
              <div className="text-xs" style={{ color: "var(--danger, #c0392b)" }}>
                {error}
              </div>
            )}
          </div>
          <div className="border-t p-3" style={{ borderColor: "var(--line)" }}>
            <textarea
              data-testid="digest-review-chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder={t("digest.chatPlaceholder")}
              rows={3}
              className="w-full resize-none rounded-md border bg-transparent px-2 py-1.5 text-sm outline-none"
              style={{ borderColor: "var(--line)", color: "var(--ink)" }}
            />
            <div className="mt-2 flex justify-end">
              {status === "streaming" ? (
                <button
                  type="button"
                  onClick={stop}
                  className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs"
                  style={{ borderColor: "var(--line)" }}
                  data-testid="digest-review-chat-stop"
                >
                  <Square className="size-3" />
                  {t("digest.stop")}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={submit}
                  disabled={!input.trim()}
                  className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs disabled:opacity-50"
                  style={{ borderColor: "var(--line)" }}
                  data-testid="digest-review-chat-send"
                >
                  <Send className="size-3" />
                  {t("digest.send")}
                </button>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function groupRawInfo(
  items: RawInfoSummary[],
  mode: GroupMode,
  t: ReturnType<typeof useTranslation>["t"],
): DigestGroup[] {
  const grouped = new Map<string, DigestGroup>();
  for (const item of items) {
    const id = mode === "time" ? timeGroupId(item.fetched_at) : item.source_name || "Unknown";
    const label = mode === "time" ? timeGroupLabel(id, t) : id;
    const existing = grouped.get(id);
    if (existing) {
      existing.items.push(item);
    } else {
      grouped.set(id, { id, label, items: [item] });
    }
  }
  return Array.from(grouped.values());
}

function timeGroupId(raw: string): string {
  const fetched = startOfDay(new Date(raw));
  const today = startOfDay(new Date());
  const days = Math.floor((today.getTime() - fetched.getTime()) / 86_400_000);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return "week";
  return "earlier";
}

function timeGroupLabel(
  id: string,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  if (id === "today") return t("digest.timeToday");
  if (id === "yesterday") return t("digest.timeYesterday");
  if (id === "week") return t("digest.timeWeek");
  return t("digest.timeEarlier");
}

function sortRawInfo(items: RawInfoSummary[]): RawInfoSummary[] {
  return [...items].sort((a, b) => {
    const byFetched = Date.parse(b.fetched_at) - Date.parse(a.fetched_at);
    if (byFetched !== 0) return byFetched;
    return a.id.localeCompare(b.id);
  });
}

function startOfDay(date: Date): Date {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

function slugId(raw: string): string {
  return raw.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

function formatDate(raw: string): string {
  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) return raw;
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function statusLabel(status: RawInfoSummary["status"]): string {
  return status.replace(/_/g, " ");
}

function isPending(item: RawInfoSummary): boolean {
  return item.status !== "discarded" && item.status !== "included";
}
