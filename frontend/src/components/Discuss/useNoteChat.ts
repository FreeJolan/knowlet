/**
 * Hook driving note-anchored discussions.
 *
 * Each note owns its own lightweight session bucket. Streams keep
 * writing into the bucket they started from even if the user switches
 * notes, so "look at another note" does not implicitly abort or
 * cross-wire an answer.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { summarizeToolPayload } from "./ToolTrace";

export type ChatRole = "user" | "assistant" | "tool";
export interface ChatToolTrace {
  id: string;
  name: string;
  status: "calling" | "done" | "error";
  arguments: Record<string, unknown>;
  resultSummary?: string;
}
export interface ChatMessage {
  role: ChatRole;
  content: string;
  tool?: ChatToolTrace;
}
export type ChatStatus = "idle" | "streaming" | "error";

export interface ChatSSEEvent {
  type: string;
  id?: string;
  name?: string;
  arguments?: Record<string, unknown>;
  payload?: unknown;
  text?: string;
  final_text?: string;
  message?: unknown;
}

interface NoteChatSession {
  messages: ChatMessage[];
  status: ChatStatus;
  error: string | null;
  abort: AbortController | null;
  listeners: Set<() => void>;
}

export function formatErrorDetail(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    return value.map(formatErrorDetail).join("; ");
  }
  if (value && typeof value === "object") {
    const obj = value as Record<string, unknown>;
    if (typeof obj.msg === "string") return obj.msg;
    if (typeof obj.message === "string") return obj.message;
    if (typeof obj.error === "string") return obj.error;
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value ?? "stream error");
}

export function chatHistoryForRequest(messages: ChatMessage[]): ChatMessage[] {
  return messages.filter(
    (m) =>
      (m.role === "user" || m.role === "assistant") &&
      m.content.trim() !== "",
  );
}

const sessions = new Map<string, NoteChatSession>();

function storageKey(noteId: string) {
  return `knowlet.discuss.${noteId}`;
}

function loadMessages(noteId: string): ChatMessage[] {
  try {
    const raw = window.localStorage.getItem(storageKey(noteId));
    return raw ? (JSON.parse(raw) as ChatMessage[]) : [];
  } catch {
    return [];
  }
}

function saveMessages(noteId: string, messages: ChatMessage[]) {
  try {
    if (messages.length > 0) {
      window.localStorage.setItem(storageKey(noteId), JSON.stringify(messages));
    } else {
      window.localStorage.removeItem(storageKey(noteId));
    }
  } catch {
    /* localStorage unavailable / over quota — non-fatal */
  }
}

function getSession(noteId: string): NoteChatSession {
  const existing = sessions.get(noteId);
  if (existing) return existing;
  const created: NoteChatSession = {
    messages: loadMessages(noteId),
    status: "idle",
    error: null,
    abort: null,
    listeners: new Set(),
  };
  sessions.set(noteId, created);
  return created;
}

function notify(noteId: string) {
  const session = sessions.get(noteId);
  if (!session) return;
  for (const listener of session.listeners) listener();
}

function updateSession(
  noteId: string,
  fn: (session: NoteChatSession) => void,
) {
  const session = getSession(noteId);
  fn(session);
  saveMessages(noteId, session.messages);
  notify(noteId);
}

function dropEmptyAssistant(messages: ChatMessage[]): ChatMessage[] {
  const last = messages[messages.length - 1];
  if (last && last.role === "assistant" && last.content === "")
    return messages.slice(0, -1);
  return messages;
}

export function upsertToolCall(
  messages: ChatMessage[],
  ev: ChatSSEEvent,
): ChatMessage[] {
  const name = ev.name || "tool";
  const id = ev.id || `${name}-${Date.now()}`;
  const toolMessage: ChatMessage = {
    role: "tool",
    content: name,
    tool: {
      id,
      name,
      status: "calling",
      arguments: ev.arguments ?? {},
    },
  };
  const pending = messages[messages.length - 1];
  const insertAt =
    pending?.role === "assistant" && pending.content === ""
      ? messages.length - 1
      : messages.length;
  return [
    ...messages.slice(0, insertAt),
    toolMessage,
    ...messages.slice(insertAt),
  ];
}

export function applyToolResult(
  messages: ChatMessage[],
  ev: ChatSSEEvent,
): ChatMessage[] {
  const id = ev.id || "";
  const name = ev.name || "tool";
  const resultSummary = summarizeToolPayload(name, ev.payload);
  let updated = false;
  const next = messages.map((message) => {
    if (
      message.role !== "tool" ||
      !message.tool ||
      updated ||
      (id && message.tool.id !== id)
    ) {
      return message;
    }
    updated = true;
    const failed =
      !!ev.payload &&
      typeof ev.payload === "object" &&
      typeof (ev.payload as Record<string, unknown>).error === "string";
    return {
      ...message,
      tool: {
        ...message.tool,
        status: failed ? ("error" as const) : ("done" as const),
        resultSummary,
      },
    };
  });
  if (updated) return next;
  const inserted = upsertToolCall(messages, {
    type: "tool_call",
    id,
    name,
    arguments: {},
  });
  let fixed = false;
  return inserted.map((message) => {
    if (fixed || message.role !== "tool" || message.tool?.id !== id) {
      return message;
    }
    fixed = true;
    return {
      ...message,
      tool: message.tool
        ? {
            ...message.tool,
            status: "done" as const,
            resultSummary,
          }
        : message.tool,
    };
  });
}

export function useNoteChat(noteId: string | null) {
  const [, forceRender] = useState(0);
  const activeNoteRef = useRef<string | null>(noteId);

  useEffect(() => {
    activeNoteRef.current = noteId;
    if (!noteId) {
      forceRender((n) => n + 1);
      return;
    }
    const session = getSession(noteId);
    const listener = () => forceRender((n) => n + 1);
    session.listeners.add(listener);
    forceRender((n) => n + 1);
    return () => {
      session.listeners.delete(listener);
    };
  }, [noteId]);

  const activeSession = noteId ? getSession(noteId) : null;
  const messages = activeSession?.messages ?? [];
  const status = activeSession?.status ?? "idle";
  const error = activeSession?.error ?? null;

  const appendUserMessage = useCallback(
    (content: string, targetNoteId?: string) => {
      const id = targetNoteId ?? activeNoteRef.current;
      const text = content.trim();
      if (!id || !text) return;
      updateSession(id, (session) => {
        session.error = null;
        session.messages = [...session.messages, { role: "user", content: text }];
      });
    },
    [],
  );

  const appendAssistantMessage = useCallback(
    (content: string, targetNoteId?: string) => {
      const id = targetNoteId ?? activeNoteRef.current;
      if (!id) return;
      updateSession(id, (session) => {
        session.messages = [
          ...session.messages,
          { role: "assistant", content },
        ];
      });
    },
    [],
  );

  const send = useCallback(async (text: string) => {
    const id = activeNoteRef.current;
    const trimmed = text.trim();
    if (!trimmed || !id) return;
    const session = getSession(id);
    if (session.status === "streaming") return;
    const history = chatHistoryForRequest(session.messages);
    const ctrl = new AbortController();
    updateSession(id, (s) => {
      s.error = null;
      s.status = "streaming";
      s.abort = ctrl;
      s.messages = [
        ...s.messages,
        { role: "user", content: trimmed },
        { role: "assistant", content: "" },
      ];
    });
    try {
      const r = await fetch(`/api/chat/note/${encodeURIComponent(id)}/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: trimmed, history }),
        signal: ctrl.signal,
      });
      if (!r.ok || !r.body) {
        let detail = r.statusText;
        try {
          const d = (await r.json()) as { detail?: unknown };
          if (d?.detail) detail = formatErrorDetail(d.detail);
        } catch {
          // body was not JSON
        }
        updateSession(id, (s) => {
          s.error = detail || "request failed";
          s.status = "error";
          s.abort = null;
          s.messages = dropEmptyAssistant(s.messages);
        });
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
            updateSession(id, (s) => {
              const copy = s.messages.slice();
              const last = copy[copy.length - 1];
              if (last && last.role === "assistant") {
                copy[copy.length - 1] = {
                  ...last,
                  content: last.content + chunk,
                };
                s.messages = copy;
              }
            });
          } else if (ev.type === "tool_call") {
            updateSession(id, (s) => {
              s.messages = upsertToolCall(s.messages, ev);
            });
          } else if (ev.type === "tool_result") {
            updateSession(id, (s) => {
              s.messages = applyToolResult(s.messages, ev);
            });
          } else if (ev.type === "error") {
            streamError = formatErrorDetail(ev.message || "stream error");
          }
        }
      }
      updateSession(id, (s) => {
        s.abort = null;
        if (streamError) {
          s.error = streamError;
          s.status = "error";
          s.messages = dropEmptyAssistant(s.messages);
        } else {
          s.status = "idle";
        }
      });
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        updateSession(id, (s) => {
          s.abort = null;
          s.status = "idle";
        });
        return;
      }
      updateSession(id, (s) => {
        s.error = (e as Error).message || "network error";
        s.status = "error";
        s.abort = null;
        s.messages = dropEmptyAssistant(s.messages);
      });
    }
  }, []);

  const stop = useCallback(() => {
    const id = activeNoteRef.current;
    if (!id) return;
    updateSession(id, (session) => {
      session.abort?.abort();
      session.abort = null;
      session.status = "idle";
    });
  }, []);

  const reset = useCallback((targetNoteId?: string) => {
    const id = targetNoteId ?? activeNoteRef.current;
    if (!id) return;
    updateSession(id, (session) => {
      session.abort?.abort();
      session.abort = null;
      session.status = "idle";
      session.error = null;
      session.messages = [];
    });
  }, []);

  return {
    messages,
    status,
    error,
    send,
    stop,
    reset,
    appendUserMessage,
    appendAssistantMessage,
  };
}
