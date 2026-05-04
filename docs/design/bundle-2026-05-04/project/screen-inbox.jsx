// Knowlet — Screen 2: Inbox focus (full-screen overlay)

const InboxScreen = () => {
  return (
    <div className="kn kn-paper" style={{ width: 1200, height: 800, position: "relative", borderRadius: 12, overflow: "hidden", border: "1px solid var(--line)" }}>
      {/* Dimmed underlay hint of home */}
      <div style={{
        position: "absolute", inset: 0,
        background: "linear-gradient(180deg, rgba(28,29,34,0.92), rgba(28,29,34,0.98))",
      }} />

      {/* Top utility row */}
      <div style={{ position: "absolute", top: 18, left: 24, right: 24, display: "flex", alignItems: "center", justifyContent: "space-between", zIndex: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, color: "var(--ink-mute)", fontSize: 12 }}>
          <I.Inbox size={13} stroke={1.7} style={{ color: "var(--warn)" }} />
          <span>Inbox</span>
          <span style={{ color: "var(--ink-faint)" }}>·</span>
          <span className="mono">3 of 12</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "var(--ink-mute)" }}>
          <span>Esc to exit</span>
          <span className="kn-kbd">Esc</span>
        </div>
      </div>

      {/* Centered card */}
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: "60px 40px 40px", zIndex: 1 }}>
        <article style={{ width: 720, maxWidth: "100%" }}>
          {/* Source */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
            <span style={{ fontSize: 11, color: "var(--ink-mute)", textTransform: "uppercase", letterSpacing: "0.1em" }}>Source</span>
            <a className="mono" style={{ fontSize: 12, color: "var(--accent)", textDecoration: "none", borderBottom: "1px solid rgba(164,139,176,0.3)", display: "inline-flex", alignItems: "center", gap: 6 }}>
              huggingface.co/blog/granite-4-1
              <I.ExternalLink size={11} />
            </a>
            <span style={{ flex: 1 }} />
            <span className="mono" style={{ fontSize: 11.5, color: "var(--ink-mute)" }}>fetched 06:14 · 2h ago</span>
          </div>

          {/* Tags */}
          <div style={{ display: "flex", gap: 6, marginBottom: 22 }}>
            <span className="kn-chip">#llm</span>
            <span className="kn-chip">#release</span>
            <span className="kn-chip">#reasoning</span>
            <span className="kn-chip accent"><I.Sparkles size={10} stroke={1.8} /> AI summary</span>
          </div>

          <h1 className="serif" style={{
            fontSize: 36, lineHeight: 1.15, fontWeight: 600, letterSpacing: "-0.015em",
            margin: "0 0 22px", color: "var(--ink)",
          }}>
            Granite 4.1 — IBM's reasoning-tuned LLMs
          </h1>

          <div style={{ fontSize: 16, lineHeight: 1.7, color: "var(--ink)", marginBottom: 14 }}>
            IBM released Granite 4.1, a family of small reasoning models (3B, 8B, 20B) tuned with a multi-stage RLHF
            pipeline that emphasizes <em>chain-of-thought distillation</em> from larger teacher models. The 8B variant
            matches Llama-3.3-70B on GSM8K and HumanEval while costing roughly a tenth as much to serve.
          </div>

          <div style={{ fontSize: 16, lineHeight: 1.7, color: "var(--ink-soft)", marginBottom: 26 }}>
            The release notes lean heavily into the open-weights story — Apache 2.0, full evaluation harness on GitHub,
            and a non-trivial safety appendix. Worth comparing against Qwen-3 and Mistral's recent reasoning models
            before betting infrastructure on it.
          </div>

          <h2 className="serif" style={{ fontSize: 18, fontWeight: 600, margin: "0 0 10px", color: "var(--ink)" }}>Key points</h2>
          <ul style={{ margin: 0, paddingLeft: 22, fontSize: 15, lineHeight: 1.75, color: "var(--ink)" }}>
            <li style={{ marginBottom: 6 }}>Three sizes — <span className="mono" style={{ fontSize: 13, color: "var(--ink-soft)" }}>3B / 8B / 20B</span> — all Apache 2.0.</li>
            <li style={{ marginBottom: 6 }}>RLHF with <em>chain-of-thought distillation</em> from a 70B teacher.</li>
            <li style={{ marginBottom: 6 }}>8B matches Llama-3.3-70B on GSM8K (92.4) and HumanEval (78.1).</li>
            <li style={{ marginBottom: 6 }}>Safety appendix details refusal rates and red-team coverage.</li>
            <li>Eval harness reproducible from the published config.</li>
          </ul>

          {/* Action row */}
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 44 }}>
            <button className="kn-btn lg">
              Discard
              <span className="kn-kbd" style={{ marginLeft: 4 }}>D</span>
            </button>
            <button className="kn-btn lg">
              Later
              <span className="kn-kbd" style={{ marginLeft: 4 }}>L</span>
            </button>
            <button className="kn-btn primary lg" style={{ flex: 1, justifyContent: "center" }}>
              <I.Plus size={14} stroke={2} />
              Keep as note
              <span className="kn-kbd" style={{
                marginLeft: 6,
                background: "rgba(28,24,32,0.18)",
                borderColor: "rgba(28,24,32,0.18)",
                color: "rgba(28,24,32,0.7)",
              }}>⏎</span>
            </button>
          </div>

          <div style={{ marginTop: 16, display: "flex", justifyContent: "center", gap: 14, fontSize: 11.5, color: "var(--ink-mute)" }}>
            <span>← prev</span>
            <span>→ next</span>
            <span>· tags <span className="kn-kbd">T</span></span>
            <span>· open source <span className="kn-kbd">O</span></span>
          </div>
        </article>
      </div>
    </div>
  );
};

window.InboxScreen = InboxScreen;
