/**
 * Cmd+P quick switcher (Phase 1 A, Slice 2.5).
 *
 * Pulls every note title once (cheap on the tree), filters client-side
 * with cmdk's fuzzy match. Phase 1 B will add a /api/search backend call
 * for body-text matching; Phase 1 A keeps it title-only for snap response.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { getTree, listQuickActions, runQuickAction } from "@/api/client";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import type { QuickAction } from "@/api/types";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { QK } from "@/lib/queryClient";

import type { TreeFolder, TreeNote } from "@/api/types";

interface FlatNote extends TreeNote {
  folderPath: string;
}

// Top-level folders the palette should NOT walk into. Mirrors the file
// tree's HIDDEN_TOP_LEVEL_FOLDERS — templates are managed via the
// dedicated Templates dialog, not surfaced as quick-switch targets,
// so the palette doesn't leak the `_templates/` storage convention.
const PALETTE_HIDDEN_FOLDERS = new Set(["_templates"]);

function flatten(root: TreeFolder, prefix: string = ""): FlatNote[] {
  const here: FlatNote[] = root.notes.map((n) => ({ ...n, folderPath: prefix }));
  for (const sub of root.folders) {
    if (!prefix && PALETTE_HIDDEN_FOLDERS.has(sub.name)) continue;
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
  const { t } = useTranslation();
  const qc = useQueryClient();
  const tree = useQuery({
    queryKey: QK.tree,
    queryFn: getTree,
    enabled: open,
  });
  const actions = useQuery<QuickAction[]>({
    queryKey: QK.quickActions,
    queryFn: listQuickActions,
    enabled: open,
    // Always refetch on open: the palette is the canonical place to
    // run actions; users editing actions in Settings (Slice 2c.2)
    // expect fresh state without a manual reload.
    staleTime: 0,
  });
  const notes = useMemo(
    () => (tree.data ? flatten(tree.data) : []),
    [tree.data],
  );
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  // Phase 2 D Slice 2c — running a quick action returns NoteFull
  // (idempotent: same-day re-runs reuse the existing note). On
  // success: invalidate tree + open the note via onSelectNote.
  const runMutation = useMutation({
    mutationFn: (id: string) => runQuickAction(id),
    onSuccess: (note) => {
      void qc.invalidateQueries({ queryKey: QK.tree });
      onSelectNote(note.id);
      onClose();
    },
  });

  // Global Cmd+P / Ctrl+P keyboard shortcut is wired by the parent (AppShell).
  // We just reset state when closed.

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onClose();
      }}
    >
      <DialogContent className="gap-0 p-0 sm:max-w-3xl">
        <DialogHeader className="sr-only">
          <DialogTitle>{t("app.quickSwitch")}</DialogTitle>
        </DialogHeader>
        <Command label={t("app.quickSwitch")} shouldFilter={true}>
          <CommandInput
            placeholder={t("palette.placeholder")}
            value={query}
            onValueChange={setQuery}
          />
          {/* Bump the list height so a dozen notes are visible without
            * scrolling. shadcn's default `max-h-72` (288px) feels
            * cramped on a wide dialog. */}
          <CommandList className="max-h-[60vh]">
            <CommandEmpty>{t("palette.noMatches")}</CommandEmpty>
            {actions.data && actions.data.length > 0 && (
              <CommandGroup heading={t("palette.actionsCount", { count: actions.data.length })}>
                {actions.data.map((a) => (
                  <CommandItem
                    key={a.id}
                    className="!py-1.5"
                    value={`${a.name} ${a.description ?? ""} ${a.shortcut ?? ""} action`}
                    onSelect={() => runMutation.mutate(a.id)}
                    data-testid="palette-action-item"
                    data-action-id={a.id}
                  >
                    <Zap
                      className="size-3.5 shrink-0"
                      style={{ color: "var(--accent)" }}
                    />
                    <span className="truncate">{a.name}</span>
                    {a.description && (
                      <span className="ml-2 truncate text-[11px] text-muted-foreground">
                        {a.description}
                      </span>
                    )}
                    {a.shortcut && (
                      <span className="ml-auto shrink-0 pl-3 font-mono text-[11px] text-muted-foreground">
                        {a.shortcut}
                      </span>
                    )}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            <CommandGroup heading={t("palette.notesCount", { count: notes.length })}>
              {notes.map((n) => (
                <CommandItem
                  key={n.id}
                  // Compact row: tighter vertical padding overrides the
                  // shadcn default `py-1.5` so a long list isn't a wall
                  // of evenly-spaced "cards". Folder context renders
                  // INLINE on the right (gray + small) so two notes
                  // with the same title but different folders are
                  // distinguishable at a glance.
                  className="!py-1.5"
                  value={`${n.title} ${n.folderPath}`}
                  onSelect={() => onSelectNote(n.id)}
                >
                  <span className="truncate">{n.title}</span>
                  {n.folderPath && (
                    <span className="ml-auto shrink-0 truncate pl-3 font-mono text-[11px] text-muted-foreground">
                      {n.folderPath}
                    </span>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
