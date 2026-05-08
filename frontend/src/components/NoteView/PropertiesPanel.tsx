/**
 * Phase 1 D / D3 — Properties surface for the note header.
 *
 * After 2026-05-09 Claude Design handoff (`note-header.jsx`), the
 * NoteView header was redesigned as a "byline" with three rows:
 *
 *   Row A — title (28px serif) + view-mode toggle
 *   Row B — kicker  folder · ULID · UPDATED · source-pill · spacer · ▸ Properties
 *   Row C — tags chip-strip │ aliases chip-strip   (only when ≥1 of either)
 *
 * Properties (this file) is no longer a full panel of fields. Most
 * meta now lives in the byline directly:
 *   - aliases  → row C (chip strip, always visible if ≥1)
 *   - updated  → kicker
 *   - source (host) → kicker
 *
 * The expanded panel only adds two things that wouldn't fit:
 *   - `created` (full UTC timestamp — kicker only shows updated)
 *   - `source` (the FULL URL — kicker shows host only)
 *
 * That keeps the expand affordance discoverable but no longer
 * carrying primary fields. Empty state (no source, no aliases, no
 * tags) → caller can hide row C entirely; this content still
 * renders created + (optionally) source.
 *
 * Collapse state is per-vault, not per-note. localStorage key
 * `knowlet.properties.collapsed.v1`. Default = collapsed.
 */

import { ChevronRight, ExternalLink } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

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
      window.dispatchEvent(
        new StorageEvent("storage", { key: COLLAPSED_KEY }),
      );
      return next;
    });
  }, []);

  return { collapsed, toggle };
}

/** Inline kicker-row toggle. Sized + colored to read as a peer of
 *  the surrounding mono-uppercase metadata. */
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
      className="inline-flex items-center gap-1 rounded-sm font-mono text-[11px] uppercase tracking-wider transition-colors hover:text-[color:var(--ink)]"
      style={{ color: "var(--ink-mute)" }}
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

/** Compact host pill, embedded in the kicker row.
 *  Shows the host (`arxiv.org`); the full URL is in expanded panel. */
export function SourceKickerPill({ url }: { url: string }) {
  const { t } = useTranslation();
  let host = url;
  try {
    host = new URL(url).host.replace(/^www\./, "");
  } catch {
    /* leave url as-is if not parseable */
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="property-source-pill"
      title={t("noteProps.sourceOpen")}
      className="inline-flex items-center gap-1 font-mono text-[11px] lowercase tracking-wide"
      style={{
        color: "var(--accent-2)",
        borderBottom: "1px dashed var(--accent)",
        paddingBottom: 1,
      }}
    >
      <ExternalLink size={10} />
      <span>{host}</span>
    </a>
  );
}

interface ContentProps {
  collapsed: boolean;
  source: string | null | undefined;
  createdAt: string;
}

export function PropertiesContent({
  collapsed,
  source,
  createdAt,
}: ContentProps) {
  const { t } = useTranslation();
  if (collapsed) return null;

  return (
    <div
      data-testid="properties-panel"
      data-collapsed="0"
      className="mt-3 grid items-center pt-3"
      style={{
        borderTop: "1px dashed var(--line)",
        gridTemplateColumns: "minmax(56px, max-content) 1fr",
        rowGap: "6px",
        columnGap: "24px",
      }}
    >
      <PropertyLabel>{t("noteProps.createdLabel")}</PropertyLabel>
      <div
        data-testid="property-created"
        className="font-mono text-[12px]"
        style={{ color: "var(--ink-soft)" }}
      >
        {formatTs(createdAt)}
      </div>

      {source ? (
        <>
          <PropertyLabel>{t("noteProps.sourceLabel")}</PropertyLabel>
          <a
            href={source}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="property-source"
            className="truncate font-mono text-[12px]"
            style={{
              color: "var(--accent-2)",
              borderBottom: "1px dashed var(--accent)",
              width: "fit-content",
              paddingBottom: 1,
            }}
            title={t("noteProps.sourceOpen")}
          >
            {source}
          </a>
        </>
      ) : null}
    </div>
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
