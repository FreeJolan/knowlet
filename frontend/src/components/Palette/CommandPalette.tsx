/**
 * Cmd+P quick switcher (Phase 1 A, Slice 2.5).
 *
 * Pulls every note title once (cheap on the tree), filters client-side
 * with cmdk's fuzzy match. Phase 1 B will add a /api/search backend call
 * for body-text matching; Phase 1 A keeps it title-only for snap response.
 */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { getTree } from "@/api/client";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { QK } from "@/lib/queryClient";

import type { TreeFolder, TreeNote } from "@/api/types";

interface FlatNote extends TreeNote {
  folderPath: string;
}

function flatten(root: TreeFolder, prefix: string = ""): FlatNote[] {
  const here: FlatNote[] = root.notes.map((n) => ({ ...n, folderPath: prefix }));
  for (const sub of root.folders) {
    here.push(...flatten(sub, prefix ? `${prefix}/${sub.name}` : sub.name));
  }
  return here;
}

export function CommandPalette({
  open,
  onClose,
  onSelectNote,
}: {
  open: boolean;
  onClose: () => void;
  onSelectNote: (id: string) => void;
}) {
  const tree = useQuery({
    queryKey: QK.tree,
    queryFn: getTree,
    enabled: open,
  });
  const notes = useMemo(
    () => (tree.data ? flatten(tree.data) : []),
    [tree.data],
  );
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  // Global Cmd+P / Ctrl+P keyboard shortcut is wired by the parent (AppShell).
  // We just reset state when closed.

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent className="max-w-xl gap-0 p-0">
        <Command label="Quick switcher" shouldFilter={true}>
          <CommandInput
            placeholder="Type a title…"
            value={query}
            onValueChange={setQuery}
          />
          <CommandList>
            <CommandEmpty>No matches.</CommandEmpty>
            <CommandGroup heading={`${notes.length} notes`}>
              {notes.map((n) => (
                <CommandItem
                  key={n.id}
                  value={`${n.title} ${n.folderPath}`}
                  onSelect={() => onSelectNote(n.id)}
                >
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate">{n.title}</span>
                    {n.folderPath && (
                      <span className="truncate font-mono text-[10px] text-muted-foreground">
                        {n.folderPath}
                      </span>
                    )}
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
