/**
 * Phase 2 E Slice S5 v2 — inline merge editor (ADR-0027 redesign).
 *
 * Three-pane layout with VSCode-style gutter buttons:
 *
 *    [ Mine ] [ → ] [ Merged ] [ ← ] [ Theirs ]
 *
 * Diff hunks render as a single CSS-grid row spanning the five
 * columns, so each gutter button stays vertically aligned with the
 * hunk it acts on. Click ``→`` to push mine into merged; ``←`` to
 * push theirs. Clicking both gives you "take both" (mine first,
 * then theirs — fixed ordering this iteration; ordered combinations
 * land later via the editable-result power mode).
 *
 * Top toolbar exposes the global shortcuts the dogfood feedback
 * surfaced ("全部用我的" / "全部用他们的" / "全部都保留") for the
 * "I'll review later, just clear the conflict" persona.
 *
 * Column headers display human-friendly identifiers — local mtime
 * vs. Drive's modifiedTime + lastModifyingUser — so users see
 * "you · 14:32" vs. "drive · 17:08 by alice" instead of opaque
 * revision ids.
 *
 * Saved file content is plain merged text — no git-style markers
 * end up on disk. The placeholder shown for unresolved hunks lives
 * in the preview only; the save button is disabled until every
 * hunk has a choice, so the file is always clean.
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
  buildPreviewText,
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
    staleTime: Infinity,
  });

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
  const pending = choices.filter((c) => c === null).length;

  const saveMut = useMutation({
    mutationFn: () => {
      if (!noteId) throw new Error("no noteId");
      return resolveMerge(noteId, merged);
    },
    onSuccess: () => {
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
        // ``!flex flex-col`` overrides DialogPrimitive's default
        // ``grid`` so we can hand height out predictably:
        //   - header / toolbar / footer get their natural height
        //     (``shrink-0`` below)
        //   - the merge body fills the remainder and scrolls
        //     internally (``flex-1 min-h-0`` on its wrapper)
        // Without this, long-form notes pushed the footer below
        // the viewport and the save button was unreachable.
        // ``min-h-[60vh]`` keeps the panes readable even when the
        // diff is tiny; ``max-h-[90vh]`` caps tall content so the
        // footer stays in view. The internal merge body flexes
        // between these bounds and scrolls past 90vh.
        className="!flex flex-col top-[5vh] left-1/2 w-[96vw] sm:max-w-[96vw] -translate-x-1/2 translate-y-0 min-h-[60vh] max-h-[90vh] gap-3 overflow-hidden"
      >
        <DialogHeader className="shrink-0">
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

        {bundleQ.data &&
          !Array.isArray(hunks) &&
          hunks.error === "too-large" && (
            <div className="text-muted-foreground text-sm">
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
          <>
            <GlobalToolbar
              setChoices={setChoices}
              count={diffHunkCount}
              pending={pending}
            />
            <MergeGrid
              hunks={hunks}
              choices={choices}
              setChoices={setChoices}
              bundle={bundleQ.data}
              placeholder={t("merge.placeholder")}
            />
          </>
        )}

        <DialogFooter className="shrink-0">
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

// --------------------------------------------------- global toolbar


function GlobalToolbar({
  setChoices,
  count,
  pending,
}: {
  setChoices: React.Dispatch<React.SetStateAction<HunkChoice[]>>;
  count: number;
  pending: number;
}): React.ReactNode {
  const { t } = useTranslation();
  const setAll = (c: HunkChoice) => {
    setChoices(new Array(count).fill(c));
  };
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-foreground/10 pb-2">
      <Button
        size="sm"
        variant="outline"
        data-testid="merge-all-mine"
        onClick={() => setAll("mine")}
      >
        {t("merge.allMine")}
      </Button>
      <Button
        size="sm"
        variant="outline"
        data-testid="merge-all-theirs"
        onClick={() => setAll("theirs")}
      >
        {t("merge.allTheirs")}
      </Button>
      <Button
        size="sm"
        variant="outline"
        data-testid="merge-all-both"
        onClick={() => setAll("both")}
      >
        {t("merge.allBoth")}
      </Button>
      {pending > 0 && (
        <span
          data-testid="merge-pending-count"
          className="text-warn-fg dark:text-warn-fg-dark ml-auto text-xs"
        >
          {t("merge.pendingCount", { count: pending })}
        </span>
      )}
    </div>
  );
}

// --------------------------------------------------- 5-column grid


function MergeGrid({
  hunks,
  choices,
  setChoices,
  bundle,
  placeholder,
}: {
  hunks: LineHunk[];
  choices: HunkChoice[];
  setChoices: React.Dispatch<React.SetStateAction<HunkChoice[]>>;
  bundle: ConflictBundle;
  placeholder: string;
}): React.ReactNode {
  const { t } = useTranslation();

  const totalDiffs = useMemo(
    () => hunks.filter((h) => h.kind === "diff").length,
    [hunks],
  );

  const toggleSide = (i: number, side: "mine" | "theirs") => {
    setChoices((prev) => {
      const next = prev.slice();
      const cur = next[i];
      const mineActive = cur === "mine" || cur === "both";
      const theirsActive = cur === "theirs" || cur === "both";
      const newMine = side === "mine" ? !mineActive : mineActive;
      const newTheirs = side === "theirs" ? !theirsActive : theirsActive;
      next[i] = deriveChoice(newMine, newTheirs);
      return next;
    });
  };

  const previewText = useMemo(
    () => buildPreviewText(hunks, choices, placeholder),
    [hunks, choices, placeholder],
  );

  // Build per-hunk row metadata for stable React keys + diff index.
  const rows: Array<
    | { kind: "equal"; key: string; lines: string[] }
    | {
        kind: "diff";
        key: string;
        diffIndex: number;
        mine: string[];
        theirs: string[];
        merged: string;
      }
  > = [];
  let diffIdx = 0;
  let mergedCursor = 0;
  const previewLines = previewText === "" ? [] : previewText.split("\n");
  for (let i = 0; i < hunks.length; i++) {
    const h = hunks[i]!;
    if (h.kind === "equal") {
      rows.push({ kind: "equal", key: `eq-${i}`, lines: h.mine });
      mergedCursor += h.mine.length;
    } else {
      // Slice the preview to figure out how many lines this hunk
      // currently contributes to the middle pane.
      const choice = choices[diffIdx];
      const mergedLineCount =
        choice === "mine"
          ? h.mine.length
          : choice === "theirs"
            ? h.theirs.length
            : choice === "both"
              ? h.mine.length + h.theirs.length
              : 1; // placeholder = 1 line
      const mergedSlice = previewLines
        .slice(mergedCursor, mergedCursor + mergedLineCount)
        .join("\n");
      rows.push({
        kind: "diff",
        key: `diff-${diffIdx}`,
        diffIndex: diffIdx,
        mine: h.mine,
        theirs: h.theirs,
        merged: mergedSlice,
      });
      diffIdx++;
      mergedCursor += mergedLineCount;
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <ColumnHeaders bundle={bundle} t={t} />
      <div
        data-testid="merge-grid"
        className="grid min-h-0 flex-1 overflow-auto"
        style={{
          gridTemplateColumns: "1fr 44px 1fr 44px 1fr",
        }}
      >
        {rows.map((r) => {
          if (r.kind === "equal") {
            return (
              <EqualRow key={r.key} lines={r.lines} />
            );
          }
          const c = choices[r.diffIndex]!;
          const mineActive = c === "mine" || c === "both";
          const theirsActive = c === "theirs" || c === "both";
          return (
            <DiffRow
              key={r.key}
              diffIndex={r.diffIndex}
              total={totalDiffs}
              mine={r.mine}
              theirs={r.theirs}
              merged={r.merged}
              mineActive={mineActive}
              theirsActive={theirsActive}
              onToggleMine={() => toggleSide(r.diffIndex, "mine")}
              onToggleTheirs={() => toggleSide(r.diffIndex, "theirs")}
              placeholder={placeholder}
              t={t}
            />
          );
        })}
      </div>
    </div>
  );
}

function ColumnHeaders({
  bundle,
  t,
}: {
  bundle: ConflictBundle;
  t: ReturnType<typeof useTranslation>["t"];
}): React.ReactNode {
  return (
    <div
      className="grid border-b border-foreground/10"
      style={{ gridTemplateColumns: "1fr 44px 1fr 44px 1fr" }}
    >
      <PaneHeader
        primary={t("merge.leftPane")}
        secondary={t("merge.leftHeaderYou", {
          when: formatLocalTime(bundle.local_modified_at),
        })}
        testId="merge-pane-mine-header"
      />
      <div className="border-x border-foreground/5" />
      <PaneHeader
        primary={t("merge.mergedPane")}
        secondary=""
        testId="merge-pane-merged-header"
        emphasized
      />
      <div className="border-x border-foreground/5" />
      <PaneHeader
        primary={t("merge.rightPane")}
        secondary={driveHeader(bundle, t)}
        testId="merge-pane-theirs-header"
      />
    </div>
  );
}

function PaneHeader({
  primary,
  secondary,
  testId,
  emphasized = false,
}: {
  primary: string;
  secondary: string;
  testId: string;
  emphasized?: boolean;
}): React.ReactNode {
  return (
    <div
      data-testid={testId}
      className={[
        "px-3 py-2 text-xs font-medium uppercase tracking-wide",
        emphasized ? "bg-accent/30" : "bg-background",
      ].join(" ")}
    >
      <div>{primary}</div>
      {secondary && (
        <div className="text-muted-foreground text-[10px] font-normal normal-case">
          {secondary}
        </div>
      )}
    </div>
  );
}

function EqualRow({ lines }: { lines: string[] }): React.ReactNode {
  // Equal hunks span all three content panes with identical text;
  // gutter cells stay empty. We use ``display: contents`` rows would
  // be neater but lose styling at the row level — the simpler path
  // is to render five direct grid children per row.
  const text = lines.join("\n");
  return (
    <>
      <PaneCell text={text} />
      <GutterCell />
      <PaneCell text={text} emphasized />
      <GutterCell />
      <PaneCell text={text} />
    </>
  );
}

function DiffRow({
  diffIndex,
  total,
  mine,
  theirs,
  merged,
  mineActive,
  theirsActive,
  onToggleMine,
  onToggleTheirs,
  placeholder,
  t,
}: {
  diffIndex: number;
  total: number;
  mine: string[];
  theirs: string[];
  merged: string;
  mineActive: boolean;
  theirsActive: boolean;
  onToggleMine: () => void;
  onToggleTheirs: () => void;
  placeholder: string;
  t: ReturnType<typeof useTranslation>["t"];
}): React.ReactNode {
  // S5 v2 colour convention — Mine = blue (Current), Theirs = green
  // (Incoming), matching VSCode's merge editor. We deliberately
  // skip git-diff red/green: red on mine reads as "this side will
  // be deleted", which is wrong here — both sides are valid.
  const mineTone =
    "bg-blue-50 dark:bg-blue-950/40 ring-blue-200 dark:ring-blue-900";
  const theirsTone =
    "bg-emerald-50 dark:bg-emerald-950/40 ring-emerald-200 dark:ring-emerald-900";
  const hunkLabel = t("merge.hunkLabel", { i: diffIndex + 1, n: total });
  const placeholderTone =
    merged === placeholder
      ? "text-muted-foreground italic"
      : "";

  return (
    <>
      <DiffPaneCell
        lines={mine}
        tone={mineTone}
        side="mine"
        diffIndex={diffIndex}
        label={hunkLabel}
      />
      <GutterCell>
        <button
          type="button"
          data-testid={`merge-push-mine-${diffIndex}`}
          aria-label={t("merge.takeMine")}
          title={t("merge.takeMine")}
          onClick={onToggleMine}
          aria-pressed={mineActive}
          className={[
            "size-7 rounded-md text-sm leading-none ring-1 transition",
            mineActive
              ? "bg-blue-500 text-white ring-blue-600"
              : "bg-background text-foreground ring-foreground/15 hover:bg-blue-50 dark:hover:bg-blue-950/40",
          ].join(" ")}
        >
          →
        </button>
      </GutterCell>
      <PaneCell
        text={merged}
        emphasized
        testId={`merge-merged-row-${diffIndex}`}
        extraClass={placeholderTone}
      />
      <GutterCell>
        <button
          type="button"
          data-testid={`merge-push-theirs-${diffIndex}`}
          aria-label={t("merge.takeTheirs")}
          title={t("merge.takeTheirs")}
          onClick={onToggleTheirs}
          aria-pressed={theirsActive}
          className={[
            "size-7 rounded-md text-sm leading-none ring-1 transition",
            theirsActive
              ? "bg-emerald-600 text-white ring-emerald-700"
              : "bg-background text-foreground ring-foreground/15 hover:bg-emerald-50 dark:hover:bg-emerald-950/40",
          ].join(" ")}
        >
          ←
        </button>
      </GutterCell>
      <DiffPaneCell
        lines={theirs}
        tone={theirsTone}
        side="theirs"
        diffIndex={diffIndex}
        label={hunkLabel}
      />
    </>
  );
}

function PaneCell({
  text,
  emphasized = false,
  testId,
  extraClass = "",
}: {
  text: string;
  emphasized?: boolean;
  testId?: string;
  extraClass?: string;
}): React.ReactNode {
  return (
    <pre
      data-testid={testId}
      className={[
        "min-w-0 overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-snug px-3 py-1",
        emphasized ? "bg-accent/15" : "",
        extraClass,
      ].join(" ")}
    >
      {text}
    </pre>
  );
}

function DiffPaneCell({
  lines,
  tone,
  side,
  diffIndex,
  label,
}: {
  lines: string[];
  tone: string;
  side: "mine" | "theirs";
  diffIndex: number;
  label: string;
}): React.ReactNode {
  return (
    <div
      data-testid={`merge-hunk-${side}-${diffIndex}`}
      className={["min-w-0 px-2 py-1", "ring-1", tone].join(" ")}
    >
      <div className="text-muted-foreground mb-1 text-[10px] uppercase tracking-wide">
        {label}
      </div>
      <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-snug">
        {lines.join("\n")}
      </pre>
    </div>
  );
}

function GutterCell({
  children,
}: {
  children?: React.ReactNode;
}): React.ReactNode {
  return (
    <div className="flex items-center justify-center px-1 py-1">
      {children ?? null}
    </div>
  );
}

// --------------------------------------------------- helpers


function deriveChoice(mineActive: boolean, theirsActive: boolean): HunkChoice {
  if (mineActive && theirsActive) return "both";
  if (mineActive) return "mine";
  if (theirsActive) return "theirs";
  return null;
}

function formatLocalTime(iso: string | null): string {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function driveHeader(
  bundle: ConflictBundle,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  const when = formatLocalTime(bundle.remote_modified_at);
  const by = bundle.remote_modified_by;
  if (when && by) return t("merge.rightHeaderBy", { when, by });
  if (when) return t("merge.rightHeaderUnknown", { when });
  return t("merge.rightHeaderUnknownTime");
}
