/**
 * CaptureBox — Phase 3 Stage 3 §3.4
 *
 * Half-screen central modal for AI-assisted capture of external
 * material (URL paste / Markdown / text file drop). After fetch +
 * summarize the user picks one of three options:
 *
 *   [📘 Knowledge]  → write Note (kind=knowledge), straight to vault
 *   [📄 Reference]  → write Note (kind=reference), straight to vault
 *   [⏸ Defer]       → write Draft for later review (drafts/草稿)
 *
 * Per ADR-0009 amendment A2.1, the Drafts queue is the explicit-defer
 * exception, NOT the default destination. Capture's whole point is
 * to extract the decision moment FROM the queue and INTO capture
 * time. The three buttons enforce that.
 *
 * Per ADR-0029 §4 原则 7: capture-time inline review is the default
 * mechanism for anti-drift. This component is the literal embodiment.
 */

import { Loader2, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  captureDecide,
  captureFromFile,
  captureFromUrl,
  type CapturePayload,
} from "@/api/client";
import type { ApiError } from "@/api/types";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { KindChip } from "@/components/KindChip";
import { QK } from "@/lib/queryClient";
import { useMutation, useQueryClient } from "@tanstack/react-query";

interface CaptureBoxProps {
  open: boolean;
  onClose: () => void;
  /** Optional initial URL to pre-fill (e.g. opened by ⌘⇧V global
   *  hotkey that read the clipboard). */
  initialUrl?: string;
}

type CaptureState =
  | { kind: "empty" }
  | { kind: "fetching" }
  | { kind: "ready"; capsule: CapturePayload }
  | { kind: "deciding"; capsule: CapturePayload; choice: string }
  | { kind: "done"; choice: "knowledge" | "reference" | "defer" }
  | { kind: "error"; message: string };

export function CaptureBox({
  open,
  onClose,
  initialUrl,
}: CaptureBoxProps): React.ReactElement {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [urlInput, setUrlInput] = useState(initialUrl ?? "");
  const [state, setState] = useState<CaptureState>({ kind: "empty" });
  const [dragOver, setDragOver] = useState(false);
  const urlRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Reset state when the modal opens/closes so a stale "done" view
  // doesn't show on reopen.
  useEffect(() => {
    if (open) {
      setUrlInput(initialUrl ?? "");
      setState({ kind: "empty" });
      // Defer focus to next tick so the input is mounted.
      setTimeout(() => urlRef.current?.focus(), 0);
    }
  }, [open, initialUrl]);

  const fetchUrl = useCallback(
    async (url: string) => {
      const trimmed = url.trim();
      if (!trimmed) return;
      setState({ kind: "fetching" });
      try {
        const capsule = await captureFromUrl(trimmed);
        setState({ kind: "ready", capsule });
      } catch (err) {
        const apiErr = err as ApiError;
        setState({
          kind: "error",
          message: apiErr.detail || t("capture.errors.fetchFailed"),
        });
      }
    },
    [t],
  );

  const fetchFile = useCallback(
    async (file: File) => {
      setState({ kind: "fetching" });
      try {
        const capsule = await captureFromFile(file);
        setState({ kind: "ready", capsule });
      } catch (err) {
        const apiErr = err as ApiError;
        setState({
          kind: "error",
          message: apiErr.detail || t("capture.errors.fileFailed"),
        });
      }
    },
    [t],
  );

  const decideMut = useMutation({
    mutationFn: captureDecide,
    onSuccess: (data) => {
      // Invalidate caches affected by either path.
      void qc.invalidateQueries({ queryKey: QK.tree });
      void qc.invalidateQueries({ queryKey: ["drafts"] });
      setState({ kind: "done", choice: data.decision });
      // Auto-close after a brief confirmation.
      setTimeout(onClose, 900);
    },
    onError: (err: ApiError) => {
      setState({
        kind: "error",
        message: err.detail || t("capture.errors.saveFailed"),
      });
    },
  });

  const decide = (
    capsule: CapturePayload,
    decision: "knowledge" | "reference" | "defer",
  ) => {
    setState({ kind: "deciding", capsule, choice: decision });
    decideMut.mutate({
      capsule,
      decision,
      // For defer: URL/file capture defaults to "reference" per
      // ADR-0029 §4.5 default-by-source table. If user wanted
      // knowledge, they'd hit the knowledge button instead of defer.
      defer_kind: "reference",
    });
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void fetchFile(file);
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent
        className="sm:max-w-2xl"
        data-testid="capture-box"
      >
        <DialogHeader>
          <DialogTitle>{t("capture.title")}</DialogTitle>
          <DialogDescription>{t("capture.subtitle")}</DialogDescription>
        </DialogHeader>

        {state.kind === "empty" && (
          <div className="space-y-3">
            <label className="block text-xs">
              <div className="text-muted-foreground mb-1">
                {t("capture.urlLabel")}
              </div>
              <input
                ref={urlRef}
                type="url"
                value={urlInput}
                onChange={(e) => setUrlInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && urlInput.trim()) {
                    e.preventDefault();
                    void fetchUrl(urlInput);
                  }
                }}
                placeholder="https://…"
                data-testid="capture-url-input"
                className="w-full rounded border px-2 py-1.5 text-sm"
                style={{
                  borderColor: "var(--line)",
                  background: "var(--bg-1)",
                }}
              />
            </label>

            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => fileRef.current?.click()}
              className="cursor-pointer rounded border border-dashed p-4 text-center text-xs"
              style={{
                borderColor: dragOver ? "var(--accent)" : "var(--line)",
                background: dragOver ? "var(--accent-tint-2)" : "transparent",
                color: "var(--muted-foreground, var(--ink-mute))",
              }}
              data-testid="capture-dropzone"
            >
              <Upload className="size-4 mx-auto mb-1" />
              {t("capture.dropzone")}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".md,.markdown,.txt,.text,text/markdown,text/plain"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void fetchFile(f);
              }}
              data-testid="capture-file-input"
            />

            {urlInput.trim() && (
              <button
                type="button"
                onClick={() => void fetchUrl(urlInput)}
                className="w-full rounded border px-3 py-1.5 text-sm"
                style={{
                  background: "var(--accent-soft, rgba(91,122,156,0.18))",
                  borderColor: "var(--accent, #5b7a9c)",
                  color: "var(--accent-2, #34495e)",
                }}
                data-testid="capture-fetch"
              >
                {t("capture.fetchButton")}
              </button>
            )}
          </div>
        )}

        {state.kind === "fetching" && (
          <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin mr-2" />
            {t("capture.fetching")}
          </div>
        )}

        {(state.kind === "ready" || state.kind === "deciding") && (
          <CapsulePreview
            capsule={state.capsule}
            deciding={state.kind === "deciding" ? state.choice : null}
            onDecide={(d) => decide(state.capsule, d)}
            t={t}
          />
        )}

        {state.kind === "done" && (
          <div
            className="rounded border p-3 text-sm text-center"
            style={{
              borderColor: "var(--ok, #198754)",
              color: "var(--ok, #198754)",
            }}
            data-testid="capture-done"
          >
            ✓ {t(`capture.done.${state.choice}`)}
          </div>
        )}

        {state.kind === "error" && (
          <div className="space-y-2">
            <div
              className="rounded border p-2 text-xs"
              style={{
                borderColor: "var(--destructive, #c0392b)",
                color: "var(--destructive, #c0392b)",
              }}
              data-testid="capture-error"
            >
              {state.message}
            </div>
            <button
              type="button"
              onClick={() => setState({ kind: "empty" })}
              className="rounded border px-2.5 py-1 text-xs"
              style={{ borderColor: "var(--line)" }}
            >
              {t("capture.errors.retry")}
            </button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

// --------------------------------------------- CapsulePreview

function CapsulePreview({
  capsule,
  deciding,
  onDecide,
  t,
}: {
  capsule: CapturePayload;
  deciding: string | null;
  onDecide: (d: "knowledge" | "reference" | "defer") => void;
  t: (key: string, vars?: Record<string, unknown>) => string;
}): React.ReactElement {
  return (
    <div className="space-y-2.5" data-testid="capture-capsule">
      {capsule.summary_failed && (
        <div
          className="rounded px-2 py-1 text-[11px] space-y-1"
          style={{
            background: "rgba(192,57,43,0.1)",
            color: "var(--destructive, #c0392b)",
          }}
          data-testid="capture-summary-failed"
        >
          <div>{t("capture.summaryFailed")}</div>
          {capsule.summary_error && (
            <div
              className="font-mono text-[10px] opacity-75"
              data-testid="capture-summary-error"
            >
              {capsule.summary_error}
            </div>
          )}
        </div>
      )}
      <div>
        <div className="text-[10.5px] uppercase tracking-wider text-muted-foreground mb-0.5">
          {capsule.hostname || t("capture.sourceLabel")}
        </div>
        <div className="font-serif text-base font-semibold">
          {capsule.title}
        </div>
      </div>
      <div
        className="rounded border p-2 text-xs max-h-48 overflow-y-auto whitespace-pre-wrap"
        style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
      >
        {capsule.body}
      </div>

      <div className="flex gap-2 pt-1">
        <DecisionButton
          icon={<KindChip kind="knowledge" variant="tag" />}
          label={t("capture.decide.knowledge")}
          onClick={() => onDecide("knowledge")}
          isLoading={deciding === "knowledge"}
          testId="capture-decide-knowledge"
        />
        <DecisionButton
          icon={<KindChip kind="reference" variant="tag" />}
          label={t("capture.decide.reference")}
          onClick={() => onDecide("reference")}
          isLoading={deciding === "reference"}
          testId="capture-decide-reference"
        />
        <DecisionButton
          icon={<span className="text-xs">⏸</span>}
          label={t("capture.decide.defer")}
          onClick={() => onDecide("defer")}
          isLoading={deciding === "defer"}
          testId="capture-decide-defer"
        />
      </div>
    </div>
  );
}

function DecisionButton({
  icon,
  label,
  onClick,
  isLoading,
  testId,
}: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  isLoading: boolean;
  testId: string;
}): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isLoading}
      data-testid={testId}
      className="flex flex-1 items-center justify-center gap-1.5 rounded border px-2 py-1.5 text-xs transition-colors hover:bg-accent/30 disabled:opacity-50"
      style={{ borderColor: "var(--line)", background: "var(--bg-1)" }}
    >
      {isLoading ? <Loader2 className="size-3 animate-spin" /> : icon}
      <span>{label}</span>
    </button>
  );
}
