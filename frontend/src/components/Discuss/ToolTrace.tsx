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
