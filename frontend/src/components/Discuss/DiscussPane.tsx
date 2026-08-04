/**
 * Note-anchored discussion pane (Phase 3 Stage 4 P1 / P3).
 *
 * Cursor-style "chat about this note": opens beside the NoteView,
 * grounded in the note the user is looking at. The AI infers its tone
 * from the note's nature (gentle for a journal, sharp for a paper) —
 * there is no user-selected stance. "改这篇" (P3) asks the AI for a
 * minimal revision and hands it up as a diff to review + accept (P4);
 * nothing is written from here.
 */

import {
  ClipboardCheck,
  GripHorizontal,
  Maximize2,
  Pencil,
  RotateCcw,
  Send,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  proposeNoteEdit,
  type CheckNoteFinding,
  type CheckNoteReport,
} from "@/api/client";
import type { ApiError } from "@/api/types";
import { Button } from "@/components/ui/button";
import { imeSafeKeyHandler } from "@/lib/imeSafe";

import { ChatTranscript } from "./ChatTranscript";
import { useNoteChat } from "./useNoteChat";

type SuggestionAction = "check" | "propose";

const DISCUSS_SUGGESTIONS: Array<{
  id: SuggestionAction;
  label: string;
  prompt: string;
}> = [
  {
    id: "check",
    label: "看看笔记是否有错漏",
    prompt:
      "帮我看看这篇笔记是否有不对的地方、关键遗漏或站不住的推理。请先指出问题，不要直接改正文。",
  },
  {
    id: "propose",
    label: "提出一版更清晰的改写",
    prompt:
      "请为这篇笔记生成一个可在 diff 中审阅的最小改写提案：在尽量保留原意的前提下，让结构更清楚、表达更准确，并删掉口语化或含混的表达。不要直接把整篇改写正文贴在聊天里，修改必须等我确认后才能应用。",
  },
];

const COMPOSER_MIN_HEIGHT = 112;
const COMPOSER_DEFAULT_HEIGHT = 156;
const COMPOSER_MAX_HEIGHT = 300;

function clampComposerHeight(value: number): number {
  return Math.min(COMPOSER_MAX_HEIGHT, Math.max(COMPOSER_MIN_HEIGHT, value));
}

function markdownContinuation(
  value: string,
  selectionStart: number,
  selectionEnd: number,
): { value: string; caret: number } | null {
  if (selectionStart !== selectionEnd) return null;
  const lineStart = value.lastIndexOf("\n", selectionStart - 1) + 1;
  const line = value.slice(lineStart, selectionStart);

  const ordered = line.match(/^(\s*)(\d+)([.)])\s+(.*)$/);
  if (ordered) {
    const [, indent = "", numberText = "0", delimiter = ".", rest = ""] = ordered;
    const replacement =
      rest.trim().length === 0
        ? "\n"
        : `\n${indent}${Number(numberText) + 1}${delimiter} `;
    return insertAtSelection(value, selectionStart, selectionEnd, replacement);
  }

  const task = line.match(/^(\s*)([-*+])\s+\[[ xX]\]\s+(.*)$/);
  if (task) {
    const [, indent = "", bullet = "-", rest = ""] = task;
    const replacement = rest.trim().length === 0 ? "\n" : `\n${indent}${bullet} [ ] `;
    return insertAtSelection(value, selectionStart, selectionEnd, replacement);
  }

  const unordered = line.match(/^(\s*)([-*+])\s+(.*)$/);
  if (unordered) {
    const [, indent = "", bullet = "-", rest = ""] = unordered;
    const replacement = rest.trim().length === 0 ? "\n" : `\n${indent}${bullet} `;
    return insertAtSelection(value, selectionStart, selectionEnd, replacement);
  }

  return null;
}

function insertAtSelection(
  value: string,
  selectionStart: number,
  selectionEnd: number,
  insertion: string,
): { value: string; caret: number } {
  return {
    value: `${value.slice(0, selectionStart)}${insertion}${value.slice(selectionEnd)}`,
    caret: selectionStart + insertion.length,
  };
}

export function DiscussPane({
  noteId,
  noteTitle,
  onClose,
  onProposeEdit,
  pendingEdit,
  onApplyEdit,
}: {
  noteId: string | null;
  noteTitle?: string;
  onClose: () => void;
  /** P3: AI proposed a minimal revision — hand it up for the diff UI. */
  onProposeEdit?: (proposal: { oldBody: string; newBody: string }) => void;
  pendingEdit?: { oldBody: string; newBody: string } | null;
  /** Called after the backend confirms that the pending diff was applied. */
  onApplyEdit?: () => void;
}) {
  const {
    messages,
    status,
    error,
    proposal,
    applied,
    send,
    stop,
    reset,
    clearProposal,
    clearApplied,
  } = useNoteChat(noteId);
  const [input, setInput] = useState("");
  const [composerHeight, setComposerHeight] = useState(COMPOSER_DEFAULT_HEIGHT);
  const [longFormOpen, setLongFormOpen] = useState(false);
  const [proposing, setProposing] = useState(false);
  const [checkReport, setCheckReport] = useState<CheckNoteReport | null>(null);
  const [proposeMsg, setProposeMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const longFormRef = useRef<HTMLTextAreaElement>(null);
  const pendingCaretRef = useRef<{
    target: HTMLTextAreaElement;
    caret: number;
  } | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const latestNoteIdRef = useRef<string | null>(noteId);
  const [followTail, setFollowTail] = useState(true);

  useEffect(() => {
    latestNoteIdRef.current = noteId;
    inputRef.current?.focus();
    setFollowTail(true);
    setCheckReport(null);
    setProposeMsg(null);
  }, [noteId]);

  useLayoutEffect(() => {
    const pendingCaret = pendingCaretRef.current;
    if (!pendingCaret) return;
    pendingCaret.target.setSelectionRange(pendingCaret.caret, pendingCaret.caret);
    pendingCaretRef.current = null;
  }, [input]);

  useEffect(() => {
    if (!longFormOpen) return;
    const handle = window.setTimeout(() => {
      longFormRef.current?.focus();
      const end = longFormRef.current?.value.length ?? 0;
      longFormRef.current?.setSelectionRange(end, end);
    }, 0);
    return () => window.clearTimeout(handle);
  }, [longFormOpen]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el && followTail) el.scrollTo({ top: el.scrollHeight });
  }, [messages, followTail]);

  useEffect(() => {
    if (!noteId || !proposal || proposal.noteId !== noteId) return;
    if (proposal.changed) {
      onProposeEdit?.({ oldBody: proposal.oldBody, newBody: proposal.newBody });
      setProposeMsg(proposal.summary || "已生成可审阅的修改提案。");
    } else {
      setProposeMsg(proposal.reason || proposal.summary || "无可应用改动");
    }
    clearProposal(noteId);
  }, [clearProposal, noteId, onProposeEdit, proposal]);

  useEffect(() => {
    if (!noteId || !applied || applied.noteId !== noteId) return;
    onApplyEdit?.();
    setProposeMsg(applied.summary || "已应用当前修改。");
    clearApplied(noteId);
  }, [applied, clearApplied, noteId, onApplyEdit]);

  const handleMessageScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    setFollowTail(distance < 40);
  };

  const busy = status === "streaming" || proposing;
  const canReset = Boolean(
    noteId && !proposing && (messages.length > 0 || error),
  );

  const focusComposerIfCurrent = (targetNoteId: string) => {
    if (latestNoteIdRef.current === targetNoteId) inputRef.current?.focus();
  };

  const submit = () => {
    if (input.trim() && status !== "streaming") {
      setFollowTail(true);
      send(input, { pendingEdit });
      setInput("");
    }
  };

  const applyTextareaValue = (
    next: { value: string; caret: number },
    target: HTMLTextAreaElement,
  ) => {
    pendingCaretRef.current = { target, caret: next.caret };
    setInput(next.value);
  };

  const closeLongForm = () => {
    setLongFormOpen(false);
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };

  const handleComposerResizeStart = (e: ReactPointerEvent<HTMLButtonElement>) => {
    e.preventDefault();
    const startY = e.clientY;
    const startHeight = composerHeight;
    const onMove = (event: PointerEvent) => {
      setComposerHeight(clampComposerHeight(startHeight + startY - event.clientY));
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  const runSuggestion = (prompt: string) => {
    if (!noteId || busy) return;
    setFollowTail(true);
    setCheckReport(null);
    setProposeMsg(null);
    send(prompt, { pendingEdit });
    focusComposerIfCurrent(noteId);
  };

  const resetConversation = () => {
    if (!noteId || !canReset) return;
    reset(noteId);
    setInput("");
    setCheckReport(null);
    setProposeMsg(null);
    setFollowTail(true);
    inputRef.current?.focus();
  };

  const doFixFinding = async (finding: CheckNoteFinding) => {
    if (!noteId || proposing) return;
    const text = finding.fix_instruction.trim() || finding.suggestion.trim();
    if (!text) {
      setProposeMsg("这条报告没有可用的修正指令");
      return;
    }
    setProposing(true);
    setProposeMsg(null);
    try {
      const res = await proposeNoteEdit(noteId, text);
      if (res.changed) {
        onProposeEdit?.({ oldBody: res.old_body, newBody: res.new_body });
      } else {
        setProposeMsg(res.reason || "无可应用改动");
      }
    } catch (e) {
      const detail = (e as ApiError)?.detail ?? "出错了";
      setProposeMsg(`提议失败：${detail}`);
    } finally {
      setProposing(false);
    }
  };

  return (
    <div
      data-testid="discuss-pane"
      className="flex h-full min-h-0 flex-col"
      style={{ background: "var(--panel)" }}
    >
      <div
        className="flex shrink-0 items-center justify-between border-b px-3 py-2"
        style={{ borderColor: "var(--line)" }}
      >
        <div className="min-w-0">
          <div
            className="text-[10px] font-mono uppercase tracking-widest"
            style={{ color: "var(--ink-mute)" }}
          >
            对谈
          </div>
          <div
            data-testid="discuss-anchor-title"
            className="truncate text-sm"
            style={{ color: "var(--ink)" }}
            title={noteTitle}
          >
            {noteTitle || "—"}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            aria-label="重置对话"
            data-testid="discuss-reset"
            title="重置当前笔记的对话"
            disabled={!canReset}
            onClick={resetConversation}
          >
            <RotateCcw className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="关闭对谈"
            data-testid="discuss-close"
            onClick={onClose}
          >
            <X className="size-4" />
          </Button>
        </div>
      </div>

      <div
        ref={scrollRef}
        data-testid="discuss-messages"
        onScroll={handleMessageScroll}
        className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3"
      >
        {messages.length === 0 && !error && (
          <div data-testid="discuss-empty" className="space-y-3">
            <div className="text-sm" style={{ color: "var(--ink-mute)" }}>
              就这篇笔记问点什么——它已经读过你写的内容。
            </div>
            <div className="flex flex-wrap gap-2">
              {DISCUSS_SUGGESTIONS.map((suggestion) => (
                <Button
                  key={suggestion.id}
                  size="sm"
                  variant="ghost"
                  className="max-w-full min-w-0 shrink justify-start overflow-hidden"
                  data-testid={`discuss-suggestion-${suggestion.id}`}
                  disabled={busy || !noteId}
                  onClick={() => runSuggestion(suggestion.prompt)}
                  title={suggestion.prompt}
                >
                  {suggestion.id === "check" ? (
                    <ClipboardCheck className="size-3 shrink-0" />
                  ) : (
                    <Sparkles className="size-3 shrink-0" />
                  )}
                  <span className="min-w-0 truncate">{suggestion.label}</span>
                </Button>
              ))}
            </div>
          </div>
        )}
        <ChatTranscript
          messages={messages}
          status={status}
          testPrefix="discuss"
        />
        {error && (
          <div
            data-testid="discuss-error"
            className="rounded-md px-3 py-2 text-sm"
            style={{
              background: "var(--danger-tint, rgba(200,60,60,0.12))",
              color: "var(--danger, #c0392b)",
            }}
          >
            对谈出错：{error}
          </div>
        )}
        {checkReport && (
          <CheckNoteReportView
            report={checkReport}
            onFix={doFixFinding}
            busy={busy}
          />
        )}
      </div>

      <div
        data-testid="discuss-composer-shell"
        className="relative flex shrink-0 flex-col border-t p-2"
        style={{
          borderColor: "var(--line)",
          height: composerHeight,
        }}
      >
        <button
          type="button"
          aria-label="调整输入框高度"
          data-testid="discuss-composer-resize-handle"
          onPointerDown={handleComposerResizeStart}
          className="absolute left-2 right-2 top-0 flex h-3 -translate-y-1/2 cursor-ns-resize items-center justify-center rounded-sm text-muted-foreground hover:bg-accent/20"
          title="拖拽调整输入框高度"
        >
          <GripHorizontal className="size-4" />
        </button>
        {proposeMsg && (
          <div
            data-testid="discuss-propose-msg"
            className="mb-1 text-xs"
            style={{ color: "var(--ink-mute)" }}
          >
            {proposeMsg}
          </div>
        )}
        <textarea
          ref={inputRef}
          data-testid="discuss-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={imeSafeKeyHandler<HTMLTextAreaElement>((e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              const next = markdownContinuation(
                input,
                e.currentTarget.selectionStart,
                e.currentTarget.selectionEnd,
              );
              if (next) {
                applyTextareaValue(next, e.currentTarget);
                return;
              }
              submit();
            }
          })}
          placeholder="聊聊这篇…（Enter 发送，Shift+Enter 换行）"
          className="min-h-0 w-full flex-1 resize-none rounded-md border bg-transparent py-1.5 pl-2 pr-9 text-sm outline-none"
          style={{ borderColor: "var(--line)", color: "var(--ink)" }}
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label="打开长文本输入"
          data-testid="discuss-longform-open"
          title="打开长文本输入"
          className="absolute bottom-11 right-3 size-7"
          onClick={() => setLongFormOpen(true)}
        >
          <Maximize2 className="size-3.5" />
        </Button>
        <div className="mt-1 flex items-center justify-end gap-2">
          {status === "streaming" ? (
            <Button
              size="sm"
              variant="ghost"
              data-testid="discuss-stop"
              title="停止生成"
              onClick={stop}
            >
              <Square className="mr-1 size-3" />
              停止
            </Button>
          ) : (
            <Button
              size="sm"
              data-testid="discuss-send"
              disabled={!input.trim() || busy}
              onClick={submit}
            >
              <Send className="mr-1 size-3" />
              发送
            </Button>
          )}
        </div>
      </div>
      {longFormOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 px-4 py-6"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeLongForm();
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            data-testid="discuss-longform-dialog"
            className="flex w-[min(760px,calc(100vw-32px))] max-w-full flex-col rounded-lg border shadow-2xl"
            style={{
              height: "min(68vh, 620px)",
              background: "var(--panel)",
              borderColor: "var(--line)",
            }}
          >
            <div
              className="flex shrink-0 items-center justify-between border-b px-3 py-2"
              style={{ borderColor: "var(--line)" }}
            >
              <div
                className="font-mono text-[10px] uppercase tracking-widest"
                style={{ color: "var(--ink-mute)" }}
              >
                长文本
              </div>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="关闭长文本输入"
                onClick={closeLongForm}
              >
                <X className="size-4" />
              </Button>
            </div>
            <textarea
              ref={longFormRef}
              data-testid="discuss-longform-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={imeSafeKeyHandler<HTMLTextAreaElement>((e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  closeLongForm();
                  return;
                }
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  const next =
                    markdownContinuation(
                      input,
                      e.currentTarget.selectionStart,
                      e.currentTarget.selectionEnd,
                    ) ??
                    insertAtSelection(
                      input,
                      e.currentTarget.selectionStart,
                      e.currentTarget.selectionEnd,
                      "\n",
                    );
                  applyTextareaValue(next, e.currentTarget);
                }
              })}
              className="min-h-0 flex-1 resize-none bg-transparent p-4 text-sm leading-6 outline-none"
              style={{ color: "var(--ink)" }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function CheckNoteReportView({
  report,
  onFix,
  busy,
}: {
  report: CheckNoteReport;
  onFix: (finding: CheckNoteFinding) => void;
  busy: boolean;
}) {
  return (
    <div
      data-testid="check-note-report"
      className="rounded-md border p-3 text-sm"
      style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
    >
      <div
        className="mb-2 text-[10px] font-mono uppercase tracking-wide"
        style={{ color: "var(--ink-mute)" }}
      >
        检查结果
      </div>
      <div className="mb-3" style={{ color: "var(--ink)" }}>
        {report.summary}
      </div>
      {report.findings.length === 0 ? (
        <div className="text-xs" style={{ color: "var(--ink-mute)" }}>
          没有发现能定位到段落的明确错漏。
        </div>
      ) : (
        <div className="space-y-3">
          {report.findings.map((finding, index) => (
            <div
              key={`${finding.paragraph ?? "x"}-${index}`}
              className="rounded border p-2"
              style={{ borderColor: "var(--line)" }}
              data-testid={`check-note-finding-${index}`}
            >
              <div className="mb-1 flex items-center justify-between gap-2">
                <div className="text-xs font-medium" style={{ color: "var(--ink)" }}>
                  {finding.finding}
                </div>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {finding.paragraph !== null
                    ? `paragraph ${finding.paragraph}`
                    : "paragraph ?"}
                </span>
              </div>
              {finding.quote && (
                <blockquote
                  className="mb-2 border-l-2 pl-2 text-xs italic"
                  style={{ borderColor: "var(--line)", color: "var(--ink-mute)" }}
                >
                  {finding.quote}
                </blockquote>
              )}
              <div className="space-y-1 text-xs" style={{ color: "var(--ink)" }}>
                <div>{finding.why}</div>
                <div>{finding.suggestion}</div>
              </div>
              <div className="mt-2 flex justify-end">
                <Button
                  size="sm"
                  variant="ghost"
                  data-testid={`check-note-fix-${index}`}
                  disabled={busy}
                  onClick={() => onFix(finding)}
                >
                  <Pencil className="mr-1 size-3" />
                  修正
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
