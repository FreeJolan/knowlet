// Knowlet — ⌘K command palette (ADR-0011 §4)

const PaletteScreen = () => {
  const Row = ({ kind, kindColor, title, hint, sub, accent, mono }) => (
    <div style={{
      display: "flex", alignItems: "center", gap: 12,
      padding: "8px 12px",
      borderRadius: 5,
      background: accent ? "var(--accent-soft)" : "transparent",
      cursor: "pointer",
    }}>
      <span className="mono" style={{
        minWidth: 38, padding: "1px 6px",
        textAlign: "center",
        fontSize: 9.5, letterSpacing: "0.06em",
        textTransform: "uppercase", fontWeight: 600,
        color: kindColor,
        background: "transparent",
        border: "1px solid var(--line)", borderRadius: 3,
      }}>{kind}</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className={mono ? "mono" : ""} style={{ fontSize: 13, color: accent ? "var(--accent-2)" : "var(--ink)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {title}
        </div>
        {sub && <div style={{ fontSize: 11, color: "var(--ink-mute)", marginTop: 2 }}>{sub}</div>}
      </div>
      <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>{hint}</span>
    </div>
  );

  return (
    <div className="kn kn-paper" style={{ width: 1280, height: 820, position: "relative", borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)" }}>
      {/* faint underlay of the home layout */}
      <div style={{ position: "absolute", inset: 0, opacity: 0.25 }}>
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 40, background: "var(--panel)", borderBottom: "1px solid var(--line)" }} />
        <div style={{ position: "absolute", top: 40, left: 0, bottom: 30, width: 240, background: "var(--panel)", borderRight: "1px solid var(--line)" }} />
        <div style={{ position: "absolute", top: 40, right: 0, bottom: 30, width: 40, background: "var(--panel)", borderLeft: "1px solid var(--line)" }} />
        <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 30, background: "var(--panel)", borderTop: "1px solid var(--line)" }} />
      </div>

      {/* dim layer */}
      <div style={{
        position: "absolute", inset: 0,
        background: "rgba(90,78,55,0.18)",
        backdropFilter: "blur(2px)",
      }} />

      {/* palette */}
      <div style={{
        position: "absolute", top: 110, left: "50%", transform: "translateX(-50%)",
        width: 640,
        background: "var(--panel)",
        border: "1px solid var(--line)",
        borderRadius: 8,
        boxShadow: "var(--shadow-lg)",
        overflow: "hidden",
      }}>
        {/* input */}
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "12px 14px",
          borderBottom: "1px solid var(--line-soft)",
        }}>
          <I.Search size={14} style={{ color: "var(--ink-mute)" }} />
          <input
            placeholder="跳转 Note · 跑命令 · 用 > 直接问 AI · 用 + 新建 Note"
            defaultValue=""
            style={{
              flex: 1, background: "transparent", border: 0, outline: 0,
              color: "var(--ink)", fontSize: 14, fontFamily: "var(--font-sans)",
              caretColor: "var(--accent)",
            }}
          />
          <span className="kn-kbd">esc</span>
        </div>

        <div style={{ padding: "8px 6px 10px", maxHeight: 500, overflow: "auto" }}>
          <div style={{ padding: "6px 12px 4px", fontSize: 9.5, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--ink-mute)" }}>
            Notes
          </div>
          <Row kind="NOTE" kindColor="var(--accent-2)" title="RAG 检索策略" hint="09:42" accent />
          <Row kind="NOTE" kindColor="var(--accent-2)" title="Attention paper notes" hint="08:55" />
          <Row kind="NOTE" kindColor="var(--accent-2)" title="检索增强生成(中文版)" hint="昨天" />

          <div style={{ padding: "10px 12px 4px", fontSize: 9.5, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--ink-mute)" }}>
            Commands
          </div>
          <Row kind="CMD" kindColor="var(--warn)" title="重建索引" hint="⏎" sub="reindex — 从盘上重扫 Note" />
          <Row kind="CMD" kindColor="var(--warn)" title="立刻跑所有 mining 任务" hint="⏎" sub="mining run-all" />
          <Row kind="CMD" kindColor="var(--warn)" title="诊断 (doctor)" hint="⏎" sub="backend / LLM / embedding" />

          <div style={{ padding: "10px 12px 4px", fontSize: 9.5, textTransform: "uppercase", letterSpacing: "0.1em", color: "var(--ink-mute)" }}>
            Ask AI
          </div>
          <Row
            kind="AI"
            kindColor="var(--accent-2)"
            title={<><span style={{ color: "var(--accent-2)" }}>{`> `}</span>这周我读过什么关于 RAG?</>}
            hint="⏎ ask"
            sub="就地 popup 一次性回答 · 不进 chat history"
            mono
          />
        </div>

        {/* footer */}
        <div style={{
          display: "flex", alignItems: "center", gap: 14,
          padding: "8px 14px",
          borderTop: "1px solid var(--line-soft)",
          background: "var(--bg-1)",
          fontSize: 10.5, color: "var(--ink-mute)",
        }}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span className="kn-kbd">↑</span><span className="kn-kbd">↓</span> 选择</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span className="kn-kbd">⏎</span> 打开</span>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}><span className="kn-kbd">⌘⏎</span> 新 tab</span>
          <span style={{ flex: 1 }} />
          <span className="mono">parity: 每条命令 = CLI · ADR-0008</span>
        </div>
      </div>
    </div>
  );
};

window.PaletteScreen = PaletteScreen;
