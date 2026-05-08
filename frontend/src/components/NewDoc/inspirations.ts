/**
 * Phase 2 D Slice 2 — inspiration chips for the New-doc dialog.
 *
 * NOT pre-shipped quick actions — these are just hints that fill the
 * dialog's `folder` + `title_template` fields when clicked. User
 * still names the action and decides whether to save it.
 *
 * Kept short on purpose; per the user's 2026-05-09 critique, six
 * shipped presets is too many — most users delete what they don't
 * need. One real default (`今日笔记`, mapped to ⌘⇧D) is enough; the
 * rest live here as form prefill suggestions.
 */

export interface InspirationPreset {
  /** Stable id — used for analytics / e2e selectors only. */
  id: string;
  /** Emoji / glyph to display on the chip. */
  icon: string;
  /** Short display name. */
  label: string;
  /** Suggested folder path (forward-slash separated). */
  folder: string;
  /** Suggested title template (with placeholders). */
  titleTemplate: string;
  /** Optional template id to pre-select (from `_templates/`). v1 leaves
   *  null — user picks template after the chip fills the form. */
  templateId?: string | null;
}

export const INSPIRATIONS: InspirationPreset[] = [
  {
    id: "weekly",
    icon: "📅",
    label: "周报",
    folder: "weekly",
    titleTemplate: "周报 · {{week}}",
  },
  {
    id: "monthly",
    icon: "📆",
    label: "月报",
    folder: "monthly",
    titleTemplate: "月报 · {{month}}",
  },
  {
    id: "one-on-one",
    icon: "🤝",
    label: "1:1 会议",
    folder: "meetings",
    titleTemplate: "1on1 · {{date}}",
  },
  {
    id: "reading-log",
    icon: "📚",
    label: "读完一篇",
    folder: "reading",
    titleTemplate: "{{date}} reading",
  },
  {
    id: "url-capture",
    icon: "🔗",
    label: "抓 URL",
    folder: "inbox",
    titleTemplate: "{{date}} url",
  },
];
