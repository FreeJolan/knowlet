/**
 * Phase 1 D / D3 — Properties UI for the note header.
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
 * Layout: after 2026-05-08 dogfood we split the panel into two
 * independently-rendered pieces, both wired to the same collapse
 * state:
 *   - `<PropertiesToggle>`  — one segment in the crumb row, looks
 *     like the other crumb dot-separated items. Saves a whole row of
 *     vertical space when collapsed (the original block-card design
 *     stacked under the crumb and felt disproportionate to the rest
 *     of the header).
 *   - `<PropertiesContent>` — the rows themselves; rendered below
 *     TagChipStrip when expanded so aliases sit at the bottom of the
 *     metadata zone, right above the body.
 *
 * Collapse state is per-vault, not per-note. localStorage key
 * `knowlet.properties.collapsed.v1`. Default = collapsed: title +
 * tags are the prominent signal; properties is opt-in detail.
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

/** Shared collapse state. Two siblings both call this and stay in
 *  sync via a `storage` event re-read on every mutation. */
export function usePropertiesCollapsed(): {
  collapsed: boolean;
  toggle: () => void;
} {
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === COLLAPSED_KEY) setCollapsed(readCollapsed());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const toggle = useCallback(() => {
    setCollapsed((prev) => {
      const next = !prev;
      writeCollapsed(next);
      // Same-tab notify so a sibling toggle/content stays in sync
      // without piggybacking on the cross-tab `storage` event (which
      // doesn't fire on the originating tab).
      window.dispatchEvent(
        new StorageEvent("storage", { key: COLLAPSED_KEY }),
      );
      return next;
    });
  }, []);

  return { collapsed, toggle };
}

export function PropertiesToggle({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={!collapsed}
      aria-label={collapsed ? t("noteProps.expand") : t("noteProps.collapse")}
      data-testid="properties-toggle"
      className="inline-flex items-center gap-0.5 rounded-sm transition-colors hover:text-[color:var(--ink)]"
      style={{ color: "inherit" }}
    >
      <ChevronRight
        size={11}
        className="transition-transform"
        style={{ transform: collapsed ? "rotate(0deg)" : "rotate(90deg)" }}
      />
      <span>{t("noteProps.title")}</span>
    </button>
  );
}

interface ContentProps {
  noteId: string;
  collapsed: boolean;
  aliases: string[];
  source: string | null | undefined;
  createdAt: string;
  updatedAt: string;
  onAliasesChange: (next: string[]) => void;
}

export function PropertiesContent({
  noteId,
  collapsed,
  aliases,
  source,
  createdAt,
  updatedAt,
  onAliasesChange,
}: ContentProps) {
  const { t } = useTranslation();
  if (collapsed) return null;

  const handleAdd = (alias: string) => onAliasesChange([...aliases, alias]);
  const handleRemove = (alias: string) =>
    onAliasesChange(aliases.filter((a) => a !== alias));

  return (
    <div
      data-testid="properties-panel"
      data-collapsed="0"
      className="mt-1.5 grid gap-y-1.5 pl-3"
      style={{
        gridTemplateColumns: "minmax(56px, max-content) 1fr",
        columnGap: "10px",
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
            className="flex min-w-0 items-center text-xs"
          >
            <a
              href={source}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-w-0 items-center gap-1 truncate underline decoration-dotted underline-offset-2 hover:decoration-solid"
              title={t("noteProps.sourceOpen")}
              style={{ color: "var(--ink-mute)" }}
            >
              <span className="truncate">{source}</span>
              <ExternalLink size={10} className="flex-shrink-0 opacity-60" />
            </a>
          </div>
        </>
      ) : null}

      <PropertyLabel>{t("noteProps.createdLabel")}</PropertyLabel>
      <div
        data-testid="property-created"
        className="font-mono text-[11px]"
        style={{ color: "var(--ink-mute)" }}
      >
        {formatTs(createdAt)}
      </div>

      <PropertyLabel>{t("noteProps.updatedLabel")}</PropertyLabel>
      <div
        data-testid="property-updated"
        className="font-mono text-[11px]"
        style={{ color: "var(--ink-mute)" }}
      >
        {formatTs(updatedAt)}
      </div>
    </div>
  );
}

function PropertyLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="flex items-center font-mono text-[10px] uppercase tracking-wider"
      style={{ color: "var(--ink-mute)", opacity: 0.7 }}
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
