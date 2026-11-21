/**
 * localStorage persistence shared by the chat hooks.
 *
 * Every write re-serializes the whole conversation and is synchronous
 * main-thread IO, while a streaming reply delivers dozens of chunks a
 * second. So while a reply streams, writes are throttled to one per
 * ``CHAT_PERSIST_THROTTLE_MS`` (a reload mid-stream loses at most that
 * much text), and the final state is written as soon as the stream
 * settles (done / error / abort).
 */

import { useEffect, useRef } from "react";

import type { ChatMessage, ChatStatus } from "./useNoteChat";

export const CHAT_PERSIST_THROTTLE_MS = 1000;

export function writeChatMessages(key: string, messages: ChatMessage[]): void {
  try {
    if (messages.length > 0) {
      window.localStorage.setItem(key, JSON.stringify(messages));
    } else {
      window.localStorage.removeItem(key);
    }
  } catch {
    /* localStorage unavailable / over quota — non-fatal */
  }
}

/** Persist a hook-local conversation under ``key`` (null = nothing to
 *  persist) with the streaming throttle described above. */
export function usePersistChatMessages(
  key: string | null,
  messages: ChatMessage[],
  status: ChatStatus,
): void {
  const pendingRef = useRef<{ key: string; messages: ChatMessage[] } | null>(
    null,
  );
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (!key) return;
    if (status === "streaming") {
      const pending = pendingRef.current;
      if (pending && pending.key !== key) {
        writeChatMessages(pending.key, pending.messages);
      }
      pendingRef.current = { key, messages };
      if (timerRef.current === null) {
        timerRef.current = window.setTimeout(() => {
          timerRef.current = null;
          const due = pendingRef.current;
          pendingRef.current = null;
          if (due) writeChatMessages(due.key, due.messages);
        }, CHAT_PERSIST_THROTTLE_MS);
      }
      return;
    }
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    pendingRef.current = null;
    writeChatMessages(key, messages);
  }, [key, messages, status]);

  useEffect(() => {
    const pendingStore = pendingRef;
    const timerStore = timerRef;
    return () => {
      if (timerStore.current !== null) {
        window.clearTimeout(timerStore.current);
        timerStore.current = null;
      }
      const due = pendingStore.current;
      pendingStore.current = null;
      if (due) writeChatMessages(due.key, due.messages);
    };
  }, []);
}
