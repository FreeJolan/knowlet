/**
 * Phase 1 C slice 1 — Backlinks right-rail panel.
 *
 * Renders notes that reference the currently-selected note via [[Title]]
 * wikilinks. Layout follows `docs/design/bundle-2026-05-04/project/audit-7-backlinks.jsx`:
 * grouped by source note, each mention shows the trimmed sentence with
 * the [[…]] underlined in accent color and an L<line> indicator below.
 *
 * Backend is `/api/notes/{id}/backlinks` (M7.0.4 — on-demand scan, no
 * precomputed index, fine up to ~5k notes per ADR-0021 baseline).
 */

import { useQuery } from "@tanstack/react-query";
import { Link as LinkIcon } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { getBacklinks } from "@/api/client";
import type { BacklinkRow } from "@/api/types";
import { QK } from "@/lib/queryClient";

interface Group {
  source_id: string;
  source_title: string;
  rows: BacklinkRow[];
}

function groupBySource(rows: BacklinkRow[]): Group[] {
  const map = new Map<string, Group>();
  for (const r of rows) {
    let g = map.get(r.source_id);
    if (!g) {
      g = { source_id: r.source_id, source_title: r.source_title, rows: [] };
      map.set(r.source_id, g);
    }
    g.rows.push(r);
  }
  return Array.from(map.values()).sort((a, b) =>
    a.source_title.toLowerCase().localeCompare(b.source_title.toLowerCase()),
  );
}

/**
 * Split a sentence on `[[…]]` matches so we can render the wikilink with
 * accent styling while keeping the surrounding text untouched. Pipe-style
 * aliases (`[[Title|alias]]`) display only the alias if present, else the
 * raw target — matching how the source text reads.
 */
const WIKILINK_RE = /\[\[([^[\]\n|]+?)(?:\|([^[\]\n]+?))?\]\]/g;

function renderSentence(sentence: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of sentence.matchAll(WIKILINK_RE)) {
    const start = m.index ?? 0;
    if (start > last) {
      parts.push(sentence.slice(last, start));
    }
    const display = (m[2] ?? m[1] ?? "").trim();
    parts.push(
      <span
        key={`wl-${key++}`}
        style={{
          color: "var(--accent-2, #34495e)",
          borderBottom: "2px solid var(--accent, #5b7a9c)",
          padding: "0 1px",
          fontWeight: 500,
        }}
      >
        {display}
      </span>,
    );
    last = start + m[0].length;
  }
  if (last < sentence.length) parts.push(sentence.slice(last));
  return parts;
}

interface Props {
  noteId: string | null;
  noteTitle: string;
  /** Click a backlink → host opens that source note. */
  onOpenSource: (sourceId: string, line: number) => void;
}

export function BacklinksPanel({ noteId, noteTitle, onOpenSource }: Props) {
  const { t } = useTranslation();
  const enabled = !!noteId;

  const query = useQuery({
    queryKey: noteId ? QK.backlinks(noteId) : ["backlinks", "_none"],
    queryFn: () => getBacklinks(noteId as string),
    enabled,
    staleTime: 10_000,
  });

  const groups = useMemo(
    () => (query.data ? groupBySource(query.data) : []),
    [query.data],
  );

  const summary = useMemo(() => {
    if (!query.data) return null;
    const totalMentions = query.data.length;
    const noteCount = groups.length;
    return { totalMentions, noteCount };
  }, [query.data, groups.length]);

  // ------------------------------------------------------------ states

  if (!noteId) {
    return (
      <PanelShell title={t("rail.tab.backlinks")}>
        <div className="px-3 py-4 text-xs" style={{ color: "var(--ink-mute)" }}>
          {t("rail.backlinks.noNote")}
        </div>
      </PanelShell>
    );
  }

  if (query.isLoading) {
    return (
      <PanelShell title={t("rail.tab.backlinks")}>
        <div className="px-3 py-4 text-xs" style={{ color: "var(--ink-mute)" }}>
          {t("rail.backlinks.loading")}
        </div>
      </PanelShell>
    );
  }

  if (query.isError) {
    return (
      <PanelShell title={t("rail.tab.backlinks")}>
        <div className="px-3 py-4 text-xs" style={{ color: "var(--ink-mute)" }}>
          {t("rail.backlinks.loadFailed", {
            error: (query.error as { detail?: string })?.detail ?? "unknown",
          })}
        </div>
      </PanelShell>
    );
  }

  if (groups.length === 0) {
    return (
      <PanelShell title={t("rail.tab.backlinks")}>
        <div
          className="space-y-2 px-3 py-4 text-xs"
          style={{ color: "var(--ink-mute)" }}
        >
          <div>{t("rail.backlinks.empty")}</div>
          <div
            className="font-mono text-[10.5px]"
            style={{ color: "var(--ink-faint, #8e857a)" }}
          >
            {t("rail.backlinks.emptyHint", { title: noteTitle })}
          </div>
        </div>
      </PanelShell>
    );
  }

  // ------------------------------------------------------------ list

  return (
    <PanelShell
      title={t("rail.tab.backlinks")}
      summary={
        summary
          ? t("rail.backlinks.summary", {
              count: summary.totalMentions,
              noteCount: summary.noteCount,
            })
          : null
      }
    >
      <div
        className="flex-1 overflow-y-auto"
        data-testid="backlinks-list"
      >
        {groups.map((g) => (
          <div key={g.source_id}>
            <div
              className="flex items-center gap-1.5 px-3 py-2 font-mono text-[10.5px]"
              style={{
                background: "var(--panel-2, #e7e0d0)",
                color: "var(--ink-mute)",
                borderTop: "1px solid var(--line-soft, #e2dac9)",
                borderBottom: "1px solid var(--line-soft, #e2dac9)",
              }}
            >
              <span style={{ color: "var(--accent-2, #34495e)" }}>
                {g.source_title}
              </span>
              <span style={{ color: "var(--ink-faint, #8e857a)" }}>
                ·{" "}
                {t("rail.backlinks.groupCount", { count: g.rows.length })}
              </span>
            </div>
            {g.rows.map((r) => (
              <button
                key={`${r.source_id}-${r.line}`}
                type="button"
                className="block w-full cursor-pointer text-left"
                onClick={() => onOpenSource(r.source_id, r.line)}
                data-testid="backlink-row"
                style={{
                  padding: "8px 12px 10px",
                  borderTop: "1px solid var(--line-soft, #e2dac9)",
                }}
              >
                <div
                  className="text-[13px] leading-relaxed"
                  style={{
                    color: "var(--ink, #2a2823)",
                    fontFamily:
                      "var(--font-serif, 'Source Serif 4', Georgia, serif)",
                  }}
                >
                  {renderSentence(r.sentence)}
                </div>
                <div
                  className="mt-1 flex items-center gap-1.5 font-mono text-[10.5px]"
                  style={{ color: "var(--ink-mute)" }}
                >
                  <LinkIcon size={9} />
                  <span>{t("rail.backlinks.lineLabel", { line: r.line })}</span>
                </div>
              </button>
            ))}
          </div>
        ))}
      </div>
    </PanelShell>
  );
}

interface PanelShellProps {
  title: string;
  summary?: string | null;
  children: React.ReactNode;
}

function PanelShell({ title, summary, children }: PanelShellProps) {
  return (
    <div
      className="flex h-full min-h-0 flex-col"
      style={{
        background: "var(--panel, #ede7d9)",
        borderLeft: "1px solid var(--line, #d8cfb9)",
      }}
    >
      <div
        className="flex shrink-0 items-center gap-2 px-3 py-2"
        style={{
          borderBottom: "1px solid var(--line, #d8cfb9)",
        }}
      >
        <LinkIcon size={12} style={{ color: "var(--ink-soft, #5a5044)" }} />
        <span className="text-xs font-medium">{title}</span>
        {summary && (
          <span
            className="font-mono text-[10.5px]"
            style={{ color: "var(--ink-mute)" }}
          >
            · {summary}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}
