/**
 * Phase 1 D slice 2 — global full-text + vector search focus mode.
 *
 * Cmd+Shift+F opens; Esc closes. Backend (`/api/search`) does RRF
 * fusion of FTS5 BM25 + sqlite-vec cosine on chunks, returning
 * note-level hits with plain-text snippets. We highlight matches
 * client-side by splitting on the query (case-insensitive).
 *
 * Click a result → opens that note (no scroll-to-match in v1; chunk
 * → line conversion isn't free and dogfood will tell us if it's
 * worth adding).
 */

import { useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import {
  type ChangeEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";

import { searchVault } from "@/api/client";
import type { SearchPayload } from "@/api/types";
import { imeSafeKeyHandler } from "@/lib/imeSafe";
import { QK } from "@/lib/queryClient";

interface Props {
  open: boolean;
  onClose: () => void;
  onOpenNote: (noteId: string) => void;
}

const SEARCH_DEBOUNCE_MS = 200;
const RESULT_TOP_K = 30;

/** Split `text` into [normal, hit, normal, hit, ...] segments,
 *  case-insensitive on `query`. Returns the segments + a flag per
 *  segment indicating whether it's a match. */
function highlightSegments(
  text: string,
  query: string,
): Array<{ value: string; match: boolean }> {
  if (!query.trim()) return [{ value: text, match: false }];
  const out: Array<{ value: string; match: boolean }> = [];
  // Match each non-empty whitespace-separated term independently;
  // dedupe so `RAG RAG` doesn't double-highlight.
  const terms = Array.from(
    new Set(
      query
        .split(/\s+/)
        .map((t) => t.trim())
        .filter(Boolean),
    ),
  );
  if (terms.length === 0) return [{ value: text, match: false }];
  // Build one regex with alternation, escaping each term.
  const pattern = terms
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join("|");
  const re = new RegExp(`(${pattern})`, "gi");
  let last = 0;
  for (const m of text.matchAll(re)) {
    const start = m.index ?? 0;
    if (start > last) {
      out.push({ value: text.slice(last, start), match: false });
    }
    out.push({ value: m[0], match: true });
    last = start + m[0].length;
  }
  if (last < text.length) {
    out.push({ value: text.slice(last), match: false });
  }
  return out;
}

export function SearchFocusMode({ open, onClose, onOpenNote }: Props) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reset state on open / close. Genuinely "external state changed
  // (open prop), reset transient UI" — the no-set-state-in-effect rule
  // applies more to derived-from-render cases; this is a clear sync
  // boundary.
  useEffect(() => {
    if (!open) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setQuery("");
    setDebouncedQuery("");
    setActiveIndex(0);
    // Focus the input after dialog mount.
    const t = window.setTimeout(() => inputRef.current?.focus(), 30);
    return () => window.clearTimeout(t);
  }, [open]);

  // Esc closes.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: globalThis.KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  // Debounce typing.
  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebouncedQuery(query);
      setActiveIndex(0);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [query]);

  const trimmed = debouncedQuery.trim();
  const results = useQuery<SearchPayload>({
    queryKey: QK.search(trimmed),
    queryFn: () => searchVault(trimmed, RESULT_TOP_K),
    enabled: open && trimmed.length > 0,
    staleTime: 30_000,
  });

  const hits = useMemo(() => results.data?.hits ?? [], [results.data]);

  // IME-safe: Enter / arrows fire only when no pinyin / IME composition
  // is active. During composition, the keys belong to the IME (confirm
  // candidate / move candidate window) and must not trigger panel
  // navigation.
  const onInputKeyDown = imeSafeKeyHandler<HTMLInputElement>((e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => Math.min(hits.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const hit = hits[activeIndex];
      if (hit) {
        onOpenNote(hit.note_id);
        onClose();
      }
    }
  });

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col"
      style={{ background: "var(--bg, #f4f0e8)" }}
      data-testid="search-focus-mode"
    >
      {/* Header — input + close */}
      <header
        className="flex shrink-0 items-center gap-3 border-b px-4 py-3"
        style={{ borderColor: "var(--line)", background: "var(--panel)" }}
      >
        <Search size={14} style={{ color: "var(--ink-mute)" }} />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e: ChangeEvent<HTMLInputElement>) =>
            setQuery(e.target.value)
          }
          onKeyDown={onInputKeyDown}
          placeholder={t("search.placeholder") as string}
          data-testid="search-input"
          className="flex-1 bg-transparent text-base outline-none"
          style={{
            color: "var(--ink)",
            fontFamily: "var(--font-serif, Source Serif 4, Georgia, serif)",
          }}
        />
        {trimmed.length > 0 && results.data && (
          <span
            className="font-mono text-[11px]"
            style={{ color: "var(--ink-mute)" }}
          >
            {t("search.summary", { count: hits.length })}
          </span>
        )}
        <span
          className="font-mono text-[10.5px]"
          style={{ color: "var(--ink-mute)" }}
        >
          ⌘⇧F
        </span>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("search.close")}
          data-testid="search-focus-close"
          className="flex size-7 items-center justify-center rounded transition-colors hover:bg-accent/30"
          style={{ color: "var(--ink-mute)" }}
        >
          <X size={14} />
        </button>
      </header>

      {/* Results */}
      <div className="flex-1 overflow-y-auto" data-testid="search-results">
        {trimmed.length === 0 ? (
          <EmptyHint title={t("search.idleTitle")} body={t("search.idleHint")} />
        ) : results.isLoading ? (
          <Status text={t("search.loading")} />
        ) : results.isError ? (
          <Status
            text={t("search.error", {
              error:
                (results.error as { detail?: string })?.detail ?? "unknown",
            })}
          />
        ) : hits.length === 0 ? (
          <EmptyHint
            title={t("search.noMatchesTitle")}
            body={t("search.noMatchesHint", { query: trimmed })}
          />
        ) : (
          <ul>
            {hits.map((h, i) => (
              <li key={`${h.note_id}-${i}`}>
                <button
                  type="button"
                  onClick={() => {
                    onOpenNote(h.note_id);
                    onClose();
                  }}
                  onMouseEnter={() => setActiveIndex(i)}
                  data-testid="search-result-row"
                  data-note-id={h.note_id}
                  data-active={activeIndex === i ? "1" : "0"}
                  className="block w-full px-4 py-3 text-left transition-colors"
                  style={{
                    background:
                      activeIndex === i
                        ? "var(--accent-soft, rgba(91, 122, 156, 0.18))"
                        : "transparent",
                    borderBottom: "1px solid var(--line-soft, #e2dac9)",
                  }}
                >
                  <div
                    className="flex items-baseline gap-2 text-[14px]"
                    style={{
                      color: "var(--ink, #2a2823)",
                      fontFamily:
                        "var(--font-serif, Source Serif 4, Georgia, serif)",
                      fontWeight: 500,
                    }}
                  >
                    <span className="truncate">
                      {highlightSegments(h.title, trimmed).map(
                        (seg, j) =>
                          seg.match ? (
                            <Mark key={j}>{seg.value}</Mark>
                          ) : (
                            <span key={j}>{seg.value}</span>
                          ),
                      )}
                    </span>
                    {h.folder && (
                      <span
                        className="font-mono text-[10.5px]"
                        style={{ color: "var(--ink-mute)" }}
                      >
                        {h.folder}
                      </span>
                    )}
                  </div>
                  {h.snippet && (
                    <div
                      className="mt-1 text-[12.5px] leading-relaxed"
                      style={{ color: "var(--ink-soft)" }}
                    >
                      {highlightSegments(h.snippet, trimmed).map((seg, j) =>
                        seg.match ? (
                          <Mark key={j}>{seg.value}</Mark>
                        ) : (
                          <span key={j}>{seg.value}</span>
                        ),
                      )}
                    </div>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Mark({ children }: { children: React.ReactNode }) {
  return (
    <mark
      style={{
        background: "var(--accent-soft, rgba(91, 122, 156, 0.32))",
        color: "var(--accent-2, #34495e)",
        padding: "0 1px",
        borderRadius: 2,
      }}
    >
      {children}
    </mark>
  );
}

function Status({ text }: { text: string }) {
  return (
    <div
      className="px-4 py-6 text-center text-xs"
      style={{ color: "var(--ink-mute)" }}
    >
      {text}
    </div>
  );
}

function EmptyHint({ title, body }: { title: string; body: string }) {
  return (
    <div className="flex h-full items-center justify-center px-12">
      <div className="max-w-md text-center">
        <h2
          className="font-serif text-xl font-semibold"
          style={{ color: "var(--ink)" }}
        >
          {title}
        </h2>
        <p
          className="mx-auto mt-2 max-w-sm text-sm leading-relaxed"
          style={{ color: "var(--ink-soft)" }}
        >
          {body}
        </p>
      </div>
    </div>
  );
}
