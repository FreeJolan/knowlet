// New Surface 2 — Weekly digest (reading view, NYT/Stratechery feel)
// 设计判断:
// - 全屏阅读体验 — Source Serif 4 标题 + 大段 prose
// - 信号串成 narrative,不是 dashboard 卡片堆
// - 没有 read/unread state — 每次打开就是"这一期"
// - 底部 cadence 一行 inline 设置

const DigestScreen = () => (
  <div className="kn kn-paper" style={{
    width: 1440, height: 920,
    display: "flex", flexDirection: "column",
    borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
  }}>
    {/* slim top bar */}
    <header style={{
      height: 40, padding: "0 28px",
      display: "flex", alignItems: "center", gap: 12,
      background: "var(--bg)",
      borderBottom: "1px solid var(--line-soft)",
    }}>
      <span className="serif" style={{ fontSize: 13.5, fontWeight: 600, color: "var(--accent-2)", letterSpacing: "-0.01em" }}>
        knowlet
      </span>
      <span style={{ width: 1, height: 14, background: "var(--line)" }} />
      <span style={{ fontSize: 11.5, color: "var(--ink-soft)" }}>本周回顾</span>
      <span style={{ flex: 1 }} />
      <button className="kn-btn ghost" style={{ height: 26, fontSize: 11 }}>← 上一期</button>
      <button className="kn-btn ghost" style={{ height: 26, fontSize: 11 }}>导出 PDF</button>
    </header>

    <div style={{ flex: 1, overflow: "auto", background: "var(--bg)" }}>
      <article style={{ maxWidth: 720, margin: "0 auto", padding: "56px 32px 80px" }}>
        {/* date / issue */}
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          fontSize: 11, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
          marginBottom: 18,
        }}>
          <I.Calendar size={11} />
          <span>第 14 期 · 2026 / W17 · 4月27 → 5月3</span>
          <span style={{ color: "var(--ink-faint)" }}>·</span>
          <span>23 notes · 7 modified · 2 created</span>
        </div>

        {/* title */}
        <h1 style={{
          fontFamily: "var(--font-serif)",
          fontSize: 48, fontWeight: 600,
          letterSpacing: "-0.022em",
          lineHeight: 1.12,
          color: "var(--ink)",
          margin: "0 0 14px",
        }}>
          这一周,你在 RAG 上花了最多时间。
        </h1>
        <div className="serif" style={{
          fontSize: 18, color: "var(--ink-soft)",
          lineHeight: 1.5,
          margin: "0 0 40px",
          fontStyle: "italic",
          letterSpacing: "-0.005em",
        }}>
          顺带把"读书方法"这个簇又往前推了两条。Balcony garden 还是没人理它。
        </div>

        {/* prose — 信号串成叙事 */}
        <div className="serif" style={{
          fontFamily: "var(--font-serif)",
          fontSize: 17,
          lineHeight: 1.75,
          color: "var(--ink)",
          letterSpacing: "-0.005em",
        }}>
          <p style={{ margin: "0 0 18px" }}>
            <strong>检索 / 索引 / FTS</strong> 这个簇本周新进了 2 条 ——
            <a style={{ color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)" }}>《FTS5 trigram 调优》</a>
            和{" "}
            <a style={{ color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)" }}>《Cormack k=60》</a>
            ,都直接挂到{" "}
            <a style={{ color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)" }}>《RAG 检索策略》</a>{" "}
            上,后者本周被 4 条新反链命中。这是 vault 中目前增长最快的局部结构。
          </p>

          <p style={{ margin: "0 0 18px" }}>
            可能值得注意的是,《RAG 检索策略》和《检索增强生成(中文版)》cosine = <span className="mono" style={{
              fontFamily: "var(--font-mono)", fontSize: 14, color: "var(--warn)",
              background: "rgba(164,122,58,0.10)", padding: "1px 6px", borderRadius: 3,
            }}>0.91</span>{" "}
            —— 接近重写。开 split-view 对比看一眼,有没有合并的必要?
          </p>

          <h2 style={{
            fontFamily: "var(--font-serif)",
            fontSize: 26, fontWeight: 600,
            letterSpacing: "-0.014em",
            margin: "44px 0 14px",
            color: "var(--ink)",
          }}>
            两个老朋友安静着
          </h2>
          <p style={{ margin: "0 0 18px" }}>
            《Balcony garden plan》和《Books · 2026 reading》本周都没被打开。前者已经 8 天,后者 12 天。
            它们都是孤立 note —— 0 链入 0 链出。要不要把"读书方法"簇里那几条和 Books 串一下?
          </p>

          <h2 style={{
            fontFamily: "var(--font-serif)",
            fontSize: 26, fontWeight: 600,
            letterSpacing: "-0.014em",
            margin: "44px 0 14px",
            color: "var(--ink)",
          }}>
            一处明显空白
          </h2>
          <p style={{ margin: "0 0 18px" }}>
            你在 RAG 笔记里 4 次提到 cross-encoder re-rank,但 vault 里没有以"re-rank"或"cross-encoder"为题的 note。
            这是空白还是故意省略?如果是前者,值得一篇。
          </p>

          <h2 style={{
            fontFamily: "var(--font-serif)",
            fontSize: 26, fontWeight: 600,
            letterSpacing: "-0.014em",
            margin: "44px 0 14px",
            color: "var(--ink)",
          }}>
            复习状态
          </h2>
          <p style={{ margin: "0 0 18px" }}>
            本周开了 3 轮卡片复习,全部围绕 RAG。第一轮 40%,第三轮 72% —— 在<em>同一个 note 上</em>提分。
            这是工程师的训练曲线,不是终点。下次试试跨 note 串题,看看你是不是真懂了这个簇。
          </p>

          <hr style={{ border: 0, borderTop: "1px solid var(--line)", margin: "44px 0 28px" }} />

          {/* signal grid — minimal, list-like */}
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 28,
            fontFamily: "var(--font-sans)",
            fontSize: 13,
            color: "var(--ink-soft)",
            lineHeight: 1.55,
          }}>
            {[
              { label: "本周修改", v: "7", sub: "23 notes 中" },
              { label: "新建", v: "2", sub: "RAG / FTS5" },
              { label: "新反链", v: "12", sub: "+ 主要在 RAG 簇" },
              { label: "近重复对", v: "3", sub: "≥ 0.86 cosine" },
              { label: "孤立", v: "4", sub: "+1 vs 上周" },
              { label: "≥ 60 天未访问", v: "6", sub: "本周 -1" },
            ].map((s) => (
              <div key={s.label} style={{ paddingTop: 12, borderTop: "1px solid var(--line-soft)" }}>
                <div style={{
                  fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
                  letterSpacing: 0.3, marginBottom: 4,
                }}>{s.label.toUpperCase()}</div>
                <div className="serif" style={{
                  fontSize: 32, fontWeight: 600, color: "var(--ink)",
                  letterSpacing: "-0.018em", lineHeight: 1,
                }}>{s.v}</div>
                <div style={{ fontSize: 11, color: "var(--ink-mute)", marginTop: 4 }}>{s.sub}</div>
              </div>
            ))}
          </div>
        </div>
      </article>
    </div>

    {/* cadence — 一行 inline,贴底 */}
    <footer style={{
      padding: "12px 28px",
      borderTop: "1px solid var(--line-soft)",
      background: "var(--bg)",
      display: "flex", alignItems: "center", gap: 14,
      fontSize: 11.5, color: "var(--ink-soft)",
    }}>
      <I.Calendar size={12} style={{ color: "var(--ink-mute)" }} />
      <span>下一期 <strong style={{ color: "var(--ink)" }}>本周日 09:00</strong></span>
      <span style={{ color: "var(--ink-faint)" }}>·</span>
      <span>每 7 天</span>
      {[
        { label: "7 天", active: true },
        { label: "14 天" },
        { label: "30 天" },
        { label: "自定义" },
      ].map((c) => (
        <button key={c.label} style={{
          height: 22, padding: "0 9px",
          fontSize: 11,
          background: c.active ? "var(--accent-soft)" : "transparent",
          color: c.active ? "var(--accent-2)" : "var(--ink-soft)",
          border: c.active ? "1px solid var(--accent)" : "1px solid var(--line-soft)",
          borderRadius: 3,
          cursor: "pointer",
          fontFamily: "var(--font-mono)",
        }}>
          {c.label}
        </button>
      ))}
      <span style={{ flex: 1 }} />
      <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>
        以前 13 期可在 设置 → 周报 中翻阅
      </span>
    </footer>
  </div>
);

window.DigestScreen = DigestScreen;
