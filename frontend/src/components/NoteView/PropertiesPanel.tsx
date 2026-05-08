/**
 * Phase 1 D / D3 — collapsible "Properties" panel under the note title.
 *
 * Surfaces the structured frontmatter fields that aren't tags or
 * title, in a typed-form layout (Obsidian-style) so users never have
 * to touch raw YAML to edit them. Conservative v1 scope:
 *
 *   - Aliases (chip strip — editable; PUT /api/notes/{id}.aliases)
 *   - Source (read-only link if the note was captured from a URL)
 *   - Created (read-only ISO date)
 *   - Updated (read-only ISO date)
 *
 * Out of scope for v1 (all explicitly deferred per ADR-0023 §7 +
 * roadmap "保守版" qualifier):
 *   - status enum (active/stub/needs-update/deprecated) — schema v2,
 *     Phase 2 E
 *   - custom user-defined fields — needs typed-field schema first
 *
 * Collapse state is per-vault, not per-note: persisted in
 * localStorage `knowlet.properties.collapsed.v1`. Default = collapsed
 * — the chevron + "Properties" label still announces the surface,
 * and the most-frequent fields (title, tags) are already prominent
 * elsewhere in the header. Expanding it eats ~50 px of vertical
 * space; we'd rather the user opt in than lose body real estate by
 * default.
 */

import { ChevronRight, ExternalLink } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { AliasChipStrip } from "./AliasChipStrip";

const COLLAPSED_KEY = "knowlet.properties.collapsed.v1";

function readCollapsed(): boolean {
  if (typeof window === "undefined") return true;
  try {
    const raw = window.localStorage.getItem(COLLAPSED_KEY);
    // Tri-valued: "1" → collapsed, "0" → expanded, null → default (collapsed).
    if (raw === "0") return false;
    return true;
  } catch {
    return true;
  }
}

function writeCollapsed(v: boolean): void {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, v ? "1" : "0");
  } catch {
    /* localStorage disabled — tolerate */
  }
}

interface Props {
  noteId: string;
  aliases: string[];
  source: string | null | undefined;
  createdAt: string;
  updatedAt: string;
  onAliasesChange: (next: string[]) => void;
}

export function PropertiesPanel({
  noteId,
  aliases,
  source,
  createdAt,
  updatedAt,
  onAliasesChange,
}: Props) {
  const { t } = useTranslation();
  const [collapsed, setCollapsedState] = useState<boolean>(readCollapsed);

  const setCollapsed = useCallback((v: boolean) => {
    setCollapsedState(v);
    writeCollapsed(v);
  }, []);

  // Cross-tab sync: another tab toggles the panel → reflect here.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === COLLAPSED_KEY) setCollapsedState(readCollapsed());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const handleAdd = (alias: string) => onAliasesChange([...aliases, alias]);
  const handleRemove = (alias: string) =>
    onAliasesChange(aliases.filter((a) => a !== alias));

  return (
    <section
      data-testid="properties-panel"
      data-collapsed={collapsed ? "1" : "0"}
      className="mt-3 rounded border"
      style={{
        borderColor: "var(--line)",
        background: "var(--card, transparent)",
      }}
    >
      <button
        type="button"
        onClick={() => setCollapsed(!collapsed)}
        aria-expanded={!collapsed}
        aria-label={collapsed ? t("noteProps.expand") : t("noteProps.collapse")}
        data-testid="properties-toggle"
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-mono uppercase tracking-wider transition-colors hover:bg-accent/20"
        style={{ color: "var(--ink-mute)" }}
      >
        <ChevronRight
          size={12}
          className="transition-transform"
          style={{ transform: collapsed ? "rotate(0deg)" : "rotate(90deg)" }}
        />
        <span>{t("noteProps.title")}</span>
      </button>
      {!collapsed && (
        <div
          className="grid gap-y-2 px-3 pb-3 pt-1"
          style={{
            gridTemplateColumns: "minmax(80px, max-content) 1fr",
            columnGap: "12px",
          }}
        >
          <PropertyLabel>{t("noteProps.aliasesLabel")}</PropertyLabel>
          <div data-testid="property-aliases">
            <AliasChipStrip
              aliases={aliases}
              noteId={noteId}
              onAdd={handleAdd}
              onRemove={handleRemove}
            />
          </div>

          {source ? (
            <>
              <PropertyLabel>{t("noteProps.sourceLabel")}</PropertyLabel>
              <div
                data-testid="property-source"
                className="flex min-w-0 items-center gap-1 text-xs"
                style={{ color: "var(--ink)" }}
              >
                <a
                  href={source}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex min-w-0 items-center gap-1 truncate underline decoration-dotted underline-offset-2 hover:decoration-solid"
                  title={t("noteProps.sourceOpen")}
                  style={{ color: "var(--accent, #5b7a9c)" }}
                >
                  <span className="truncate">{source}</span>
                  <ExternalLink size={11} className="flex-shrink-0" />
                </a>
              </div>
            </>
          ) : null}

          <PropertyLabel>{t("noteProps.createdLabel")}</PropertyLabel>
          <div
            data-testid="property-created"
            className="font-mono text-xs"
            style={{ color: "var(--ink-mute)" }}
          >
            {formatTs(createdAt)}
          </div>

          <PropertyLabel>{t("noteProps.updatedLabel")}</PropertyLabel>
          <div
            data-testid="property-updated"
            className="font-mono text-xs"
            style={{ color: "var(--ink-mute)" }}
          >
            {formatTs(updatedAt)}
          </div>
        </div>
      )}
    </section>
  );
}

function PropertyLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex items-center font-mono text-[11px] uppercase tracking-wider"
      style={{ color: "var(--ink-mute)" }}
    >
      {children}
    </div>
  );
}

function formatTs(iso: string): string {
  // Notes use UTC ISO strings ("2026-05-08T10:23:11Z"). Keep the
  // human-readable shape ("2026-05-08 10:23 UTC") — full timestamp
  // matters for "did I edit this today?" decisions; relative time
  // ("2 hours ago") obscures it. The crumb row above the title still
  // shows just the date for at-a-glance.
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const yyyy = d.getUTCFullYear();
  const mm = String(d.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mi = String(d.getUTCMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi} UTC`;
}
