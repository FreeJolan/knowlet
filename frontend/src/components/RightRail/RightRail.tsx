/**
 * Phase 1 C — right rail container.
 *
 * Phase 1 C ships only one panel (Backlinks). The container is built with
 * tab structure ready so Phase 3 can drop in AI dock / Capsules / History
 * tabs without restructuring the layout.
 */

import { BacklinksPanel } from "./BacklinksPanel";

interface Props {
  noteId: string | null;
  noteTitle: string;
  onOpenSource: (sourceId: string, line: number) => void;
  onOpenTarget: (targetNoteId: string) => void;
}

export function RightRail({
  noteId,
  noteTitle,
  onOpenSource,
  onOpenTarget,
}: Props) {
  // Single tab for now (Backlinks). When Phase 3 adds AI dock + Capsules
  // + History, replace this with a tab list + active-tab state.
  return (
    <BacklinksPanel
      noteId={noteId}
      noteTitle={noteTitle}
      onOpenSource={onOpenSource}
      onOpenTarget={onOpenTarget}
    />
  );
}
