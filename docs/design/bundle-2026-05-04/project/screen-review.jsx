// Knowlet — Screen 3: Card review focus

const ReviewScreen = () => {
  return (
    <div className="kn kn-paper" style={{ width: 1200, height: 800, position: "relative", borderRadius: 12, overflow: "hidden", border: "1px solid var(--line)" }}>
      <div style={{
        position: "absolute", inset: 0,
        background: "linear-gradient(180deg, rgba(28,29,34,0.94), rgba(28,29,34,0.99))",
      }} />

      {/* Top row */}
      <div style={{ position: "absolute", top: 18, left: 24, right: 24, display: "flex", alignItems: "center", justifyContent: "space-between", zIndex: 2 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "var(--ink-mute)" }}>
          <I.Check size={13} stroke={1.7} style={{ color: "var(--good)" }} />
          <span>Review</span>
          <span style={{ color: "var(--ink-faint)" }}>·</span>
          <span className="mono">2 of 3 due</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 12, color: "var(--ink-mute)" }}>
          <span>Esc to exit</span>
          <span className="kn-kbd">Esc</span>
        </div>
      </div>

      {/* Progress hairline */}
      <div style={{ position: "absolute", top: 50, left: 0, right: 0, height: 1, background: "var(--line-soft)", zIndex: 2 }}>
        <div style={{ width: "66%", height: "100%", background: "var(--accent-soft)" }} />
      </div>

      {/* Card */}
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", padding: 40, zIndex: 1 }}>
        <div style={{ width: 760, maxWidth: "100%", display: "flex", flexDirection: "column", alignItems: "center" }}>
          {/* card meta */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 26, fontSize: 12, color: "var(--ink-mute)" }}>
            <span className="kn-chip" style={{ background: "rgba(164,139,176,0.08)", borderColor: "rgba(164,139,176,0.20)", color: "#bca3c5" }}>
              learning
            </span>
            <span className="mono">10 min interval</span>
            <span style={{ color: "var(--ink-faint)" }}>·</span>
            <span className="mono">from “RAG retrieval strategies”</span>
          </div>

          {/* Front */}
          <div className="cjk" style={{
            fontFamily: 'var(--font-serif), "Source Han Serif SC", "Noto Serif SC", serif',
            fontSize: 40, lineHeight: 1.3, textAlign: "center", color: "var(--ink)",
            fontWeight: 500, letterSpacing: "-0.01em",
            maxWidth: 720,
            marginBottom: 36,
          }}>
            RRF 中 <span style={{ color: "var(--accent)" }}>k</span> 的典型值是多少？为什么？
          </div>

          {/* Reveal */}
          <div style={{ width: "100%", maxWidth: 560, display: "flex", flexDirection: "column", alignItems: "center", gap: 24 }}>
            <button className="kn-btn lg" style={{
              width: "100%",
              borderStyle: "dashed",
              borderColor: "var(--line)",
              color: "var(--ink-soft)",
              background: "rgba(255,255,255,0.015)",
              height: 56,
              fontSize: 14,
              gap: 10,
            }}>
              <span className="kn-kbd">⏎</span>
              Reveal answer
            </button>

            {/* Hint of answer area */}
            <div style={{
              width: "100%",
              fontSize: 13,
              color: "var(--ink-faint)",
              textAlign: "center",
              fontStyle: "italic",
              fontFamily: "var(--font-serif)",
            }}>
              answer hidden · press <span className="kn-kbd" style={{ fontStyle: "normal" }}>space</span> to peek
            </div>
          </div>

          {/* Rating row — disabled-looking until reveal, but shown for layout */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 60, opacity: 0.45 }}>
            <button className="kn-btn" style={{ minWidth: 110 }}>
              Again
              <span className="kn-kbd" style={{ marginLeft: 4 }}>1</span>
            </button>
            <button className="kn-btn" style={{ minWidth: 110 }}>
              Hard
              <span className="kn-kbd" style={{ marginLeft: 4 }}>2</span>
            </button>
            <button className="kn-btn primary" style={{ minWidth: 130, opacity: 1 }}>
              Good
              <span className="kn-kbd" style={{
                marginLeft: 4,
                background: "rgba(28,24,32,0.18)",
                borderColor: "rgba(28,24,32,0.18)",
                color: "rgba(28,24,32,0.7)",
              }}>3</span>
            </button>
            <button className="kn-btn" style={{ minWidth: 110 }}>
              Easy
              <span className="kn-kbd" style={{ marginLeft: 4 }}>4</span>
            </button>
          </div>

          <div style={{ marginTop: 20, fontSize: 11.5, color: "var(--ink-faint)" }}>
            FSRS · next interval shown after rating
          </div>
        </div>
      </div>
    </div>
  );
};

window.ReviewScreen = ReviewScreen;
