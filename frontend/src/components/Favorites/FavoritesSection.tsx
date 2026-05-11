/**
 * Phase 2 D B1 — starred notes panel.
 *
 * Lives above the file tree when leftTab === "files". Collapsible
 * (state in localStorage so it survives reloads).
 *
 * Why above the tree instead of a dedicated ActivityBar tab:
 *   - Per the B1 user stories, both 小张 (power user) and 小红
 *     (casual) want their starred notes visible while they're
 *     navigating — not behind a click on a sidebar icon.
 *   - Logseq + Bear ship this pattern; Obsidian gates it behind a
 *     Bookmarks tab and gets criticized for it in practice.
 *
 * Self-pruning: the backend drops favorites pointing at deleted
 * notes on every list call, so this component doesn't need to track
 * note-delete events itself. A simple staleTime + invalidation on
 * relevant mutations keeps the list fresh.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Star, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type FavoriteSummary,
  listFavorites,
  removeFavorite,
} from "@/api/client";
import { QK } from "@/lib/queryClient";

const LS_KEY = "knowlet.favorites.collapsed";

export function FavoritesSection({
  selectedNoteId,
  onSelectNote,
}: {
  selectedNoteId: string | null;
  onSelectNote: (id: string) => void;
}): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [collapsed, setCollapsed] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return window.localStorage.getItem(LS_KEY) === "1";
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(LS_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  const favs = useQuery({
    queryKey: QK.favorites,
    queryFn: listFavorites,
    staleTime: 30_000,
  });

  const unstar = useMutation({
    mutationFn: removeFavorite,
    onSuccess: (res) => {
      qc.setQueryData(QK.favorites, res);
    },
  });

  const favorites: FavoriteSummary[] = favs.data?.favorites ?? [];
  // Don't render anything when there's nothing AND the section is
  // collapsed. Avoids a stray empty header when the user has never
  // starred anything — discoverability happens via the right-click
  // path + the ⌘K @ prefix instead.
  if (favorites.length === 0 && collapsed) return null;

  return (
    <section
      data-testid="favorites-section"
      className="border-b text-sm"
      style={{ borderColor: "var(--line)" }}
    >
      <button
        type="button"
        onClick={() => setCollapsed((c) => !c)}
        className="flex w-full items-center gap-1 px-2 py-1.5 text-left text-xs font-medium tracking-wide uppercase text-muted-foreground hover:text-foreground"
        data-testid="favorites-toggle"
      >
        {collapsed ? (
          <ChevronRight className="size-3" />
        ) : (
          <ChevronDown className="size-3" />
        )}
        <Star className="size-3 fill-current text-amber-500" />
        <span>{t("favorites.heading")}</span>
        {favorites.length > 0 && (
          <span className="ml-auto text-[10px] text-muted-foreground">
            {favorites.length}
          </span>
        )}
      </button>
      {!collapsed && (
        <ul data-testid="favorites-list">
          {favorites.length === 0 ? (
            <li className="text-muted-foreground px-3 pb-2 text-xs italic">
              {t("favorites.empty")}
            </li>
          ) : (
            favorites.map((f) => (
              <li
                key={f.id}
                className={`group flex items-center gap-1 px-2 py-1 hover:bg-accent/30 ${
                  selectedNoteId === f.id ? "bg-accent/30" : ""
                }`}
              >
                <button
                  type="button"
                  onClick={() => onSelectNote(f.id)}
                  className="min-w-0 flex-1 truncate text-left"
                  data-testid={`favorite-row-${f.id}`}
                  title={f.title ?? f.id}
                >
                  {f.title ?? t("favorites.untitled")}
                </button>
                <button
                  type="button"
                  onClick={() => unstar.mutate(f.id)}
                  className="opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
                  aria-label={t("favorites.unstar")}
                  title={t("favorites.unstar")}
                  data-testid={`favorite-unstar-${f.id}`}
                >
                  <X className="size-3" />
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </section>
  );
}
