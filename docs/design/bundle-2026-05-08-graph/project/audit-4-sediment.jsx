// Audit Surface 4 — Sediment inline collapsed line
// 设计判断:
// - 默认折叠成一行 inline:"3 条相关 ↗ Personal energy · Books 2026 · Balcony garden"
// - 不带"建议"动词 (ADR-0013 §1)
// - 展开 = 完整段落预览,inline 在 note 底部,而不是浮窗
// - 用户可以 dismiss → 折叠后那行也消失,本 session 不再出现
// - 折叠态 / 展开态 / dismissed 三态并排

const SedimentScreen = () => {
  // 共用 mini note
  const MiniNote = ({ children, label, footer }) => (
    <div style={{
      width: 380, height: 360,
      background: "var(--bg)",
      border: "1px solid var(--line)",
      borderRadius: 8,
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      <div style={{
        height: 28, padding: "0 12px",
        display: "flex", alignItems: "center",
        background: "var(--panel)", borderBottom: "1px solid var(--line)",
        fontSize: 11, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
      }}>
        {label}
      </div>
      <div style={{ flex: 1, padding: "20px 24px", overflow: "hidden" }}>
        <div className="kn-md" style={{ fontSize: 13.5, lineHeight: 1.7 }}>
          <h2 style={{ fontSize: 16, marginTop: 0, marginBottom: 10 }}>RAG 检索策略</h2>
          <p style={{ color: "var(--ink-soft)", fontSize: 12.5, marginBottom: 8 }}>
            关键词通路(BM25)解决精确匹配 —— 函数名、错误码;向量通路解决语义近邻。
          </p>
          <p style={{ color: "var(--ink-soft)", fontSize: 12.5 }}>
            <strong style={{ color: "var(--ink)" }}>不要把分数相加</strong> —— 两路尺度不同。
            等权 RRF 比手调权重稳。
          </p>
        </div>
      </div>
      {/* sediment area */}
      <div style={{
        borderTop: "1px solid var(--line-soft)",
        background: "var(--panel-2)",
      }}>
        {footer}
      </div>
    </div>
  );

  return (
    <div className="kn kn-paper" style={{
      width: 1280, height: 760,
      display: "flex", flexDirection: "column",
      borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
    }}>
      <header style={{
        height: 36, padding: "0 14px",
        display: "flex", alignItems: "center", gap: 10,
        background: "var(--panel)", borderBottom: "1px solid var(--line)",
        fontSize: 11.5, color: "var(--ink-mute)",
      }}>
        <span className="serif" style={{ fontSize: 13.5, fontWeight: 600, color: "var(--accent-2)" }}>knowlet</span>
        <span style={{ flex: 1 }} />
        <span>沉淀提示 · 默认 inline 一行,无"建议"动词,可展开 / 可永久关</span>
      </header>

      <div style={{ flex: 1, padding: "32px 40px", display: "flex", gap: 28, alignItems: "flex-start", justifyContent: "center", overflow: "auto" }}>
        {/* 1 — collapsed */}
        <div>
          <div style={{
            fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
            marginBottom: 8, display: "flex", alignItems: "center", gap: 6,
          }}>
            <I.Dot size={10} style={{ color: "var(--accent)" }} />
            state 1 · 默认折叠
          </div>
          <MiniNote label="notes/AI papers/RAG.md" footer={
            <div style={{
              padding: "8px 14px",
              display: "flex", alignItems: "center", gap: 8,
              fontSize: 11.5,
            }}>
              <I.ArrowUR size={11} style={{ color: "var(--ink-mute)" }} />
              <span style={{ color: "var(--ink-soft)" }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--ink-mute)", marginRight: 4 }}>3 条相关</span>
                <a style={{ color: "var(--accent-2)", borderBottom: "1px solid transparent" }}>Personal energy</a>
                <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>·</span>
                <a style={{ color: "var(--accent-2)" }}>Books · 2026</a>
                <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>·</span>
                <a style={{ color: "var(--accent-2)" }}>Balcony garden</a>
              </span>
              <span style={{ flex: 1 }} />
              <button className="kn-icon-btn" style={{ width: 22, height: 22 }} title="展开">
                <I.ChevronD size={11} />
              </button>
              <button className="kn-icon-btn" style={{ width: 22, height: 22 }} title="本 vault 关闭">
                <I.X size={11} />
              </button>
            </div>
          } />
          <div style={{ width: 380, fontSize: 11, color: "var(--ink-soft)", lineHeight: 1.55, marginTop: 10 }}>
            一行 inline,贴在 note 底部。不动词,不"建议",不弹窗。
          </div>
        </div>

        {/* 2 — expanded */}
        <div>
          <div style={{
            fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
            marginBottom: 8, display: "flex", alignItems: "center", gap: 6,
          }}>
            <I.Dot size={10} style={{ color: "var(--good)" }} />
            state 2 · 用户点开
          </div>
          <MiniNote label="notes/AI papers/RAG.md" footer={
            <div style={{ padding: "10px 14px", fontSize: 11.5 }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
                color: "var(--ink-mute)", fontSize: 10.5, fontFamily: "var(--font-mono)",
              }}>
                <I.ArrowUR size={10} />
                <span>3 条相关</span>
                <span style={{ flex: 1 }} />
                <button className="kn-icon-btn" style={{ width: 22, height: 22 }} title="折起">
                  <I.Up size={11} />
                </button>
                <button className="kn-icon-btn" style={{ width: 22, height: 22 }} title="本 vault 关闭">
                  <I.X size={11} />
                </button>
              </div>
              {[
                { title: "Personal energy", excerpt: "下午脑力低 → 优先做检索/索引这种结构性工作", score: 0.78 },
                { title: "Books · 2026 reading", excerpt: '"Designing Data-Intensive Applications" — search/index 章节', score: 0.71 },
                { title: "Balcony garden", excerpt: "番茄分两批种,主次旁通路 — 这条是 spurious", score: 0.42 },
              ].map((row, i) => (
                <div key={i} style={{
                  display: "flex", alignItems: "flex-start", gap: 8,
                  padding: "6px 0",
                  borderTop: i ? "1px dashed var(--line-soft)" : "none",
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ color: "var(--accent-2)", fontWeight: 500, fontSize: 12 }}>{row.title}</div>
                    <div style={{ color: "var(--ink-soft)", fontSize: 11, marginTop: 2, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {row.excerpt}
                    </div>
                  </div>
                  <span className="mono" style={{ fontSize: 10, color: "var(--ink-mute)", marginTop: 2 }}>
                    {row.score.toFixed(2)}
                  </span>
                </div>
              ))}
            </div>
          } />
          <div style={{ width: 380, fontSize: 11, color: "var(--ink-soft)", lineHeight: 1.55, marginTop: 10 }}>
            展开后是<strong>预览,不是动作</strong>。每行可点跳转。分数显示给用户判断 spurious。
          </div>
        </div>

        {/* 3 — dismissed */}
        <div>
          <div style={{
            fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
            marginBottom: 8, display: "flex", alignItems: "center", gap: 6,
          }}>
            <I.Dot size={10} style={{ color: "var(--ink-faint)" }} />
            state 3 · 永久关闭
          </div>
          <MiniNote label="notes/AI papers/RAG.md" footer={null} />
          <div style={{ width: 380, fontSize: 11, color: "var(--ink-soft)", lineHeight: 1.55, marginTop: 10 }}>
            footer 完全消失。本 vault 不再自动浮现 sediment。
            <span style={{ color: "var(--ink-mute)" }}> 设置里可重启。</span>
          </div>
        </div>
      </div>
    </div>
  );
};

window.SedimentScreen = SedimentScreen;
