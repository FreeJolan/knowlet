import { Folder, FolderOpen } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Tree, type NodeRendererProps } from "react-arborist";

import { getTree } from "@/api/client";
import type { TreeFolder } from "@/api/types";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useQuery } from "@tanstack/react-query";
import { QK } from "@/lib/queryClient";

type FolderNodeData = {
  id: string;
  name: string;
  folderPath: string;
  recommended?: boolean;
  children?: FolderNodeData[];
};

interface Props {
  open: boolean;
  recommendedFolder: string;
  committing?: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (folder: string) => void;
}

export function DigestFolderCommitDialog({
  open,
  recommendedFolder,
  committing,
  onOpenChange,
  onConfirm,
}: Props): React.ReactNode {
  const { t } = useTranslation();
  const [selectedFolder, setSelectedFolder] = useState("");
  const tree = useQuery({
    queryKey: QK.tree,
    queryFn: getTree,
    enabled: open,
  });
  const normalizedRecommendation = normalizeFolder(recommendedFolder);

  useEffect(() => {
    if (open) setSelectedFolder(normalizedRecommendation);
  }, [normalizedRecommendation, open]);

  const data = useMemo(
    () => folderTreeData(tree.data, normalizedRecommendation),
    [normalizedRecommendation, tree.data],
  );
  const rowCount = useMemo(() => countRows(data), [data]);
  const selectedId = `folder:${selectedFolder}`;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="z-[80] max-w-xl rounded-md"
        data-testid="digest-folder-dialog"
      >
        <DialogHeader>
          <DialogTitle>{t("digest.folderDialogTitle")}</DialogTitle>
          <DialogDescription>
            {t("digest.folderDialogDescription", {
              folder: normalizedRecommendation || t("digest.rootFolder"),
            })}
          </DialogDescription>
        </DialogHeader>

        <div
          className="min-h-[320px] rounded-md border p-2"
          style={{ borderColor: "var(--line)", background: "var(--bg)" }}
          data-testid="digest-folder-tree"
        >
          {tree.isLoading ? (
            <div className="p-3 text-sm text-muted-foreground">
              {t("digest.folderDialogLoading")}
            </div>
          ) : (
            <Tree<FolderNodeData>
              data={data}
              openByDefault
              width="100%"
              height={Math.max(260, rowCount * 30 + 8)}
              rowHeight={30}
              indent={16}
              selection={selectedId}
            >
              {(props) => (
                <FolderRow
                  {...props}
                  selectedFolder={selectedFolder}
                  onSelect={setSelectedFolder}
                />
              )}
            </Tree>
          )}
        </div>

        <div
          className="rounded border px-3 py-2 text-xs"
          style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
          data-testid="digest-folder-selected"
        >
          {t("digest.folderDialogSelected", {
            folder: selectedFolder || t("digest.rootFolder"),
          })}
        </div>

        <DialogFooter>
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-xs"
            style={{ borderColor: "var(--line)" }}
            data-testid="digest-folder-cancel"
            onClick={() => onOpenChange(false)}
          >
            {t("digest.folderDialogCancel")}
          </button>
          <button
            type="button"
            className="rounded border px-3 py-1.5 text-xs disabled:opacity-50"
            style={{
              borderColor: "var(--accent)",
              background: "var(--accent-soft, rgba(91,122,156,0.14))",
            }}
            data-testid="digest-folder-confirm"
            disabled={committing}
            onClick={() => onConfirm(selectedFolder)}
          >
            {committing ? t("digest.committingDraft") : t("digest.commitDraftConfirm")}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FolderRow({
  node,
  style,
  selectedFolder,
  onSelect,
}: NodeRendererProps<FolderNodeData> & {
  selectedFolder: string;
  onSelect: (folder: string) => void;
}) {
  const { t } = useTranslation();
  const selected = selectedFolder === node.data.folderPath;
  const isOpen = node.isOpen;

  return (
    <div style={style} className="flex items-center">
      <button
        type="button"
        className="flex h-[28px] w-full items-center gap-2 rounded-sm px-2 text-left text-sm transition-colors hover:bg-accent/20"
        style={{
          background: selected ? "var(--accent-tint-2)" : "transparent",
          color: "var(--ink)",
        }}
        data-testid={`digest-folder-option-${slugFolder(node.data.folderPath)}`}
        data-selected={selected ? "true" : "false"}
        onClick={() => {
          onSelect(node.data.folderPath);
          if (node.children?.length) node.toggle();
        }}
      >
        {isOpen ? (
          <FolderOpen className="size-4 shrink-0 text-muted-foreground" />
        ) : (
          <Folder className="size-4 shrink-0 text-muted-foreground" />
        )}
        <span className="truncate">
          {node.data.folderPath ? node.data.name : t("digest.rootFolder")}
        </span>
        {node.data.recommended && (
          <span
            className="ml-auto shrink-0 rounded border px-1.5 py-0.5 text-[10px]"
            style={{ borderColor: "var(--accent)", color: "var(--ink-mute)" }}
          >
            {t("digest.folderRecommended")}
          </span>
        )}
      </button>
    </div>
  );
}

function normalizeFolder(folder: string): string {
  return folder.trim().replace(/^\/+|\/+$/g, "");
}

function folderTreeData(
  root: TreeFolder | undefined,
  recommendedFolder: string,
): FolderNodeData[] {
  const rootNode: FolderNodeData = {
    id: "folder:",
    name: "root",
    folderPath: "",
    recommended: recommendedFolder === "",
    children: (root?.folders ?? []).map((folder) =>
      folderToNode(folder, recommendedFolder),
    ),
  };
  if (recommendedFolder && !hasFolder(rootNode, recommendedFolder)) {
    rootNode.children = insertVirtualFolder(
      rootNode.children ?? [],
      recommendedFolder.split("/"),
      "",
      recommendedFolder,
    );
  }
  return [rootNode];
}

function folderToNode(folder: TreeFolder, recommendedFolder: string): FolderNodeData {
  return {
    id: `folder:${folder.path}`,
    name: folder.name,
    folderPath: folder.path,
    recommended: folder.path === recommendedFolder,
    children: folder.folders.map((child) => folderToNode(child, recommendedFolder)),
  };
}

function hasFolder(node: FolderNodeData, path: string): boolean {
  if (node.folderPath === path) return true;
  return (node.children ?? []).some((child) => hasFolder(child, path));
}

function insertVirtualFolder(
  nodes: FolderNodeData[],
  parts: string[],
  parentPath: string,
  recommendedFolder: string,
): FolderNodeData[] {
  const [head, ...rest] = parts;
  if (!head) return nodes;
  const path = parentPath ? `${parentPath}/${head}` : head;
  const existing = nodes.find((node) => node.name === head);
  if (existing) {
    return nodes.map((node) =>
      node === existing
        ? {
            ...node,
            children: insertVirtualFolder(
              node.children ?? [],
              rest,
              path,
              recommendedFolder,
            ),
          }
        : node,
    );
  }
  const virtual: FolderNodeData = {
    id: `folder:${path}`,
    name: head,
    folderPath: path,
    recommended: path === recommendedFolder,
    children: insertVirtualFolder([], rest, path, recommendedFolder),
  };
  return [...nodes, virtual].sort((a, b) => a.name.localeCompare(b.name));
}

function countRows(nodes: FolderNodeData[]): number {
  return nodes.reduce(
    (total, node) => total + 1 + countRows(node.children ?? []),
    0,
  );
}

function slugFolder(folder: string): string {
  return folder ? folder.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") : "root";
}
