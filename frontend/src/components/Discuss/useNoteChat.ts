/**
 * Hook driving a note-anchored discussion (Phase 3 Stage 4 P1).
 *
 * Reads the backend's `POST /api/chat/note/{id}/stream` ChatEvent SSE
 * via fetch + ReadableStream (no Vercel AI SDK — the existing SSE is
 * the single source of streaming truth per ADR-0008). Accumulates
 * `reply_chunk` events into the in-flight assistant message; surfaces
 * `error` events as an informed failure (never a silent stall, per the
 * failure-path discipline).
 */

import { useCallback, useEffect, useRef, useState } from "react";

export type ChatRole = "user" | "assistant";
export interface ChatMessage {
  role: ChatRole;
  content: string;
}
export type ChatStatus = "idle" | "streaming" | "error";

interface SSEEvent {
  type: string;
  text?: string;
  final_text?: string;
  message?: string;
}

export function useNoteChat(noteId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Latest messages, readable synchronously inside `send` (to forward
  // as history) without putting `messages` in the callback deps.
  const messagesRef = useRef<ChatMessage[]>([]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  // A6: persist the per-note conversation in localStorage so closing the
  // pane and reopening on the same note restores it. Load on note
  // switch; save on every change.
  useEffect(() => {
    if (!noteId) {
      setMessages([]);
      return;
    }
    try {
      const raw = window.localStorage.getItem(`knowlet.discuss.${noteId}`);
      setMessages(raw ? (JSON.parse(raw) as ChatMessage[]) : []);
    } catch {
      setMessages([]);
    }
    setError(null);
    setStatus("idle");
  }, [noteId]);

  useEffect(() => {
    if (!noteId) return;
    try {
      if (messages.length > 0) {
        window.localStorage.setItem(
          `knowlet.discuss.${noteId}`,
          JSON.stringify(messages),
        );
      } else {
        window.localStorage.removeItem(`knowlet.discuss.${noteId}`);
      }
    } catch {
      /* localStorage unavailable / over quota — non-fatal */
    }
  }, [noteId, messages]);

  const dropEmptyAssistant = (m: ChatMessage[]): ChatMessage[] => {
    const last = m[m.length - 1];
    if (last && last.role === "assistant" && last.content === "")
      return m.slice(0, -1);
    return m;
  };

  /** Abort an in-flight stream (P5 stop button binds here). */
  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("idle");
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || !noteId || status === "streaming") return;
      // Forward prior clean turns so the model has conversation memory
      // (A6). The note grounding rides in the current turn server-side.
      const history = messagesRef.current.filter((m) => m.content !== "");
      setError(null);
      // Optimistic echo: user bubble + an empty assistant bubble the
      // stream fills in. Echo is client-side so it's deterministic.
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
          `/api/chat/note/${encodeURIComponent(noteId)}/stream`,
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
            const d = (await r.json()) as { detail?: string };
            if (d?.detail) detail = d.detail;
          } catch {
            // body wasn't JSON
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
            let ev: SSEEvent;
            try {
              ev = JSON.parse(block.slice(5).trim()) as SSEEvent;
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
            } else if (ev.type === "error") {
              streamError = ev.message || "stream error";
            }
            // turn_done / reply_done / tool_* — nothing to render in P1.
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
    [noteId, status],
  );

  return { messages, status, error, send, stop };
}
