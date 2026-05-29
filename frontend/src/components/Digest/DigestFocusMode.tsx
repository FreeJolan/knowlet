/**
 * DigestFocusMode — Stage C2/C3.
 *
 * Read-only intake list for drafts produced by digest sources, plus
 * Stage C3's per-item decision path: read, discuss, then skip / save as
 * reference / internalize as knowledge through diff review.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  BookOpenCheck,
  Brain,
  ExternalLink,
  Send,
  Square,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  approveDraft,
  listDigestDrafts,
  proposeDraftInternalize,
  rejectDraft,
  updateDraft,
  type DigestPeriod,
  type DraftSummary,
  type ProposedEdit,
} from "@/api/client";
import { ChatTranscript, DiffReview } from "@/components/Discuss";
import { QK } from "@/lib/queryClient";

import { useDraftChat } from "./useDraftChat";

interface Props {
  open: boolean;
  onClose: () => void;
  onOpenNote?: (noteId: string, opts?: { discuss?: boolean }) => void;
}

type DraftProposal = ProposedEdit & { draftId: string };

export function DigestFocusMode({
  open,
  onClose,
  onOpenNote,
}: Props): React.ReactElement | null {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [period, setPeriod] = useState<DigestPeriod>("today");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [proposal, setProposal] = useState<DraftProposal | null>(null);
  const [savingInternalize, setSavingInternalize] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setSelectedId(null);
      setProposal(null);
      setNotice(null);
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

  const drafts = useQuery({
    queryKey: ["digest-drafts", period],
    queryFn: () => listDigestDrafts(period),
    enabled: open,
    refetchOnMount: "always",
    staleTime: 0,
  });

  const items = useMemo(() => drafts.data ?? [], [drafts.data]);
  const selected = useMemo(
    () => items.find((draft) => draft.id === selectedId) ?? null,
    [items, selectedId],
  );

  useEffect(() => {
    if (!open || !drafts.data) return;
    if (items.length === 0) {
      setSelectedId(null);
      setProposal(null);
      return;
    }
    if (!selectedId || !items.some((draft) => draft.id === selectedId)) {
      const first = items[0];
      if (first) setSelectedId(first.id);
      setProposal(null);
    }
  }, [drafts.data, items, open, selectedId]);

  const refreshQueues = () => {
    void qc.invalidateQueries({ queryKey: ["digest-drafts"] });
    void qc.invalidateQueries({ queryKey: ["drafts"] });
  };

  const skipMut = useMutation({
    mutationFn: (draft: DraftSummary) => rejectDraft(draft.id),
    onSuccess: () => {
      refreshQueues();
      setSelectedId(null);
      setProposal(null);
    },
  });

  const saveReferenceMut = useMutation({
    mutationFn: async (draft: DraftSummary) => {
      await updateDraft(draft.id, { kind: "reference" });
      return approveDraft(draft.id);
    },
    onSuccess: (res) => {
      refreshQueues();
      void qc.invalidateQueries({ queryKey: QK.tree });
      onOpenNote?.(res.note_id);
      onClose();
    },
  });

  const proposeInternalizeMut = useMutation({
    mutationFn: (draft: DraftSummary) =>
      proposeDraftInternalize(
        draft.id,
        "把这条 digest 内化成我自己的知识笔记,保留出处线索,不要虚构。",
      ),
    onSuccess: (res, draft) => {
      if (res.changed) {
        setProposal({ ...res, draftId: draft.id });
        setNotice(null);
      } else {
        setNotice(res.reason || t("digest.noProposal"));
      }
    },
  });

  const acceptInternalize = async (finalBody: string) => {
    if (!proposal) return;
    setSavingInternalize(true);
    try {
      await updateDraft(proposal.draftId, {
        body: finalBody,
        kind: "knowledge",
      });
      const res = await approveDraft(proposal.draftId);
      refreshQueues();
      void qc.invalidateQueries({ queryKey: QK.tree });
      setProposal(null);
      onOpenNote?.(res.note_id, { discuss: true });
      onClose();
    } catch (err) {
      console.error("internalize digest draft failed", err);
      setNotice(t("digest.internalizeFailed"));
    } finally {
      setSavingInternalize(false);
    }
  };

  if (!open) return null;

  const busy =
    skipMut.isPending ||
    saveReferenceMut.isPending ||
    proposeInternalizeMut.isPending ||
    savingInternalize;

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

      <div className="grid min-h-0 flex-1 gap-4 px-6 py-4 lg:grid-cols-[minmax(0,1fr)_430px]">
        <div className="min-h-0 overflow-y-auto">
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
              <DigestCard
                key={draft.id}
                draft={draft}
                selected={draft.id === selectedId}
                onSelect={() => {
                  setSelectedId(draft.id);
                  setProposal(null);
                  setNotice(null);
                }}
              />
            ))}
          </div>
        </div>

        <aside className="min-h-0">
          {proposal ? (
            <div
              className="h-full min-h-[520px] overflow-hidden rounded-md border"
              style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
            >
              <DiffReview
                oldBody={proposal.old_body}
                newBody={proposal.new_body}
                saving={savingInternalize}
                onAccept={acceptInternalize}
                onReject={() => setProposal(null)}
              />
            </div>
          ) : selected ? (
            <DigestDetail
              draft={selected}
              busy={busy}
              notice={notice}
              onSkip={() => skipMut.mutate(selected)}
              onSaveReference={() => saveReferenceMut.mutate(selected)}
              onInternalize={() => proposeInternalizeMut.mutate(selected)}
            />
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

function DigestCard({
  draft,
  selected,
  onSelect,
}: {
  draft: DraftSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const { t } = useTranslation();
  const preview = (draft.body ?? "").trim();
  return (
    <article
      className="min-h-[150px] cursor-pointer rounded-md border p-4 outline-none"
      style={{
        borderColor: selected ? "var(--accent)" : "var(--line)",
        background: selected ? "var(--accent-tint-2)" : "var(--bg-1)",
      }}
      data-testid={`digest-card-${draft.id}`}
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
          onClick={(e) => e.stopPropagation()}
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

function DigestDetail({
  draft,
  busy,
  notice,
  onSkip,
  onSaveReference,
  onInternalize,
}: {
  draft: DraftSummary;
  busy: boolean;
  notice: string | null;
  onSkip: () => void;
  onSaveReference: () => void;
  onInternalize: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div
      className="flex h-full min-h-[520px] flex-col overflow-hidden rounded-md border"
      style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      data-testid="digest-detail"
    >
      <div className="border-b p-4" style={{ borderColor: "var(--line)" }}>
        <div className="mb-1 text-[10px] font-mono uppercase tracking-widest text-muted-foreground">
          {t("digest.detail")}
        </div>
        <h3 className="font-serif text-lg font-medium">
          {draft.title || t("digest.untitled")}
        </h3>
        {draft.source && (
          <a
            href={draft.source}
            target="_blank"
            rel="noreferrer"
            className="mt-2 flex items-center gap-1 truncate text-[11px] text-muted-foreground hover:text-foreground"
          >
            <ExternalLink className="size-3" />
            {draft.source}
          </a>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        <div className="whitespace-pre-wrap text-sm leading-relaxed">
          {draft.body || t("digest.bodyMissing")}
        </div>
        <DraftDiscussion draftId={draft.id} />
      </div>

      {notice && (
        <div
          className="border-t px-4 py-2 text-xs text-muted-foreground"
          style={{ borderColor: "var(--line)" }}
          data-testid="digest-action-notice"
        >
          {notice}
        </div>
      )}

      <div
        className="flex flex-wrap justify-end gap-2 border-t p-3"
        style={{ borderColor: "var(--line)" }}
      >
        <ActionButton
          icon={<Archive className="size-3.5" />}
          label={t("digest.skip")}
          onClick={onSkip}
          disabled={busy}
          testId="digest-action-skip"
        />
        <ActionButton
          icon={<BookOpenCheck className="size-3.5" />}
          label={t("digest.saveReference")}
          onClick={onSaveReference}
          disabled={busy}
          testId="digest-action-save-reference"
        />
        <ActionButton
          icon={<Brain className="size-3.5" />}
          label={busy ? t("digest.working") : t("digest.internalize")}
          onClick={onInternalize}
          disabled={busy}
          testId="digest-action-internalize"
          primary
        />
      </div>
    </div>
  );
}

function ActionButton({
  icon,
  label,
  onClick,
  disabled,
  testId,
  primary = false,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  disabled: boolean;
  testId: string;
  primary?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-1.5 rounded border px-2.5 py-1.5 text-xs disabled:opacity-50"
      style={{
        borderColor: primary ? "var(--accent)" : "var(--line)",
        background: primary ? "var(--accent-tint-2)" : "transparent",
        color: "var(--ink)",
      }}
      data-testid={testId}
    >
      {icon}
      {label}
    </button>
  );
}

function DraftDiscussion({ draftId }: { draftId: string }) {
  const { t } = useTranslation();
  const { messages, status, error, send, stop } = useDraftChat(draftId);
  const [input, setInput] = useState("");

  useEffect(() => {
    setInput("");
  }, [draftId]);

  const submit = () => {
    if (input.trim() && status !== "streaming") {
      send(input);
      setInput("");
    }
  };

  return (
    <div
      className="mt-5 rounded-md border"
      style={{ borderColor: "var(--line)" }}
      data-testid="digest-discussion"
    >
      <div
        className="border-b px-3 py-2 text-[10px] font-mono uppercase tracking-widest text-muted-foreground"
        style={{ borderColor: "var(--line)" }}
      >
        {t("digest.discuss")}
      </div>
      <div className="max-h-48 space-y-4 overflow-y-auto px-3 py-3">
        {messages.length === 0 && !error && (
          <div className="text-xs text-muted-foreground">
            {t("digest.chatEmpty")}
          </div>
        )}
        <ChatTranscript
          messages={messages}
          status={status}
          testPrefix="digest"
          generatingLabel={t("digest.working")}
        />
        {error && (
          <div className="text-xs" style={{ color: "var(--danger, #c0392b)" }}>
            {error}
          </div>
        )}
      </div>
      <div className="border-t p-2" style={{ borderColor: "var(--line)" }}>
        <textarea
          data-testid="digest-chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={t("digest.chatPlaceholder")}
          rows={2}
          className="w-full resize-none rounded-md border bg-transparent px-2 py-1.5 text-sm outline-none"
          style={{ borderColor: "var(--line)", color: "var(--ink)" }}
        />
        <div className="mt-1 flex justify-end">
          {status === "streaming" ? (
            <button
              type="button"
              onClick={stop}
              className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs"
              style={{ borderColor: "var(--line)" }}
              data-testid="digest-chat-stop"
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
              data-testid="digest-chat-send"
            >
              <Send className="size-3" />
              {t("digest.send")}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
