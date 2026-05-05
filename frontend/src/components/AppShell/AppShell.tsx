/**
 * Phase 1 A app shell — left tree | right note view.
 *
 * Tree mutates the vault, NoteView reads from it. Selection state lives
 * here so a future palette / Cmd+P can also drive it.
 */

import { useEffect, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";

import { FileTree } from "@/components/FileTree/FileTree";
import { NoteView } from "@/components/NoteView/NoteView";
import { TrashPanel } from "@/components/Trash/TrashPanel";
import { CommandPalette } from "@/components/Palette/CommandPalette";
import { Button } from "@/components/ui/button";
import { Trash2 } from "lucide-react";

export function AppShell() {
  const [selectedNoteId, setSelectedNoteId] = useState<string | null>(null);
  const [trashOpen, setTrashOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Reserved for Phase 1 B — when a tree mutation is in flight we may want
  // to mark the editor read-only so the user doesn't type into a stale
  // note that's about to be moved out from under them.
  const [, setTreeBusy] = useState(false);

  useEffect(() => {
    const openPalette = () => setPaletteOpen(true);
    const openTrash = () => setTrashOpen(true);
    window.addEventListener("knowlet:open-palette", openPalette);
    window.addEventListener("knowlet:open-trash", openTrash);
    return () => {
      window.removeEventListener("knowlet:open-palette", openPalette);
      window.removeEventListener("knowlet:open-trash", openTrash);
    };
  }, []);

  return (
    <>
      <div
        className="grid h-screen grid-rows-[auto_1fr]"
        style={{ background: "var(--bg)" }}
      >
        <header
          className="flex items-center justify-between border-b px-4 py-2"
          style={{ borderColor: "var(--line)", background: "var(--panel)" }}
        >
          <div
            className="font-mono text-xs uppercase tracking-widest"
            style={{ color: "var(--ink-mute)" }}
          >
            knowlet
          </div>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setPaletteOpen(true)}
              className="font-mono text-xs"
            >
              <span style={{ color: "var(--ink-mute)" }}>⌘P</span>
              <span className="ml-2">Quick switch</span>
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="Trash"
              onClick={() => setTrashOpen(true)}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
        </header>
        <Group orientation="horizontal" className="overflow-hidden">
          <Panel defaultSize={26} minSize={16}>
            <FileTree
              selectedNoteId={selectedNoteId}
              onSelectNote={setSelectedNoteId}
              onMutating={setTreeBusy}
            />
          </Panel>
          <Separator
            className="w-px cursor-col-resize transition-colors hover:bg-accent data-[separator-state=drag]:bg-accent"
            style={{ background: "var(--line)" }}
          />
          <Panel minSize={30}>
            <NoteView noteId={selectedNoteId} />
          </Panel>
        </Group>
      </div>
      <TrashPanel
        open={trashOpen}
        onClose={() => setTrashOpen(false)}
        onRestored={(restoredId) => setSelectedNoteId(restoredId)}
      />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onSelectNote={(id) => {
          setSelectedNoteId(id);
          setPaletteOpen(false);
        }}
      />
    </>
  );
}
