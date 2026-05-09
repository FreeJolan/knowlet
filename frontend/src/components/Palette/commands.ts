/**
 * Phase 2 D Slice 2c.3 — Built-in palette commands.
 *
 * The palette renders two kinds of "commands" in commands mode:
 *   1. User-defined quick actions (fetched from /api/quick-actions).
 *   2. Built-in UI commands (this file) — toggle theme, focus tree,
 *      open a tab, etc. UI-only side effects, no backend round-trip.
 *
 * AppShell builds the list at render time so the closures can capture
 * the live setters/handlers it owns. The palette receives a flat
 * array and stays presentation-only.
 */

import type { TFunction } from "i18next";

import {
  getThemePreference,
  setThemePreference,
  type ThemePreference,
} from "@/lib/theme";

export interface PaletteCommand {
  id: string;
  /** Display label. */
  name: string;
  /** One-line hint shown after the name in muted text. */
  description?: string;
  /** Shortcut hint shown right-aligned (purely informational). */
  shortcut?: string;
  /** Search keywords appended to the cmdk match value. */
  keywords?: string[];
  run: () => void | Promise<void>;
  /** Whether the palette should close itself after `run()` returns.
   *  Default: true. Quick actions set this to false because their
   *  React Query mutation handles close-on-success itself (so we
   *  don't double-close before the note opens). */
  closeAfterRun?: boolean;
}

export interface BuildBuiltinsArgs {
  t: TFunction;
  /** App-shell setters / openers. */
  setLeftTab: (t: "files" | "tags" | "templates") => void;
  setQuickActionsOpen: (open: boolean) => void;
  openNewDocDialog: (seedFolder?: string) => void;
  setGraphFocusOpen: (updater: (v: boolean) => boolean) => void;
  setSearchFocusOpen: (updater: (v: boolean) => boolean) => void;
  setSettingsOpen: (open: boolean) => void;
}

const cycleTheme = (cur: ThemePreference): ThemePreference =>
  cur === "light" ? "dark" : cur === "dark" ? "system" : "light";

export function buildBuiltinCommands(
  args: BuildBuiltinsArgs,
): PaletteCommand[] {
  const { t } = args;
  return [
    {
      id: "builtin.new-note",
      name: t("commands.newNote"),
      shortcut: "⌘N",
      keywords: ["new", "note", "create", "新建", "笔记"],
      run: () => args.openNewDocDialog(),
    },
    {
      id: "builtin.toggle-theme",
      name: t("commands.toggleTheme"),
      description: t("commands.toggleThemeHint", {
        current: t(`commands.theme.${getThemePreference()}`),
      }),
      keywords: ["theme", "dark", "light", "主题", "深色", "浅色"],
      run: () => setThemePreference(cycleTheme(getThemePreference())),
    },
    {
      id: "builtin.tab-notes",
      name: t("commands.openNotesTab"),
      shortcut: "⌘1",
      keywords: ["notes", "files", "tree", "笔记", "文件"],
      run: () => args.setLeftTab("files"),
    },
    {
      id: "builtin.tab-tags",
      name: t("commands.openTagsTab"),
      shortcut: "⌘2",
      keywords: ["tags", "tag", "标签"],
      run: () => args.setLeftTab("tags"),
    },
    {
      id: "builtin.tab-templates",
      name: t("commands.openTemplatesTab"),
      shortcut: "⌘3",
      keywords: ["templates", "template", "模板"],
      run: () => args.setLeftTab("templates"),
    },
    {
      id: "builtin.quick-actions-manager",
      name: t("commands.openQuickActionsManager"),
      shortcut: "⌘⇧A",
      keywords: ["quick", "action", "manager", "actions", "快捷", "操作"],
      run: () => args.setQuickActionsOpen(true),
    },
    {
      id: "builtin.graph-focus",
      name: t("commands.toggleGraph"),
      shortcut: "⌘⇧G",
      keywords: ["graph", "focus", "图谱"],
      run: () => args.setGraphFocusOpen((v) => !v),
    },
    {
      id: "builtin.search-focus",
      name: t("commands.toggleSearch"),
      shortcut: "⌘⇧F",
      keywords: ["search", "find", "搜索"],
      run: () => args.setSearchFocusOpen((v) => !v),
    },
    {
      id: "builtin.settings",
      name: t("commands.openSettings"),
      keywords: ["settings", "preferences", "config", "设置", "配置"],
      run: () => args.setSettingsOpen(true),
    },
  ];
}
