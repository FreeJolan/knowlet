/**
 * DigestFocusMode — Stage C v2.
 *
 * Raw Info inbox, source configuration, full-screen review, and note-draft
 * settlement all live together because Digest is a workflow surface, not a
 * generic settings panel.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock,
  ExternalLink,
  FileText,
  RefreshCw,
  Rss,
  Send,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  acceptDraftDiff,
  commitNoteDraft,
  createRawInfoDraft,
  discardRawInfo,
  getDigestStatus,
  getDraft,
  listRawInfoItems,
  pullDigestSources,
  rejectDraftDiff,
  updateDraft,
  type DigestStatus,
  type RawInfoDraftResult,
  type RawInfoSummary,
} from "@/api/client";
import { ChatTranscript, DiffReview, chatHistoryForRequest } from "@/components/Discuss";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { QK } from "@/lib/queryClient";

import { DigestFolderCommitDialog } from "./DigestFolderCommitDialog";
import { DigestDraftNoteSurface } from "./DigestDraftNoteSurface";
import { DigestSourcePanel } from "./DigestSourcePanel";
import { useRawInfoChat } from "./useRawInfoChat";

interface Props {
  open: boolean;
  onClose: () => void;
  onOpenNote?: (noteId: string, opts?: { discuss?: boolean }) => void;
}

type GroupMode = "time" | "source";

const DRAFT_AUTOSAVE_DEBOUNCE_MS = 500;
const DRAFT_SAVED_IDLE_MS = 1200;
const REVIEW_TRANSITION_MS = 2000;

type DraftSaveState = "idle" | "dirty" | "saving" | "saved" | "error";

type DraftEdit = {
  title: string;
  tags: string;
  kind: "knowledge" | "reference";
  folder: string;
  body: string;
};

type ReviewTransition = {
  kind: "commit" | "discard";
  title: string;
  nextTitle: string | null;
};

interface DigestGroup {
  id: string;
  label: string;
  items: RawInfoSummary[];
}

export function DigestFocusMode({
  open,
  onClose,
  onOpenNote,
}: Props): React.ReactElement | null {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [groupMode, setGroupMode] = useState<GroupMode>("time");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [configOpen, setConfigOpen] = useState(false);

  useEffect(() => {
    if (!open) {
      setSelectedId(null);
      setReviewId(null);
      setGroupMode("time");
      setConfigOpen(false);
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
  const sourceCount = status.data?.sources.length ?? 0;
  const showSourceConfig =
    configOpen || (rawInfo.data !== undefined && items.length === 0 && sourceCount === 0);

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
            onClick={() => setConfigOpen((value) => !value)}
            className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs"
            style={{
              borderColor: configOpen ? "var(--accent)" : "var(--line)",
              background: configOpen ? "var(--accent-tint-2)" : "transparent",
              color: "var(--ink)",
            }}
            data-testid="digest-config-toggle"
          >
            <SlidersHorizontal className="size-3.5" />
            {t("digest.configureSources")}
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

      {showSourceConfig && (
        <div
          className="border-b px-6 py-4"
          style={{ borderColor: "var(--line)", background: "var(--bg)" }}
          data-testid="digest-source-config"
        >
          <DigestSourcePanel />
        </div>
      )}

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
          onOpenNote={onOpenNote}
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

function StageTabButton({
  active,
  disabled,
  icon,
  label,
  onClick,
  testId,
}: {
  active: boolean;
  disabled?: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  testId: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      aria-disabled={disabled ? "true" : "false"}
      disabled={disabled}
      onClick={onClick}
      data-testid={testId}
      className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-45"
      style={{
        borderColor: active ? "var(--accent)" : "var(--line)",
        background: active ? "var(--accent-tint-2)" : "transparent",
        color: active ? "var(--ink)" : "var(--ink-mute)",
      }}
    >
      {icon}
      {label}
    </button>
  );
}

function draftToEdit(draft: RawInfoDraftResult["draft"]): DraftEdit {
  return {
    title: draft.title,
    tags: draft.tags.join(", "),
    kind: draft.kind,
    folder: draft.folder ?? "",
    body: draft.body ?? "",
  };
}

function normalizeDraftEdit(edit: DraftEdit) {
  return {
    title: edit.title,
    body: edit.body,
    tags: normalizeDraftTags(edit.tags),
    kind: edit.kind,
    folder: edit.folder,
  };
}

function normalizeDraftTags(value: string): string[] {
  return value
    .split(",")
    .map((tag) => tag.trim().replace(/^#/, ""))
    .filter(Boolean);
}

function sameDraftEdit(a: DraftEdit, b: DraftEdit): boolean {
  return (
    a.title.trim() === b.title.trim() &&
    normalizeDraftTags(a.tags).join("\0") === normalizeDraftTags(b.tags).join("\0") &&
    a.kind === b.kind &&
    a.folder.trim() === b.folder.trim() &&
    a.body === b.body
  );
}

function ReviewOverlay({
  items,
  activeId,
  onChangeItem,
  onClose,
  onOpenNote,
}: {
  items: RawInfoSummary[];
  activeId: string;
  onChangeItem: (id: string) => void;
  onClose: () => void;
  onOpenNote?: (noteId: string, opts?: { discuss?: boolean }) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [processedIds, setProcessedIds] = useState<Set<string>>(() => new Set());
  const reviewItems = useMemo(
    () => items.filter((candidate) => isPending(candidate) && !processedIds.has(candidate.id)),
    [items, processedIds],
  );
  const index = Math.max(
    0,
    reviewItems.findIndex((item) => item.id === activeId),
  );
  const item = reviewItems[index] ?? null;
  const previous = index > 0 ? reviewItems[index - 1] : null;
  const next = index >= 0 && index < reviewItems.length - 1 ? reviewItems[index + 1] : null;
  const { messages, status, error, proposal, send, stop, clearProposal } = useRawInfoChat(
    item?.id ?? null,
  );
  const [input, setInput] = useState("");
  const [draftResult, setDraftResult] = useState<RawInfoDraftResult | null>(null);
  const [pendingDiff, setPendingDiff] = useState<typeof proposal>(null);
  const [commitResult, setCommitResult] = useState<{
    note_id: string;
    title: string;
  } | null>(null);
  const [stageTab, setStageTab] = useState<"raw" | "draft">("raw");
  const [folderDialogOpen, setFolderDialogOpen] = useState(false);
  const [draftEdit, setDraftEdit] = useState({
    title: "",
    tags: "",
    kind: "reference" as "knowledge" | "reference",
    folder: "",
    body: "",
  });
  const [draftError, setDraftError] = useState<string | null>(null);
  const [draftSaveState, setDraftSaveState] = useState<DraftSaveState>("idle");
  const [draftEditorRevision, setDraftEditorRevision] = useState(0);
  const [reviewTransition, setReviewTransition] = useState<ReviewTransition | null>(null);
  const autosaveTimerRef = useRef<number | null>(null);
  const savedIdleTimerRef = useRef<number | null>(null);
  const latestSaveSeqRef = useRef(0);
  const transitionTimerRef = useRef<number | null>(null);
  const delayedTransitionTimerRef = useRef<number | null>(null);
  const draftEditRef = useRef<DraftEdit>(draftEdit);
  const draftResultRef = useRef<RawInfoDraftResult | null>(draftResult);
  const draftSaveStateRef = useRef<DraftSaveState>(draftSaveState);
  const existingDraft = useQuery({
    queryKey: ["draft", item?.note_draft_id],
    queryFn: () => getDraft(item?.note_draft_id ?? ""),
    enabled: Boolean(item?.note_draft_id),
  });

  useEffect(() => {
    draftEditRef.current = draftEdit;
  }, [draftEdit]);

  useEffect(() => {
    draftResultRef.current = draftResult;
  }, [draftResult]);

  useEffect(() => {
    draftSaveStateRef.current = draftSaveState;
  }, [draftSaveState]);

  const clearAutosaveTimer = useCallback(() => {
    if (autosaveTimerRef.current !== null) {
      window.clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
  }, []);

  const clearSavedIdleTimer = useCallback(() => {
    if (savedIdleTimerRef.current !== null) {
      window.clearTimeout(savedIdleTimerRef.current);
      savedIdleTimerRef.current = null;
    }
  }, []);

  const clearTransitionTimer = useCallback(() => {
    if (transitionTimerRef.current !== null) {
      window.clearTimeout(transitionTimerRef.current);
      transitionTimerRef.current = null;
    }
  }, []);

  const clearDelayedTransitionTimer = useCallback(() => {
    if (delayedTransitionTimerRef.current !== null) {
      window.clearTimeout(delayedTransitionTimerRef.current);
      delayedTransitionTimerRef.current = null;
    }
  }, []);

  useEffect(
    () => () => {
      clearAutosaveTimer();
      clearSavedIdleTimer();
      clearTransitionTimer();
      clearDelayedTransitionTimer();
    },
    [
      clearAutosaveTimer,
      clearDelayedTransitionTimer,
      clearSavedIdleTimer,
      clearTransitionTimer,
    ],
  );

  const advanceAfterProcessed = useCallback(
    (processedId: string) => {
      const currentIndex = reviewItems.findIndex((candidate) => candidate.id === processedId);
      const remaining = reviewItems.filter((candidate) => candidate.id !== processedId);
      const nextItem =
        remaining[currentIndex] ??
        remaining[Math.max(0, currentIndex - 1)] ??
        remaining[0] ??
        null;
      setProcessedIds((current) => new Set(current).add(processedId));
      if (nextItem) onChangeItem(nextItem.id);
    },
    [onChangeItem, reviewItems],
  );

  const beginReviewTransition = useCallback(
    (
      kind: ReviewTransition["kind"],
      processedId: string,
      afterAdvance?: () => void,
    ) => {
      const currentIndex = reviewItems.findIndex((candidate) => candidate.id === processedId);
      const remaining = reviewItems.filter((candidate) => candidate.id !== processedId);
      const nextItem =
        remaining[currentIndex] ??
        remaining[Math.max(0, currentIndex - 1)] ??
        remaining[0] ??
        null;
      const processedTitle =
        reviewItems.find((candidate) => candidate.id === processedId)?.title ??
        item?.title ??
        t("digest.untitled");
      clearTransitionTimer();
      setReviewTransition({
        kind,
        title: processedTitle,
        nextTitle: nextItem?.title ?? null,
      });
      transitionTimerRef.current = window.setTimeout(() => {
        setReviewTransition(null);
        advanceAfterProcessed(processedId);
        afterAdvance?.();
      }, REVIEW_TRANSITION_MS);
    },
    [advanceAfterProcessed, clearTransitionTimer, item?.title, reviewItems, t],
  );

  const draftMut = useMutation({
    mutationFn: async () => {
      if (!item) throw new Error("No Raw Info item selected");
      return createRawInfoDraft(item.id, {
        history: chatHistoryForRequest(messages),
      });
    },
    onSuccess: (result) => {
      const edit = draftToEdit(result.draft);
      setDraftResult(result);
      setCommitResult(null);
      setDraftEdit(edit);
      setDraftEditorRevision((revision) => revision + 1);
      draftSaveStateRef.current = "idle";
      setDraftSaveState("idle");
      setStageTab("draft");
      setDraftError(null);
      void qc.invalidateQueries({ queryKey: ["digest-items"] });
      void qc.invalidateQueries({ queryKey: ["digest-status"] });
    },
    onError: (err) => {
      setDraftError(err instanceof Error ? err.message : t("digest.draftFailed"));
    },
  });

  const saveDraftMut = useMutation({
    mutationFn: async ({
      draftId,
      edit,
      seq,
    }: {
      draftId: string;
      edit: DraftEdit;
      seq: number;
    }) => {
      const draft = await updateDraft(draftId, normalizeDraftEdit(edit));
      return { draft, seq };
    },
    onSuccess: ({ draft, seq }) => {
      if (seq < latestSaveSeqRef.current) return;
      const savedEdit = draftToEdit(draft);
      setDraftResult((current) => (current ? { ...current, draft } : current));
      setDraftError(null);
      clearSavedIdleTimer();
      if (sameDraftEdit(draftEditRef.current, savedEdit)) {
        draftSaveStateRef.current = "saved";
        setDraftSaveState("saved");
        savedIdleTimerRef.current = window.setTimeout(() => {
          draftSaveStateRef.current = "idle";
          setDraftSaveState("idle");
          savedIdleTimerRef.current = null;
        }, DRAFT_SAVED_IDLE_MS);
      } else {
        draftSaveStateRef.current = "dirty";
        setDraftSaveState("dirty");
      }
    },
    onError: (err, variables) => {
      if (variables.seq < latestSaveSeqRef.current) return;
      clearSavedIdleTimer();
      draftSaveStateRef.current = "error";
      setDraftSaveState("error");
      setDraftError(err instanceof Error ? err.message : t("digest.draftSaveFailed"));
    },
  });
  const saveDraftMutateRef = useRef(saveDraftMut.mutate);
  useEffect(() => {
    saveDraftMutateRef.current = saveDraftMut.mutate;
  }, [saveDraftMut.mutate]);

  const startDraftSave = useCallback(
    (edit: DraftEdit = draftEditRef.current) => {
      const current = draftResultRef.current;
      if (!current) return;
      clearAutosaveTimer();
      clearSavedIdleTimer();
      const seq = latestSaveSeqRef.current + 1;
      latestSaveSeqRef.current = seq;
      draftSaveStateRef.current = "saving";
      setDraftSaveState("saving");
      saveDraftMutateRef.current({ draftId: current.draft.id, edit, seq });
    },
    [clearAutosaveTimer, clearSavedIdleTimer],
  );

  const acceptDiffMut = useMutation({
    mutationFn: async (finalBody: string) => {
      if (!pendingDiff) throw new Error("No draft diff to accept");
      return acceptDraftDiff(pendingDiff.draftId, { final_body: finalBody });
    },
    onSuccess: (result) => {
      const edit = draftToEdit(result.draft);
      setDraftResult((current) => (current ? { ...current, draft: result.draft } : current));
      setDraftEdit(edit);
      setDraftEditorRevision((revision) => revision + 1);
      draftSaveStateRef.current = "idle";
      setDraftSaveState("idle");
      setPendingDiff(null);
      clearProposal();
      setDraftError(null);
    },
    onError: (err) => {
      setDraftError(err instanceof Error ? err.message : t("digest.draftDiffFailed"));
    },
  });

  const rejectDiffMut = useMutation({
    mutationFn: async () => {
      if (!pendingDiff) throw new Error("No draft diff to reject");
      return rejectDraftDiff(pendingDiff.draftId);
    },
    onSuccess: (result) => {
      const edit = draftToEdit(result.draft);
      setDraftResult((current) => (current ? { ...current, draft: result.draft } : current));
      setDraftEdit(edit);
      setDraftEditorRevision((revision) => revision + 1);
      draftSaveStateRef.current = "idle";
      setDraftSaveState("idle");
      setPendingDiff(null);
      clearProposal();
      setDraftError(null);
    },
    onError: (err) => {
      setDraftError(err instanceof Error ? err.message : t("digest.draftDiffFailed"));
    },
  });

  const commitMut = useMutation({
    mutationFn: async (folder: string) => {
      if (!draftResult) throw new Error("No draft to commit");
      return commitNoteDraft(draftResult.draft.id, { folder });
    },
    onSuccess: (result) => {
      setCommitResult({ note_id: result.note_id, title: result.title });
      setFolderDialogOpen(false);
      setPendingDiff(null);
      clearProposal();
      clearDelayedTransitionTimer();
      delayedTransitionTimerRef.current = window.setTimeout(() => {
        delayedTransitionTimerRef.current = null;
        beginReviewTransition("commit", result.raw_info_id ?? item?.id ?? activeId, () => {
          void qc.invalidateQueries({ queryKey: ["digest-items"] });
          void qc.invalidateQueries({ queryKey: ["digest-status"] });
          void qc.invalidateQueries({ queryKey: ["drafts"] });
          void qc.invalidateQueries({ queryKey: QK.tree });
          onOpenNote?.(result.note_id);
        });
      }, 120);
    },
    onError: (err) => {
      setDraftError(err instanceof Error ? err.message : t("digest.commitFailed"));
    },
  });

  const discardMut = useMutation({
    mutationFn: async (infoId: string) => discardRawInfo(infoId),
    onSuccess: (result) => {
      clearAutosaveTimer();
      clearSavedIdleTimer();
      setPendingDiff(null);
      clearProposal();
      beginReviewTransition("discard", result.id, () => {
        void qc.invalidateQueries({ queryKey: ["digest-items"] });
        void qc.invalidateQueries({ queryKey: ["digest-status"] });
        void qc.invalidateQueries({ queryKey: ["drafts"] });
      });
    },
    onError: (err) => {
      setDraftError(err instanceof Error ? err.message : t("digest.discardFailed"));
    },
  });

  useEffect(() => {
    clearAutosaveTimer();
    clearSavedIdleTimer();
    setInput("");
    setDraftResult(null);
    setPendingDiff(null);
    setCommitResult(null);
    setFolderDialogOpen(false);
    setStageTab("raw");
    setDraftEdit({ title: "", tags: "", kind: "reference", folder: "", body: "" });
    setDraftError(null);
    draftSaveStateRef.current = "idle";
    setDraftSaveState("idle");
    setDraftEditorRevision((revision) => revision + 1);
    clearProposal();
  }, [clearAutosaveTimer, clearProposal, clearSavedIdleTimer, item?.id]);

  useEffect(() => {
    if (!item?.note_draft_id || !existingDraft.data) return;
    const draft = existingDraft.data;
    if (draftResult?.draft.id === draft.id) return;
    const edit = draftToEdit(draft);
    setDraftResult({
      raw_info: item,
      draft,
      rationale: t("digest.existingDraftRationale"),
    });
    setDraftEdit(edit);
    setDraftEditorRevision((revision) => revision + 1);
    draftSaveStateRef.current = "idle";
    setDraftSaveState("idle");
    setStageTab("draft");
    setDraftError(null);
  }, [draftResult?.draft.id, existingDraft.data, item, t]);

  useEffect(() => {
    if (!proposal) return;
    if (proposal.changed) {
      setPendingDiff(proposal);
      setStageTab("draft");
    } else {
      setDraftError(proposal.reason || proposal.summary || t("digest.noDraftDiff"));
      clearProposal();
    }
  }, [clearProposal, proposal, t]);

  const persistedDraftEdit = draftResult ? draftToEdit(draftResult.draft) : null;
  const draftChanged =
    draftResult !== null &&
    persistedDraftEdit !== null &&
    !sameDraftEdit(draftEdit, persistedDraftEdit);
  const draftWaitingForSave =
    draftChanged ||
    draftSaveState === "dirty" ||
    draftSaveState === "saving" ||
    draftSaveState === "error" ||
    saveDraftMut.isPending;

  useEffect(() => {
    clearAutosaveTimer();
    if (!draftResult) {
      draftSaveStateRef.current = "idle";
      setDraftSaveState("idle");
      return;
    }
    if (!draftChanged) {
      if (draftSaveStateRef.current === "dirty") {
        draftSaveStateRef.current = "idle";
        setDraftSaveState("idle");
      }
      return;
    }
    if (draftSaveStateRef.current === "saving") return;
    clearSavedIdleTimer();
    draftSaveStateRef.current = "dirty";
    setDraftSaveState("dirty");
    const edit = draftEdit;
    autosaveTimerRef.current = window.setTimeout(() => {
      startDraftSave(edit);
    }, DRAFT_AUTOSAVE_DEBOUNCE_MS);
    return clearAutosaveTimer;
  }, [
    clearAutosaveTimer,
    clearSavedIdleTimer,
    draftChanged,
    draftEdit,
    draftResult,
    startDraftSave,
  ]);

  if (!item) {
    return (
      <div
        className="fixed inset-0 z-[60] flex flex-col"
        style={{ background: "var(--bg, #f4f0e8)" }}
        data-testid="digest-review-workspace"
      >
        <header
          className="flex items-center justify-between gap-4 border-b px-5 py-3"
          style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
        >
          <div className="min-w-0">
            <div className="text-[11px] font-mono uppercase text-muted-foreground">
              {t("digest.reviewComplete")}
            </div>
            <h2 className="truncate font-serif text-xl font-medium">
              {t("digest.reviewEmptyTitle")}
            </h2>
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
        </header>
        <div
          className="flex min-h-0 flex-1 items-center justify-center p-8 text-center"
          data-testid="digest-review-empty-state"
        >
          <div className="max-w-md">
            <div className="font-serif text-2xl font-semibold">
              {t("digest.reviewEmptyTitle")}
            </div>
            <p className="mt-2 text-sm text-muted-foreground">
              {t("digest.reviewEmptyHint")}
            </p>
          </div>
        </div>
      </div>
    );
  }

  const hasExistingDraft = Boolean(draftResult || item.note_draft_id);

  const submit = () => {
    if (input.trim() && status !== "streaming") {
      send(input);
      setInput("");
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex flex-col overflow-hidden"
      style={{ background: "var(--bg, #f4f0e8)" }}
      data-testid="digest-review-workspace"
    >
      <header
        className="flex items-center justify-between gap-4 border-b px-5 py-3"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        <div className="min-w-0">
          <div className="text-[11px] font-mono uppercase text-muted-foreground">
            {t("digest.reviewPosition", { current: index + 1, total: reviewItems.length })}
          </div>
          <h2
            className="truncate font-serif text-xl font-medium"
            data-testid="digest-review-current-title"
          >
            {item.title || t("digest.untitled")}
          </h2>
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
      </header>

      {reviewTransition && <ReviewTransitionOverlay transition={reviewTransition} />}

      <ResizablePanelGroup direction="horizontal" className="min-h-0 flex-1">
        <ResizablePanel defaultSize={60} minSize={40}>
          <section
            className="flex h-full min-h-0 flex-col"
            style={{ background: "var(--bg-1)" }}
            data-testid="digest-review-left-pane"
          >
            <div
              className="flex items-center gap-2 border-b px-4 py-2"
              role="tablist"
              aria-label={t("digest.reviewStages")}
              style={{ borderColor: "var(--line)" }}
            >
              <StageTabButton
                active={stageTab === "raw"}
                icon={<ExternalLink className="size-3.5" />}
                label={t("digest.rawInfoStage")}
                onClick={() => setStageTab("raw")}
                testId="digest-review-stage-tab-raw"
              />
              <ArrowRight className="size-3.5 text-muted-foreground" />
              <StageTabButton
                active={stageTab === "draft"}
                disabled={!draftResult}
                icon={<FileText className="size-3.5" />}
                label={t("digest.draftStage")}
                onClick={() => draftResult && setStageTab("draft")}
                testId="digest-review-stage-tab-draft"
              />
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {stageTab === "raw" ? (
                <div className="space-y-4" data-testid="digest-review-raw-panel">
                  <div>
                    <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
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
                  {hasExistingDraft ? (
                    <div
                      className="flex flex-wrap items-center gap-2 rounded border px-3 py-2 text-xs"
                      style={{ borderColor: "var(--line)", background: "var(--bg)" }}
                      data-testid="digest-existing-draft-notice"
                    >
                      <FileText className="size-3.5" />
                      <span>{t("digest.existingDraftNotice")}</span>
                      {draftResult && (
                        <button
                          type="button"
                          className="rounded border px-2 py-1"
                          style={{ borderColor: "var(--accent)" }}
                          onClick={() => setStageTab("draft")}
                          data-testid="digest-open-existing-draft"
                        >
                          {t("digest.openDraft")}
                        </button>
                      )}
                    </div>
                  ) : (
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
                  )}
                </div>
              ) : (
                <div className="min-h-[720px]" data-testid="digest-draft-result">
                  {draftResult ? (
                    <DigestDraftNoteSurface
                      draft={draftResult.draft}
                      draftEdit={draftEdit}
                      editorRevision={draftEditorRevision}
                      onDraftEditChange={setDraftEdit}
                      rationale={draftResult.rationale}
                      footer={
                        <div className="space-y-3">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <div className="flex flex-wrap items-center gap-2">
                              <DraftAutosaveStatus
                                state={draftSaveState}
                                onRetry={() => startDraftSave()}
                              />
                            </div>
                            <div className="flex items-center gap-2">
                              <button
                                type="button"
                                disabled={
                                  commitMut.isPending ||
                                  Boolean(pendingDiff) ||
                                  draftWaitingForSave ||
                                  !draftEdit.title.trim() ||
                                  !draftEdit.body.trim()
                                }
                                onClick={() => setFolderDialogOpen(true)}
                                className="rounded border px-2.5 py-1.5 text-xs disabled:opacity-50"
                                style={{
                                  borderColor: "var(--accent)",
                                  background: "var(--accent-soft, rgba(91,122,156,0.14))",
                                }}
                                data-testid="digest-draft-commit"
                              >
                                {commitMut.isPending ? t("digest.committingDraft") : t("digest.commitDraft")}
                              </button>
                              <DigestFolderCommitDialog
                                open={folderDialogOpen}
                                recommendedFolder={draftEdit.folder}
                                committing={commitMut.isPending}
                                onOpenChange={setFolderDialogOpen}
                                onConfirm={(folder) => {
                                  setFolderDialogOpen(false);
                                  commitMut.mutate(folder);
                                }}
                              />
                            </div>
                          </div>
                          {commitResult && (
                            <div
                              className="rounded border px-2 py-1.5 text-xs"
                              style={{ borderColor: "var(--accent)", background: "var(--accent-tint)" }}
                              data-testid="digest-draft-committed"
                            >
                              {t("digest.draftCommitted", { title: commitResult.title })}
                            </div>
                          )}
                          {pendingDiff && (
                            <div
                              className="h-[420px] overflow-hidden rounded-md border"
                              style={{ borderColor: "var(--line)" }}
                              data-testid="digest-draft-diff-panel"
                            >
                              <DiffReview
                                oldBody={pendingDiff.oldBody}
                                newBody={pendingDiff.newBody}
                                saving={acceptDiffMut.isPending || rejectDiffMut.isPending}
                                onAccept={(finalBody) => acceptDiffMut.mutate(finalBody)}
                                onReject={() => rejectDiffMut.mutate()}
                              />
                            </div>
                          )}
                        </div>
                      }
                    />
                  ) : (
                    <div className="text-sm text-muted-foreground">
                      {t("digest.draftStageDisabled")}
                    </div>
                  )}
                </div>
              )}
              {draftError && (
                <div className="mt-4 text-xs" style={{ color: "var(--danger, #c0392b)" }}>
                  {draftError}
                </div>
              )}
            </div>
            <div
              className="flex flex-wrap items-center justify-between gap-2 border-t p-4"
              style={{ borderColor: "var(--line)" }}
            >
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={
                    !previous ||
                    status === "streaming" ||
                    Boolean(reviewTransition) ||
                    discardMut.isPending
                  }
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
                  disabled={status === "streaming" || Boolean(reviewTransition) || discardMut.isPending}
                  onClick={() => {
                    clearAutosaveTimer();
                    clearSavedIdleTimer();
                    discardMut.mutate(item.id);
                  }}
                  className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs disabled:opacity-50"
                  style={{ borderColor: "var(--line)" }}
                  data-testid="digest-review-discard"
                >
                  <Trash2 className="size-3.5" />
                  {discardMut.isPending ? t("digest.discarding") : t("digest.discard")}
                </button>
              </div>
              <button
                type="button"
                disabled={
                  !next ||
                  status === "streaming" ||
                  Boolean(reviewTransition) ||
                  discardMut.isPending
                }
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
        </ResizablePanel>
        <ResizableHandle />
        <ResizablePanel defaultSize={40} minSize={30}>
          <section
            className="flex h-full min-h-0 flex-col"
            style={{ background: "var(--bg)" }}
            data-testid="digest-review-chat-pane"
          >
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
        </ResizablePanel>
      </ResizablePanelGroup>
    </div>
  );
}

function DraftAutosaveStatus({
  state,
  onRetry,
}: {
  state: DraftSaveState;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  const label =
    state === "saving"
      ? t("digest.draftAutosaveSaving")
      : state === "saved"
        ? t("digest.draftAutosaveSaved")
        : state === "dirty"
          ? t("digest.draftAutosaveDirty")
          : state === "error"
            ? t("digest.draftAutosaveError")
            : t("digest.draftAutosaveIdle");
  return (
    <span
      className="inline-flex min-h-7 items-center gap-1.5 rounded px-1 text-[11px] text-muted-foreground"
      data-testid="digest-draft-autosave-state"
      data-state={state}
    >
      {state === "saving" ? (
        <RefreshCw className="size-3 animate-spin" />
      ) : state === "error" ? (
        <AlertTriangle className="size-3" />
      ) : state === "saved" || state === "idle" ? (
        <CheckCircle2 className="size-3" />
      ) : null}
      <span>{label}</span>
      {state === "error" && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded border px-1.5 py-0.5 text-[11px]"
          style={{ borderColor: "var(--line)" }}
          data-testid="digest-draft-autosave-retry"
        >
          {t("digest.draftAutosaveRetry")}
        </button>
      )}
    </span>
  );
}

function ReviewTransitionOverlay({
  transition,
}: {
  transition: ReviewTransition;
}) {
  const { t } = useTranslation();
  const isCommit = transition.kind === "commit";
  const target = isCommit ? "library" : "discard";
  const TargetIcon = isCommit ? BookOpen : Trash2;
  return (
    <div
      className="absolute inset-0 z-[110] flex items-center justify-center overflow-hidden px-6"
      style={{ background: "rgb(244 240 232 / 0.74)" }}
      data-testid="digest-review-transition"
      data-kind={transition.kind}
      data-target={target}
      data-duration-ms={REVIEW_TRANSITION_MS}
    >
      <div className="pointer-events-none relative h-72 w-full max-w-4xl">
        <div
          className="digest-review-transition-snapshot absolute left-1/2 top-1/2 w-[min(52vw,440px)] -translate-x-1/2 -translate-y-1/2 rounded-md border p-4 shadow-lg"
          style={{
            borderColor: "var(--line)",
            background: "var(--card-paper)",
            color: "var(--ink)",
          }}
          data-testid="digest-review-transition-snapshot"
        >
          <div className="text-[11px] font-mono uppercase text-muted-foreground">
            {isCommit ? t("digest.transitionArchiveLabel") : t("digest.transitionDiscardLabel")}
          </div>
          <div className="mt-2 truncate font-serif text-xl font-medium">
            {transition.title}
          </div>
          <div className="mt-3 h-2 w-4/5 rounded-full" style={{ background: "var(--line-soft)" }} />
          <div className="mt-2 h-2 w-3/5 rounded-full" style={{ background: "var(--line-soft)" }} />
        </div>
        <div
          className="digest-review-transition-target absolute right-[8%] top-1/2 flex size-24 -translate-y-1/2 items-center justify-center rounded-full border shadow-sm"
          style={{
            borderColor: isCommit ? "var(--good)" : "var(--line)",
            background: "var(--bg-1)",
            color: isCommit ? "var(--good)" : "var(--ink-soft)",
          }}
          data-testid="digest-review-transition-target"
        >
          <TargetIcon className="size-9" />
        </div>
        {isCommit && (
          <div
            className="digest-review-transition-complete absolute bottom-4 right-[7%] flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs"
            style={{
              borderColor: "var(--good)",
              background: "rgb(94 135 87 / 0.12)",
              color: "var(--good)",
            }}
            data-testid="digest-review-transition-complete"
          >
            <CheckCircle2 className="size-3.5" />
            {t("digest.transitionComplete")}
          </div>
        )}
      </div>
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 text-center text-xs text-muted-foreground">
        {transition.nextTitle
          ? t("digest.transitionNext", { title: transition.nextTitle })
          : t("digest.transitionDone")}
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
