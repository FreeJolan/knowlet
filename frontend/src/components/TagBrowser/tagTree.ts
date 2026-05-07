/**
 * Phase 1 C slice 2 polish D — build a tag tree from the flat
 * `TagWithNotes[]` payload so react-arborist can render it.
 *
 * Convention: `/` is the path separator (Bear / Obsidian style). So
 * `#design/ui` becomes node `design > ui`. The "design" parent node
 * exists even if no note is tagged exactly `design` — in that case the
 * parent is a "synthetic" node with no notes of its own (count=0,
 * own_notes=[]).
 *
 * Subtree count = own count + sum of children subtree counts. We do
 * NOT dedup notes that appear in both parent and child tags (most
 * vaults rarely double-tag), so a note tagged with both `#design` and
 * `#design/ui` will be counted in both rows of the parent's subtree
 * total. Direct count (the `count` field on each TagWithNotes) stays
 * accurate.
 */

import type { NoteSummary, TagWithNotes } from "@/api/types";

export interface TagTreeNode {
  /** Unique key for react-arborist. Use the full path. */
  id: string;
  /** Last segment after the final `/`. Used for display. */
  name: string;
  /** Full tag string, e.g. "design/ui". For synthetic parents this
   *  is the path even though no note carries that exact tag. */
  fullTag: string;
  /** Notes that carry exactly this tag string (NOT including descendants). */
  ownNotes: NoteSummary[];
  /** Notes directly tagged here, in same order as ownNotes. */
  ownCount: number;
  /** Cumulative count: ownCount + sum of children subtreeCount. Used in
   *  the row label as `<name> (N)`. */
  subtreeCount: number;
  children: TagTreeNode[];
  /** True when no note is tagged exactly this string. Synthetic parents
   *  exist only because some descendant tag uses `<name>/...`. They
   *  expand to show children but clicking doesn't open a note list. */
  synthetic: boolean;
}

/**
 * Sort a list of tag tree nodes for display: children grouped together,
 * sorted by direct count desc then alpha asc — matching the "what
 * matters most first" feel of the flat list.
 */
function sortNodes(nodes: TagTreeNode[]): TagTreeNode[] {
  return [...nodes].sort((a, b) => {
    if (a.ownCount !== b.ownCount) return b.ownCount - a.ownCount;
    return a.name.toLowerCase().localeCompare(b.name.toLowerCase());
  });
}

export function buildTagTree(rows: TagWithNotes[]): TagTreeNode[] {
  type IntermediateNode = TagTreeNode & { _childMap: Map<string, IntermediateNode> };
  const rootMap = new Map<string, IntermediateNode>();

  const ensureNode = (
    map: Map<string, IntermediateNode>,
    name: string,
    fullPath: string,
  ): IntermediateNode => {
    let node = map.get(name);
    if (!node) {
      node = {
        id: fullPath,
        name,
        fullTag: fullPath,
        ownNotes: [],
        ownCount: 0,
        subtreeCount: 0,
        children: [],
        synthetic: true,
        _childMap: new Map(),
      };
      map.set(name, node);
    }
    return node;
  };

  for (const row of rows) {
    const segments = row.tag.split("/").filter(Boolean);
    if (segments.length === 0) continue;
    let cursor = rootMap;
    let runningPath = "";
    let lastNode: IntermediateNode | null = null;
    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      if (seg === undefined) continue;
      runningPath = runningPath ? `${runningPath}/${seg}` : seg;
      const node = ensureNode(cursor, seg, runningPath);
      if (i === segments.length - 1) {
        node.ownNotes = row.notes;
        node.ownCount = row.count;
        node.synthetic = false;
      }
      lastNode = node;
      cursor = node._childMap;
    }
    void lastNode;
  }

  // Serialize: walk the map structure into plain arrays + compute subtreeCount.
  function finalize(map: Map<string, IntermediateNode>): TagTreeNode[] {
    const nodes: TagTreeNode[] = [];
    for (const node of map.values()) {
      const children = finalize(node._childMap);
      const subtreeCount =
        node.ownCount + children.reduce((s, c) => s + c.subtreeCount, 0);
      nodes.push({
        id: node.id,
        name: node.name,
        fullTag: node.fullTag,
        ownNotes: node.ownNotes,
        ownCount: node.ownCount,
        subtreeCount,
        children: sortNodes(children),
        synthetic: node.synthetic,
      });
    }
    return sortNodes(nodes);
  }

  return finalize(rootMap);
}
