/**
 * Phase 1 B slice 7 — minimal remark plugin for Obsidian-style
 * `[[Title]]` / `[[Title#Heading]]` wiki-links.
 *
 * Why we own this (instead of `@portaljs/remark-wiki-link`): that
 * package pins `mdast-util-to-markdown@^1` + `micromark-util-symbol@^1`,
 * which conflict with the unified v11 chain react-markdown v10
 * already brings in. Loading both at once throws "Cannot read
 * properties of undefined (reading 'data')" deep inside the parser.
 *
 * This plugin follows the unified cookbook pattern for "splitting a
 * text node on a regex": walk every `text` node with `unist-util-visit`,
 * split on `[[…]]`, and emit standard `link` AST nodes. The link's
 * url is `wikilink:<target>` so PreviewAnchor picks it up — no custom
 * AST node type, no need for an mdast-util / hast-util escape hatch.
 */

import type { Link, Root, RootContent, Text } from "mdast";
import { SKIP, visit } from "unist-util-visit";

const WIKILINK_RE = /\[\[([^\]\n]+?)\]\]/g;

export function remarkWikilink() {
  return (tree: Root) => {
    visit(tree, "text", (node: Text, index, parent) => {
      if (!parent || index === undefined) return;
      // Don't disturb wiki-link-like text inside code blocks / inline
      // code — those should render verbatim. unist-util-visit doesn't
      // descend into those by default for `text` nodes (since they're
      // value-only `code`/`inlineCode` types), but be defensive.
      const value = node.value;
      WIKILINK_RE.lastIndex = 0;
      if (!WIKILINK_RE.test(value)) return;
      WIKILINK_RE.lastIndex = 0;

      const replacement: RootContent[] = [];
      let cursor = 0;
      let m: RegExpExecArray | null;
      while ((m = WIKILINK_RE.exec(value)) !== null) {
        const match = m[0];
        const raw = m[1] ?? "";
        if (m.index > cursor) {
          replacement.push({
            type: "text",
            value: value.slice(cursor, m.index),
          } as Text);
        }
        // Allow `[[Title|Display]]` aliasing — matches Obsidian.
        const pipeIdx = raw.indexOf("|");
        const target = (pipeIdx === -1 ? raw : raw.slice(0, pipeIdx)).trim();
        // Default display: Obsidian convention. `[[Title]]` → "Title",
        // `[[Title#Heading]]` → "Title > Heading", `[[Title|Alias]]`
        // → "Alias". Pipe alias takes precedence over heading split.
        let display: string;
        if (pipeIdx !== -1) {
          display = raw.slice(pipeIdx + 1).trim() || target;
        } else {
          const hashIdx = target.indexOf("#");
          display =
            hashIdx === -1
              ? target
              : `${target.slice(0, hashIdx)} › ${target.slice(hashIdx + 1)}`;
        }
        const link: Link = {
          type: "link",
          // The full path including #heading or ^block stays in target.
          url: `wikilink:${encodeURIComponent(target)}`,
          children: [{ type: "text", value: display }],
          // Smuggle a class hint via mdast.data → hast.properties.
          data: {
            hProperties: { className: ["kn-wikilink"] },
          },
        };
        replacement.push(link);
        cursor = m.index + match.length;
      }
      if (cursor < value.length) {
        replacement.push({ type: "text", value: value.slice(cursor) } as Text);
      }
      // splice in the replacement nodes; SKIP so visit doesn't try to
      // re-enter the new nodes we just inserted (they don't contain
      // wiki-link syntax themselves).
      parent.children.splice(index, 1, ...replacement);
      return [SKIP, index + replacement.length];
    });
  };
}
