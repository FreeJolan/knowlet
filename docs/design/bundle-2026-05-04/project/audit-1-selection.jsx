// Audit Surface 1 — Selection popover (above/below collision)
// 在真实编辑器语境里展示选区浮起、定位、动作
//
// 设计判断:
// - 两态:above (选区顶 -32px) / below (选区距 viewport top < 80px 时翻)
// - 不带阴影、不进 footer/palette 占用区
// - 6 个动作:加粗 / 斜体 / 删除线 / 引用块 / 高亮 / 转 quote → AI

const SelectionPopover = ({ flip = false }) => (
  <div style={{
    position: "absolute",
    ...(flip ? { top: "calc(100% + 8px)" } : { bottom: "calc(100% + 8px)" }),
    left: 0,
    display: "flex", alignItems: "center", gap: 1,
    height: 30, padding: "0 2px",
    background: "var(--card)",
    border: "1px solid var(--line)",
    borderRadius: 6,
    zIndex: 5,
    fontSize: 12,
  }}>
    {[
      { icon: <I.Bold size={13} />, k: "B" },
      { icon: <I.Italic size={13} />, k: "I" },
      { icon: <I.Strike size={13} />, k: "" },
      { icon: <I.Quote size={13} />, k: "" },
      { icon: <I.Highlight size={13} />, k: "" },
    ].map((b, i) => (
      <button key={i} className="kn-icon-btn" style={{ width: 26, height: 26, color: "var(--ink-soft)" }}>
        {b.icon}
      </button>
    ))}
    <span style={{ width: 1, height: 16, background: "var(--line-soft)", margin: "0 4px" }} />
    <button style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      height: 24, padding: "0 9px",
      background: "var(--accent-soft)", color: "var(--accent-2)",
      border: 0, borderRadius: 4,
      fontSize: 11.5, fontWeight: 500,
      cursor: "pointer",
    }}>
      <I.Sparkles size={11} /> 引用 → AI
    </button>
    {/* 小三角 */}
    <span style={{
      position: "absolute",
      ...(flip
        ? { top: -5, borderBottom: "5px solid var(--line)" }
        : { bottom: -5, borderTop: "5px solid var(--line)" }),
      left: 28,
      width: 0, height: 0,
      borderLeft: "5px solid transparent",
      borderRight: "5px solid transparent",
    }} />
    <span style={{
      position: "absolute",
      ...(flip
        ? { top: -4, borderBottom: "4px solid var(--card)" }
        : { bottom: -4, borderTop: "4px solid var(--card)" }),
      left: 29,
      width: 0, height: 0,
      borderLeft: "4px solid transparent",
      borderRight: "4px solid transparent",
    }} />
  </div>
);

const SelectionScreen = ({ flip = false }) => (
  <div className="kn kn-paper" style={{
    width: 1280, height: 760,
    display: "flex", flexDirection: "column",
    borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
  }}>
    {/* 简化 header */}
    <header style={{
      height: 36, padding: "0 14px",
      display: "flex", alignItems: "center", gap: 10,
      background: "var(--panel)", borderBottom: "1px solid var(--line)",
      fontSize: 11.5, color: "var(--ink-mute)",
    }}>
      <span className="serif" style={{ fontSize: 13.5, fontWeight: 600, color: "var(--accent-2)" }}>knowlet</span>
      <span className="mono" style={{ fontSize: 11 }}>
        <span style={{ color: "var(--ink-faint)" }}>notes/AI papers/</span>
        <span style={{ color: "var(--ink-soft)" }}>RAG 检索策略.md</span>
      </span>
      <span style={{ flex: 1 }} />
      <span style={{ color: "var(--ink-faint)" }}>{flip ? "选区在视口顶部 → popover 翻到下方" : "选区在视口中部 → popover 默认在上方"}</span>
    </header>

    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "240px 1fr 40px", minHeight: 0 }}>
      {/* sidebar */}
      <aside style={{ background: "var(--panel)", borderRight: "1px solid var(--line)", padding: "8px 4px" }}>
        <div className="kn-tree-item" style={{ paddingLeft: 8, color: "var(--ink-soft)" }}>
          <I.ChevronD size={11} className="ico" /><I.FolderOpen size={13} className="ico" /><span>AI papers</span>
        </div>
        <div className="kn-tree-item active" style={{ paddingLeft: 20 }}>
          <I.Doc size={13} className="ico" /><span>RAG 检索策略</span>
        </div>
        <div className="kn-tree-item" style={{ paddingLeft: 20 }}>
          <I.Doc size={13} className="ico" /><span>检索增强生成(中文版)</span>
        </div>
      </aside>

      {/* center editor */}
      <section style={{ background: "var(--bg)", overflow: "auto", padding: "32px 64px", position: "relative" }}>
        <div className="kn-md" style={{ maxWidth: 720, margin: "0 auto", position: "relative" }}>
          {flip && (
            <>
              <h1 style={{ position: "relative" }}>
                <span style={{
                  background: "var(--accent-tint-2)",
                  borderRadius: 2,
                  padding: "0 1px",
                  position: "relative",
                  display: "inline-block",
                }}>
                  RAG 检索策略
                  <SelectionPopover flip={true} />
                </span>
              </h1>
              <p style={{ color: "var(--ink-soft)", fontSize: 14 }}>
                关于 vault 检索质量的工程化思考与实测记录。两路通路 + RRF 融合是 default;在生产里少有例外。
              </p>
              <h2>混合检索的核心思路</h2>
              <p>
                关键词通路(BM25)解决精确匹配 —— 函数名、错误码、文件路径、人名;向量通路解决语义近邻 ——
                "怎么取消订单" ≈ "退款流程"。
              </p>
            </>
          )}
          {!flip && (
            <>
              <h1>RAG 检索策略</h1>
              <p style={{ color: "var(--ink-soft)", fontSize: 14 }}>
                关于 vault 检索质量的工程化思考与实测记录。两路通路 + RRF 融合是 default;在生产里少有例外。
              </p>
              <h2>混合检索的核心思路</h2>
              <p>
                关键词通路(BM25)解决精确匹配 —— 函数名、错误码、文件路径、人名;向量通路解决语义近邻 ——
                "怎么取消订单" ≈ "退款流程"。两路的失败模式不同,所以混合的 ROI 比两个都调到极致都更高。
              </p>
              <h2>BM25 与向量的权重</h2>
              <p style={{ position: "relative" }}>
                <strong>不要把分数相加</strong> —— 两路分数尺度完全不同。<span style={{
                  background: "var(--accent-tint-2)", borderRadius: 2,
                  position: "relative", display: "inline",
                }}>等权 RRF 比手调权重稳;<code>k≈60</code> 是 Cormack 等人在 TREC 上的经验值<SelectionPopover flip={false} /></span>,不是玄学。
              </p>
              <p>
                短查询(2–4 字)表现尚可;长查询稍弱。建议跟向量通路并用,不依赖单路。
              </p>
            </>
          )}
        </div>

        {/* annotation pin */}
        <div style={{
          position: "absolute",
          ...(flip ? { top: 92 } : { top: 360 }),
          right: 28,
          maxWidth: 200,
          fontSize: 10.5, color: "var(--ink-mute)",
          fontFamily: "var(--font-mono)",
          lineHeight: 1.45,
        }}>
          <span style={{ color: "var(--accent-2)" }}>● </span>
          {flip
            ? "选区距 viewport top 32px,< 80px 阈值 → popover 翻到下方"
            : "popover anchor = above,选区顶 -32px;贴住选区跟随滚动"}
        </div>
      </section>

      {/* right rail */}
      <aside style={{ background: "var(--panel)", borderLeft: "1px solid var(--line)", padding: "8px 0", display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
        <button className="kn-icon-btn" style={{ width: 28, height: 28 }}><I.List /></button>
        <button className="kn-icon-btn" style={{ width: 28, height: 28 }}><I.Link /></button>
        <button className="kn-icon-btn" style={{ width: 28, height: 28, color: "var(--accent-2)" }}><I.Sparkles /></button>
      </aside>
    </div>
  </div>
);

window.SelectionScreen = SelectionScreen;
