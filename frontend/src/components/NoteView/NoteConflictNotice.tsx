/**
 * Shown when a save was refused because the note changed on disk since
 * the editor loaded it. The editor has already reloaded the newer
 * version; any text the user had not saved yet is offered here instead
 * of being written over the newer file or thrown away.
 */

import { AlertTriangle } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import type { UnsavedRecovery } from "./unsavedRecovery";

export function NoteConflictNotice({
  recovery,
  onRestore,
  onDismiss,
}: {
  recovery: UnsavedRecovery | null;
  onRestore: (body: string) => void;
  onDismiss: () => void;
}): React.ReactNode {
  const { t } = useTranslation();
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");

  const copyText = async (body: string) => {
    try {
      await navigator.clipboard.writeText(body);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  };

  return (
    <div
      role="alert"
      data-testid="note-conflict-notice"
      className="mx-3 mt-2 flex flex-col gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 size-4 shrink-0" />
        <div className="flex-1">
          <div className="font-medium">
            {t("note.conflict.reloaded", {
              defaultValue:
                "This note was changed by another device or process. The latest version has been loaded.",
            })}
          </div>
          {recovery && (
            <div className="text-xs opacity-80">
              {t("note.conflict.unsavedKept", {
                defaultValue:
                  "Your unsaved text was not saved over it. It is kept below — copy it, or put it back into the editor.",
              })}
            </div>
          )}
        </div>
      </div>
      {recovery && (
        <textarea
          readOnly
          data-testid="note-conflict-unsaved"
          value={recovery.body}
          rows={4}
          className="w-full resize-y rounded border border-amber-300 bg-white/70 p-2 font-mono text-xs leading-snug text-[color:var(--ink)] dark:border-amber-800 dark:bg-black/20"
        />
      )}
      <div className="flex flex-wrap items-center gap-2">
        {recovery && (
          <>
            <Button
              size="sm"
              variant="outline"
              data-testid="note-conflict-copy"
              onClick={() => void copyText(recovery.body)}
            >
              {copy === "copied"
                ? t("note.conflict.copied", { defaultValue: "Copied" })
                : t("note.conflict.copy", { defaultValue: "Copy my text" })}
            </Button>
            <Button
              size="sm"
              data-testid="note-conflict-restore"
              title={t("note.conflict.restoreHint", {
                defaultValue:
                  "Replaces the loaded version in the editor and saves over it. The replaced version stays in the note's backups.",
              })}
              onClick={() => onRestore(recovery.body)}
            >
              {t("note.conflict.restore", { defaultValue: "Put my text back" })}
            </Button>
          </>
        )}
        <Button
          size="sm"
          variant="ghost"
          data-testid="note-conflict-dismiss"
          title={
            recovery
              ? t("note.conflict.dismissHint", {
                  defaultValue: "Discards the kept text.",
                })
              : undefined
          }
          onClick={onDismiss}
        >
          {t("note.conflict.dismiss", { defaultValue: "Dismiss" })}
        </Button>
        {copy === "failed" && (
          <span className="text-xs text-destructive">
            {t("note.conflict.copyFailed", {
              defaultValue: "Couldn't copy — select the text above instead.",
            })}
          </span>
        )}
      </div>
    </div>
  );
}
