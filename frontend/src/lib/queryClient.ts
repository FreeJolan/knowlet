import { QueryClient } from "@tanstack/react-query";

/**
 * Single shared TanStack Query client. Tree refetches whenever the user
 * mutates anything (create / rename / move / delete) — the backend is the
 * source of truth, and the cost of a refetch on a single-user vault is
 * negligible compared to the bookkeeping a fully-optimistic cache would
 * need (folders cascading into notes, etc).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // No automatic refetch on focus — single-user, this would surprise.
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 30_000,
    },
  },
});

export const QK = {
  tree: ["tree"] as const,
  note: (id: string) => ["note", id] as const,
  trash: ["trash"] as const,
  templates: ["templates"] as const,
  backlinks: (id: string) => ["backlinks", id] as const,
  tags: ["tags"] as const,
  tagNotes: (tag: string) => ["tag-notes", tag] as const,
  tagsWithNotes: ["tags-with-notes"] as const,
  graph: ["graph"] as const,
  search: (q: string) => ["search", q] as const,
  quickActions: ["quick-actions"] as const,
  noteSyncStatus: (id: string) => ["note-sync-status", id] as const,
};
