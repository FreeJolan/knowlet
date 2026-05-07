// Knowlet — Cards focus (FSRS review)

const CardsScreen = () => (
  <div className="kn kn-paper" style={{ width: 1280, height: 820, display: "flex", flexDirection: "column", borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)" }}>
    <header style={{ height: 44, padding: "0 16px", display: "flex", alignItems: "center", gap: 12, background: "var(--panel)", borderBottom: "1px solid var(--line)" }}>
      <I.Cards size={14} style={{ color: "var(--accent-2)" }} />
      <span style={{ fontSize: 13, color: "var(--ink)", fontWeight: 500 }}>卡片复习</span>
      <span style={{ fontSize: 11.5, color: "var(--ink-mute)" }}>
        <span className="mono">2 / 3</span>
        <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>·</span>
        到期 today
      </span>
      <span style={{ flex: 1 }} />
      <button style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 8px", borderRadius: 5, background: "transparent", border: 0, color: "var(--ink-soft)", fontSize: 12, cursor: "pointer" }}>
        <span className="kn-kbd">esc</span>
        <span>退出</span>
      </button>
    </header>

    <div style={{ height: 1, background: "var(--line-soft)" }}>
      <div style={{ width: "66%", height: "100%", background: "var(--accent)" }} />
    </div>

    <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: "40px 24px" }}>
      <div style={{ width: "100%", maxWidth: 760, display: "flex", flexDirection: "column", alignItems: "center" }}>
        {/* meta */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 32, fontSize: 11.5, color: "var(--ink-mute)" }}>
          <span className="kn-chip" style={{ color: "var(--accent-2)", borderColor: "var(--accent-soft)", background: "var(--accent-tint)" }}>
            learning
          </span>
          <span className="mono">interval 10 min</span>
          <span style={{ color: "var(--ink-faint)" }}>·</span>
          <span className="mono">notes/AI papers/RAG 检索策略.md</span>
        </div>

        {/* front */}
        <div className="serif" style={{
          fontFamily: "var(--font-serif)",
          fontSize: 36, lineHeight: 1.35, textAlign: "center",
          color: "var(--ink)", fontWeight: 500, letterSpacing: "-0.01em",
          maxWidth: 720, marginBottom: 36,
        }}>
          RRF 中 <span style={{ color: "var(--accent-2)" }}>k</span> 的典型值是多少?为什么?
        </div>

        {/* reveal */}
        <button style={{
          width: 360, height: 48,
          display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 10,
          background: "transparent",
          border: "1px dashed var(--line)",
          borderRadius: 6,
          color: "var(--ink-soft)",
          fontSize: 13, cursor: "pointer",
        }}>
          <span className="kn-kbd">⏎</span>
          翻面查看答案
        </button>

        {/* rating row — disabled until reveal */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 56, opacity: 0.4 }}>
          <button className="kn-btn" style={{ minWidth: 96 }}>重来 <span className="kn-kbd">1</span></button>
          <button className="kn-btn" style={{ minWidth: 96 }}>困难 <span className="kn-kbd">2</span></button>
          <button className="kn-btn primary" style={{ minWidth: 110, opacity: 1 }}>
            良好
            <span className="kn-kbd" style={{ background: "rgba(22,24,33,0.18)", borderColor: "rgba(22,24,33,0.18)", color: "rgba(22,24,33,0.7)" }}>3</span>
          </button>
          <button className="kn-btn" style={{ minWidth: 96 }}>简单 <span className="kn-kbd">4</span></button>
        </div>
        <div style={{ marginTop: 14, fontSize: 11, color: "var(--ink-faint)" }}>
          FSRS · 翻面后显示下一次间隔
        </div>
      </div>
    </div>
  </div>
);

window.CardsScreen = CardsScreen;
