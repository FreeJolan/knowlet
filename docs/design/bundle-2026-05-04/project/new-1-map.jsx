// New Surface 1 — Knowledge map (focus mode, Cmd+Shift+M)
// 设计判断:
// - 4 个 signal 横向 4 列:near-dup pairs / clusters / orphans / aging
// - 每列独立滚动
// - 没有动作按钮 — 每条只是"点击 → 在新 tab 打开 Note A,split-view 显示 Note B"
// - 没有 dashboard 卡片堆积感 — list-density,每条占一行

const KnowledgeMapScreen = () => {
  const Col = ({ icon, title, count, hint, children }) => (
    <div style={{
      flex: 1, minWidth: 0,
      display: "flex", flexDirection: "column",
      borderRight: "1px solid var(--line)",
    }}>
      <div style={{
        padding: "14px 18px 10px",
        borderBottom: "1px solid var(--line)",
        background: "var(--panel-2)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span style={{
            width: 24, height: 24, borderRadius: 4,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            background: "var(--bg-1)", color: "var(--ink-soft)",
          }}>{icon}</span>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--ink)" }}>{title}</span>
          <span style={{ flex: 1 }} />
          <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>{count}</span>
        </div>
        <div style={{ fontSize: 10.5, color: "var(--ink-mute)", lineHeight: 1.5, fontFamily: "var(--font-mono)" }}>
          {hint}
        </div>
      </div>
      <div style={{ flex: 1, overflow: "auto", padding: "4px 0" }}>
        {children}
      </div>
    </div>
  );

  const Row = ({ children, sub }) => (
    <div style={{
      padding: "10px 18px",
      borderBottom: "1px solid var(--line-soft)",
      cursor: "pointer",
      fontSize: 12.5,
      color: "var(--ink)",
      lineHeight: 1.55,
    }}>
      {children}
      {sub && (
        <div style={{
          fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
          marginTop: 4,
        }}>{sub}</div>
      )}
    </div>
  );

  const Score = ({ v, type }) => {
    const c = type === "warn" ? "var(--warn)" : type === "good" ? "var(--good)" : "var(--accent)";
    return (
      <span style={{
        display: "inline-block", width: 32,
        textAlign: "right",
        fontFamily: "var(--font-mono)", fontSize: 10.5,
        color: c,
      }}>{v}</span>
    );
  };

  return (
    <div className="kn kn-paper" style={{
      width: 1440, height: 880,
      display: "flex", flexDirection: "column",
      borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
    }}>
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
          <I.Map size={11} /> 知识图 · 信号面板
        </span>
        <span className="serif" style={{ fontSize: 14, color: "var(--ink)", fontWeight: 500 }}>
          四种待审视的结构
        </span>
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>
          上次更新 09:31 · 23 notes 全扫
        </span>
        <button className="kn-btn ghost" style={{ height: 26, fontSize: 11 }}>
          <I.Refresh size={11} /> 重新扫描
        </button>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>⌘⇧M</span>
        <button className="kn-icon-btn" title="退出"><I.X /></button>
      </header>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        <Col
          icon={<I.NearDup size={13} />}
          title="近重复对"
          count="3 对"
          hint="cosine ≥ 0.86 — 可能写了同一件事两次"
        >
          <Row sub="两条,L24 / L18 · 距 0.91">
            <span style={{ color: "var(--accent-2)" }}>RAG 检索策略</span>
            <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>↔</span>
            <span style={{ color: "var(--accent-2)" }}>检索增强生成(中文版)</span>
            <Score v="0.91" type="warn" />
          </Row>
          <Row sub="两条,头段几乎相同 · 距 0.88">
            <span style={{ color: "var(--accent-2)" }}>Personal energy</span>
            <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>↔</span>
            <span style={{ color: "var(--accent-2)" }}>下午精力管理</span>
            <Score v="0.88" type="warn" />
          </Row>
          <Row sub="同一书的两次笔记 · 距 0.86">
            <span style={{ color: "var(--accent-2)" }}>"How to Read a Book" 摘</span>
            <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>↔</span>
            <span style={{ color: "var(--accent-2)" }}>读书三层级</span>
            <Score v="0.86" />
          </Row>
        </Col>

        <Col
          icon={<I.Cluster size={13} />}
          title="语义聚类"
          count="5 簇"
          hint="HDBSCAN min_cluster=3 — 看哪些主题在长出来"
        >
          <Row sub="6 条 · 中心 = RAG 检索策略">
            <span style={{ fontWeight: 500 }}>检索 / 索引 / FTS</span>
            <span style={{ color: "var(--ink-mute)", marginLeft: 8 }}>· 含 6 条</span>
          </Row>
          <Row sub="4 条 · 中心 = 注意力机制">
            <span style={{ fontWeight: 500 }}>Transformer 内部</span>
            <span style={{ color: "var(--ink-mute)", marginLeft: 8 }}>· 含 4 条</span>
          </Row>
          <Row sub="3 条 · 都是 reading 类">
            <span style={{ fontWeight: 500 }}>读书方法</span>
            <span style={{ color: "var(--ink-mute)", marginLeft: 8 }}>· 含 3 条</span>
          </Row>
          <Row sub="3 条 · TOEFL writing/speaking">
            <span style={{ fontWeight: 500 }}>TOEFL 备考</span>
            <span style={{ color: "var(--ink-mute)", marginLeft: 8 }}>· 含 3 条</span>
          </Row>
          <Row sub="3 条 · 节奏 / 精力">
            <span style={{ fontWeight: 500 }}>个人能量</span>
            <span style={{ color: "var(--ink-mute)", marginLeft: 8 }}>· 含 3 条</span>
          </Row>
        </Col>

        <Col
          icon={<I.Orphan size={13} />}
          title="孤立 note"
          count="4 条"
          hint="0 个反链且不属任何簇 — 容易被忘掉"
        >
          <Row sub="creating 8 天前 · 0 链入 0 链出">
            <span style={{ color: "var(--accent-2)" }}>Balcony garden plan</span>
          </Row>
          <Row sub="creating 12 天前 · 0 链入 0 链出">
            <span style={{ color: "var(--accent-2)" }}>Books · 2026 reading</span>
          </Row>
          <Row sub="creating 21 天前 · 0 链入 0 链出">
            <span style={{ color: "var(--accent-2)" }}>春耕日历</span>
          </Row>
          <Row sub="creating 35 天前 · 0 链入 0 链出">
            <span style={{ color: "var(--accent-2)" }}>家用网络的 router 选型</span>
          </Row>
        </Col>

        <Col
          icon={<I.Aging size={13} />}
          title="老旧未访问"
          count="6 条"
          hint="≥ 60 天未打开 + 包含外链 — 可能过期"
        >
          <Row sub="92 天未访问 · 含 3 条外链 (paper)">
            <span style={{ color: "var(--accent-2)" }}>2024 RAG papers 整理</span>
            <Score v="92d" />
          </Row>
          <Row sub="78 天未访问 · 含 1 条外链">
            <span style={{ color: "var(--accent-2)" }}>jieba vs hanlp 对比</span>
            <Score v="78d" />
          </Row>
          <Row sub="73 天未访问">
            <span style={{ color: "var(--accent-2)" }}>SQLite FTS4 旧笔记</span>
            <Score v="73d" />
          </Row>
          <Row sub="68 天未访问">
            <span style={{ color: "var(--accent-2)" }}>Whisper.cpp 部署</span>
            <Score v="68d" />
          </Row>
          <Row sub="64 天未访问">
            <span style={{ color: "var(--accent-2)" }}>Streamlit 替代方案</span>
            <Score v="64d" />
          </Row>
          <Row sub="61 天未访问">
            <span style={{ color: "var(--accent-2)" }}>Postgres extensions 调研</span>
            <Score v="61d" />
          </Row>
        </Col>
      </div>

      <footer style={{
        height: 36, padding: "0 18px",
        display: "flex", alignItems: "center", gap: 14,
        background: "var(--panel)", borderTop: "1px solid var(--line)",
        fontSize: 11, color: "var(--ink-mute)",
      }}>
        <span><strong style={{ color: "var(--ink)" }}>提示</strong>:这里只<em>呈现</em>结构,不下结论。</span>
        <span style={{ color: "var(--ink-faint)" }}>·</span>
        <span>点击任意条目 → split-view 打开,你判断要不要合并 / 删除 / 加链。</span>
        <span style={{ flex: 1 }} />
        <button className="kn-btn ghost" style={{ height: 24, fontSize: 11 }}>导出 JSON</button>
      </footer>
    </div>
  );
};

window.KnowledgeMapScreen = KnowledgeMapScreen;
