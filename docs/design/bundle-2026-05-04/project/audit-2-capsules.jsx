// Audit Surface 2 — Capsule strip (5 caps wrap, NOTE/URL color blocks)
// 设计判断:
// - 5 颗在 340px 内 wrap 到第二行,不压缩单颗
// - NOTE = accent-soft 左色条;URL = bg-1 中性灰
// - active = 实色边 + ×;sent = 50% 透明 + hover "再用" 变实
// - 输入框上方贴住 capsule strip(贴住,不挤)

const Capsule = ({ kind, label, sent, active, ghost }) => {
  const isNote = kind === "note";
  const isUrl = kind === "url";
  const isQuote = kind === "quote";

  const base = {
    display: "inline-flex", alignItems: "center", gap: 6,
    height: 22, padding: "0 8px 0 6px",
    borderRadius: 4,
    fontSize: 11.5,
    maxWidth: 180,
    cursor: "pointer",
    position: "relative",
    flexShrink: 0,
  };

  // ghost = URL 解析中
  if (ghost) {
    return (
      <span style={{
        ...base,
        background: "transparent",
        border: "1px dashed var(--line)",
        color: "var(--ink-mute)",
        opacity: 0.7,
      }}>
        <I.Loader size={10} style={{ animation: "kn-spin 1.2s linear infinite" }} />
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontFamily: "var(--font-mono)", fontSize: 10.5 }}>
          {label}
        </span>
      </span>
    );
  }

  let bg, color, leftBar, opacity = 1;
  if (isNote) {
    bg = "var(--accent-soft)"; color = "var(--accent-2)"; leftBar = "var(--accent)";
  } else if (isUrl) {
    bg = "var(--bg-1)"; color = "var(--ink)"; leftBar = "var(--ink-mute)";
  } else if (isQuote) {
    bg = "var(--bg-1)"; color = "var(--ink)"; leftBar = "var(--warn)";
  }
  if (sent) opacity = 0.45;

  return (
    <span style={{
      ...base,
      background: bg,
      border: active ? `1px solid ${color}` : "1px solid transparent",
      color, opacity,
    }}>
      <span style={{ width: 2, height: 12, background: leftBar, borderRadius: 1 }} />
      {isNote && <span style={{ fontSize: 10.5, fontFamily: "var(--font-mono)" }}>[[</span>}
      {isUrl && <I.ExtLink size={10} />}
      {isQuote && <I.Quote size={10} />}
      <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
      {isNote && <span style={{ fontSize: 10.5, fontFamily: "var(--font-mono)" }}>]]</span>}
      {active && <I.X size={10} style={{ marginLeft: 2, color: "var(--ink-mute)" }} />}
    </span>
  );
};

const CapsulesScreen = () => (
  <div className="kn kn-paper" style={{
    width: 1280, height: 760,
    display: "flex", flexDirection: "column",
    borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
  }}>
    <style>{`@keyframes kn-spin { to { transform: rotate(360deg); } }`}</style>

    <header style={{
      height: 36, padding: "0 14px",
      display: "flex", alignItems: "center", gap: 10,
      background: "var(--panel)", borderBottom: "1px solid var(--line)",
      fontSize: 11.5, color: "var(--ink-mute)",
    }}>
      <span className="serif" style={{ fontSize: 13.5, fontWeight: 600, color: "var(--accent-2)" }}>knowlet</span>
      <span style={{ flex: 1 }} />
      <span>AI 右栏 — capsule 多源 attach,5 颗满载状态</span>
    </header>

    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 420px", minHeight: 0 }}>
      {/* center note (灰一点,非 focus) */}
      <section style={{ background: "var(--bg)", padding: "32px 56px", overflow: "auto" }}>
        <div className="kn-md" style={{ maxWidth: 640, opacity: 0.55 }}>
          <h1>RAG 检索策略</h1>
          <p style={{ color: "var(--ink-soft)", fontSize: 14 }}>
            关于 vault 检索质量的工程化思考与实测记录。
          </p>
          <h2>BM25 与向量的权重</h2>
          <p>
            <strong>不要把分数相加</strong> —— 两路分数尺度完全不同。等权 RRF 比手调权重稳;<code>k≈60</code> 是
            Cormack 等人在 TREC 上的经验值,不是玄学。
          </p>
        </div>
      </section>

      {/* AI 右栏 */}
      <aside style={{
        background: "var(--panel)",
        borderLeft: "1px solid var(--line)",
        display: "flex", flexDirection: "column", minHeight: 0,
      }}>
        <div style={{
          height: 36, padding: "0 12px",
          display: "flex", alignItems: "center", gap: 8,
          borderBottom: "1px solid var(--line)",
        }}>
          <I.Sparkles size={12} style={{ color: "var(--accent-2)" }} />
          <span style={{ fontSize: 12, fontWeight: 500 }}>AI</span>
          <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>· 当前 note</span>
          <span style={{ flex: 1 }} />
          <button className="kn-icon-btn" title="收起"><I.X size={11} /></button>
        </div>

        {/* conversation area */}
        <div style={{ flex: 1, padding: "16px 12px", overflow: "auto", fontSize: 13, lineHeight: 1.6 }}>
          {/* 之前的一轮 — 已 sent capsules 显示在 user 气泡里 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{
              fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
              marginBottom: 6,
            }}>USER · 09:38</div>
            <div style={{
              padding: "10px 12px",
              background: "var(--card)", border: "1px solid var(--line-soft)",
              borderRadius: 6,
            }}>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
                <Capsule kind="note" label="RAG 检索策略" sent />
                <Capsule kind="quote" label='"k≈60 是 Cormack 等…"' sent />
              </div>
              <div style={{ color: "var(--ink)" }}>这个 k 值在中文短查询上是不是要调?</div>
            </div>
          </div>

          <div style={{ marginBottom: 20 }}>
            <div style={{
              fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
              marginBottom: 6,
            }}>AI · 09:38</div>
            <div style={{ color: "var(--ink-soft)" }}>
              对中文短查询(2-4 字),trigram FTS5 在文档密度低时召回偏弱,适当调低 k(到 30-40)能让向量通路得分更突出。建议 A/B 测试,而不是凭直觉调。
            </div>
          </div>

          <div style={{ marginBottom: 12 }}>
            <div style={{
              fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
              marginBottom: 6,
            }}>USER · 正在输入…</div>
          </div>
        </div>

        {/* capsule strip — 贴住输入框上方 */}
        <div style={{
          padding: "8px 10px 6px",
          borderTop: "1px solid var(--line-soft)",
          background: "var(--panel-2)",
        }}>
          <div style={{
            fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
            marginBottom: 6, display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span>引用 · 5</span>
            <span style={{ color: "var(--ink-faint)" }}>⌘⇧C 清空</span>
          </div>
          {/* 5 颗 wrap 到第二行 */}
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            <Capsule kind="note" label="RAG 检索策略" active />
            <Capsule kind="note" label="检索增强生成(中文版)" />
            <Capsule kind="url" label="cormack-2009.pdf" />
            <Capsule kind="quote" label='"trigram 在 PKM…"' />
            <Capsule kind="url" label="github.com/AnswerDotAI/byaldi" />
          </div>
        </div>

        {/* input */}
        <div style={{
          padding: "8px 10px 12px",
          borderTop: "1px solid var(--line)",
          background: "var(--panel)",
        }}>
          <div style={{
            background: "var(--card)",
            border: "1px solid var(--line)",
            borderRadius: 6,
            padding: "10px 12px",
            minHeight: 64,
            position: "relative",
            fontSize: 13,
            color: "var(--ink)",
          }}>
            综合这五个引用,我应该把<span style={{
              display: "inline-flex", alignItems: "center", height: 18, padding: "0 5px",
              background: "var(--accent-soft)", color: "var(--accent-2)",
              borderRadius: 3, fontSize: 11, margin: "0 2px",
            }}>k</span>调到多少<span style={{
              display: "inline-block", width: 1.5, height: 14,
              background: "var(--accent)", marginLeft: 1, verticalAlign: "middle",
              animation: "kn-blink 1s steps(1) infinite",
            }} />
          </div>
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            marginTop: 6,
          }}>
            <span style={{ fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)" }}>
              ⌘↵ 发送 · @ 引 Note · / 命令
            </span>
            <button className="kn-btn primary" style={{ height: 26, fontSize: 12 }}>
              <I.Send2 size={11} /> 发送
            </button>
          </div>
        </div>
      </aside>
    </div>

    <style>{`
      @keyframes kn-blink { 50% { opacity: 0; } }
    `}</style>
  </div>
);

window.CapsulesScreen = CapsulesScreen;
