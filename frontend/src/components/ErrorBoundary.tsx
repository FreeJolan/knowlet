/**
 * Top-level error boundary. White-screen-on-bug is the worst possible
 * dev experience; this catches render errors and shows the stack so the
 * actual problem is visible. Production users see the same fallback —
 * we don't ship a separate "production-friendly" error UI yet because
 * knowlet is single-user and the user IS the developer (开发期).
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Echo to the console so DevTools sees the full React component stack.
    console.error("[knowlet] render error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      // Plain English here on purpose: the error boundary catches *render*
      // failures, which may include i18next failing to init. Don't risk
      // calling t() from a broken state.
      return (
        <div className="flex min-h-screen flex-col items-center justify-center bg-background p-8 text-foreground">
          <div className="max-w-2xl rounded-lg border border-destructive/40 bg-card p-6">
            <h1 className="font-serif text-xl text-destructive">
              Something broke.
            </h1>
            <p className="mt-2 text-sm text-muted-foreground">
              {this.state.error.message}
            </p>
            <pre className="mt-4 max-h-80 overflow-auto rounded bg-muted p-3 font-mono text-xs">
              {this.state.error.stack}
            </pre>
            <button
              type="button"
              onClick={() => location.reload()}
              className="mt-4 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground hover:opacity-90"
            >
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
