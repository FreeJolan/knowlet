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

import { ClipboardCheck, Pencil, Send, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

import {
  checkNote,
  proposeNoteEdit,
  type CheckNoteFinding,
  type CheckNoteReport,
} from "@/api/client";
import type { ApiError } from "@/api/types";
import { Button } from "@/components/ui/button";

import { useNoteChat } from "./useNoteChat";

export function DiscussPane({
  noteId,
  noteTitle,
  onClose,
  onProposeEdit,
}: {
  noteId: string | null;
  noteTitle?: string;
  onClose: () => void;
  /** P3: AI proposed a minimal revision — hand it up for the diff UI. */
  onProposeEdit?: (proposal: { oldBody: string; newBody: string }) => void;
}) {
  const { messages, status, error, send, stop } = useNoteChat(noteId);
  const [input, setInput] = useState("");
  const [proposing, setProposing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkReport, setCheckReport] = useState<CheckNoteReport | null>(null);
  const [proposeMsg, setProposeMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, [noteId]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight });
  }, [messages]);

  const submit = () => {
    if (input.trim() && status !== "streaming") {
      send(input);
      setInput("");
    }
  };

  const doPropose = async () => {
    const text = input.trim();
    if (!text || !noteId || proposing) return;
    setProposing(true);
    setProposeMsg(null);
    try {
      const res = await proposeNoteEdit(noteId, text);
      if (res.changed) {
        onProposeEdit?.({ oldBody: res.old_body, newBody: res.new_body });
        setInput("");
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

  const doCheck = async () => {
    if (!noteId || checking || status === "streaming") return;
    setChecking(true);
    setProposeMsg(null);
    try {
      const res = await checkNote(noteId, { standard_answer: input.trim() });
      setCheckReport(res);
    } catch (e) {
      const detail = (e as ApiError)?.detail ?? "出错了";
      setProposeMsg(`查这篇失败：${detail}`);
    } finally {
      setChecking(false);
    }
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

  const busy = status === "streaming" || proposing || checking;

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

      <div
        ref={scrollRef}
        data-testid="discuss-messages"
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3"
      >
        {messages.length === 0 && !error && (
          <div
            data-testid="discuss-empty"
            className="text-sm"
            style={{ color: "var(--ink-mute)" }}
          >
            就这篇笔记问点什么——它已经读过你写的内容。
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} data-testid={`discuss-message-${m.role}`} className="text-sm">
            <div
              className="mb-1 text-[10px] font-mono uppercase tracking-wide"
              style={{ color: "var(--ink-mute)" }}
            >
              {m.role === "user" ? "你" : "AI"}
            </div>
            <div className="prose prose-sm max-w-none" style={{ color: "var(--ink)" }}>
              {m.role === "assistant" ? (
                <ReactMarkdown>{m.content}</ReactMarkdown>
              ) : (
                <p className="whitespace-pre-wrap">{m.content}</p>
              )}
            </div>
          </div>
        ))}
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

      <div className="shrink-0 border-t p-2" style={{ borderColor: "var(--line)" }}>
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
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="聊聊这篇…（Enter 发送，Shift+Enter 换行）"
          rows={2}
          className="w-full resize-none rounded-md border bg-transparent px-2 py-1.5 text-sm outline-none"
          style={{ borderColor: "var(--line)", color: "var(--ink)" }}
        />
        <div className="mt-1 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              data-testid="discuss-check"
              title="按输入里的标准答案/校准依据检查这篇笔记"
              disabled={busy || !noteId}
              onClick={doCheck}
            >
              <ClipboardCheck className="mr-1 size-3" />
              {checking ? "…" : "查这篇"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              data-testid="discuss-propose"
              title="让 AI 按你的输入给出这篇笔记的最小修改，再由你审 diff"
              disabled={!input.trim() || busy}
              onClick={doPropose}
            >
              <Pencil className="mr-1 size-3" />
              {proposing ? "…" : "改这篇"}
            </Button>
          </div>
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
        查这篇
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
