import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { AppShell } from "@/components/AppShell/AppShell";
import {
  DesktopVaultLauncher,
  isDesktopVaultLauncherPage,
} from "@/components/DesktopVaultLauncher";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import {
  installExternalLinkHandler,
  type ExternalLinkFailure,
} from "@/lib/externalLinks";
import { queryClient } from "@/lib/queryClient";

function isTextEditingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    target.isContentEditable ||
    Boolean(target.closest('[contenteditable="true"], .cm-editor'))
  );
}

export default function App() {
  const { t } = useTranslation();
  const desktopLauncher = isDesktopVaultLauncherPage();
  const [externalLinkFailure, setExternalLinkFailure] =
    useState<ExternalLinkFailure | null>(null);

  useEffect(
    () => installExternalLinkHandler({ onFailure: setExternalLinkFailure }),
    [],
  );

  useEffect(() => {
    if (!externalLinkFailure) return;
    const timer = window.setTimeout(() => setExternalLinkFailure(null), 5000);
    return () => window.clearTimeout(timer);
  }, [externalLinkFailure]);

  // Global keyboard shortcuts. Mirrors VS Code:
  //   ⌘P     → quick switcher (files mode)
  //   ⌘⇧P    → command palette (commands mode)
  //   ⌘⇧T    → trash
  //   ⌘⇧K    → toggle active note's kind (Phase 3 Stage 2, ADR-0029 §4.5)
  //   ⌘⇧V    → open CaptureBox; auto-reads clipboard (Stage 3, ADR-0009)
  //   ⌘I     → open Drafts focus mode (Stage 3)
  // We dispatch CustomEvents so AppShell can stay the single owner of
  // dialog state without threading setters through QueryClientProvider.
  useEffect(() => {
    if (desktopLauncher) return;
    const onKey = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      const key = e.key.toLowerCase();
      if (meta && key === "p") {
        e.preventDefault();
        window.dispatchEvent(
          new CustomEvent<{ mode: "files" | "commands" }>(
            "knowlet:open-palette",
            { detail: { mode: e.shiftKey ? "commands" : "files" } },
          ),
        );
      }
      if (meta && e.shiftKey && key === "t") {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("knowlet:open-trash"));
      }
      if (meta && e.shiftKey && key === "k") {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("knowlet:toggle-active-note-kind"));
      }
      // Phase 3 Stage 3 §3.6 — ⌘⇧V opens CaptureBox. We dispatch the
      // event then AppShell reads the clipboard from inside its
      // user-gesture handler (browsers gate navigator.clipboard.readText
      // on user activation; the keypress IS user activation).
      if (meta && e.shiftKey && key === "v") {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("knowlet:open-capture"));
      }
      // Phase 3 Stage 3 §3.5 — ⌘I opens Drafts focus mode.
      if (
        meta &&
        !e.shiftKey &&
        !e.altKey &&
        key === "i" &&
        !isTextEditingTarget(e.target)
      ) {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("knowlet:open-drafts"));
      }
      // Phase 2 D Slice 2c.4 — ⌘W closes the active tab (matches
      // VS Code / browser tab semantics). Browsers reserve ⌘W for
      // closing the window/tab; we preventDefault to claim it for
      // ourselves. ⌘⇧W still falls through to the browser.
      if (meta && !e.shiftKey && !e.altKey && key === "w") {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("knowlet:close-active-tab"));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [desktopLauncher]);

  const content = desktopLauncher ? (
    <ErrorBoundary>
      <DesktopVaultLauncher />
    </ErrorBoundary>
  ) : (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AppShell />
      </QueryClientProvider>
    </ErrorBoundary>
  );

  return (
    <>
      {content}
      {externalLinkFailure && (
        <div
          data-testid="external-link-error"
          role="status"
          aria-live="polite"
          className="fixed right-4 top-4 z-[100] max-w-sm rounded-lg border px-4 py-3 text-sm shadow-lg"
          style={{
            borderColor: "var(--line)",
            background: "var(--panel)",
            color: "var(--ink)",
          }}
        >
          {t(
            externalLinkFailure === "invalid-url"
              ? "app.externalLinkInvalid"
              : "app.externalLinkOpenFailed",
          )}
        </div>
      )}
    </>
  );
}
