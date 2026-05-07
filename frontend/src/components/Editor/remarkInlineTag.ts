/**
 * Phase 1 C polish — remark plugin for inline `#tag` syntax.
 *
 * Pattern matches what `knowlet/core/inline_tags.py` extracts:
 *   - `#` not following a word char (so `prefix#tag` isn't a tag)
 *   - capture: word chars (Unicode-aware via /u flag, matches CJK),
 *     `-`, `_`, `/`
 *   - boundary: stop at non-word boundary
 *
 * Markdown headings (`# Title` with a space) are naturally excluded
 * because the regex requires no whitespace after `#`.
 *
 * Renders as a `<a class="kn-inline-tag" href="tag:<name>">` so
 * PreviewAnchor can intercept clicks the same way it does for wiki-
 * links — dispatch a `knowlet:open-tag` event the AppShell listens to.
 */

import type { Link, Root, RootContent, Text } from "mdast";
import { SKIP, visit } from "unist-util-visit";

const INLINE_TAG_RE = /(?<!\w)#([\p{L}\p{N}_\-/]+)(?!\w)/gu;

export function remarkInlineTag() {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index, parent) => {
      if (!parent || index === undefined) return;
      // Skip when the parent is a heading — `#` is meaningful there.
      // unist-util-visit traverses into heading children for its `text`
      // type so we have to filter ourselves.
      if (parent.type === "heading") return;
      const value = node.value;
      INLINE_TAG_RE.lastIndex = 0;
      if (!INLINE_TAG_RE.test(value)) return;
      INLINE_TAG_RE.lastIndex = 0;

      const replacement: RootContent[] = [];
      let cursor = 0;
      let m: RegExpExecArray | null;
      while ((m = INLINE_TAG_RE.exec(value)) !== null) {
        const match = m[0];
        const tag = (m[1] ?? "").trim();
        if (!tag) continue;
        if (m.index > cursor) {
          replacement.push({
            type: "text",
            value: value.slice(cursor, m.index),
          } as Text);
        }
        const link: Link = {
          type: "link",
          url: `tag:${encodeURIComponent(tag)}`,
          children: [{ type: "text", value: `#${tag}` }],
          data: {
            hProperties: { className: ["kn-inline-tag"] },
          },
        };
        replacement.push(link);
        cursor = m.index + match.length;
      }
      if (cursor < value.length) {
        replacement.push({ type: "text", value: value.slice(cursor) } as Text);
      }
      parent.children.splice(index, 1, ...replacement);
      return [SKIP, index + replacement.length];
    });
  };
}
