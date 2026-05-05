import { QueryClientProvider } from "@tanstack/react-query";
import { useEffect } from "react";

import { AppShell } from "@/components/AppShell/AppShell";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { queryClient } from "@/lib/queryClient";

export default function App() {
  // Global keyboard shortcuts. Cmd+P / Ctrl+P → toggle palette. We dispatch
  // a CustomEvent that AppShell listens for; this avoids threading state
  // through the QueryClientProvider boundary.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      if (meta && e.key.toLowerCase() === "p") {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("knowlet:open-palette"));
      }
      if (meta && e.shiftKey && e.key.toLowerCase() === "t") {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent("knowlet:open-trash"));
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
