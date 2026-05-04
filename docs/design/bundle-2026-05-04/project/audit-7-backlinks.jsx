// Audit Surface 7 — Backlinks panel
// 设计判断:
// - 列表按 source note group
// - 句子用前后省略号 + line 号:"…如 [[RAG 检索策略]] 中描述的 RRF 融合… L24"
// - mark 改为 2px 底色横条(不是矩形 highlight),accent 上读不清的问题靠"用线不用块"绕过
// - 过滤:全部 / 直接 / 经引用(transitive)
// - 空态:不是"没有反链",而是"试试在其他 note 里 [[…]] 引用本 note"

const BacklinksScreen = () => {
  const Mention = ({ before, link, after, line, source }) => (
    <div style={{
      padding: "8px 12px 10px",
      borderTop: "1px solid var(--line-soft)",
      cursor: "pointer",
    }}>
      <div className="serif" style={{
        fontSize: 13, lineHeight: 1.7, color: "var(--ink)",
        fontFamily: "var(--font-serif)",
      }}>
        <span style={{ color: "var(--ink-faint)" }}>… </span>
        {before}
        <span style={{
          color: "var(--accent-2)",
          borderBottom: "2px solid var(--accent)",
          padding: "0 1px",
          fontWeight: 500,
        }}>{link}</span>
        {after}
        <span style={{ color: "var(--ink-faint)" }}> …</span>
      </div>
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
        marginTop: 4,
      }}>
        <I.ArrowUR size={9} />
        <span>{source}</span>
        <span style={{ color: "var(--ink-faint)" }}>·</span>
        <span>{line}</span>
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
        <span>反链面板 — 按 source note 分组,2px 底色横条 mark,line 号</span>
      </header>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "240px 1fr 380px", minHeight: 0 }}>
        {/* sidebar (灰一点,非 focus) */}
        <aside style={{ background: "var(--panel)", borderRight: "1px solid var(--line)", padding: "8px 4px", opacity: 0.7 }}>
          <div className="kn-tree-item" style={{ paddingLeft: 8 }}>
            <I.ChevronD size={11} className="ico" /><I.FolderOpen size={13} className="ico" /><span>AI papers</span>
          </div>
          <div className="kn-tree-item active" style={{ paddingLeft: 20 }}>
            <I.Doc size={13} className="ico" /><span>RAG 检索策略</span>
          </div>
        </aside>

        {/* center note */}
        <section style={{ background: "var(--bg)", padding: "32px 56px", overflow: "auto", opacity: 0.7 }}>
          <div className="kn-md" style={{ maxWidth: 640 }}>
            <h1>RAG 检索策略</h1>
            <p style={{ color: "var(--ink-soft)" }}>
              关于 vault 检索质量的工程化思考与实测记录。
            </p>
            <h2>BM25 与向量的权重</h2>
            <p>
              <strong>不要把分数相加</strong> —— 等权 RRF 比手调权重稳;<code>k≈60</code>。
            </p>
          </div>
        </section>

        {/* backlinks panel */}
        <aside style={{
          background: "var(--panel)",
          borderLeft: "1px solid var(--line)",
          display: "flex", flexDirection: "column", minHeight: 0,
        }}>
          {/* header */}
          <div style={{
            padding: "10px 12px 8px",
            borderBottom: "1px solid var(--line)",
          }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
              marginBottom: 8,
            }}>
              <I.Link size={12} style={{ color: "var(--ink-soft)" }} />
              <span style={{ fontSize: 12, fontWeight: 500 }}>反链</span>
              <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>· 4 处 / 3 个 note</span>
              <span style={{ flex: 1 }} />
              <button className="kn-icon-btn" style={{ width: 22, height: 22 }}><I.Filter size={11} /></button>
            </div>
            {/* filter chips */}
            <div style={{ display: "flex", gap: 4 }}>
              {[
                { label: "全部", n: 4, active: true },
                { label: "直接", n: 3 },
                { label: "经引用", n: 1 },
              ].map((f) => (
                <button key={f.label} style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  height: 22, padding: "0 8px",
                  borderRadius: 4,
                  fontSize: 11,
                  background: f.active ? "var(--accent-soft)" : "transparent",
                  color: f.active ? "var(--accent-2)" : "var(--ink-soft)",
                  border: f.active ? "1px solid var(--accent)" : "1px solid var(--line-soft)",
                  cursor: "pointer",
                }}>
                  {f.label}
                  <span className="mono" style={{ fontSize: 10, color: "var(--ink-mute)" }}>{f.n}</span>
                </button>
              ))}
            </div>
          </div>

          <div style={{ flex: 1, overflow: "auto" }}>
            {/* group 1 */}
            <div>
              <div style={{
                padding: "10px 12px 6px",
                fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
                display: "flex", alignItems: "center", gap: 6,
                background: "var(--panel-2)",
              }}>
                <I.Doc size={10} />
                <span style={{ color: "var(--accent-2)" }}>检索增强生成(中文版)</span>
                <span style={{ color: "var(--ink-faint)" }}>· 2 处</span>
              </div>
              <Mention
                before="两路结果用 RRF 融合,具体细节见 "
                link="[[RAG 检索策略#BM25 与向量的权重]]"
                after="。这里只复述结论:不要相加,要 RRF。"
                line="L42"
                source="检索增强生成(中文版).md"
              />
              <Mention
                before="对中文 corpus,trigram FTS 仍是稳定的关键词通路;参 "
                link="[[RAG 检索策略]]"
                after="。"
                line="L78"
                source="检索增强生成(中文版).md"
              />
            </div>

            {/* group 2 */}
            <div>
              <div style={{
                padding: "10px 12px 6px",
                fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
                display: "flex", alignItems: "center", gap: 6,
                background: "var(--panel-2)",
                marginTop: 4,
              }}>
                <I.Doc size={10} />
                <span style={{ color: "var(--accent-2)" }}>FTS5 trigram 调优</span>
                <span style={{ color: "var(--ink-faint)" }}>· 1 处</span>
              </div>
              <Mention
                before="2-4 字短查询的实测命中率优于预期;主要决策见 "
                link="[[RAG 检索策略]]"
                after=" 第三节。"
                line="L12"
                source="FTS5 trigram 调优.md"
              />
            </div>

            {/* group 3 — transitive */}
            <div>
              <div style={{
                padding: "10px 12px 6px",
                fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
                display: "flex", alignItems: "center", gap: 6,
                background: "var(--panel-2)",
                marginTop: 4,
              }}>
                <I.Doc size={10} />
                <span style={{ color: "var(--accent-2)" }}>Personal energy</span>
                <span style={{ color: "var(--ink-faint)" }}>· 1 处 经引用</span>
              </div>
              <Mention
                before="下午脑力低 → 优先做结构性工作,例如 "
                link="[[搜索/索引设计]]"
                after=" 系列(其中第三篇直接引 RAG 检索策略)。"
                line="L8"
                source="Personal energy.md"
              />
            </div>
          </div>

          {/* empty state hint at bottom */}
          <div style={{
            padding: "8px 12px",
            borderTop: "1px solid var(--line-soft)",
            fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
            background: "var(--panel-2)",
          }}>
            空 vault 时空态 → "在其他 note 里用 [[RAG 检索策略]] 即出现"
          </div>
        </aside>
      </div>
    </div>
  );
};

window.BacklinksScreen = BacklinksScreen;
