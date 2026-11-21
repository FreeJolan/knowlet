/**
 * Phase 1 B slice 6 — Mermaid block renderer.
 *
 * Used by MarkdownPreview's `code` slot when the language tag is
 * `mermaid`. The mermaid lib (~500 KB minified) is lazy-imported so the
 * cost only lands the first time a user opens a note that contains a
 * diagram.
 *
 * On render error: fall back to the original source inside a styled
 * <pre> block so the user can still see what they wrote (and the error
 * message), instead of a silent empty box.
 */

import { useEffect, useId, useRef, useState } from "react";

let mermaidPromise: Promise<typeof import("mermaid").default> | null = null;
function loadMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import("mermaid").then((m) => {
      m.default.initialize({
        startOnLoad: false,
        theme: "default",
        securityLevel: "strict",
        flowchart: { htmlLabels: true },
      });
      return m.default;
    });
  }
  return mermaidPromise;
}

type Props = { source: string };

export function MermaidBlock({ source }: Props) {
  // useId gives us an SSR-stable id, but we also need a *unique* id for
  // mermaid.render — useId returns the same value on each render. We
  // append a counter ref to be safe across multiple diagrams in one
  // document.
  const baseId = useId().replace(/:/g, "");
  const idRef = useRef(0);
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setSvg(null);
    idRef.current += 1;
    const id = `mmd-${baseId}-${idRef.current}`;
    loadMermaid()
      .then(async (mermaid) => {
        try {
          // Validate FIRST with parse({ suppressErrors: true }) — this
          // is the only mermaid call without DOM side effects. If we
          // skip it and call render() on broken input, mermaid v11+
          // injects a "Syntax error in text" bomb-icon SVG into the
          // document body for debug purposes, and leaks it across
          // re-renders. Each keystroke in split mode would stack
          // another bomb visible at the bottom of the page.
          const parsed = await mermaid.parse(source, { suppressErrors: true });
          if (parsed === false) {
            if (!cancelled) setError("syntax error");
            return;
          }
          const { svg: rendered } = await mermaid.render(id, source);
          if (!cancelled) setSvg(rendered);
        } catch (e) {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        }
      })
      .catch((e) => {
        if (!cancelled) setError(`failed to load mermaid: ${String(e)}`);
      });
    return () => {
      cancelled = true;
      // Defensive cleanup: if one of THIS block's renders slipped through
      // and left orphan scratch DOM, vacuum it. mermaid.render(id) mounts
      // `d<id>` (or `i<id>` when sandboxed) wrapping the `<id>` svg on
      // <body> while it works; other blocks may be mid-render with their
      // own scratch there, so match only this block's id prefix.
      const own = `mmd-${baseId}-`;
      for (const orphan of Array.from(document.querySelectorAll(
        `[id^="${own}"], [id^="d${own}"], [id^="i${own}"]`
      ))) {
        if (!orphan.closest(".kn-mermaid")) orphan.remove();
      }
    };
  }, [source, baseId]);

  if (error !== null) {
    return (
      <pre
        className="kn-mermaid-error"
        style={{
          background: "var(--accent-tint)",
          border: "1px solid var(--accent-soft)",
          color: "var(--ink-soft)",
          padding: "0.7em 0.9em",
          borderRadius: "6px",
          fontSize: "0.88em",
          // Wrap long error lines instead of stretching horizontally —
          // a multi-line "Expecting 'SEMI', 'NEWLINE', ..." parser error
          // would otherwise blow out the split-mode column width.
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          overflowX: "auto",
          maxWidth: "100%",
        }}
      >
        <code style={{ display: "block", marginBottom: "0.6em" }}>{source}</code>
        <span style={{ color: "var(--ink-mute)" }}>mermaid: {error}</span>
      </pre>
    );
  }
  if (svg === null) {
    return (
      <div
        style={{
          padding: "1em 0",
          color: "var(--ink-mute)",
          fontSize: "0.88em",
          fontStyle: "italic",
        }}
      >
        rendering diagram…
      </div>
    );
  }
  return (
    <div
      className="kn-mermaid"
      // mermaid output is well-known + sanitised by mermaid itself
      // (securityLevel: "strict" above strips scripts). We trust it.
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
