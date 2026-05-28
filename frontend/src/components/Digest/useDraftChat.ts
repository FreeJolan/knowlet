/**
 * Draft-anchored discussion for Stage C3.
 *
 * Digest items are still Drafts while the user decides what to keep.
 * This hook mirrors useNoteChat but targets `/api/chat/draft/{id}/stream`,
 * so discussion does not require promoting the draft to a Note first.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  applyToolResult,
  chatHistoryForRequest,
  formatErrorDetail,
  type ChatMessage,
  type ChatSSEEvent,
  type ChatStatus,
  upsertToolCall,
} from "@/components/Discuss";

export function useDraftChat(draftId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    if (!draftId) {
      setMessages([]);
      return;
    }
    try {
      const raw = window.localStorage.getItem(`knowlet.digest.discuss.${draftId}`);
      setMessages(raw ? (JSON.parse(raw) as ChatMessage[]) : []);
    } catch {
      setMessages([]);
    }
    setError(null);
    setStatus("idle");
  }, [draftId]);

  useEffect(() => {
    if (!draftId) return;
    try {
      if (messages.length > 0) {
        window.localStorage.setItem(
          `knowlet.digest.discuss.${draftId}`,
          JSON.stringify(messages),
        );
      } else {
        window.localStorage.removeItem(`knowlet.digest.discuss.${draftId}`);
      }
    } catch {
      /* localStorage unavailable / over quota — non-fatal */
    }
  }, [draftId, messages]);

  const dropEmptyAssistant = (m: ChatMessage[]): ChatMessage[] => {
    const last = m[m.length - 1];
    if (last && last.role === "assistant" && last.content === "")
      return m.slice(0, -1);
    return m;
  };

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("idle");
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !draftId || status === "streaming") return;
      const history = chatHistoryForRequest(messagesRef.current);
      setError(null);
      setMessages((m) => [
        ...m,
        { role: "user", content: trimmed },
        { role: "assistant", content: "" },
      ]);
      setStatus("streaming");
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      try {
        const r = await fetch(
          `/api/chat/draft/${encodeURIComponent(draftId)}/stream`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text: trimmed, history }),
            signal: ctrl.signal,
          },
        );
        if (!r.ok || !r.body) {
          let detail = r.statusText;
          try {
            const d = (await r.json()) as { detail?: unknown };
            if (d?.detail) detail = formatErrorDetail(d.detail);
          } catch {
            // body was not JSON
          }
          setError(detail || "request failed");
          setStatus("error");
          setMessages(dropEmptyAssistant);
          return;
        }
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        let streamError: string | null = null;
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buf.indexOf("\n\n")) !== -1) {
            const block = buf.slice(0, idx).trim();
            buf = buf.slice(idx + 2);
            if (!block.startsWith("data:")) continue;
            let ev: ChatSSEEvent;
            try {
              ev = JSON.parse(block.slice(5).trim()) as ChatSSEEvent;
            } catch {
              continue;
            }
            if (ev.type === "reply_chunk" && ev.text) {
              const chunk = ev.text;
              setMessages((m) => {
                const copy = m.slice();
                const last = copy[copy.length - 1];
                if (last && last.role === "assistant")
                  copy[copy.length - 1] = {
                    ...last,
                    content: last.content + chunk,
                  };
                return copy;
              });
            } else if (ev.type === "tool_call") {
              setMessages((m) => upsertToolCall(m, ev));
            } else if (ev.type === "tool_result") {
              setMessages((m) => applyToolResult(m, ev));
            } else if (ev.type === "error") {
              streamError = formatErrorDetail(ev.message || "stream error");
            }
          }
        }
        if (streamError) {
          setError(streamError);
          setStatus("error");
          setMessages(dropEmptyAssistant);
        } else {
          setStatus("idle");
        }
      } catch (e) {
        if ((e as Error).name === "AbortError") {
          setStatus("idle");
          return;
        }
        setError((e as Error).message || "network error");
        setStatus("error");
        setMessages(dropEmptyAssistant);
      } finally {
        abortRef.current = null;
      }
    },
    [draftId, status],
  );

  return { messages, status, error, send, stop };
}
