/**
 * Phase 1 C — right rail container.
 *
 * Slice 1 shipped a single-panel rail (Backlinks). Slice 3 adds Graph
 * as a peer tab. Phase 3 will add AI dock + Capsules + History.
 *
 * Tab strip styling matches the design spec frame in
 * `docs/design/bundle-2026-05-08-graph/project/graph.jsx` —
 * paper background, accent top-border on the active tab.
 */

import { Link as LinkIcon, Network } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { BacklinksPanel } from "./BacklinksPanel";
import { GraphPanel } from "@/components/Graph/GraphPanel";

type Tab = "backlinks" | "graph";

interface Props {
  noteId: string | null;
  noteTitle: string;
  onOpenSource: (sourceId: string, line: number) => void;
  onOpenTarget: (targetNoteId: string) => void;
  onEnterGraphFocus: () => void;
}

export function RightRail({
  noteId,
  noteTitle,
  onOpenSource,
  onOpenTarget,
  onEnterGraphFocus,
}: Props) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("backlinks");

  return (
    <div
      className="flex h-full min-h-0 flex-col"
      style={{
        background: "var(--panel, #ede7d9)",
        borderLeft: "1px solid var(--line, #d8cfb9)",
      }}
    >
      <div
        className="flex shrink-0"
        style={{
          borderBottom: "1px solid var(--line)",
          background: "var(--panel-2, #e7e0d0)",
        }}
        data-testid="rail-tabs"
      >
        <TabButton
          label={t("rail.tab.backlinks")}
          icon={<LinkIcon size={11} />}
          active={tab === "backlinks"}
          onClick={() => setTab("backlinks")}
          testid="rail-tab-backlinks"
        />
        <TabButton
          label={t("rail.tab.graph")}
          icon={<Network size={11} />}
          active={tab === "graph"}
          onClick={() => setTab("graph")}
          testid="rail-tab-graph"
        />
      </div>
      <div className="min-h-0 flex-1">
        {tab === "backlinks" && (
          <BacklinksPanel
            noteId={noteId}
            noteTitle={noteTitle}
            onOpenSource={onOpenSource}
            onOpenTarget={onOpenTarget}
          />
        )}
        {tab === "graph" && (
          <GraphPanel
            noteId={noteId}
            onOpenNote={onOpenTarget}
            onEnterFocus={onEnterGraphFocus}
          />
        )}
      </div>
    </div>
  );
}

interface TabButtonProps {
  label: string;
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
  testid: string;
}

function TabButton({ label, icon, active, onClick, testid }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testid}
      aria-pressed={active}
      className="flex flex-1 items-center justify-center gap-1.5 px-3 py-2 text-xs transition-colors"
      style={{
        color: active ? "var(--ink)" : "var(--ink-mute)",
        fontWeight: active ? 500 : 400,
        background: active ? "var(--panel, #ede7d9)" : "transparent",
        borderTop: active
          ? "2px solid var(--accent, #5b7a9c)"
          : "2px solid transparent",
      }}
    >
      {icon}
      {label}
    </button>
  );
}
