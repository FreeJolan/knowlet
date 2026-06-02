/**
 * Cmd+K quick switcher (Phase 1 A, Slice 2.5) +
 * Cmd+Shift+P command palette (Phase 2 D Slice 2c.3).
 *
 * Two modes share one dialog (VS Code pattern):
 *   - "files":    list notes only. Default for ⌘K.
 *   - "commands": list quick actions + built-in UI commands.
 *                 Default for ⌘⇧P; reachable from files mode by
 *                 typing "`>`" as the first character.
 *
 * Backspace at empty input in commands mode returns to files mode.
 * Esc closes the dialog.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, FileText, Loader2, Star, Zap } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  getTree,
  listFavorites,
  listQuickActions,
  runQuickAction,
} from "@/api/client";
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

import type { PaletteCommand } from "./commands";
import type { TreeFolder, TreeNote } from "@/api/types";

interface FlatNote extends TreeNote {
  folderPath: string;
}

export type PaletteMode = "files" | "commands";

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
  initialMode = "files",
  onClose,
  onSelectNote,
  builtinCommands,
}: {
  open: boolean;
  /** Mode the palette opens in. Caller resets this each time it opens
   *  (⌘K → "files", ⌘⇧P → "commands"). */
  initialMode?: PaletteMode;
  onClose: () => void;
  onSelectNote: (id: string) => void;
  /** Built-in UI commands provided by AppShell — closures over its
   *  setters. Quick actions are fetched separately. */
  builtinCommands: PaletteCommand[];
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [mode, setMode] = useState<PaletteMode>(initialMode);
  const [query, setQuery] = useState("");
  // Phase 2 D B1 — sticky "favorites only" filter within files mode.
  // Activated by typing ``@`` as the first char (mirroring ``>`` for
  // commands). Cleared by Backspace at empty input. Persists across
  // subsequent keystrokes so the user can refine without retyping @.
  const [favoritesOnly, setFavoritesOnly] = useState(false);

  const tree = useQuery({
    queryKey: QK.tree,
    queryFn: getTree,
    enabled: open && mode === "files",
  });
  const actions = useQuery<QuickAction[]>({
    queryKey: QK.quickActions,
    queryFn: listQuickActions,
    enabled: open && mode === "commands",
    // Always refetch on open: the palette is the canonical place to
    // run actions; users editing actions in the manager (Slice 2c.2)
    // expect fresh state without a manual reload.
    staleTime: 0,
  });
  const notes = useMemo(
    () => (tree.data ? flatten(tree.data) : []),
    [tree.data],
  );

  // Phase 2 D B1 — favorites integration. Loaded once when the
  // palette opens in files mode; used for (a) the always-on
  // "Starred" group at the top of the empty-input state, and
  // (b) the ``@`` prefix filter that scopes the search to favorites.
  const favs = useQuery({
    queryKey: QK.favorites,
    queryFn: listFavorites,
    enabled: open && mode === "files",
    staleTime: 30_000,
  });
  const starredIds = useMemo(
    () => new Set((favs.data?.favorites ?? []).map((f) => f.id)),
    [favs.data],
  );
  const starredNotes = useMemo(
    () => notes.filter((n) => starredIds.has(n.id)),
    [notes, starredIds],
  );
  // When the favorites filter is on, narrow files-mode results to
  // starred notes only. Otherwise show every note (cmdk fuzz-matches
  // by the user's query).
  const filesGroup = useMemo(
    () => (favoritesOnly ? starredNotes : notes),
    [favoritesOnly, starredNotes, notes],
  );

  // Reset state on every open so the dialog is "clean" each time.
  useEffect(() => {
    if (open) {
      setMode(initialMode);
      setQuery("");
      setFavoritesOnly(false);
    }
  }, [open, initialMode]);

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

  const handleQueryChange = (next: string) => {
    // Files-mode "`>`" prefix → switch to commands mode + strip the `>`.
    // Mirrors VS Code's ⌘P → "`>`" behavior. We only react to the very
    // first character so users can still search note titles that
    // legitimately contain a ">" later in the query.
    if (mode === "files" && next.startsWith(">")) {
      setMode("commands");
      setQuery(next.slice(1).trimStart());
      return;
    }
    // Files-mode "`@`" prefix → activate favorites-only filter (sticky).
    // Symmetric with `>`. Once active, the prefix is consumed and the
    // pill at the top of the dialog shows the user we're filtered.
    if (mode === "files" && !favoritesOnly && next.startsWith("@")) {
      setFavoritesOnly(true);
      setQuery(next.slice(1).trimStart());
      return;
    }
    setQuery(next);
  };

  const handleInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (
      e.key !== "Backspace" ||
      query.length !== 0 ||
      e.metaKey ||
      e.ctrlKey ||
      e.altKey
    ) {
      return;
    }
    // Backspace at empty input — peel back one layer of state.
    // (Pressing Esc still closes the dialog at the cmdk level.)
    if (mode === "commands") {
      e.preventDefault();
      setMode("files");
    } else if (favoritesOnly) {
      e.preventDefault();
      setFavoritesOnly(false);
    }
  };

  // Build the commands-mode list once per render. Quick actions are
  // mapped to PaletteCommand shape so cmdk filters uniformly.
  const commandRows: PaletteCommand[] = useMemo(() => {
    if (mode !== "commands") return [];
    const actionRows: PaletteCommand[] =
      actions.data?.map((a) => ({
        id: `action.${a.id}`,
        name: a.name,
        description: a.description ?? undefined,
        shortcut: a.shortcut ?? undefined,
        keywords: ["action", "quick", "快捷", "操作"],
        // Mutation onSuccess handles close (after the note opens).
        // We must NOT close here, or selectedNoteId never updates.
        closeAfterRun: false,
        run: () => runMutation.mutate(a.id),
      })) ?? [];
    return [...actionRows, ...builtinCommands];
  }, [mode, actions.data, builtinCommands, runMutation]);
  const runningActionId = runMutation.isPending ? runMutation.variables : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o && !runMutation.isPending) onClose();
      }}
    >
      <DialogContent
        // Top-align the dialog (override the default centering) so
        // changes to the list height — typing a query, switching modes,
        // anything that drops or adds rows — don't bounce the input
        // vertically. VS Code's palette uses the same trick.
        className="top-[12vh] translate-y-0 gap-0 p-0 sm:max-w-3xl"
      >
        <DialogHeader className="sr-only">
          <DialogTitle>
            {mode === "commands"
              ? t("palette.commandsTitle")
              : t("app.quickSwitch")}
          </DialogTitle>
        </DialogHeader>
        <Command
          label={
            mode === "commands"
              ? t("palette.commandsTitle")
              : t("app.quickSwitch")
          }
          shouldFilter={true}
        >
          {/* Mode banner — rendered in BOTH modes for layout stability.
              Files mode shows a non-interactive hint about the > prefix
              (also serves as discovery for the alternate mode). Commands
              mode shows a clickable pill that returns to files. Same
              vertical footprint either way, so switching modes doesn't
              shift the input position vertically. */}
          {mode === "commands" ? (
            <button
              type="button"
              onClick={() => setMode("files")}
              className="flex items-center gap-1 px-3 pt-2 text-left font-mono text-[11px] text-muted-foreground transition-colors hover:text-foreground"
              title={t("palette.switchToFiles")}
              data-testid="palette-mode-pill"
            >
              <ChevronRight className="size-3" />
              <span>{t("palette.commandsLabel")}</span>
              <span className="ml-1 text-[10px] opacity-70">
                {t("palette.backspaceHint")}
              </span>
            </button>
          ) : favoritesOnly ? (
            <button
              type="button"
              onClick={() => setFavoritesOnly(false)}
              className="flex items-center gap-1 px-3 pt-2 text-left font-mono text-[11px] text-amber-700 transition-colors hover:text-foreground dark:text-amber-400"
              title={t("palette.switchToFiles")}
              data-testid="palette-favorites-pill"
            >
              <Star className="size-3 fill-current" />
              <span>{t("palette.favoritesLabel")}</span>
              <span className="ml-1 text-[10px] opacity-70">
                {t("palette.backspaceHint")}
              </span>
            </button>
          ) : (
            <div
              className="flex items-center gap-1 px-3 pt-2 font-mono text-[11px] text-muted-foreground/60"
              data-testid="palette-mode-hint"
            >
              <ChevronRight className="size-3 opacity-40" />
              <span>{t("palette.filesLabel")}</span>
              <span className="ml-1 text-[10px] opacity-70">
                {t("palette.commandsHint")}
              </span>
            </div>
          )}
          <CommandInput
            data-testid="palette-input"
            placeholder={
              mode === "commands"
                ? t("palette.commandsPlaceholder")
                : t("palette.placeholder")
            }
            value={query}
            onValueChange={handleQueryChange}
            onKeyDown={handleInputKeyDown}
          />
          {/* Bump the list height so a dozen rows are visible without
              scrolling. shadcn's default `max-h-72` (288px) feels
              cramped on a wide dialog. */}
          <CommandList className="max-h-[60vh]">
            <CommandEmpty>{t("palette.noMatches")}</CommandEmpty>
            {mode === "commands" ? (
              <CommandGroup
                heading={t("palette.commandsCount", {
                  count: commandRows.length,
                })}
              >
                {commandRows.map((c) => {
                  const isAction = c.id.startsWith("action.");
                  const actionId = isAction ? c.id.slice("action.".length) : null;
                  const isRunning = actionId !== null && runningActionId === actionId;
                  return (
                    <CommandItem
                      key={c.id}
                      className={`!py-1.5 ${runMutation.isPending ? "opacity-60" : ""}`}
                      value={`${c.name} ${c.description ?? ""} ${
                        c.shortcut ?? ""
                      } ${(c.keywords ?? []).join(" ")}`}
                      onSelect={() => {
                        if (runMutation.isPending) return;
                        void c.run();
                        // Default: close after run. Async commands
                        // (quick actions) opt out via closeAfterRun:
                        // false so their mutation can close after the
                        // note opens.
                        if (c.closeAfterRun !== false) onClose();
                      }}
                      data-testid={
                        isAction ? "palette-action-item" : "palette-command-item"
                      }
                      data-command-id={c.id}
                      aria-busy={isRunning}
                      data-busy={isRunning ? "true" : undefined}
                    >
                      {isRunning ? (
                        <Loader2
                          className="size-3.5 shrink-0 animate-spin"
                          style={{ color: "var(--accent)" }}
                          data-testid="palette-action-spinner"
                        />
                      ) : isAction ? (
                        <Zap
                          className="size-3.5 shrink-0"
                          style={{ color: "var(--accent)" }}
                        />
                      ) : (
                        <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
                      )}
                      <span className="truncate">{c.name}</span>
                      {isRunning ? (
                        <span className="ml-2 truncate text-[11px] text-muted-foreground">
                          {t("quickActions.running")}
                        </span>
                      ) : c.description ? (
                        <span className="ml-2 truncate text-[11px] text-muted-foreground">
                          {c.description}
                        </span>
                      ) : null}
                      {c.shortcut && (
                        <span className="ml-auto shrink-0 pl-3 font-mono text-[11px] text-muted-foreground">
                          {c.shortcut}
                        </span>
                      )}
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            ) : (
              <>
                {/* When input is empty AND we're not already in
                    favorites-only mode, surface a "Starred" group at the
                    top so the user's most-used notes are one keystroke
                    away. Hidden once they start typing (cmdk handles
                    the global filter from filesGroup) or once they
                    explicitly entered favorites-only mode. */}
                {!favoritesOnly && query.length === 0 && starredNotes.length > 0 && (
                  <CommandGroup
                    heading={t("palette.starredHeading", {
                      count: starredNotes.length,
                    })}
                  >
                    {starredNotes.map((n) => (
                      <CommandItem
                        key={`starred:${n.id}`}
                        className="!py-1.5"
                        value={`★ ${n.title} ${n.folderPath}`}
                        onSelect={() => onSelectNote(n.id)}
                        data-testid={`palette-starred-${n.id}`}
                      >
                        <Star className="size-3.5 shrink-0 fill-current text-amber-500" />
                        <span className="truncate">{n.title}</span>
                        {n.folderPath && (
                          <span className="ml-auto shrink-0 truncate pl-3 font-mono text-[11px] text-muted-foreground">
                            {n.folderPath}
                          </span>
                        )}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                )}
                <CommandGroup
                  heading={
                    favoritesOnly
                      ? t("palette.starredHeading", {
                          count: filesGroup.length,
                        })
                      : t("palette.notesCount", { count: filesGroup.length })
                  }
                >
                  {filesGroup.map((n) => (
                    <CommandItem
                      key={n.id}
                      className="!py-1.5"
                      value={`${n.title} ${n.folderPath}`}
                      onSelect={() => onSelectNote(n.id)}
                    >
                      {starredIds.has(n.id) ? (
                        <Star className="size-3.5 shrink-0 fill-current text-amber-500" />
                      ) : (
                        <FileText className="size-3.5 shrink-0 text-muted-foreground" />
                      )}
                      <span className="truncate">{n.title}</span>
                      {n.folderPath && (
                        <span className="ml-auto shrink-0 truncate pl-3 font-mono text-[11px] text-muted-foreground">
                          {n.folderPath}
                        </span>
                      )}
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </CommandList>
          {/* Footer — quiet hint about the alternate mode. */}
          <div className="border-t px-3 py-1.5 text-[11px] text-muted-foreground">
            {mode === "commands"
              ? t("palette.footerCommands")
              : t("palette.footerFiles")}
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
