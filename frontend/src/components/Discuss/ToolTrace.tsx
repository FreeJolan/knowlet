import { AlertCircle, CheckCircle2, Wrench } from "lucide-react";

import type { ChatToolTrace } from "./useNoteChat";

function shortJson(value: unknown): string {
  try {
    const text = JSON.stringify(value);
    return text.length > 180 ? `${text.slice(0, 177)}...` : text;
  } catch {
    return String(value);
  }
}

export function summarizeToolPayload(name: string, payload: unknown): string {
  if (!payload || typeof payload !== "object") return "";
  const obj = payload as Record<string, unknown>;
  if (typeof obj.error === "string") return obj.error;
  if (obj.kind === "note_edit_proposal") {
    if (obj.changed === false) {
      return typeof obj.reason === "string" && obj.reason
        ? obj.reason
        : "没有可应用改动";
    }
    return typeof obj.summary === "string" && obj.summary
      ? obj.summary
      : "已生成可审阅的修改提案";
  }
  if (obj.kind === "note_edit_applied") {
    return typeof obj.summary === "string" && obj.summary
      ? obj.summary
      : "已应用当前修改";
  }
  if (obj.kind === "note_edit_apply_rejected") {
    return typeof obj.error === "string" && obj.error
      ? obj.error
      : "无法应用当前修改";
  }
  if (obj.kind === "draft_edit_proposal") {
    if (obj.changed === false) {
      return typeof obj.reason === "string" && obj.reason
        ? obj.reason
        : "没有可应用到草稿的改动";
    }
    return typeof obj.summary === "string" && obj.summary
      ? obj.summary
      : "已生成可审阅的草稿 diff";
  }
  if (obj.kind === "draft_diff_accepted") return "已接受草稿 diff";
  if (obj.kind === "draft_diff_rejected") return "已撤回草稿 diff";
  if (obj.kind === "note_draft_committed") return "已落库为正式笔记";
  if (Array.isArray(obj.findings) && typeof obj.summary === "string") {
    return `${obj.findings.length} 个发现 · ${obj.summary}`;
  }
  if (Array.isArray(obj.results)) {
    const first = obj.results[0] as Record<string, unknown> | undefined;
    const title = typeof first?.title === "string" ? ` · ${first.title}` : "";
    return `${obj.results.length} result(s)${title}`;
  }
  if (typeof obj.title === "string") return obj.title;
  if (typeof obj.content === "string") return obj.content.slice(0, 180);
  if (typeof obj.body === "string") return obj.body.slice(0, 180);
  return `${name}: ${shortJson(payload)}`;
}

export function ToolTrace({ trace }: { trace: ChatToolTrace }) {
  const failed = trace.status === "error";
  const done = trace.status === "done";
  return (
    <div
      data-testid={`tool-trace-${trace.name}`}
      className="rounded-md border px-2.5 py-2 text-xs"
      style={{
        borderColor: "var(--line)",
        background: "var(--bg-1)",
        color: "var(--ink-mute)",
      }}
    >
      <div className="flex items-center gap-2">
        {failed ? (
          <AlertCircle className="size-3.5 text-red-600" />
        ) : done ? (
          <CheckCircle2 className="size-3.5 text-emerald-600" />
        ) : (
          <Wrench className="size-3.5" />
        )}
        <span className="font-mono uppercase tracking-wide">
          {trace.status === "calling" ? "调用工具" : failed ? "工具失败" : "工具完成"}
        </span>
        <span className="font-mono" style={{ color: "var(--ink)" }}>
          {trace.name}
        </span>
      </div>
      {Object.keys(trace.arguments ?? {}).length > 0 && (
        <div className="mt-1 break-words font-mono text-[10px]">
          {shortJson(trace.arguments)}
        </div>
      )}
      {trace.resultSummary && (
        <div className="mt-1 break-words" style={{ color: "var(--ink)" }}>
          {trace.resultSummary}
        </div>
      )}
    </div>
  );
}
