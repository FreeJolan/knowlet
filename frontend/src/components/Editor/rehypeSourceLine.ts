/**
 * Phase 1 B slice 9 — rehype plugin: copy each element's source line
 * (1-indexed, from remark-parse's position info) onto the rendered
 * HTML as `data-source-line="N"`. The split-mode scroll sync reads
 * those attributes to map between CodeMirror line numbers and
 * preview DOM nodes.
 *
 * unified ecosystem standard pattern: visit elements, read
 * `node.position`, write to `node.properties`. Same approach VS
 * Code's markdown preview uses (MIT) — generalised here as a tiny
 * reusable plugin so we never have to reach into mdast / hast
 * internals from the React layer.
 */

import type { Element, Root } from "hast";
import { visit } from "unist-util-visit";

export function rehypeSourceLine() {
  return (tree: Root) => {
    visit(tree, "element", (node: Element) => {
      const line = node.position?.start?.line;
      if (typeof line !== "number") return;
      node.properties = node.properties ?? {};
      // string form so React renders `data-source-line="3"` in the DOM
      node.properties["data-source-line"] = String(line);
    });
  };
}
