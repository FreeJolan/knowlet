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

export interface DraftEditProposal {
  id: string;
  draftId: string;
  title?: string;
  oldBody: string;
  newBody: string;
  changed: boolean;
  reason?: string;
  summary?: string;
}

function draftProposalFromToolResult(ev: ChatSSEEvent): DraftEditProposal | null {
  if (ev.name !== "propose_current_draft_edit") return null;
  const payload = ev.payload;
  if (!payload || typeof payload !== "object") return null;
  const obj = payload as Record<string, unknown>;
  const draftId = typeof obj.draft_id === "string" ? obj.draft_id : "";
  if (
    !draftId ||
    typeof obj.old_body !== "string" ||
    typeof obj.new_body !== "string"
  ) {
    return null;
  }
  const proposal: DraftEditProposal = {
    id: ev.id || `draft-proposal-${Date.now()}`,
    draftId,
    oldBody: obj.old_body,
    newBody: obj.new_body,
    changed: obj.changed === true,
  };
  if (typeof obj.title === "string") proposal.title = obj.title;
  if (typeof obj.reason === "string") proposal.reason = obj.reason;
  if (typeof obj.summary === "string") proposal.summary = obj.summary;
  return proposal;
}

export function useRawInfoChat(infoId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const [proposal, setProposal] = useState<DraftEditProposal | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<ChatMessage[]>([]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (!infoId) {
      setMessages([]);
      return;
    }
    try {
      const raw = window.localStorage.getItem(`knowlet.digest.raw-info.${infoId}`);
      setMessages(raw ? (JSON.parse(raw) as ChatMessage[]) : []);
    } catch {
      setMessages([]);
    }
    setError(null);
    setProposal(null);
    setStatus("idle");
  }, [infoId]);

  useEffect(() => {
    if (!infoId) return;
    try {
      if (messages.length > 0) {
        window.localStorage.setItem(
          `knowlet.digest.raw-info.${infoId}`,
          JSON.stringify(messages),
        );
      } else {
        window.localStorage.removeItem(`knowlet.digest.raw-info.${infoId}`);
      }
    } catch {
      // localStorage unavailable / over quota; conversation still works in memory.
    }
  }, [infoId, messages]);

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
      if (!trimmed || !infoId || status === "streaming") return;
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
          `/api/chat/raw-info/${encodeURIComponent(infoId)}/stream`,
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
              const draftProposal = draftProposalFromToolResult(ev);
              if (draftProposal) setProposal(draftProposal);
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
    [infoId, status],
  );

  const clearProposal = useCallback(() => setProposal(null), []);

  return { messages, status, error, proposal, send, stop, clearProposal };
}
