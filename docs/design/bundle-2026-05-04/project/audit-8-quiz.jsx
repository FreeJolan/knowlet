// Audit Surface 8 — Quiz focus mode (4 phases)
// Cmd+Shift+Q
//
// 设计判断:
// - Phase 1 Scope:两步 — 先选 source 类型 (单 Note/多 Note/tag(灰)/cluster(灰)),再 search-then-pick
// - Phase 2 Loop:每页一题,左题右"参考来源"split
// - Phase 3 Summary:per-question 评分卡,disagree = 一键 inline textarea(不必填)
// - Phase 4 History:列表 + 只读查看

const QuizFrame = ({ phase, total, label, children, footerLeft, footerRight }) => (
  <div className="kn kn-paper" style={{
    width: 1280, height: 820,
    display: "flex", flexDirection: "column",
    borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
    position: "relative",
  }}>
    {/* focus header */}
    <header style={{
      height: 44, padding: "0 18px",
      display: "flex", alignItems: "center", gap: 12,
      background: "var(--panel)", borderBottom: "1px solid var(--line)",
    }}>
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 6,
        height: 24, padding: "0 9px",
        background: "var(--accent-soft)", color: "var(--accent-2)",
        borderRadius: 4, fontSize: 11, fontWeight: 500,
      }}>
        <I.Question size={11} /> 卡片 · 主动复习
      </span>
      <span className="serif" style={{ fontSize: 14, color: "var(--ink)", fontWeight: 500 }}>
        {label}
      </span>
      <span style={{ flex: 1 }} />
      {/* phase pips */}
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        {["范围", "答题", "评分", "记录"].map((p, i) => (
          <span key={i} style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            fontSize: 11, color: i + 1 === phase ? "var(--ink)" : "var(--ink-mute)",
            fontWeight: i + 1 === phase ? 500 : 400,
          }}>
            <span style={{
              width: 16, height: 16, borderRadius: 8,
              background: i + 1 < phase ? "var(--accent)" : i + 1 === phase ? "var(--accent-soft)" : "transparent",
              border: i + 1 === phase ? "1px solid var(--accent)" : i + 1 < phase ? "1px solid var(--accent)" : "1px solid var(--line)",
              color: i + 1 < phase ? "#faf7f0" : "var(--ink-mute)",
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              fontSize: 9, fontFamily: "var(--font-mono)",
            }}>
              {i + 1 < phase ? <I.CheckSm size={9} stroke={2.4} /> : i + 1}
            </span>
            {p}
            {i < 3 && <span style={{ width: 14, height: 1, background: i + 1 < phase ? "var(--accent)" : "var(--line)", marginLeft: 4 }} />}
          </span>
        ))}
      </div>
      <span style={{ flex: 1 }} />
      <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>⌘⇧Q</span>
      <button className="kn-icon-btn" title="退出"><I.X /></button>
    </header>

    {/* body */}
    <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      {children}
    </div>

    {/* footer */}
    <footer style={{
      height: 44, padding: "0 18px",
      display: "flex", alignItems: "center", gap: 10,
      background: "var(--panel)", borderTop: "1px solid var(--line)",
      fontSize: 12, color: "var(--ink-soft)",
    }}>
      <span>{footerLeft}</span>
      <span style={{ flex: 1 }} />
      {footerRight}
    </footer>
  </div>
);

// ============= Phase 1: Scope picker =============
const QuizScopeScreen = () => (
  <QuizFrame
    phase={1}
    label="选范围"
    footerLeft={<span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>⌫ 取消 · ↵ 下一步</span>}
    footerRight={
      <>
        <button className="kn-btn" style={{ height: 30 }}>取消</button>
        <button className="kn-btn primary" style={{ height: 30 }}>开始 · 5 题 <I.ArrowRight size={11} /></button>
      </>
    }
  >
    <div style={{ flex: 1, padding: "32px 0", overflow: "auto", background: "var(--bg)" }}>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "0 24px" }}>
        {/* Step 1 — source type */}
        <div style={{
          fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
          marginBottom: 8,
        }}>STEP 1 / 2</div>
        <h2 className="serif" style={{ fontSize: 22, fontWeight: 600, color: "var(--ink)", margin: "0 0 16px", letterSpacing: "-0.012em" }}>
          从哪里出题?
        </h2>
        <div style={{
          display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10,
          marginBottom: 32,
        }}>
          {[
            { id: "single", label: "单个 Note", desc: "覆盖范围最小,适合细读后回测", active: true },
            { id: "multi", label: "多个 Note", desc: "选 2-10 个,跨主题串联", active: false },
            { id: "tag", label: "按 tag", desc: "需 vault 有 tag 系统", soon: "M7.4.3" },
            { id: "cluster", label: "按 cluster", desc: "向量聚类自动选近邻", soon: "M7.4.3" },
          ].map((opt) => (
            <button key={opt.id} disabled={!!opt.soon} style={{
              display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 4,
              padding: "12px 14px",
              background: opt.active ? "var(--accent-soft)" : "var(--card)",
              border: opt.active ? "1px solid var(--accent)" : "1px solid var(--line)",
              borderRadius: 6,
              textAlign: "left",
              cursor: opt.soon ? "not-allowed" : "pointer",
              opacity: opt.soon ? 0.5 : 1,
              color: "var(--ink)",
              fontSize: 13,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, width: "100%" }}>
                <span style={{ fontWeight: 500, color: opt.active ? "var(--accent-2)" : "var(--ink)" }}>{opt.label}</span>
                {opt.soon && <span className="mono" style={{
                  fontSize: 9.5, color: "var(--ink-mute)",
                  border: "1px solid var(--line)", borderRadius: 3,
                  padding: "0 5px", letterSpacing: 0.5,
                }}>{opt.soon}</span>}
                {opt.active && <span style={{ flex: 1 }} />}
                {opt.active && <I.CheckSm size={13} style={{ color: "var(--accent-2)" }} stroke={2.4} />}
              </div>
              <div style={{ fontSize: 11.5, color: "var(--ink-soft)" }}>{opt.desc}</div>
            </button>
          ))}
        </div>

        {/* Step 2 — search then pick */}
        <div style={{
          fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
          marginBottom: 8,
        }}>STEP 2 / 2</div>
        <h2 className="serif" style={{ fontSize: 22, fontWeight: 600, color: "var(--ink)", margin: "0 0 12px", letterSpacing: "-0.012em" }}>
          挑哪一个 Note?
        </h2>

        <div style={{
          display: "flex", alignItems: "center", gap: 8,
          padding: "8px 12px",
          background: "var(--card)",
          border: "1px solid var(--accent)",
          borderRadius: 6,
          marginBottom: 14,
        }}>
          <I.Search size={13} style={{ color: "var(--ink-mute)" }} />
          <span style={{ fontSize: 13, color: "var(--ink)" }}>RAG</span>
          <span style={{
            display: "inline-block", width: 1.5, height: 14,
            background: "var(--accent)", animation: "kn-blink 1s steps(1) infinite",
          }} />
          <span style={{ flex: 1 }} />
          <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>3 hits</span>
        </div>

        {/* search results */}
        <div style={{ background: "var(--card)", border: "1px solid var(--line)", borderRadius: 6, overflow: "hidden" }}>
          {[
            { name: "RAG 检索策略", path: "AI papers/", words: "1,247 字", match: "RAG", picked: true },
            { name: "检索增强生成(中文版)", path: "AI papers/", words: "892 字", match: "RAG" },
            { name: "RAG eval — Ragas 笔记", path: "AI papers/Evaluation/", words: "440 字", match: "RAG" },
          ].map((r, i) => (
            <div key={i} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "10px 14px",
              borderTop: i ? "1px solid var(--line-soft)" : "none",
              background: r.picked ? "var(--accent-soft)" : "transparent",
              cursor: "pointer",
            }}>
              <span style={{
                width: 16, height: 16, borderRadius: 4,
                border: r.picked ? "1px solid var(--accent)" : "1px solid var(--line)",
                background: r.picked ? "var(--accent)" : "transparent",
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                color: "#faf7f0",
                flexShrink: 0,
              }}>
                {r.picked && <I.CheckSm size={11} stroke={2.6} />}
              </span>
              <I.Doc size={13} style={{ color: "var(--ink-mute)", flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, color: "var(--ink)" }}>
                  {r.name}
                </div>
                <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>
                  {r.path} · {r.words}
                </div>
              </div>
              <span style={{
                fontSize: 10.5, color: "var(--accent-2)", fontFamily: "var(--font-mono)",
                background: "var(--accent-tint)", padding: "1px 6px", borderRadius: 3,
              }}>
                匹配 “RAG”
              </span>
            </div>
          ))}
        </div>

        {/* options */}
        <div style={{
          marginTop: 24, padding: "12px 14px",
          background: "var(--bg-1)", borderRadius: 6,
          display: "flex", alignItems: "center", gap: 16,
          fontSize: 12, color: "var(--ink-soft)",
        }}>
          <span>题数</span>
          <div style={{ display: "flex", gap: 4 }}>
            {[3, 5, 8, 10].map((n) => (
              <button key={n} style={{
                width: 32, height: 26, borderRadius: 4,
                fontSize: 12,
                background: n === 5 ? "var(--accent)" : "transparent",
                color: n === 5 ? "#faf7f0" : "var(--ink)",
                border: "1px solid",
                borderColor: n === 5 ? "var(--accent)" : "var(--line)",
                cursor: "pointer",
                fontFamily: "var(--font-mono)",
              }}>{n}</button>
            ))}
          </div>
          <span style={{ color: "var(--ink-faint)" }}>·</span>
          <span style={{ color: "var(--ink-mute)", fontSize: 11.5 }}>
            难度由模型按 note 内容自适应
          </span>
        </div>
      </div>
    </div>
    <style>{`@keyframes kn-blink { 50% { opacity: 0; } }`}</style>
  </QuizFrame>
);

window.QuizScopeScreen = QuizScopeScreen;

// ============= Phase 2: Loop =============
const QuizLoopScreen = () => (
  <QuizFrame
    phase={2}
    label="第 3 题 / 共 5 题 — RAG 检索策略"
    footerLeft={<span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>⌘↵ 提交答案 · ⌘→ 跳过</span>}
    footerRight={
      <>
        <button className="kn-btn" style={{ height: 30 }}>跳过</button>
        <button className="kn-btn primary" style={{ height: 30 }}>提交 · 第 3 题 <I.ArrowRight size={11} /></button>
      </>
    }
  >
    {/* progress strip */}
    <div style={{
      height: 4, background: "var(--bg-1)", position: "relative", flexShrink: 0,
    }}>
      <div style={{ width: "40%", height: "100%", background: "var(--accent)" }} />
    </div>

    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "1fr 1fr", minHeight: 0 }}>
      {/* LEFT — question + answer */}
      <div style={{ padding: "32px 32px", overflow: "auto", background: "var(--bg)" }}>
        <div style={{
          fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
          marginBottom: 10, display: "flex", alignItems: "center", gap: 6,
        }}>
          <I.Question size={10} /> Q3 · 简答 · 来自 RAG 检索策略 §3
        </div>
        <h2 className="serif" style={{
          fontSize: 22, fontWeight: 600, color: "var(--ink)",
          margin: "0 0 24px", letterSpacing: "-0.008em", lineHeight: 1.4,
        }}>
          为什么 RRF 用<code style={{
            fontFamily: "var(--font-mono)", fontSize: 19, padding: "0 6px",
            background: "var(--panel-2)", borderRadius: 3, color: "var(--accent-2)",
          }}>k≈60</code> 而不是直接相加 BM25 与向量分数?
        </h2>

        <textarea defaultValue={`两路的分数尺度不同 —— BM25 是 TF-IDF 量级,可以到几十;向量 cosine 在 [0,1]。直接加,BM25 永远碾压向量。

RRF 把两路都转 rank,再用 1/(k+r) 求和,k=60 是 Cormack 在 TREC 上的经验值,对 rank 1-10 的差距比较平,后面拉得开。

总之:不是为了"准",是为了"两路尺度可比"。`} style={{
          width: "100%",
          minHeight: 240,
          padding: "12px 14px",
          background: "var(--card)",
          border: "1px solid var(--line)",
          borderRadius: 6,
          fontFamily: "var(--font-serif)",
          fontSize: 14,
          lineHeight: 1.7,
          color: "var(--ink)",
          resize: "vertical",
          outline: "none",
        }} />

        <div style={{
          display: "flex", alignItems: "center", gap: 12,
          marginTop: 10,
          fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
        }}>
          <span>134 字 · 写于 1m 12s</span>
          <span style={{ color: "var(--ink-faint)" }}>·</span>
          <button style={{
            background: "transparent", border: 0, color: "var(--ink-soft)", cursor: "pointer",
            fontSize: 10.5, fontFamily: "var(--font-mono)", padding: 0,
          }}>清空</button>
        </div>
      </div>

      {/* RIGHT — source split */}
      <div style={{
        padding: "0",
        borderLeft: "1px solid var(--line)",
        background: "var(--panel)",
        display: "flex", flexDirection: "column",
      }}>
        <div style={{
          height: 32, padding: "0 16px",
          display: "flex", alignItems: "center", gap: 8,
          borderBottom: "1px solid var(--line-soft)",
          background: "var(--panel-2)",
          fontSize: 11, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
        }}>
          <I.Doc size={11} />
          <span style={{ color: "var(--accent-2)" }}>RAG 检索策略.md</span>
          <span style={{ color: "var(--ink-faint)" }}>· 出题来源(可读,不可编辑)</span>
        </div>
        <div style={{ flex: 1, padding: "24px 28px", overflow: "auto" }}>
          <div className="kn-md" style={{ maxWidth: 540 }}>
            <h2 style={{
              background: "var(--accent-tint)",
              padding: "1px 4px",
              borderRadius: 2,
              borderLeft: "3px solid var(--accent)",
            }}>BM25 与向量的权重</h2>
            <p style={{ background: "var(--accent-tint)", padding: "2px 4px", borderRadius: 2 }}>
              <strong>不要把分数相加</strong> —— 两路分数尺度完全不同。等权 RRF 比手调权重稳;<code>k≈60</code> 是
              Cormack 等人在 TREC 上的经验值,不是玄学。
            </p>
            <pre style={{ opacity: 0.7 }}><code>{`def rrf(rankings, k=60):
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] += 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])`}</code></pre>
            <p style={{ opacity: 0.6 }}>
              短查询(2–4 字)表现尚可;长查询稍弱。建议跟向量通路并用,不依赖单路。
            </p>
          </div>
        </div>
        <div style={{
          padding: "8px 16px",
          borderTop: "1px solid var(--line-soft)",
          fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <I.Lightning size={10} style={{ color: "var(--accent)" }} />
          <span>高亮段落 = 模型生成此题的依据</span>
        </div>
      </div>
    </div>
  </QuizFrame>
);

window.QuizLoopScreen = QuizLoopScreen;

// ============= Phase 3: Summary =============
const QuizSummaryScreen = () => {
  const QCard = ({ idx, q, ans, score, scoreLabel, scoreColor, disagreement, expanded }) => (
    <div style={{
      background: "var(--card)",
      border: "1px solid var(--line)",
      borderRadius: 6,
      overflow: "hidden",
    }}>
      <div style={{
        padding: "10px 14px",
        display: "flex", alignItems: "flex-start", gap: 12,
        borderBottom: "1px solid var(--line-soft)",
      }}>
        <div style={{
          width: 22, height: 22, borderRadius: 11,
          background: scoreColor,
          color: "#faf7f0",
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          fontSize: 11, fontFamily: "var(--font-mono)", fontWeight: 600,
          flexShrink: 0, marginTop: 1,
        }}>
          {idx}
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13, color: "var(--ink)", fontWeight: 500 }}>{q}</div>
          <div style={{
            fontSize: 11.5, color: "var(--ink-soft)",
            marginTop: 4, fontFamily: "var(--font-serif)", lineHeight: 1.6,
            display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
            overflow: "hidden",
          }}>{ans}</div>
        </div>
        <div style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          padding: "2px 8px", borderRadius: 11, fontSize: 11, fontWeight: 500,
          background: scoreColor === "var(--good)" ? "rgba(94,135,87,0.12)" : scoreColor === "var(--warn)" ? "rgba(164,122,58,0.12)" : "rgba(184,85,77,0.12)",
          color: scoreColor,
          flexShrink: 0,
        }}>
          <span className="mono">{score}</span> · {scoreLabel}
        </div>
      </div>
      {/* feedback row */}
      <div style={{
        padding: "8px 14px",
        display: "flex", alignItems: "center", gap: 8,
        fontSize: 11.5, color: "var(--ink-soft)",
        background: disagreement ? "var(--bg-1)" : "transparent",
      }}>
        <I.Lightning size={10} style={{ color: scoreColor }} />
        <span style={{ flex: 1 }}>
          {disagreement
            ? <span><strong style={{ color: "var(--ink)" }}>你已标“不同意”:</strong>{disagreement}</span>
            : "AI 评:" + (scoreLabel === "正确" ? "覆盖关键点 (尺度差异 + RRF 转 rank);可加深 k=60 的 TREC 来源" : scoreLabel === "部分" ? "缺少 RRF 公式形式 1/(k+r)" : "把“两路分数”理解反了")}
        </span>
        {!disagreement && (
          <button style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "2px 8px", borderRadius: 3,
            background: "transparent", border: "1px solid var(--line)",
            color: "var(--ink-soft)", fontSize: 11, cursor: "pointer",
          }}>
            <I.X size={10} /> 不同意
          </button>
        )}
      </div>
      {/* expanded textarea */}
      {expanded && (
        <div style={{
          padding: "8px 14px 12px",
          borderTop: "1px solid var(--line-soft)",
          background: "var(--bg-1)",
        }}>
          <textarea placeholder="为什么不同意?(可空,提交后保留作为后续上下文 / 可作为重测起点)"
            style={{
              width: "100%", minHeight: 56,
              padding: "8px 10px",
              background: "var(--card)",
              border: "1px solid var(--line)",
              borderRadius: 4,
              fontFamily: "var(--font-sans)",
              fontSize: 12,
              color: "var(--ink)",
              resize: "vertical",
              outline: "none",
            }} />
          <div style={{ display: "flex", gap: 6, marginTop: 6, justifyContent: "flex-end" }}>
            <button className="kn-btn" style={{ height: 24, fontSize: 11 }}>取消</button>
            <button className="kn-btn primary" style={{ height: 24, fontSize: 11 }}>保留 · 改判</button>
          </div>
        </div>
      )}
    </div>
  );

  const Pill = ({ label, color }) => (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "2px 8px", borderRadius: 11, fontSize: 11,
      background: `${color}1a`, color: color, fontWeight: 500,
    }}>{label}</span>
  );

  return (
    <QuizFrame
      phase={3}
      label="本轮评分 — RAG 检索策略 · 5 题"
      footerLeft={<span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>已存入历史 · ⌘⇧Q 重新开始</span>}
      footerRight={
        <>
          <button className="kn-btn" style={{ height: 30 }}>查看 note</button>
          <button className="kn-btn" style={{ height: 30 }}>同范围再来一轮</button>
          <button className="kn-btn primary" style={{ height: 30 }}>关闭</button>
        </>
      }
    >
      <div style={{ flex: 1, padding: "24px 0", overflow: "auto", background: "var(--bg)" }}>
        <div style={{ maxWidth: 800, margin: "0 auto", padding: "0 24px" }}>
          {/* score header */}
          <div style={{
            display: "flex", alignItems: "center", gap: 16,
            padding: "16px 20px",
            background: "var(--card)",
            border: "1px solid var(--line)",
            borderRadius: 8,
            marginBottom: 18,
          }}>
            <div style={{
              width: 56, height: 56, borderRadius: 28,
              background: "conic-gradient(var(--good) 0 72%, var(--bg-1) 72% 100%)",
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0,
            }}>
              <span style={{
                width: 44, height: 44, borderRadius: 22, background: "var(--card)",
                display: "inline-flex", alignItems: "center", justifyContent: "center",
                fontFamily: "var(--font-mono)", fontWeight: 600, color: "var(--ink)",
                fontSize: 14,
              }}>72%</span>
            </div>
            <div style={{ flex: 1 }}>
              <div className="serif" style={{ fontSize: 18, fontWeight: 600, color: "var(--ink)", marginBottom: 4 }}>
                3 全对 · 1 部分 · 1 错 · 1 已标"不同意"
              </div>
              <div style={{ fontSize: 12, color: "var(--ink-soft)" }}>
                耗时 7m 32s · 难度自适应 · 共 5 题
              </div>
            </div>
            <div style={{ display: "flex", gap: 6 }}>
              <Pill label="3 正确" color="var(--good)" />
              <Pill label="1 部分" color="var(--warn)" />
              <Pill label="1 错" color="var(--danger)" />
            </div>
          </div>

          {/* per-question cards */}
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <QCard idx={1} q="BM25 处理什么类型的 query 比向量好?" ans="精确字符串、函数名、错误码、人名,这类没有近义词的硬匹配。" score="100" scoreLabel="正确" scoreColor="var(--good)" />
            <QCard idx={2} q="为什么 trigram FTS 在中文上仍可用?" ans="中文不分词的情况下,trigram 把『信息检索』切成『信息』、『息检』、『检索』三段,短查询召回稳定。" score="100" scoreLabel="正确" scoreColor="var(--good)" />
            <QCard idx={3} q="为什么 RRF 用 k≈60 而不是直接相加 BM25 与向量分数?" ans="两路尺度不同;RRF 转 rank 后才可比。k=60 是 Cormack 在 TREC 的经验值。" score="80" scoreLabel="部分" scoreColor="var(--warn)" />
            <QCard idx={4} q="cross-encoder re-rank 的延迟预算是多少?" ans="200ms p50,超出就该牺牲精度。" score="100" scoreLabel="正确" scoreColor="var(--good)" />
            <QCard idx={5} q="向量召回失败的典型边缘 case?" ans="同义词/近义词被切到不同子向量空间;短查询语义模糊。"
              score="40" scoreLabel="错" scoreColor="var(--danger)"
              disagreement="向量召回的边缘是 OOV / 域外术语,不是子空间问题。"
              expanded
            />
          </div>
        </div>
      </div>
    </QuizFrame>
  );
};

window.QuizSummaryScreen = QuizSummaryScreen;

// ============= Phase 4: History =============
const QuizHistoryScreen = () => (
  <QuizFrame
    phase={4}
    label="复习记录"
    footerLeft={<span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>↑↓ 选择 · ↵ 查看 · ⌫ 关闭</span>}
    footerRight={
      <>
        <button className="kn-btn" style={{ height: 30 }}>导出</button>
        <button className="kn-btn primary" style={{ height: 30 }}>开新一轮 · ⌘⇧Q</button>
      </>
    }
  >
    <div style={{ flex: 1, display: "grid", gridTemplateColumns: "320px 1fr", minHeight: 0 }}>
      {/* list */}
      <aside style={{ background: "var(--panel)", borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column", minHeight: 0 }}>
        <div style={{
          padding: "10px 12px",
          borderBottom: "1px solid var(--line)",
          fontSize: 11, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <I.History size={11} /> 12 轮 · 最近 30 天
        </div>
        <div style={{ flex: 1, overflow: "auto" }}>
          {[
            { active: true, when: "今天 09:42", note: "RAG 检索策略", score: 72, n: 5, time: "7m" },
            { when: "昨天 21:15", note: "RAG 检索策略", score: 60, n: 5, time: "9m" },
            { when: "5月 1日", note: "RAG 检索策略", score: 40, n: 3, time: "4m" },
            { when: "4月 28日", note: "Attention paper notes", score: 80, n: 5, time: "6m" },
            { when: "4月 25日", note: "FTS5 trigram 调优", score: 100, n: 3, time: "3m" },
            { when: "4月 22日", note: "TOEFL writing 独立 vs 综合", score: 60, n: 5, time: "8m" },
            { when: "4月 20日", note: "Personal energy", score: 80, n: 3, time: "4m" },
          ].map((row, i) => {
            const c = row.score >= 80 ? "var(--good)" : row.score >= 60 ? "var(--warn)" : "var(--danger)";
            return (
              <div key={i} style={{
                padding: "10px 12px",
                borderBottom: "1px solid var(--line-soft)",
                display: "flex", alignItems: "center", gap: 10,
                background: row.active ? "var(--accent-soft)" : "transparent",
                cursor: "pointer",
              }}>
                <span style={{
                  width: 6, height: 6, borderRadius: 3, background: c, flexShrink: 0,
                }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, color: "var(--ink)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {row.note}
                  </div>
                  <div style={{
                    fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
                    marginTop: 2,
                  }}>
                    {row.when} · {row.n} 题 · {row.time}
                  </div>
                </div>
                <span style={{
                  fontSize: 11, fontFamily: "var(--font-mono)", color: c,
                  fontWeight: 600,
                }}>
                  {row.score}%
                </span>
              </div>
            );
          })}
        </div>
      </aside>

      {/* detail (read-only summary view) */}
      <section style={{ background: "var(--bg)", overflow: "auto", padding: "32px 40px" }}>
        <div style={{ maxWidth: 640 }}>
          <div style={{
            fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
            marginBottom: 6,
          }}>READ-ONLY · 不可改判</div>
          <h2 className="serif" style={{ fontSize: 22, fontWeight: 600, color: "var(--ink)", margin: "0 0 6px", letterSpacing: "-0.012em" }}>
            RAG 检索策略 — 5 题
          </h2>
          <div style={{ fontSize: 12, color: "var(--ink-soft)", marginBottom: 24, fontFamily: "var(--font-mono)" }}>
            今天 09:42 · 7m 32s · 72%
          </div>

          {/* trend strip */}
          <div style={{
            background: "var(--card)", border: "1px solid var(--line)",
            borderRadius: 6, padding: "12px 14px", marginBottom: 20,
          }}>
            <div style={{ fontSize: 11.5, color: "var(--ink-soft)", marginBottom: 8 }}>
              这个 note 的复习趋势 — 共 3 轮
            </div>
            <div style={{ display: "flex", alignItems: "flex-end", gap: 16, height: 48 }}>
              {[40, 60, 72].map((s, i) => {
                const c = s >= 80 ? "var(--good)" : s >= 60 ? "var(--warn)" : "var(--danger)";
                return (
                  <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", flex: 1 }}>
                    <span className="mono" style={{ fontSize: 10, color: c, marginBottom: 2 }}>{s}</span>
                    <div style={{ width: "100%", height: 32, background: "var(--bg-1)", borderRadius: 3, position: "relative" }}>
                      <div style={{
                        position: "absolute", bottom: 0, left: 0, right: 0,
                        height: `${s * 32 / 100}px`,
                        background: c,
                        borderRadius: 3,
                      }} />
                    </div>
                    <span className="mono" style={{ fontSize: 9.5, color: "var(--ink-mute)", marginTop: 4 }}>5/1 · 4/30 · 5/3</span>
                  </div>
                );
              })}
            </div>
          </div>

          <div style={{ fontSize: 11, color: "var(--ink-mute)", fontFamily: "var(--font-mono)", marginBottom: 8 }}>
            题目 (read-only)
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {[
              { n: 1, q: "BM25 处理什么类型的 query 比向量好?", c: "var(--good)" },
              { n: 2, q: "为什么 trigram FTS 在中文上仍可用?", c: "var(--good)" },
              { n: 3, q: "为什么 RRF 用 k≈60 而不是直接相加 BM25 与向量分数?", c: "var(--warn)" },
              { n: 4, q: "cross-encoder re-rank 的延迟预算是多少?", c: "var(--good)" },
              { n: 5, q: "向量召回失败的典型边缘 case?", c: "var(--danger)", note: "已标不同意" },
            ].map((row) => (
              <div key={row.n} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "8px 12px",
                background: "var(--card)",
                border: "1px solid var(--line-soft)",
                borderRadius: 4,
                fontSize: 12.5,
              }}>
                <span style={{
                  width: 18, height: 18, borderRadius: 9,
                  background: row.c, color: "#faf7f0",
                  fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 600,
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  flexShrink: 0,
                }}>{row.n}</span>
                <span style={{ flex: 1, color: "var(--ink)" }}>{row.q}</span>
                {row.note && <span className="mono" style={{ fontSize: 10, color: "var(--danger)" }}>· {row.note}</span>}
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  </QuizFrame>
);

window.QuizHistoryScreen = QuizHistoryScreen;
