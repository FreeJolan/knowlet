/**
 * Phase 2 E Slice S5 — inline merge editor (ADR-0027 redesign).
 *
 * Logseq-style first cut: two side-by-side panes (Mine | Theirs)
 * plus a live preview of the merged result. Each diff hunk gets
 * three buttons — Take Mine, Take Theirs, Take Both — and the
 * preview rebuilds as the user clicks through. Save → POST
 * /api/sync/resolve-merge with the assembled merged_text. Drive
 * keeps both pre-merge versions in its 30-day version history if
 * the merge needs to be unwound.
 *
 * Deliberate scope cuts for this iteration:
 *  - No "Edit merged result" power-mode toggle yet (line buttons
 *    only). Power users land in the next slice.
 *  - No 3-pane base view — base bytes would require a Drive
 *    revisions.get_media call and we don't store it locally.
 *  - No syntax-aware diff. Line-level only. Fine for markdown;
 *    if the team wants word-level inside diff hunks later, swap
 *    the diff helper.
 *  - No keyboard shortcuts. Click-driven for the first dogfood
 *    pass; shortcuts come once the layout is settled.
 *
 * The component is mounted as a ``Dialog`` from the conflict-state
 * SyncStatusBadge (S5 Step D). Outside that path it renders nothing
 * — the parent owns visibility.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  type ConflictBundle,
  getConflictBundle,
  resolveMerge,
} from "@/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { QK } from "@/lib/queryClient";
import {
  buildMergedText,
  countDiffHunks,
  diffLines,
  type HunkChoice,
  type LineHunk,
  TooLargeForDiffError,
} from "@/lib/lineDiff";

interface Props {
  noteId: string | null;
  noteTitle: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function ConflictMergeView({
  noteId,
  noteTitle,
  open,
  onOpenChange,
}: Props): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const bundleQ = useQuery<ConflictBundle>({
    queryKey: ["sync-conflict-bundle", noteId],
    queryFn: () => {
      if (!noteId) throw new Error("no noteId");
      return getConflictBundle(noteId);
    },
    enabled: !!noteId && open,
    refetchOnWindowFocus: false,
    staleTime: Infinity, // user is actively merging — don't reshuffle under them
  });

  // diffLines + the choices array reset every time we get a new
  // bundle. useMemo so we don't recompute on every keystroke once
  // the user starts editing (a future power-mode feature).
  const hunks = useMemo<LineHunk[] | { error: "too-large" }>(() => {
    if (!bundleQ.data) return [];
    try {
      return diffLines(bundleQ.data.local_text, bundleQ.data.remote_text);
    } catch (e) {
      if (e instanceof TooLargeForDiffError) return { error: "too-large" };
      throw e;
    }
  }, [bundleQ.data]);

  const diffHunkCount = useMemo(() => {
    if (Array.isArray(hunks)) return countDiffHunks(hunks);
    return 0;
  }, [hunks]);

  const [choices, setChoices] = useState<HunkChoice[]>([]);
  useEffect(() => {
    setChoices(new Array(diffHunkCount).fill(null));
  }, [diffHunkCount]);

  const merged = useMemo(() => {
    if (!Array.isArray(hunks)) return "";
    return buildMergedText(hunks, choices);
  }, [hunks, choices]);

  const allChosen = useMemo(
    () => choices.length > 0 && choices.every((c) => c !== null),
    [choices],
  );
  const noConflicts = diffHunkCount === 0 && Array.isArray(hunks);

  const saveMut = useMutation({
    mutationFn: () => {
      if (!noteId) throw new Error("no noteId");
      return resolveMerge(noteId, merged);
    },
    onSuccess: () => {
      // Sync-status badge polls; nudge it so the badge flips to
      // "synced" without waiting up to 10s for the next tick.
      void qc.invalidateQueries({
        queryKey: QK.noteSyncStatus(noteId ?? ""),
      });
      onOpenChange(false);
    },
  });

  if (!noteId) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid="conflict-merge-dialog"
        className="top-[5vh] left-1/2 w-[92vw] sm:max-w-[92vw] -translate-x-1/2 translate-y-0 max-h-[90vh] gap-3 overflow-hidden"
      >
        <DialogHeader>
          <DialogTitle>{t("merge.title", { title: noteTitle })}</DialogTitle>
          <DialogDescription>{t("merge.subtitle")}</DialogDescription>
        </DialogHeader>

        {bundleQ.isLoading && (
          <div className="text-muted-foreground text-sm">
            {t("merge.loading")}
          </div>
        )}

        {bundleQ.isError && (
          <div className="text-destructive text-sm">
            {t("merge.error", {
              detail:
                (bundleQ.error as { detail?: string } | undefined)?.detail ??
                String(bundleQ.error),
            })}
          </div>
        )}

        {bundleQ.data && !Array.isArray(hunks) && hunks.error === "too-large" && (
          <div className="text-muted-foreground text-sm">
            {/* Future polish: offer take-mine / take-theirs full-file
             * fallback for the cap-exceeded case. */}
            Note exceeds the inline merge cap. Use Drive's web UI to
            resolve manually for now.
          </div>
        )}

        {bundleQ.data && Array.isArray(hunks) && noConflicts && (
          <div className="text-muted-foreground text-sm">
            {t("merge.noConflicts")}
          </div>
        )}

        {bundleQ.data && Array.isArray(hunks) && !noConflicts && (
          <MergeBody
            hunks={hunks}
            choices={choices}
            setChoices={setChoices}
            merged={merged}
            bundle={bundleQ.data}
          />
        )}

        <DialogFooter>
          <p className="text-muted-foreground mr-auto text-xs">
            {t("merge.fallbackHint")}
          </p>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={saveMut.isPending}
          >
            {t("merge.cancel")}
          </Button>
          <Button
            data-testid="merge-save"
            onClick={() => saveMut.mutate()}
            disabled={
              !bundleQ.data ||
              !Array.isArray(hunks) ||
              (!noConflicts && !allChosen) ||
              saveMut.isPending
            }
          >
            {saveMut.isPending ? t("merge.saving") : t("merge.save")}
          </Button>
        </DialogFooter>
        {saveMut.isError && (
          <div className="text-destructive text-xs">
            {t("merge.saveError", {
              detail:
                (saveMut.error as { detail?: string } | undefined)?.detail ??
                String(saveMut.error),
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// --------------------------------------------------- inner panes


function MergeBody({
  hunks,
  choices,
  setChoices,
  merged,
  bundle,
}: {
  hunks: LineHunk[];
  choices: HunkChoice[];
  setChoices: React.Dispatch<React.SetStateAction<HunkChoice[]>>;
  merged: string;
  bundle: ConflictBundle;
}): React.ReactNode {
  const { t } = useTranslation();
  // Pre-walk the hunks to assign each diff hunk a stable index +
  // collect what to render in each pane. Equal hunks render the
  // same line range on both sides; diff hunks get tinted +
  // floated buttons.
  const rendered: Array<
    | {
        kind: "equal";
        mine: string[];
      }
    | {
        kind: "diff";
        diffIndex: number;
        mine: string[];
        theirs: string[];
      }
  > = [];
  let diffIdx = 0;
  for (const h of hunks) {
    if (h.kind === "equal") {
      rendered.push({ kind: "equal", mine: h.mine });
    } else {
      rendered.push({
        kind: "diff",
        diffIndex: diffIdx,
        mine: h.mine,
        theirs: h.theirs,
      });
      diffIdx++;
    }
  }

  const setChoice = (i: number, c: HunkChoice) => {
    setChoices((prev) => {
      const next = prev.slice();
      next[i] = c;
      return next;
    });
  };

  return (
    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3 overflow-hidden flex-1 min-h-0">
      {/* Left pane — mine */}
      <Pane
        label={t("merge.leftPane")}
        sublabel={
          bundle.last_known_revision
            ? t("merge.leftRevision", { rev: bundle.last_known_revision })
            : ""
        }
        testId="merge-pane-mine"
      >
        {rendered.map((r, idx) => {
          if (r.kind === "equal") {
            return (
              <PaneLines
                key={`eq-${idx}`}
                lines={r.mine}
                tone="equal"
              />
            );
          }
          const c = choices[r.diffIndex];
          return (
            <PaneDiffBlock
              key={`diff-mine-${r.diffIndex}`}
              lines={r.mine}
              side="mine"
              chosen={c === "mine" || c === "both"}
              hunkLabel={t("merge.hunkLabel", {
                i: r.diffIndex + 1,
                n: rendered.filter((x) => x.kind === "diff").length,
              })}
              onTakeThis={() => setChoice(r.diffIndex, "mine")}
              onTakeBoth={() => setChoice(r.diffIndex, "both")}
              takeThisLabel={t("merge.takeMine")}
              takeBothLabel={t("merge.takeBoth")}
            />
          );
        })}
      </Pane>

      {/* Middle pane — merged preview */}
      <Pane
        label={t("merge.mergedPane")}
        sublabel=""
        testId="merge-pane-merged"
        emphasized
      >
        <pre className="font-mono text-xs whitespace-pre-wrap leading-snug">
          {merged}
        </pre>
      </Pane>

      {/* Right pane — theirs */}
      <Pane
        label={t("merge.rightPane")}
        sublabel={
          bundle.current_drive_revision
            ? t("merge.rightRevision", { rev: bundle.current_drive_revision })
            : ""
        }
        testId="merge-pane-theirs"
      >
        {rendered.map((r, idx) => {
          if (r.kind === "equal") {
            return (
              <PaneLines
                key={`eq-r-${idx}`}
                lines={r.mine}
                tone="equal"
              />
            );
          }
          const c = choices[r.diffIndex];
          return (
            <PaneDiffBlock
              key={`diff-theirs-${r.diffIndex}`}
              lines={r.theirs}
              side="theirs"
              chosen={c === "theirs" || c === "both"}
              hunkLabel={t("merge.hunkLabel", {
                i: r.diffIndex + 1,
                n: rendered.filter((x) => x.kind === "diff").length,
              })}
              onTakeThis={() => setChoice(r.diffIndex, "theirs")}
              onTakeBoth={() => setChoice(r.diffIndex, "both")}
              takeThisLabel={t("merge.takeTheirs")}
              takeBothLabel={t("merge.takeBoth")}
            />
          );
        })}
      </Pane>
    </div>
  );
}

function Pane({
  label,
  sublabel,
  children,
  testId,
  emphasized = false,
}: {
  label: string;
  sublabel: string;
  children: React.ReactNode;
  testId: string;
  emphasized?: boolean;
}): React.ReactNode {
  return (
    <div
      data-testid={testId}
      className={[
        "flex min-h-0 min-w-0 flex-col rounded-md ring-1 ring-foreground/10",
        emphasized ? "bg-accent/30" : "bg-background",
      ].join(" ")}
    >
      <div className="border-b border-foreground/10 px-3 py-2 text-xs font-medium uppercase tracking-wide">
        <div>{label}</div>
        {sublabel && (
          <div className="text-muted-foreground text-[10px] font-normal normal-case">
            {sublabel}
          </div>
        )}
      </div>
      <div className="flex-1 overflow-auto p-3">{children}</div>
    </div>
  );
}

function PaneLines({
  lines,
  tone,
}: {
  lines: string[];
  tone: "equal";
}): React.ReactNode {
  return (
    <pre
      data-tone={tone}
      className="font-mono text-xs whitespace-pre-wrap leading-snug"
    >
      {lines.join("\n")}
    </pre>
  );
}

function PaneDiffBlock({
  lines,
  side,
  chosen,
  hunkLabel,
  onTakeThis,
  onTakeBoth,
  takeThisLabel,
  takeBothLabel,
}: {
  lines: string[];
  side: "mine" | "theirs";
  chosen: boolean;
  hunkLabel: string;
  onTakeThis: () => void;
  onTakeBoth: () => void;
  takeThisLabel: string;
  takeBothLabel: string;
}): React.ReactNode {
  const sideClass =
    side === "mine"
      ? "bg-blue-50 dark:bg-blue-950/40 ring-blue-200 dark:ring-blue-900"
      : "bg-amber-50 dark:bg-amber-950/40 ring-amber-200 dark:ring-amber-900";
  return (
    <div
      data-testid={`merge-hunk-${side}`}
      data-chosen={chosen ? "true" : "false"}
      className={[
        "my-2 rounded-md p-2 ring-1",
        chosen ? "opacity-100" : "opacity-90",
        sideClass,
      ].join(" ")}
    >
      <div className="mb-1 flex items-center gap-2 text-[10px] uppercase tracking-wide text-muted-foreground">
        <span>{hunkLabel}</span>
        <Button
          size="sm"
          variant={chosen ? "default" : "outline"}
          onClick={onTakeThis}
        >
          {takeThisLabel}
        </Button>
        <Button size="sm" variant="outline" onClick={onTakeBoth}>
          {takeBothLabel}
        </Button>
      </div>
      <pre className="font-mono text-xs whitespace-pre-wrap leading-snug">
        {lines.join("\n")}
      </pre>
    </div>
  );
}
