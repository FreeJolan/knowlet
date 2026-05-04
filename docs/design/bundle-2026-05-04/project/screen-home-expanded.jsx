// Knowlet — Screen 1b: Home with AI panel expanded (~360px)
// Same three-column shell as HomeScreen, right rail expanded into a full assistant panel.

const HomeExpandedScreen = () => {
  return (
    <div className="kn kn-paper" style={{ width: 1440, height: 900, display: "flex", flexDirection: "column", borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)" }}>
      {/* HEADER */}
      <header style={{
        height: 40, padding: "0 14px",
        display: "flex", alignItems: "center", gap: 12,
        background: "var(--panel)", borderBottom: "1px solid var(--line)",
      }}>
        <span style={{ display: "inline-flex", alignItems: "center", gap: 7 }}>
          <span className="serif" style={{ fontSize: 14.5, fontWeight: 600, color: "var(--accent-2)", letterSpacing: "-0.01em" }}>knowlet</span>
        </span>
        <span className="mono" style={{ fontSize: 11, color: "var(--ink-mute)" }}>
          vault: <span style={{ color: "var(--ink-soft)" }}>knowlet-real</span>
          <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>·</span>
          model: <span style={{ color: "var(--ink-soft)" }}>claude-opus-4-7</span>
          <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>·</span>
          <span style={{ color: "var(--ink-soft)" }}>zh</span>
        </span>
        <span style={{ flex: 1 }} />
        <button style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          height: 26, padding: "0 10px",
          fontSize: 11.5, color: "var(--ink-soft)",
          background: "transparent",
          border: "1px solid var(--line)", borderRadius: 5,
          cursor: "pointer",
        }}>
          <I.Search size={12} stroke={1.7} />
          <span>跳转 / 命令 / ask AI</span>
          <span className="kn-kbd">⌘K</span>
        </button>
        <button className="kn-icon-btn" title="设置"><I.Cog /></button>
      </header>

      {/* MAIN — 3 columns, right one expanded */}
      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "240px 1fr 360px", minHeight: 0 }}>

        {/* LEFT — vault tree */}
        <aside style={{ background: "var(--panel)", borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column", minHeight: 0 }}>
          <div style={{ padding: "8px 8px", display: "flex", alignItems: "center", gap: 6, borderBottom: "1px solid var(--line-soft)" }}>
            <div className="kn-input">
              <I.Search size={11} style={{ color: "var(--ink-mute)" }} />
              <input placeholder="搜索 Note 名…" defaultValue="" />
            </div>
            <button className="kn-icon-btn" title="新建 Note  ⌘N" style={{ width: 26, height: 26, border: "1px solid var(--line)" }}>
              <I.Plus size={13} />
            </button>
          </div>
          <div style={{ padding: "6px 4px", overflow: "auto", flex: 1 }}>
            <TreeFolder name="AI papers" />
            <TreeNote name="Attention paper notes" depth={1} />
            <TreeNote name="RAG 检索策略" depth={1} active />
            <TreeNote name="检索增强生成(中文版)" depth={1} />
            <TreeFolder name="TOEFL" />
            <TreeNote name="writing 独立 vs 综合" depth={1} />
            <TreeNote name="speaking task 1 模板" depth={1} />
            <TreeFolder name="Reading" open={false} />
            <TreeNote name="Personal energy" depth={0} />
            <TreeNote name="Balcony garden plan" depth={0} />
            <TreeNote name="Books · 2026 reading" depth={0} />
            <div style={{ height: 8 }} />
          </div>
        </aside>

        {/* CENTER — note */}
        <section style={{ background: "var(--bg)", display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div style={{
            display: "flex", alignItems: "center",
            height: 32,
            background: "var(--panel)",
            borderBottom: "1px solid var(--line)",
          }}>
            <div className="kn-tab">
              <I.Doc size={11} style={{ color: "var(--ink-mute)" }} />
              <span>Attention paper notes</span>
              <I.X size={11} className="x" />
            </div>
            <div className="kn-tab active">
              <I.Doc size={11} style={{ color: "var(--accent-2)" }} />
              <span>RAG 检索策略</span>
              <I.X size={11} className="x" />
            </div>
            <span style={{ flex: 1 }} />
            <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)", padding: "0 12px" }}>
              notes/AI papers/RAG 检索策略.md
              <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>·</span>
              <span>1,247 字</span>
            </span>
          </div>

          <div style={{ flex: 1, overflow: "auto", padding: "32px 56px 40px" }}>
            <div className="kn-md" style={{ maxWidth: 680, margin: "0 auto" }}>
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
              <p>
                <strong>不要把分数相加</strong> —— 两路分数尺度完全不同。等权 RRF 比手调权重稳;<code>k≈60</code> 是
                Cormack 等人在 TREC 上的经验值,不是玄学。
              </p>
              <pre><code>{`def rrf(rankings, k=60):
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])`}</code></pre>

              <h2>中文 FTS5 trigram 表现</h2>
              <p>
                短查询(2–4 字)表现尚可;长查询稍弱。建议跟向量通路并用,不依赖单路。
              </p>
            </div>
          </div>

          <div style={{
            display: "flex", alignItems: "center", gap: 4,
            height: 28, padding: "0 8px",
            background: "var(--panel)", borderTop: "1px solid var(--line)",
            fontSize: 11.5,
          }}>
            <button style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 8px", borderRadius: 4, background: "transparent", border: 0, color: "var(--ink-soft)", cursor: "pointer", fontSize: 11.5 }}>
              <I.Edit size={11} /> 编辑
            </button>
            <button style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 8px", borderRadius: 4, background: "transparent", border: 0, color: "var(--ink-soft)", cursor: "pointer", fontSize: 11.5 }}>
              <I.Columns size={11} /> 双栏
            </button>
            <button style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 8px", borderRadius: 4, background: "var(--accent-soft)", border: 0, color: "var(--accent-2)", cursor: "pointer", fontSize: 11.5 }}>
              <I.Eye size={11} /> 预览
            </button>
            <span style={{ flex: 1 }} />
            <span className="mono" style={{ color: "var(--ink-mute)", fontSize: 10.5 }}>已保存 · UTF-8 · LF</span>
          </div>
        </section>

        {/* RIGHT — AI panel expanded */}
        <aside style={{
          background: "var(--panel)", borderLeft: "1px solid var(--line)",
          display: "flex", flexDirection: "column", minHeight: 0,
        }}>
          {/* sub-tabs */}
          <div style={{
            display: "flex", alignItems: "center",
            height: 32, padding: "0 6px", gap: 2,
            borderBottom: "1px solid var(--line)",
          }}>
            <button style={{ display: "inline-flex", alignItems: "center", gap: 5, height: 24, padding: "0 9px", borderRadius: 4, background: "transparent", border: 0, color: "var(--ink-soft)", cursor: "pointer", fontSize: 11.5 }}>
              <I.List size={11} /> 大纲
            </button>
            <button style={{ display: "inline-flex", alignItems: "center", gap: 5, height: 24, padding: "0 9px", borderRadius: 4, background: "transparent", border: 0, color: "var(--ink-soft)", cursor: "pointer", fontSize: 11.5 }}>
              <I.Link size={11} /> 反链 <span className="mono" style={{ fontSize: 10, color: "var(--ink-mute)" }}>4</span>
            </button>
            <button style={{ display: "inline-flex", alignItems: "center", gap: 5, height: 24, padding: "0 9px", borderRadius: 4, background: "var(--accent-soft)", border: 0, color: "var(--accent-2)", cursor: "pointer", fontSize: 11.5, fontWeight: 550 }}>
              <I.Sparkles size={11} /> AI
            </button>
            <span style={{ flex: 1 }} />
            <button className="kn-icon-btn" style={{ width: 24, height: 24 }} title="新对话"><I.Plus size={12} /></button>
            <button className="kn-icon-btn" style={{ width: 24, height: 24 }} title="折叠右栏">
              <I.ChevronR size={12} stroke={2} />
            </button>
          </div>

          {/* context selector */}
          <div style={{
            padding: "8px 12px",
            display: "flex", alignItems: "center", gap: 6,
            borderBottom: "1px solid var(--line-soft)",
            fontSize: 11.5,
          }}>
            <span style={{ color: "var(--ink-mute)" }}>上下文</span>
            <button style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              height: 22, padding: "0 8px",
              background: "var(--bg)", border: "1px solid var(--line)", borderRadius: 4,
              color: "var(--ink)", fontSize: 11.5, cursor: "pointer",
            }}>
              <I.Doc size={10.5} style={{ color: "var(--accent-2)" }} />
              <span>当前 Note</span>
              <I.ChevronD size={10} style={{ color: "var(--ink-mute)" }} />
            </button>
            <span className="mono" style={{ color: "var(--ink-faint)", fontSize: 10.5 }}>+2 已选</span>
          </div>

          {/* conversation */}
          <div style={{ flex: 1, overflow: "auto", padding: "12px 14px 6px", display: "flex", flexDirection: "column", gap: 12 }}>

            {/* user msg */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end" }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--ink-faint)" }}>你 · 09:42</span>
              <div style={{
                maxWidth: "88%",
                background: "var(--accent-tint-2)",
                border: "1px solid rgba(91,122,156,0.22)",
                borderRadius: "10px 10px 2px 10px",
                padding: "8px 11px",
                fontSize: 13, lineHeight: 1.55,
                color: "var(--ink)",
              }}>
                RRF 中 k 的典型值是多少?为什么是这个?
              </div>
            </div>

            {/* assistant msg */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--ink-faint)" }}>
                <I.Sparkles size={9} style={{ color: "var(--accent)" }} /> claude · 09:42 · <span style={{ color: "var(--accent-2)" }}>1.2s · 312 tok</span>
              </span>
              <div style={{
                maxWidth: "92%",
                background: "var(--card)",
                border: "1px solid var(--line-soft)",
                borderRadius: "10px 10px 10px 2px",
                padding: "10px 12px",
                fontSize: 13, lineHeight: 1.65,
                color: "var(--ink)",
              }}>
                典型值是 <code style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, background: "var(--panel-2)", padding: "1px 5px", borderRadius: 3, color: "var(--accent-2)" }}>k=60</code>,来自 Cormack 等人 2009 年在 TREC 上的实证 <sup style={{ color: "var(--accent)", fontSize: 10 }}>[1]</sup>。
                <div style={{ height: 8 }} />
                直觉是 <strong>缓冲长尾</strong> —— k 越大,排名靠后的文档贡献的分数越接近,等价于把 top-k 的"硬截断"软化。k 太小时第 1 名权重过大;k 太大时不同 ranker 的差异被抹平。
                <div style={{ height: 8 }} />
                这个 Note 里 <span style={{ color: "var(--accent-2)" }}>RRF 实现已用 k=60</span><sup style={{ color: "var(--accent)", fontSize: 10 }}>[2]</sup>,跟主流一致;不需要调。
              </div>

              {/* sources */}
              <div style={{
                marginTop: 4, padding: "8px 10px",
                background: "var(--bg)",
                border: "1px solid var(--line-soft)",
                borderRadius: 6,
                fontSize: 11, color: "var(--ink-soft)",
                width: "92%",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--ink-mute)", fontSize: 10.5, marginBottom: 5 }}>
                  <I.Link size={10} /> <span className="mono">引用 · 2</span>
                </div>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 6, padding: "3px 0" }}>
                  <span className="mono" style={{ color: "var(--accent)", fontSize: 10, marginTop: 1 }}>[1]</span>
                  <span style={{ flex: 1 }}>
                    <span style={{ color: "var(--accent-2)" }}>检索增强生成(中文版)</span>
                    <span className="mono" style={{ color: "var(--ink-mute)", fontSize: 10, marginLeft: 5 }}>§ RRF 来源</span>
                  </span>
                </div>
                <div style={{ display: "flex", alignItems: "flex-start", gap: 6, padding: "3px 0" }}>
                  <span className="mono" style={{ color: "var(--accent)", fontSize: 10, marginTop: 1 }}>[2]</span>
                  <span style={{ flex: 1 }}>
                    <span style={{ color: "var(--accent-2)" }}>RAG 检索策略</span>
                    <span className="mono" style={{ color: "var(--ink-mute)", fontSize: 10, marginLeft: 5 }}>§ BM25 与向量的权重</span>
                  </span>
                </div>
              </div>

              {/* msg actions */}
              <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
                <button className="kn-icon-btn" style={{ width: 22, height: 22, color: "var(--ink-mute)" }} title="复制">
                  <I.Copy size={11} />
                </button>
                <button className="kn-icon-btn" style={{ width: 22, height: 22, color: "var(--ink-mute)" }} title="作为新 Note">
                  <I.NewNote size={11} />
                </button>
                <button className="kn-icon-btn" style={{ width: 22, height: 22, color: "var(--ink-mute)" }} title="重新生成">
                  <I.Refresh size={11} />
                </button>
              </div>
            </div>

            {/* user follow-up */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-end" }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--ink-faint)" }}>你 · 09:43</span>
              <div style={{
                maxWidth: "88%",
                background: "var(--accent-tint-2)",
                border: "1px solid rgba(91,122,156,0.22)",
                borderRadius: "10px 10px 2px 10px",
                padding: "8px 11px",
                fontSize: 13, lineHeight: 1.55,
                color: "var(--ink)",
              }}>
                能基于这个,生成一张抽认卡吗?
              </div>
            </div>

            <div style={{ display: "flex", flexDirection: "column", gap: 4, alignItems: "flex-start" }}>
              <span className="mono" style={{ fontSize: 10, color: "var(--ink-faint)" }}>
                <I.Sparkles size={9} style={{ color: "var(--accent)" }} /> claude · 正在生成…
              </span>
              <div style={{
                background: "var(--card)",
                border: "1px dashed var(--line)",
                borderRadius: 8,
                padding: "8px 11px",
                fontSize: 12, color: "var(--ink-soft)",
                display: "inline-flex", alignItems: "center", gap: 8,
              }}>
                <span style={{ display: "inline-flex", gap: 3 }}>
                  <span style={{ width: 4, height: 4, borderRadius: 2, background: "var(--accent)", opacity: 0.9 }} />
                  <span style={{ width: 4, height: 4, borderRadius: 2, background: "var(--accent)", opacity: 0.6 }} />
                  <span style={{ width: 4, height: 4, borderRadius: 2, background: "var(--accent)", opacity: 0.3 }} />
                </span>
                调用 <span className="mono" style={{ color: "var(--accent-2)" }}>generate_card</span> tool…
              </div>
            </div>
          </div>

          {/* composer */}
          <div style={{
            padding: "8px 10px 10px",
            borderTop: "1px solid var(--line)",
          }}>
            <div style={{
              background: "var(--bg)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              padding: "8px 10px",
              display: "flex", flexDirection: "column", gap: 6,
            }}>
              <div style={{
                fontSize: 12.5, color: "var(--ink-mute)",
                minHeight: 38, lineHeight: 1.5,
              }}>
                继续追问,或 / 调用工具…
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <button className="kn-icon-btn" style={{ width: 22, height: 22 }} title="附加 Note · @"><I.At size={11} /></button>
                <button className="kn-icon-btn" style={{ width: 22, height: 22 }} title="工具 · /"><I.Slash size={11} /></button>
                <span style={{ flex: 1 }} />
                <span className="mono" style={{ fontSize: 10, color: "var(--ink-faint)" }}>⏎ 发送 · ⇧⏎ 换行</span>
              </div>
            </div>
          </div>
        </aside>
      </div>

      {/* STATUS BAR */}
      <footer style={{
        height: 30, padding: "0 12px",
        display: "flex", alignItems: "center", gap: 4,
        background: "var(--panel)", borderTop: "1px solid var(--line)",
        fontSize: 11.5,
      }}>
        <button className="kn-status-btn" title="⌘⇧D 草稿审查">
          <I.Inbox size={12} style={{ color: "var(--ink-soft)" }} />
          <span className="lbl">草稿</span>
          <span className="num" style={{ color: "var(--warn)", background: "rgba(164,122,58,0.10)" }}>9+</span>
        </button>
        <button className="kn-status-btn" title="⌘⇧R 卡片复习">
          <I.Cards size={12} style={{ color: "var(--ink-soft)" }} />
          <span className="lbl">卡片</span>
          <span className="num" style={{ color: "var(--good)" }}>3</span>
        </button>
        <div className="kn-status-btn" style={{ cursor: "default" }}>
          <I.Mining size={12} style={{ color: "var(--ink-soft)" }} />
          <span className="lbl">挖掘</span>
          <span style={{ color: "var(--accent-2)" }}>HF blog daily</span>
          <span style={{ color: "var(--ink-mute)" }}>· 下次 09:00</span>
        </div>
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ color: "var(--ink-mute)", fontSize: 10.5 }}>v0.0.1 · zh</span>
      </footer>
    </div>
  );
};

window.HomeExpandedScreen = HomeExpandedScreen;
