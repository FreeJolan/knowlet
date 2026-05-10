/**
 * Task #108 — warning chip for notes whose YAML frontmatter is
 * damaged (missing markers / parse error / non-mapping shape).
 *
 * Renders an amber strip above the editor with the corruption
 * detail + three actions:
 *   - View details: expands the parser's error message in place
 *   - Auto-repair: POSTs to /api/notes/{id}/repair-frontmatter,
 *     which atomically writes a fresh frontmatter on top of the
 *     salvaged body (original file backed up under .knowlet/backups/
 *     so the action is reversible).
 *   - Use as-is: dismisses the chip for this session only — the
 *     warning returns on the next reload until the file is fixed.
 *
 * The chip sits inside the note's main column rather than as a
 * full-width banner so the user notices it while still being able
 * to read / edit body content beneath it.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { repairFrontmatter } from "@/api/client";
import type { NoteFull } from "@/api/types";
import { Button } from "@/components/ui/button";
import { QK } from "@/lib/queryClient";

export function FrontmatterCorruptedNotice({
  noteId,
  corruption,
}: {
  noteId: string;
  corruption: string | null | undefined;
}): React.ReactNode {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [showDetails, setShowDetails] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  const repair = useMutation({
    mutationFn: () => repairFrontmatter(noteId),
    onSuccess: (fresh: NoteFull) => {
      // Replace the cached note with the repaired version so the
      // editor / Properties UI stop showing the corrupted body.
      qc.setQueryData(QK.note(noteId), fresh);
      // Tree titles may have changed if the repair swapped in a
      // first-heading title for the filename stem.
      void qc.invalidateQueries({ queryKey: QK.tree });
    },
  });

  if (dismissed) return null;

  return (
    <div
      data-testid="frontmatter-corrupted-notice"
      className="mx-3 mt-2 flex flex-col gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <div className="flex-1">
          <div className="font-medium">{t("frontmatterCorrupted.headline")}</div>
          <div className="text-xs opacity-80">
            {t("frontmatterCorrupted.fallbackHint")}
          </div>
        </div>
      </div>
      {showDetails && corruption && (
        <div className="rounded bg-amber-100/60 p-2 font-mono text-xs leading-snug dark:bg-amber-900/30">
          <div className="mb-1 text-[10px] uppercase tracking-wide opacity-70">
            {t("frontmatterCorrupted.detailLabel")}
          </div>
          {corruption}
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="outline"
          data-testid="frontmatter-toggle-details"
          onClick={() => setShowDetails((s) => !s)}
          disabled={!corruption}
        >
          {showDetails ? (
            <ChevronUp className="size-3" />
          ) : (
            <ChevronDown className="size-3" />
          )}
          {t("frontmatterCorrupted.viewDetails")}
        </Button>
        <Button
          size="sm"
          data-testid="frontmatter-auto-repair"
          onClick={() => repair.mutate()}
          disabled={repair.isPending}
        >
          {repair.isPending
            ? t("frontmatterCorrupted.repairing")
            : t("frontmatterCorrupted.autoRepair")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          data-testid="frontmatter-use-as-is"
          onClick={() => setDismissed(true)}
        >
          {t("frontmatterCorrupted.useAsIs")}
        </Button>
        {repair.isError && (
          <span className="text-destructive text-xs">
            {t("frontmatterCorrupted.repairFailed", {
              detail:
                (repair.error as { detail?: string } | undefined)?.detail ??
                String(repair.error),
            })}
          </span>
        )}
      </div>
    </div>
  );
}
