/**
 * Phase 1 D / D1 — multi-tab basic version.
 *
 * The single-`selectedNoteId` state in AppShell is replaced by a list
 * of open note IDs (`tabs`) plus an `activeId`. Tabs are append-only
 * on a fresh open; existing tab activates if the user re-clicks the
 * same note.
 *
 * v1 explicitly drops the following — left for v2 (D1 polish):
 *   - pin / transient distinction (every tree click adds a tab if
 *     it's not already open; tabs persist until ✕)
 *   - drag-to-reorder
 *   - middle-click / right-click context menu
 *   - vertical/horizontal split panes
 *   - Cmd+W / Cmd+T keyboard
 *
 * Persistence: localStorage `knowlet.tabs.v1` stores
 * `{ tabs: string[], activeId: string | null }`. Restored on mount.
 * If the persisted active id no longer exists in the vault (note
 * deleted between sessions), NoteView's existing 404 handling kicks
 * in; the tab strip renders "(missing)" until the user closes it.
 */

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "knowlet.tabs.v1";

interface PersistedState {
  tabs: string[];
  activeId: string | null;
}

function readPersisted(): PersistedState {
  if (typeof window === "undefined") return { tabs: [], activeId: null };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { tabs: [], activeId: null };
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    const tabs = Array.isArray(parsed.tabs)
      ? parsed.tabs.filter((t): t is string => typeof t === "string")
      : [];
    const activeId =
      typeof parsed.activeId === "string" && tabs.includes(parsed.activeId)
        ? parsed.activeId
        : tabs[0] ?? null;
    return { tabs, activeId };
  } catch {
    return { tabs: [], activeId: null };
  }
}

function writePersisted(state: PersistedState): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    /* localStorage disabled — tolerate */
  }
}

export interface TabsApi {
  /** Note IDs in tab strip order (left-to-right). */
  tabs: string[];
  /** Currently active note ID. `null` when no tabs are open. */
  activeId: string | null;
  /** Open a note in a tab (activate existing or append a new one). */
  openNote: (id: string) => void;
  /** Close a tab; if it was active, fall back to neighbor or null. */
  closeTab: (id: string) => void;
  /** Switch active tab without changing the tab list. */
  setActive: (id: string) => void;
  /** Close all tabs (used on vault reset / "open trash" flows). */
  closeAll: () => void;
}

export function useTabs(): TabsApi {
  const [state, setState] = useState<PersistedState>(readPersisted);

  // Persist whenever state changes.
  useEffect(() => {
    writePersisted(state);
  }, [state]);

  const openNote = useCallback((id: string) => {
    setState((prev) => {
      if (prev.tabs.includes(id)) {
        // Already open — just activate.
        return prev.activeId === id ? prev : { ...prev, activeId: id };
      }
      // Append + activate.
      return { tabs: [...prev.tabs, id], activeId: id };
    });
  }, []);

  const closeTab = useCallback((id: string) => {
    setState((prev) => {
      if (!prev.tabs.includes(id)) return prev;
      const idx = prev.tabs.indexOf(id);
      const nextTabs = prev.tabs.filter((t) => t !== id);
      let nextActive = prev.activeId;
      if (prev.activeId === id) {
        // Pick neighbor: prefer the tab that was on the right; fall
        // back to left; else null. Matches browser tab UX.
        nextActive = nextTabs[idx] ?? nextTabs[idx - 1] ?? null;
      }
      return { tabs: nextTabs, activeId: nextActive };
    });
  }, []);

  const setActive = useCallback((id: string) => {
    setState((prev) =>
      prev.tabs.includes(id) && prev.activeId !== id
        ? { ...prev, activeId: id }
        : prev,
    );
  }, []);

  const closeAll = useCallback(() => {
    setState({ tabs: [], activeId: null });
  }, []);

  return {
    tabs: state.tabs,
    activeId: state.activeId,
    openNote,
    closeTab,
    setActive,
    closeAll,
  };
}
