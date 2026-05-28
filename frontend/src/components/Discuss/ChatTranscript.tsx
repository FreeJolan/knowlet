import { ChevronDown, CircleDashed } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { ChatMarkdown } from "./ChatMarkdown";
import { ToolTrace } from "./ToolTrace";
import type { ChatMessage, ChatStatus } from "./useNoteChat";

type ChatRenderItem =
  | { type: "user"; message: ChatMessage }
  | {
      type: "assistant";
      assistant?: ChatMessage;
      tools: ChatMessage[];
    };

export function groupChatMessages(messages: ChatMessage[]): ChatRenderItem[] {
  const grouped: ChatRenderItem[] = [];
  for (let i = 0; i < messages.length; i += 1) {
    const message = messages[i];
    if (!message) continue;
    if (message.role === "user") {
      grouped.push({ type: "user", message });
      continue;
    }
    if (message.role === "tool") {
      const tools: ChatMessage[] = [];
      while (messages[i]?.role === "tool") {
        const toolMessage = messages[i];
        if (toolMessage) tools.push(toolMessage);
        i += 1;
      }
      const assistant =
        messages[i]?.role === "assistant" ? messages[i] : undefined;
      grouped.push({ type: "assistant", assistant, tools });
      continue;
    }
    grouped.push({ type: "assistant", assistant: message, tools: [] });
  }
  return grouped;
}

function GeneratingIndicator({
  testPrefix,
  label,
}: {
  testPrefix: string;
  label: string;
}) {
  return (
    <div
      data-testid={`${testPrefix}-generating`}
      role="status"
      aria-live="polite"
      className="inline-flex items-center gap-2 rounded-md border px-2.5 py-1.5 text-xs"
      style={{
        background: "var(--bg-1)",
        borderColor: "var(--line)",
        color: "var(--ink-mute)",
      }}
    >
      <span>{label}</span>
      <span className="flex items-center gap-1" aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="size-1.5 animate-bounce rounded-full"
            style={{
              animationDelay: `${i * 120}ms`,
              background: "var(--ink-mute)",
            }}
          />
        ))}
      </span>
    </div>
  );
}

function TracePanel({
  tools,
  testPrefix,
  active,
}: {
  tools: ChatMessage[];
  testPrefix: string;
  active: boolean;
}) {
  const failed = tools.some((message) => message.tool?.status === "error");
  const calling = tools.some((message) => message.tool?.status === "calling");
  const shouldAutoOpen = active || calling || failed;
  const [open, setOpen] = useState(shouldAutoOpen);

  useEffect(() => {
    setOpen(shouldAutoOpen);
  }, [shouldAutoOpen]);

  const toolCount = tools.length;
  const summary = calling
    ? `正在调用 ${toolCount} 个工具`
    : failed
      ? `过程有错误 · ${toolCount} 个工具`
      : `已完成 ${toolCount} 个工具`;

  return (
    <details
      data-testid={`${testPrefix}-trace-panel`}
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className="group/trace rounded-md border text-xs"
      style={{
        background: "var(--bg-1)",
        borderColor: "var(--line)",
        color: "var(--ink-mute)",
      }}
    >
      <summary
        data-testid={`${testPrefix}-trace-toggle`}
        className="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2"
      >
        <ChevronDown className="size-3.5 shrink-0 transition-transform group-open/trace:rotate-180" />
        <CircleDashed className="size-3.5 shrink-0" />
        <span className="font-mono uppercase tracking-wide">过程</span>
        <span className="min-w-0 truncate">{summary}</span>
      </summary>
      <div data-testid={`${testPrefix}-trace-body`} className="space-y-2 px-2 pb-2">
        {tools.map((message, index) =>
          message.tool ? (
            <ToolTrace key={`${message.tool.id}-${index}`} trace={message.tool} />
          ) : null,
        )}
      </div>
    </details>
  );
}

export function ChatTranscript({
  messages,
  status,
  testPrefix,
  generatingLabel = "正在生成",
}: {
  messages: ChatMessage[];
  status: ChatStatus;
  testPrefix: string;
  generatingLabel?: string;
}) {
  const items = useMemo(() => groupChatMessages(messages), [messages]);

  return (
    <>
      {items.map((item, index) => {
        if (item.type === "user") {
          return (
            <div
              key={`user-${index}`}
              data-testid={`${testPrefix}-message-user`}
              className="flex justify-end"
            >
              <div
                data-testid={`${testPrefix}-user-bubble`}
                className="min-w-0 max-w-[82%] rounded-2xl rounded-tr-md border px-3 py-2 shadow-sm"
                style={{
                  background: "var(--accent-tint)",
                  borderColor: "var(--accent-soft)",
                  color: "var(--ink)",
                }}
              >
                <ChatMarkdown content={item.message.content} />
              </div>
            </div>
          );
        }

        const isLast = index === items.length - 1;
        const pendingAssistant =
          item.assistant?.content === "" && status === "streaming" && isLast;
        const hasAnswer = Boolean(item.assistant?.content);
        const active = status === "streaming" && isLast && !hasAnswer;

        return (
          <div
            key={`assistant-${index}`}
            data-testid={`${testPrefix}-message-assistant`}
            className="flex justify-start"
          >
            <div className="min-w-0 max-w-[92%] space-y-2" style={{ color: "var(--ink)" }}>
              {item.tools.length > 0 && (
                <TracePanel
                  tools={item.tools}
                  testPrefix={testPrefix}
                  active={active}
                />
              )}
              {pendingAssistant ? (
                <GeneratingIndicator
                  testPrefix={testPrefix}
                  label={generatingLabel}
                />
              ) : hasAnswer ? (
                <div data-testid={`${testPrefix}-answer`}>
                  <ChatMarkdown content={item.assistant?.content ?? ""} />
                </div>
              ) : null}
            </div>
          </div>
        );
      })}
    </>
  );
}
