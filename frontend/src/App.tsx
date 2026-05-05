// Phase 0 placeholder per ADR-0021. Renders nothing functional — proves the
// stack (React 19 + Vite + Tailwind v4 + design tokens) wires up end-to-end.
// Phase 1 replaces this with the file-tree / editor / graph layout.
export default function App() {
  return (
    <main className="kn-paper flex min-h-screen items-center justify-center">
      <div className="max-w-md rounded-lg border px-8 py-10 text-center" style={{ borderColor: "var(--line)", background: "var(--card)" }}>
        <p className="font-mono text-xs uppercase tracking-widest" style={{ color: "var(--ink-mute)" }}>
          knowlet · phase 0
        </p>
        <h1 className="mt-4 font-serif text-2xl" style={{ color: "var(--ink)" }}>
          Scaffold ready.
        </h1>
        <p className="mt-3 text-sm" style={{ color: "var(--ink-soft)" }}>
          React 19 + Vite + Tailwind v4 + design tokens online. Phase 1 lands
          the knowledge-base UI.
        </p>
      </div>
    </main>
  );
}
