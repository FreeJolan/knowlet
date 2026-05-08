/**
 * Title-template placeholder rendering for quick actions / new-doc dialog.
 *
 * Supported tokens:
 *   {{date}}     2026-05-09          local YYYY-MM-DD
 *   {{week}}     2026-W19            ISO week
 *   {{month}}    2026-05             YYYY-MM
 *   {{year}}     2026                YYYY
 *   {{time}}     14:23               HH:MM
 *   {{datetime}} 2026-05-09 14:23
 *
 * Mirrors the backend's `apply_template_placeholders` in spirit but
 * expands the time-type tokens (backend handles `{{title}}` /
 * `{{date}}` for body templates today; titles need more granularity).
 */

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

/** ISO week number (1..53) per ISO-8601:
 *  Thursday-based week, week containing Jan 4 is week 1. */
function isoWeek(d: Date): { year: number; week: number } {
  // Copy date so we don't mutate the input.
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  // Thursday in current week decides the year.
  const dayNum = (t.getUTCDay() + 6) % 7; // Mon=0..Sun=6
  t.setUTCDate(t.getUTCDate() - dayNum + 3);
  const firstThursday = new Date(Date.UTC(t.getUTCFullYear(), 0, 4));
  const week =
    1 +
    Math.round(
      ((t.getTime() - firstThursday.getTime()) / 86400000 -
        3 +
        ((firstThursday.getUTCDay() + 6) % 7)) /
        7,
    );
  return { year: t.getUTCFullYear(), week };
}

export interface PlaceholderContext {
  /** Override "now" for testing. Defaults to `new Date()`. */
  now?: Date;
  /** Optional `{{title}}` substitution (used when applying a template
   *  to an already-created note, not for the new-doc dialog itself). */
  title?: string;
}

export function renderPlaceholders(
  template: string,
  ctx: PlaceholderContext = {},
): string {
  const d = ctx.now ?? new Date();
  const yyyy = d.getFullYear();
  const mm = pad(d.getMonth() + 1);
  const dd = pad(d.getDate());
  const hh = pad(d.getHours());
  const mi = pad(d.getMinutes());
  const date = `${yyyy}-${mm}-${dd}`;
  const month = `${yyyy}-${mm}`;
  const time = `${hh}:${mi}`;
  const datetime = `${date} ${time}`;
  const { year: isoY, week: isoW } = isoWeek(d);
  const week = `${isoY}-W${pad(isoW)}`;
  const map: Record<string, string> = {
    date,
    week,
    month,
    year: String(yyyy),
    time,
    datetime,
  };
  if (ctx.title !== undefined) map.title = ctx.title;
  return template.replace(/\{\{(\w+)\}\}/g, (_, key: string) =>
    map[key] !== undefined ? (map[key] as string) : `{{${key}}}`,
  );
}
