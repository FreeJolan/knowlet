/**
 * Phase 1 B slice 8 v2 — `/` slash command for inserting a template
 * at the cursor inside an existing note. Mirrors Notion / Logseq /
 * Roam inline-template UX: at line start, `/` opens a fuzzy picker;
 * accepting a template replaces the `/<query>` with the template body
 * (with `{{title}}` and `{{date}}` substituted on the fly).
 */

import {
  type CompletionContext,
  type CompletionResult,
  type CompletionSource,
} from "@codemirror/autocomplete";

import type { TemplateSummary } from "@/api/client";

// Trigger: a line whose only preceding non-whitespace content is
// `/<partial>`. Anchoring at line start keeps the trigger from
// clashing with regular slashes inside prose (URLs, file paths).
const TRIGGER = /^\s*\/([^\s]*)$/;

export type TemplateSlashOptions = {
  // Cached snapshot of the vault's templates. Closure over the
  // QueryClient so suggestions track creates / deletes without
  // re-installing the extension.
  getTemplates: () => TemplateSummary[];
  // Async fetch of a template body. Returning null skips insertion.
  fetchTemplateBody: (id: string) => Promise<string | null>;
  // Apply title / date substitution. The host knows the current
  // note's title; the slash extension stays i18n / vault-agnostic.
  substitute: (body: string) => string;
  // Localized labels.
  labels: { insert: string; empty: string };
};

export function templateSlashSource(
  opts: TemplateSlashOptions,
): CompletionSource {
  const { getTemplates, fetchTemplateBody, substitute, labels } = opts;

  function source(context: CompletionContext): CompletionResult | null {
    const line = context.state.doc.lineAt(context.pos);
    const before = context.state.sliceDoc(line.from, context.pos);
    const m = TRIGGER.exec(before);
    if (!m) return null;
    const partial = m[1] ?? "";
    // CM6's filter scores options against the text in [from, to].
    // If `from` covers the leading `/`, the filter would compare option
    // labels against "/<partial>" — every match scores -infinity and
    // the popup never renders. Anchor `from` strictly AFTER the slash
    // so filter only sees `<partial>`; apply wipes the slash separately.
    const slashOffset = before.length - partial.length - 1;
    const from = line.from + slashOffset + 1; // after the `/`
    const to = context.pos;
    const slashFrom = line.from + slashOffset; // the `/` itself

    const templates = getTemplates();
    if (templates.length === 0) {
      return {
        from,
        to,
        options: [
          {
            label: labels.empty,
            type: "text",
            apply: () => {
              // Inert: this row is a hint, not actionable.
            },
          },
        ],
        validFor: /^[^\s]*$/,
      };
    }
    return {
      from,
      to,
      options: templates.map((tpl) => ({
        label: tpl.title,
        detail: labels.insert,
        type: "text",
        apply: (view, _completion, _applyFrom, applyTo) => {
          // Wipe the leading `/` *and* the partial in one transaction,
          // then drop in a placeholder until the async body fetch lands.
          const tag = `__knowlet_tpl_${Date.now()}_${Math.random()
            .toString(36)
            .slice(2, 8)}__`;
          const placeholder = `<!-- inserting template: ${tpl.title} (${tag}) -->`;
          view.dispatch({
            changes: {
              from: slashFrom,
              to: applyTo,
              insert: placeholder,
            },
            selection: { anchor: slashFrom + placeholder.length },
          });
          void fetchTemplateBody(tpl.id).then((body) => {
            const doc = view.state.doc.toString();
            const idx = doc.indexOf(placeholder);
            if (idx < 0) return;
            const replacement =
              body == null
                ? `<!-- template insert failed: ${tpl.title} -->`
                : substitute(body);
            view.dispatch({
              changes: {
                from: idx,
                to: idx + placeholder.length,
                insert: replacement,
              },
              selection: { anchor: idx + replacement.length },
            });
          });
        },
      })),
      validFor: /^[^\s]*$/,
    };
  }

  return source;
}

export { TRIGGER as TEMPLATE_SLASH_TRIGGER };
