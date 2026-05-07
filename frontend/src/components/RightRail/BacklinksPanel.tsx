/**
 * Phase 1 C slice 1 (+ slice 1 polish) — right-rail "Linked notes" panel.
 *
 * Layout: PanelShell with two collapsible sub-sections:
 *   1. Inbound — notes that reference THIS one via [[Title]]
 *      (consumes /api/notes/{id}/backlinks, M7.0.4)
 *   2. Outbound — notes THIS note references via [[Title]]
 *      (parsed client-side from the cached note body; dangling links
 *      rendered with strikethrough)
 *
 * Both sections share the same row look (sentence preview with
 * underlined wikilink, source/target title + line indicator). Click any
 * row → opens the relevant note + scrolls editor to the right line.
 */

import { useQuery } from "@tanstack/react-query";
import {
  ArrowDownLeft,
  ArrowUpRight,
  ChevronDown,
  ChevronRight,
  Link as LinkIcon,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getBacklinks, getNote, getTree } from "@/api/client";
import type { BacklinkRow, NoteFull, TreeFolder } from "@/api/types";
import { QK } from "@/lib/queryClient";
import {
  buildTitleIndex,
  extractOutboundLinks,
  type OutboundLink,
} from "@/lib/wikilinks";

const WIKILINK_RE = /\[\[([^[\]\n|]+?)(?:\|([^[\]\n]+?))?\]\]/g;

interface InboundGroup {
  source_id: string;
  source_title: string;
  rows: BacklinkRow[];
}

function groupBySource(rows: BacklinkRow[]): InboundGroup[] {
  const map = new Map<string, InboundGroup>();
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
 * True when the trimmed sentence is essentially just the wikilink itself
 * — i.e. the source note's line was `[[Title]]` with at most surrounding
 * whitespace or terminal punctuation. In that case showing the styled
 * link in the row is purely redundant with the section header (which
 * already reads "Inbound"; the source title group header already names
 * the source) AND the current note's title (which the user is viewing).
 * Replace with a muted placeholder.
 */
function isLinkOnlySentence(sentence: string): boolean {
  const stripped = sentence.replace(WIKILINK_RE, "").trim();
  if (stripped.length === 0) return true;
  // Common terminal / list punctuation that adds no real context.
  return /^[\s.,;:!?。、！？·•\-—()（）"'""]+$/u.test(stripped);
}

function renderSentence(sentence: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of sentence.matchAll(WIKILINK_RE)) {
    const start = m.index ?? 0;
    if (start > last) parts.push(sentence.slice(last, start));
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
  /** Click an inbound row → host opens the source note + scrolls to line. */
  onOpenSource: (sourceId: string, line: number) => void;
  /** Click an outbound row → host opens the target note. The current
   *  note's line is irrelevant for outbound, so no line param. */
  onOpenTarget: (targetNoteId: string) => void;
}

export function BacklinksPanel({
  noteId,
  noteTitle,
  onOpenSource,
  onOpenTarget,
}: Props) {
  const { t } = useTranslation();
  const enabled = !!noteId;

  const inbound = useQuery({
    queryKey: noteId ? QK.backlinks(noteId) : ["backlinks", "_none"],
    queryFn: () => getBacklinks(noteId as string),
    enabled,
    staleTime: 10_000,
  });

  // We pull the note via the same QK.note key NoteView uses, so the
  // request is deduped (or hits cache if NoteView already fetched it).
  const note = useQuery<NoteFull>({
    queryKey: noteId ? QK.note(noteId) : ["note", "_empty"],
    queryFn: () => getNote(noteId as string),
    enabled,
    staleTime: 10_000,
  });

  // Subscribe to the tree cache so the outbound resolution updates
  // automatically when notes get renamed / created / deleted elsewhere.
  const tree = useQuery<TreeFolder>({
    queryKey: QK.tree,
    queryFn: getTree,
    staleTime: 30_000,
  });
  const titleIndex = useMemo(
    () => buildTitleIndex(tree.data),
    [tree.data],
  );

  const outbound: OutboundLink[] = useMemo(() => {
    if (!note.data) return [];
    return extractOutboundLinks(note.data.body, titleIndex, noteId ?? null);
  }, [note.data, titleIndex, noteId]);

  const inboundGroups = useMemo(
    () => (inbound.data ? groupBySource(inbound.data) : []),
    [inbound.data],
  );

  const inboundSummary = useMemo(() => {
    if (!inbound.data) return null;
    return {
      totalMentions: inbound.data.length,
      noteCount: inboundGroups.length,
    };
  }, [inbound.data, inboundGroups.length]);

  const outboundSummary = useMemo(() => {
    if (!note.data) return null;
    const broken = outbound.filter((o) => o.dangling).length;
    return { total: outbound.length, broken };
  }, [note.data, outbound]);

  // Both sections collapse independently, default to expanded so the
  // dogfood path is "open note → see linked notes" without an extra click.
  const [inboundOpen, setInboundOpen] = useState(true);
  const [outboundOpen, setOutboundOpen] = useState(true);

  // -------------------------------------------------------- empty / no-note

  if (!noteId) {
    return (
      <PanelShell title={t("rail.tab.backlinks")}>
        <div className="px-3 py-4 text-xs" style={{ color: "var(--ink-mute)" }}>
          {t("rail.backlinks.noNote")}
        </div>
      </PanelShell>
    );
  }

  // -------------------------------------------------------------- main render

  return (
    <PanelShell title={t("rail.tab.backlinks")}>
      <div className="flex-1 overflow-y-auto">
        {/* ---------- Inbound section ---------- */}
        <SectionHeader
          icon={<ArrowDownLeft size={11} />}
          label={t("rail.section.inbound")}
          summary={
            inboundSummary
              ? t("rail.backlinks.summary", {
                  count: inboundSummary.totalMentions,
                  noteCount: inboundSummary.noteCount,
                })
              : null
          }
          open={inboundOpen}
          onToggle={() => setInboundOpen((v) => !v)}
          testid="rail-inbound-header"
        />
        {inboundOpen && (
          <div data-testid="backlinks-list">
            {inbound.isLoading && (
              <SectionPlaceholder text={t("rail.backlinks.loading")} />
            )}
            {inbound.isError && (
              <SectionPlaceholder
                text={t("rail.backlinks.loadFailed", {
                  error:
                    (inbound.error as { detail?: string })?.detail ?? "unknown",
                })}
              />
            )}
            {inbound.data && inboundGroups.length === 0 && (
              <SectionPlaceholder
                text={t("rail.backlinks.empty")}
                hint={t("rail.backlinks.emptyHint", { title: noteTitle })}
              />
            )}
            {inboundGroups.map((g) => (
              <div key={g.source_id}>
                <GroupHeader
                  title={g.source_title}
                  count={t("rail.backlinks.groupCount", { count: g.rows.length })}
                />
                {g.rows.map((r) => {
                  const linkOnly = isLinkOnlySentence(r.sentence);
                  return (
                    <button
                      key={`${r.source_id}-${r.line}`}
                      type="button"
                      className="block w-full cursor-pointer text-left"
                      onClick={() => onOpenSource(r.source_id, r.line)}
                      data-testid="backlink-row"
                      data-link-only={linkOnly ? "1" : "0"}
                      style={rowStyle}
                    >
                      {linkOnly ? (
                        <div
                          className="text-[12px] italic"
                          style={{ color: "var(--ink-mute)" }}
                        >
                          {t("rail.backlinks.linkOnly")}
                        </div>
                      ) : (
                        <div className="text-[13px] leading-relaxed" style={sentenceStyle}>
                          {renderSentence(r.sentence)}
                        </div>
                      )}
                      <div
                        className="mt-1 flex items-center gap-1.5 font-mono text-[10.5px]"
                        style={{ color: "var(--ink-mute)" }}
                      >
                        <LinkIcon size={9} />
                        <span>{t("rail.backlinks.lineLabel", { line: r.line })}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        )}

        {/* ---------- Outbound section ---------- */}
        <SectionHeader
          icon={<ArrowUpRight size={11} />}
          label={t("rail.section.outbound")}
          summary={
            outboundSummary
              ? outboundSummary.broken > 0
                ? t("rail.outbound.summaryWithBroken", {
                    count: outboundSummary.total,
                    broken: outboundSummary.broken,
                  })
                : t("rail.outbound.summary", { count: outboundSummary.total })
              : null
          }
          open={outboundOpen}
          onToggle={() => setOutboundOpen((v) => !v)}
          testid="rail-outbound-header"
        />
        {outboundOpen && (
          <div data-testid="outbound-list">
            {note.isLoading && (
              <SectionPlaceholder text={t("rail.backlinks.loading")} />
            )}
            {note.data && outbound.length === 0 && (
              <SectionPlaceholder text={t("rail.outbound.empty")} />
            )}
            {outbound.map((o) => (
              <button
                key={o.targetKey}
                type="button"
                disabled={o.dangling}
                className="block w-full text-left"
                onClick={() => {
                  if (!o.dangling && o.resolvedNoteId)
                    onOpenTarget(o.resolvedNoteId);
                }}
                data-testid="outbound-row"
                data-dangling={o.dangling ? "1" : "0"}
                style={{
                  ...rowStyle,
                  cursor: o.dangling ? "not-allowed" : "pointer",
                  opacity: o.dangling ? 0.6 : 1,
                }}
              >
                <div
                  className="flex items-center gap-1.5 text-[13px] leading-snug"
                  style={{
                    fontFamily:
                      "var(--font-serif, 'Source Serif 4', Georgia, serif)",
                    color: "var(--ink, #2a2823)",
                  }}
                >
                  <span
                    style={{
                      color: o.dangling
                        ? "var(--ink-mute)"
                        : "var(--accent-2, #34495e)",
                      borderBottom: o.dangling
                        ? "1px dashed var(--ink-mute)"
                        : "2px solid var(--accent, #5b7a9c)",
                      padding: "0 1px",
                      fontWeight: 500,
                      textDecoration: o.dangling ? "line-through" : "none",
                    }}
                  >
                    {o.target}
                  </span>
                  {o.count > 1 && (
                    <span
                      className="font-mono text-[10.5px]"
                      style={{ color: "var(--ink-mute)" }}
                    >
                      ×{o.count}
                    </span>
                  )}
                  {o.dangling && (
                    <span
                      className="font-mono text-[10px] uppercase tracking-wider"
                      style={{ color: "var(--ink-mute)" }}
                    >
                      {t("rail.outbound.brokenLabel")}
                    </span>
                  )}
                </div>
                {!isLinkOnlySentence(o.sentence) && (
                  <div className="mt-1 text-[12px]" style={sentenceStyle}>
                    {renderSentence(o.sentence)}
                  </div>
                )}
                <div
                  className="mt-1 flex items-center gap-1.5 font-mono text-[10.5px]"
                  style={{ color: "var(--ink-mute)" }}
                >
                  <LinkIcon size={9} />
                  <span>{t("rail.backlinks.lineLabel", { line: o.line })}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </PanelShell>
  );
}

// -------------------------------------------------------------- subcomponents

interface SectionHeaderProps {
  icon: React.ReactNode;
  label: string;
  summary: string | null;
  open: boolean;
  onToggle: () => void;
  testid: string;
}

function SectionHeader({
  icon,
  label,
  summary,
  open,
  onToggle,
  testid,
}: SectionHeaderProps) {
  return (
    <button
      type="button"
      onClick={onToggle}
      data-testid={testid}
      className="flex w-full items-center gap-1.5 px-3 py-1.5 font-mono text-[10.5px] transition-colors hover:bg-accent/20"
      style={{
        background: "var(--panel-2, #e7e0d0)",
        color: "var(--ink-soft)",
        borderBottom: "1px solid var(--line-soft, #e2dac9)",
      }}
    >
      {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
      {icon}
      <span style={{ fontWeight: 500 }}>{label}</span>
      {summary && (
        <span style={{ color: "var(--ink-mute)" }}>· {summary}</span>
      )}
    </button>
  );
}

function GroupHeader({ title, count }: { title: string; count: string }) {
  return (
    <div
      className="flex items-center gap-1.5 px-3 py-1 font-mono text-[10.5px]"
      style={{
        color: "var(--ink-mute)",
        background: "var(--panel, #ede7d9)",
      }}
    >
      <span style={{ color: "var(--accent-2, #34495e)" }}>{title}</span>
      <span style={{ color: "var(--ink-faint, #8e857a)" }}>· {count}</span>
    </div>
  );
}

function SectionPlaceholder({ text, hint }: { text: string; hint?: string }) {
  return (
    <div className="space-y-2 px-3 py-3 text-xs" style={{ color: "var(--ink-mute)" }}>
      <div>{text}</div>
      {hint && (
        <div
          className="font-mono text-[10.5px]"
          style={{ color: "var(--ink-faint, #8e857a)" }}
        >
          {hint}
        </div>
      )}
    </div>
  );
}

const rowStyle = {
  width: "100%",
  padding: "8px 12px 10px",
  borderTop: "1px solid var(--line-soft, #e2dac9)",
} as const;

const sentenceStyle = {
  color: "var(--ink, #2a2823)",
  fontFamily: "var(--font-serif, 'Source Serif 4', Georgia, serif)",
} as const;

interface PanelShellProps {
  title: string;
  children: React.ReactNode;
}

function PanelShell({ title, children }: PanelShellProps) {
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
        style={{ borderBottom: "1px solid var(--line, #d8cfb9)" }}
      >
        <LinkIcon size={12} style={{ color: "var(--ink-soft, #5a5044)" }} />
        <span className="text-xs font-medium">{title}</span>
      </div>
      {children}
    </div>
  );
}
