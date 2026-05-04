// Audit Surface 5 — Hover quote tooltip
// 设计判断:
// - max-width: min(420px, 80vw)
// - 边缘碰撞:viewport 内做 collision detection,翻边 / 下移
// - CJK 1.7 行高,Source Serif 4 西文 stack + Noto Serif SC 中文
// - tooltip 内显示:Note 名 (link) + 上下文段落 + 节标题面包屑

const QuoteTooltipScreen = () => {
  const Tooltip = ({ flip, edge }) => (
    <div style={{
      position: "absolute",
      ...(flip ? { top: "calc(100% + 10px)" } : { bottom: "calc(100% + 10px)" }),
      ...(edge === "right" ? { right: 0 } : edge === "left" ? { left: 0 } : { left: "50%", transform: "translateX(-50%)" }),
      width: 420, maxWidth: "calc(80vw)",
      background: "var(--card)",
      border: "1px solid var(--line)",
      borderRadius: 6,
      padding: "12px 14px",
      zIndex: 5,
      fontSize: 12.5,
      lineHeight: 1.7,
    }}>
      {/* 面包屑 */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
        marginBottom: 8, paddingBottom: 8, borderBottom: "1px solid var(--line-soft)",
      }}>
        <I.Doc size={10} />
        <span style={{ color: "var(--accent-2)" }}>RAG 检索策略</span>
        <I.ChevronR size={9} style={{ color: "var(--ink-faint)" }} />
        <span>BM25 与向量的权重</span>
      </div>
      {/* quote — serif + cjk lh */}
      <div className="serif" style={{
        color: "var(--ink)", fontSize: 13.5, lineHeight: 1.7, fontFamily: "var(--font-serif)",
      }}>
        <strong>不要把分数相加</strong> —— 两路分数尺度完全不同。等权 RRF 比手调权重稳;<code style={{
          fontFamily: "var(--font-mono)", fontSize: 12, padding: "0 4px",
          background: "var(--panel-2)", borderRadius: 3, color: "var(--accent-2)",
        }}>k≈60</code> 是 Cormack 等人在 TREC 上的经验值,不是玄学。
      </div>
      {/* footer */}
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
        marginTop: 10, paddingTop: 8, borderTop: "1px solid var(--line-soft)",
      }}>
        <span>L24 · 2026-04-28</span>
        <span style={{ flex: 1 }} />
        <button style={{
          display: "inline-flex", alignItems: "center", gap: 4,
          padding: "2px 6px", background: "transparent", border: 0,
          color: "var(--ink-soft)", fontSize: 10.5, cursor: "pointer", fontFamily: "var(--font-mono)",
          borderRadius: 3,
        }}><I.ArrowUR size={10} /> 跳转</button>
      </div>
      {/* 三角 */}
      <span style={{
        position: "absolute",
        ...(flip ? { top: -5 } : { bottom: -5 }),
        ...(edge === "right" ? { right: 24 } : edge === "left" ? { left: 24 } : { left: "50%", marginLeft: -5 }),
        width: 0, height: 0,
        borderLeft: "5px solid transparent",
        borderRight: "5px solid transparent",
        ...(flip ? { borderBottom: "5px solid var(--line)" } : { borderTop: "5px solid var(--line)" }),
      }} />
      <span style={{
        position: "absolute",
        ...(flip ? { top: -4 } : { bottom: -4 }),
        ...(edge === "right" ? { right: 25 } : edge === "left" ? { left: 25 } : { left: "50%", marginLeft: -4 }),
        width: 0, height: 0,
        borderLeft: "4px solid transparent",
        borderRight: "4px solid transparent",
        ...(flip ? { borderBottom: "4px solid var(--card)" } : { borderTop: "4px solid var(--card)" }),
      }} />
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
        <span>悬浮 [[wikilink]] — 420px tooltip,collision-aware,CJK 1.7 行高</span>
      </header>

      <section style={{ flex: 1, padding: "32px 64px", overflow: "auto", background: "var(--bg)", position: "relative" }}>
        <div className="kn-md" style={{ maxWidth: 720, margin: "0 auto", position: "relative" }}>
          <h1>检索增强生成(中文版)</h1>
          <p style={{ color: "var(--ink-soft)", fontSize: 14 }}>
            基于 vault 内 RAG 工程笔记的中文整理。
          </p>

          {/* hover scenario A — 默认上方居中 */}
          <h2>RRF 融合的工程实践</h2>
          <p style={{ position: "relative" }}>
            两路结果用 RRF 融合,具体细节见 <span style={{
              color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)",
              cursor: "pointer", position: "relative",
              background: "var(--accent-tint)", padding: "0 2px", borderRadius: 2,
            }}>
              [[RAG 检索策略#BM25 与向量的权重]]
              <Tooltip flip={false} edge="center" />
            </span>。这里只复述结论:不要相加,要 RRF。
          </p>

          {/* annotation */}
          <div style={{
            position: "absolute",
            top: 268, right: -50,
            maxWidth: 180,
            fontSize: 10.5, color: "var(--ink-mute)",
            fontFamily: "var(--font-mono)",
            lineHeight: 1.45,
          }}>
            <span style={{ color: "var(--accent-2)" }}>● </span>
            420px 宽,默认在链上方居中。鼠标移到 tooltip 内不消失。
          </div>

          <h2>失败模式</h2>
          <p>
            BM25 在中文上对短查询(2-4 字)友好,这是 trigram 编码的特点。具体实测见{" "}
            <span style={{
              color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)",
              cursor: "pointer", padding: "0 2px",
            }}>[[FTS5 trigram 调优]]</span>{" "}
            和{" "}
            <span style={{
              color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)",
              cursor: "pointer", padding: "0 2px",
            }}>[[向量召回的边缘 case]]</span>。
          </p>

          {/* hover scenario B — 边缘碰撞 → 锚右对齐 */}
          <h2 style={{ marginTop: 40 }}>边缘场景</h2>
          <p style={{ position: "relative", textAlign: "right" }}>
            另一份 note 在右侧贴边时:
            {" "}
            <span style={{
              color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)",
              cursor: "pointer", position: "relative",
              background: "var(--accent-tint)", padding: "0 2px", borderRadius: 2,
            }}>
              [[Cormack k=60]]
              <Tooltip flip={false} edge="right" />
            </span>
          </p>
          <div style={{
            position: "absolute",
            top: 535, right: -50,
            maxWidth: 180,
            fontSize: 10.5, color: "var(--ink-mute)",
            fontFamily: "var(--font-mono)",
            lineHeight: 1.45,
          }}>
            <span style={{ color: "var(--accent-2)" }}>● </span>
            链贴右,tooltip 右对齐;不溢出 viewport。
          </div>
        </div>
      </section>
    </div>
  );
};

window.QuoteTooltipScreen = QuoteTooltipScreen;
