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

import { useCallback, useEffect, useMemo, useState } from "react";

const STORAGE_KEY = "knowlet.tabs.v1";

interface PersistedState {
  tabs: string[];
  activeId: string | null;
  /** Ordered list of pinned ids; subset of `tabs`. Pinned tabs render
   *  first in the strip and survive `closeOthers`. */
  pinned: string[];
}

function readPersisted(): PersistedState {
  if (typeof window === "undefined")
    return { tabs: [], activeId: null, pinned: [] };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { tabs: [], activeId: null, pinned: [] };
    const parsed = JSON.parse(raw) as Partial<PersistedState>;
    const tabs = Array.isArray(parsed.tabs)
      ? parsed.tabs.filter((t): t is string => typeof t === "string")
      : [];
    const activeId =
      typeof parsed.activeId === "string" && tabs.includes(parsed.activeId)
        ? parsed.activeId
        : tabs[0] ?? null;
    // Pinned must be a subset of tabs. Filter so a pre-existing
    // localStorage payload from before Slice 3 (no `pinned` key)
    // round-trips cleanly to an empty array.
    const tabSet = new Set(tabs);
    const pinned = Array.isArray(parsed.pinned)
      ? parsed.pinned.filter(
          (p): p is string => typeof p === "string" && tabSet.has(p),
        )
      : [];
    return { tabs, activeId, pinned };
  } catch {
    return { tabs: [], activeId: null, pinned: [] };
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
  /** Note IDs in raw insertion order (storage shape). For UI layout
   *  prefer `displayTabs` — pinned tabs come first there. */
  tabs: string[];
  /** Currently active note ID. `null` when no tabs are open. */
  activeId: string | null;
  /** Tab IDs that are currently pinned, in pin order. Pinned tabs
   *  render first in the strip and survive `closeOthers`. */
  pinned: string[];
  /** Pinned tabs first (in pin order), then the rest of `tabs` in
   *  insertion order. This is what TabStrip renders. */
  displayTabs: string[];
  /** Open a note in a tab (activate existing or append a new one). */
  openNote: (id: string) => void;
  /** Close a tab; if it was active, fall back to neighbor or null.
   *  Closing a pinned tab also unpins it. */
  closeTab: (id: string) => void;
  /** Switch active tab without changing the tab list. */
  setActive: (id: string) => void;
  /** Close every tab — pinned included. Used by "vault reset" type
   *  flows. The user-facing "Close All" command in TabStrip /
   *  palette uses `closeUnpinned` instead so pinned tabs stick. */
  closeAll: () => void;
  /** Close all unpinned tabs. Pinned tabs (and their active state if
   *  the active was pinned) survive. The user-facing "Close All"
   *  action maps to this. */
  closeUnpinned: () => void;
  /** Close every tab EXCEPT the given id and any pinned tabs;
   *  activate the kept id. No-op if the id isn't open. */
  closeOthers: (id: string) => void;
  /** Toggle the pinned state of `id`. Pinning moves the tab to the
   *  end of the pinned section; unpinning moves it to the start of
   *  the unpinned section. Display order is recomputed via
   *  `displayTabs`. */
  togglePin: (id: string) => void;
  /** True iff `id` is in `pinned`. */
  isPinned: (id: string) => boolean;
  /** Reorder a tab within its current section (pinned or unpinned).
   *  `sourceId` is dropped `position` of `targetId`. No-op if the
   *  source and target are in different sections (prevents implicit
   *  pin/unpin from drag-and-drop) or if source === target. */
  reorder: (
    sourceId: string,
    targetId: string,
    position: "before" | "after",
  ) => void;
  /** Move the active tab one slot left within its section. No-op if
   *  it's already at the section's left edge. Powers the palette
   *  "Move tab left" command (keyboard / accessibility path). */
  moveActiveLeft: () => void;
  /** Mirror of `moveActiveLeft`. */
  moveActiveRight: () => void;
  /** True iff the active tab can move left within its section. */
  canMoveActiveLeft: boolean;
  /** Mirror of `canMoveActiveLeft`. */
  canMoveActiveRight: boolean;
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
      // Append + activate. Pinned list unchanged — newly opened tabs
      // are always unpinned.
      return { tabs: [...prev.tabs, id], activeId: id, pinned: prev.pinned };
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
      // Pinned implicitly drops when the underlying tab closes.
      const nextPinned = prev.pinned.filter((p) => p !== id);
      return { tabs: nextTabs, activeId: nextActive, pinned: nextPinned };
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
    setState({ tabs: [], activeId: null, pinned: [] });
  }, []);

  const closeUnpinned = useCallback(() => {
    setState((prev) => {
      if (prev.pinned.length === 0) {
        return { tabs: [], activeId: null, pinned: [] };
      }
      const pinnedSet = new Set(prev.pinned);
      const nextTabs = prev.tabs.filter((t) => pinnedSet.has(t));
      const activeStillOpen =
        prev.activeId && pinnedSet.has(prev.activeId) ? prev.activeId : null;
      return {
        tabs: nextTabs,
        activeId: activeStillOpen ?? prev.pinned[0] ?? null,
        pinned: prev.pinned,
      };
    });
  }, []);

  const closeOthers = useCallback((id: string) => {
    setState((prev) => {
      if (!prev.tabs.includes(id)) return prev;
      // Keep pinned + the explicitly-kept id. Order: existing pinned
      // (in their pin order), then the kept id if it isn't already
      // pinned. activeId becomes the kept id.
      const pinnedSet = new Set(prev.pinned);
      const nextTabs = pinnedSet.has(id)
        ? [...prev.pinned]
        : [...prev.pinned, id];
      // No-op if nothing actually changes.
      if (
        nextTabs.length === prev.tabs.length &&
        nextTabs.every((t, i) => prev.tabs[i] === t) &&
        prev.activeId === id
      ) {
        return prev;
      }
      return {
        tabs: nextTabs,
        activeId: id,
        pinned: prev.pinned,
      };
    });
  }, []);

  const togglePin = useCallback((id: string) => {
    setState((prev) => {
      if (!prev.tabs.includes(id)) return prev;
      const isPinned = prev.pinned.includes(id);
      if (isPinned) {
        // Unpin: keep the visual position the tab had while pinned.
        // The tab was at the right edge of the pinned section; after
        // unpin it should be the leftmost unpinned (= just past the
        // remaining pinned tabs). Move it within `tabs` so the
        // displayTabs computation places it at the boundary. Without
        // this, the tab would snap back to its original insertion
        // position and the user's mental model of "where is my tab"
        // breaks (VS Code parity).
        const nextPinned = prev.pinned.filter((p) => p !== id);
        const without = prev.tabs.filter((t) => t !== id);
        const pinnedSet = new Set(nextPinned);
        let boundary = without.findIndex((t) => !pinnedSet.has(t));
        if (boundary < 0) boundary = without.length;
        return {
          ...prev,
          tabs: [...without.slice(0, boundary), id, ...without.slice(boundary)],
          pinned: nextPinned,
        };
      }
      // Pin: append to pinned list (end of the pinned section). The
      // pinned-array order drives the leading display section, so we
      // don't need to reorder `tabs` itself.
      return { ...prev, pinned: [...prev.pinned, id] };
    });
  }, []);

  const reorder = useCallback(
    (sourceId: string, targetId: string, position: "before" | "after") => {
      setState((prev) => {
        if (sourceId === targetId) return prev;
        if (
          !prev.tabs.includes(sourceId) ||
          !prev.tabs.includes(targetId)
        ) {
          return prev;
        }
        const pinnedSet = new Set(prev.pinned);
        const srcPinned = pinnedSet.has(sourceId);
        const tgtPinned = pinnedSet.has(targetId);
        // Cross-boundary drops are no-ops. Crossing pinned↔unpinned
        // would amount to an implicit pin/unpin that conflicts with
        // the explicit Pin/Unpin affordances; we keep DnD as a
        // pure reorder-within-section.
        if (srcPinned !== tgtPinned) return prev;
        if (srcPinned) {
          const without = prev.pinned.filter((p) => p !== sourceId);
          const tgtIdx = without.indexOf(targetId);
          const insertIdx = position === "after" ? tgtIdx + 1 : tgtIdx;
          const nextPinned = [
            ...without.slice(0, insertIdx),
            sourceId,
            ...without.slice(insertIdx),
          ];
          return { ...prev, pinned: nextPinned };
        }
        // Unpinned: reorder `tabs`. The unpinned section's display
        // order is filtered from `tabs` (preserves order), so moving
        // sourceId within `tabs` is enough.
        const without = prev.tabs.filter((t) => t !== sourceId);
        const tgtIdx = without.indexOf(targetId);
        const insertIdx = position === "after" ? tgtIdx + 1 : tgtIdx;
        const nextTabs = [
          ...without.slice(0, insertIdx),
          sourceId,
          ...without.slice(insertIdx),
        ];
        return { ...prev, tabs: nextTabs };
      });
    },
    [],
  );

  // Computed display order: pinned tabs first (in pin order), then
  // unpinned (in original insertion order). Memoizing here avoids
  // every TabStrip render recomputing — and also gives consumers a
  // stable reference when the underlying state hasn't changed.
  const displayTabs = useMemo(() => {
    const pinnedSet = new Set(state.pinned);
    return [
      ...state.pinned,
      ...state.tabs.filter((t) => !pinnedSet.has(t)),
    ];
  }, [state.tabs, state.pinned]);

  const isPinned = useCallback(
    (id: string) => state.pinned.includes(id),
    [state.pinned],
  );

  // Active-tab movement helpers — palette uses these so keyboard /
  // accessibility users have a path equivalent to dragging.
  const moveActiveBy = useCallback((delta: -1 | 1) => {
    setState((prev) => {
      const id = prev.activeId;
      if (!id) return prev;
      const pinnedSet = new Set(prev.pinned);
      const srcPinned = pinnedSet.has(id);
      // Section-scoped index. Compute display order inline so we
      // don't re-derive `displayTabs` here (this lives outside
      // useMemo).
      const display = [
        ...prev.pinned,
        ...prev.tabs.filter((t) => !pinnedSet.has(t)),
      ];
      const sectionStart = srcPinned ? 0 : prev.pinned.length;
      const sectionEnd = srcPinned ? prev.pinned.length : display.length;
      const idx = display.indexOf(id);
      const next = idx + delta;
      if (next < sectionStart || next >= sectionEnd) return prev;
      // Swap with the neighbor in the appropriate underlying array.
      // Bounds checked above guarantee neighborId is defined; we
      // narrow with an explicit guard so the compiler agrees.
      const neighborId = display[next];
      if (!neighborId) return prev;
      if (srcPinned) {
        const a = prev.pinned.indexOf(id);
        const b = prev.pinned.indexOf(neighborId);
        const nextPinned = [...prev.pinned];
        const tmp = nextPinned[a]!;
        nextPinned[a] = nextPinned[b]!;
        nextPinned[b] = tmp;
        return { ...prev, pinned: nextPinned };
      }
      const a = prev.tabs.indexOf(id);
      const b = prev.tabs.indexOf(neighborId);
      const nextTabs = [...prev.tabs];
      const tmp = nextTabs[a]!;
      nextTabs[a] = nextTabs[b]!;
      nextTabs[b] = tmp;
      return { ...prev, tabs: nextTabs };
    });
  }, []);

  const moveActiveLeft = useCallback(() => moveActiveBy(-1), [moveActiveBy]);
  const moveActiveRight = useCallback(() => moveActiveBy(1), [moveActiveBy]);

  const { canMoveActiveLeft, canMoveActiveRight } = useMemo(() => {
    const id = state.activeId;
    if (!id)
      return { canMoveActiveLeft: false, canMoveActiveRight: false };
    const pinnedSet = new Set(state.pinned);
    const srcPinned = pinnedSet.has(id);
    const display = [
      ...state.pinned,
      ...state.tabs.filter((t) => !pinnedSet.has(t)),
    ];
    const sectionStart = srcPinned ? 0 : state.pinned.length;
    const sectionEnd = srcPinned ? state.pinned.length : display.length;
    const idx = display.indexOf(id);
    return {
      canMoveActiveLeft: idx > sectionStart,
      canMoveActiveRight: idx < sectionEnd - 1,
    };
  }, [state.activeId, state.tabs, state.pinned]);

  return {
    tabs: state.tabs,
    activeId: state.activeId,
    pinned: state.pinned,
    displayTabs,
    openNote,
    closeTab,
    setActive,
    closeAll,
    closeUnpinned,
    closeOthers,
    togglePin,
    isPinned,
    reorder,
    moveActiveLeft,
    moveActiveRight,
    canMoveActiveLeft,
    canMoveActiveRight,
  };
}
