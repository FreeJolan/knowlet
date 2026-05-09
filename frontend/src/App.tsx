import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";

import { AppShell } from "@/components/AppShell/AppShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { queryClient } from "@/lib/queryClient";

export default function App() {
  // Global keyboard shortcuts. Mirrors VS Code:
  //   ⌘P     → quick switcher (files mode)
  //   ⌘⇧P    → command palette (commands mode)
  //   ⌘⇧T    → trash
  // We dispatch CustomEvents so AppShell can stay the single owner of
  // dialog state without threading setters through QueryClientProvider.
  useEffect(() => {
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
  }, []);

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AppShell />
      </QueryClientProvider>
    </ErrorBoundary>
  );
}
