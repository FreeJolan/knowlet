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

import { ClipboardCheck, Pencil, Send, Sparkles, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  checkNote,
  proposeNoteEdit,
  type CheckNoteFinding,
  type CheckNoteReport,
} from "@/api/client";
import type { ApiError } from "@/api/types";
import { Button } from "@/components/ui/button";

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
      "请帮我基于这篇笔记提出一版更清晰但尽量少改动的修改建议，修改必须经过我确认后才能应用。",
  },
];

function renderCheckReportMarkdown(report: CheckNoteReport): string {
  if (report.findings.length === 0) {
    return `### 检查结果\n\n${report.summary || "没有发现能定位到段落的明确错漏。"}`;
  }
  const lines = [`### 检查结果`, "", report.summary, ""];
  for (const finding of report.findings) {
    const location =
      finding.paragraph !== null ? `第 ${finding.paragraph} 段` : "未定位段落";
    lines.push(
      `- **${finding.finding}**（${location}，${finding.severity}）`,
      `  - 原文：${finding.quote ? `“${finding.quote}”` : "未提供短引"}`,
      `  - 原因：${finding.why}`,
      `  - 建议：${finding.suggestion}`,
    );
  }
  return lines.join("\n");
}

function AssistantMarkdown({ content }: { content: string }) {
  return (
    <div className="kn-md prose-paper py-0" style={{ color: "var(--ink)" }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

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
  const {
    messages,
    status,
    error,
    send,
    stop,
    appendUserMessage,
    appendAssistantMessage,
  } = useNoteChat(noteId);
  const [input, setInput] = useState("");
  const [proposing, setProposing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkReport, setCheckReport] = useState<CheckNoteReport | null>(null);
  const [proposeMsg, setProposeMsg] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
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

  useEffect(() => {
    const el = scrollRef.current;
    if (el && followTail) el.scrollTo({ top: el.scrollHeight });
  }, [messages, followTail]);

  const handleMessageScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const distance = el.scrollHeight - el.scrollTop - el.clientHeight;
    setFollowTail(distance < 40);
  };

  const busy = status === "streaming" || proposing || checking;

  const focusComposerIfCurrent = (targetNoteId: string) => {
    if (latestNoteIdRef.current === targetNoteId) inputRef.current?.focus();
  };

  const submit = () => {
    if (input.trim() && status !== "streaming") {
      setFollowTail(true);
      send(input);
      setInput("");
    }
  };

  const runSuggestion = async (action: SuggestionAction, prompt: string) => {
    if (!noteId || busy) return;
    setFollowTail(true);
    setCheckReport(null);
    setProposeMsg(null);
    appendUserMessage(prompt, noteId);
    if (action === "check") {
      setChecking(true);
      try {
        const res = await checkNote(noteId, { instruction: prompt });
        if (latestNoteIdRef.current === noteId) setCheckReport(res);
        appendAssistantMessage(renderCheckReportMarkdown(res), noteId);
      } catch (e) {
        const detail = (e as ApiError)?.detail ?? "出错了";
        appendAssistantMessage(`检查失败：${detail}`, noteId);
      } finally {
        setChecking(false);
        focusComposerIfCurrent(noteId);
      }
      return;
    }
    setProposing(true);
    try {
      const res = await proposeNoteEdit(noteId, prompt);
      if (res.changed) {
        if (latestNoteIdRef.current === noteId) {
          onProposeEdit?.({ oldBody: res.old_body, newBody: res.new_body });
        }
        appendAssistantMessage(
          "我提出了一版最小修改，已经打开 diff review。你确认后才会写入笔记。",
          noteId,
        );
      } else {
        appendAssistantMessage(res.reason || "我没有找到值得应用的明确改动。", noteId);
      }
    } catch (e) {
      const detail = (e as ApiError)?.detail ?? "出错了";
      appendAssistantMessage(`提议失败：${detail}`, noteId);
    } finally {
      setProposing(false);
      focusComposerIfCurrent(noteId);
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
        onScroll={handleMessageScroll}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3"
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
                  onClick={() => runSuggestion(suggestion.id, suggestion.prompt)}
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
        {messages.map((m, i) => (
          <div key={i} data-testid={`discuss-message-${m.role}`} className="text-sm">
            <div
              className="mb-1 text-[10px] font-mono uppercase tracking-wide"
              style={{ color: "var(--ink-mute)" }}
            >
              {m.role === "user" ? "你" : "AI"}
            </div>
            <div className="max-w-none" style={{ color: "var(--ink)" }}>
              {m.role === "assistant" ? (
                <AssistantMarkdown content={m.content} />
              ) : (
                <p className="whitespace-pre-wrap break-words">{m.content}</p>
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
