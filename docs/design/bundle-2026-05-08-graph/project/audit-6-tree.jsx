// Audit Surface 6 — Recursive folder tree (240px, depth ≥ 3 不卡)
// 设计判断:
// - depth × 12px (从 14 缩到 12)
// - 每级 1px 竖向 guide line(像 GitHub web)
// - root sticky 到 tree 顶部,折叠态滚动时仍可见
// - hover 整行高亮,active = accent-soft 整行
// - chevron 在最左,12px hit (实际 hit 区域 = 整行)

const RecursiveTreeScreen = () => {
  // Row primitive — 用 padding-left + ::before guide
  const Row = ({ depth, children, active, isFolder, open, sticky, soft }) => (
    <div style={{
      display: "flex", alignItems: "center", gap: 0,
      height: 26,
      paddingLeft: 8,
      borderRadius: 4,
      cursor: "pointer",
      position: sticky ? "sticky" : "static",
      top: sticky ? 0 : "auto",
      zIndex: sticky ? 2 : 0,
      background: sticky ? "var(--panel)" : (active ? "var(--accent-soft)" : "transparent"),
      color: active ? "var(--accent-2)" : (soft ? "var(--ink-soft)" : "var(--ink)"),
      fontSize: 12.5,
      borderBottom: sticky ? "1px solid var(--line)" : "none",
    }}>
      {/* indent guides */}
      {Array.from({ length: depth }).map((_, i) => (
        <span key={i} style={{
          width: 12, height: 26, flexShrink: 0,
          position: "relative",
        }}>
          <span style={{
            position: "absolute",
            left: 5, top: 0, bottom: 0,
            width: 1,
            background: "var(--line-soft)",
          }} />
        </span>
      ))}
      {/* chevron / spacer */}
      {isFolder ? (
        open ? <I.ChevronD size={11} style={{ color: "var(--ink-mute)", flexShrink: 0 }} /> : <I.ChevronR size={11} style={{ color: "var(--ink-mute)", flexShrink: 0 }} />
      ) : (
        <span style={{ width: 11, flexShrink: 0 }} />
      )}
      <span style={{ marginLeft: 4, marginRight: 6, flexShrink: 0, color: active ? "var(--accent-2)" : "var(--ink-mute)" }}>
        {isFolder ? (open ? <I.FolderOpen size={13} /> : <I.Folder size={13} />) : <I.Doc size={13} />}
      </span>
      <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {children}
      </span>
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
        <span>左栏 — 递归 vault 树,depth × 12px,guide line + sticky root</span>
      </header>

      <div style={{ flex: 1, display: "grid", gridTemplateColumns: "240px 1fr", minHeight: 0 }}>
        <aside style={{
          background: "var(--panel)", borderRight: "1px solid var(--line)",
          display: "flex", flexDirection: "column", minHeight: 0,
        }}>
          {/* search + new */}
          <div style={{ padding: "8px 8px", display: "flex", alignItems: "center", gap: 6, borderBottom: "1px solid var(--line-soft)" }}>
            <div className="kn-input">
              <I.Search size={11} style={{ color: "var(--ink-mute)" }} />
              <input placeholder="搜索 Note 名…" defaultValue="" />
            </div>
            <button className="kn-icon-btn" title="新建 Note  ⌘N" style={{ width: 26, height: 26, border: "1px solid var(--line)" }}>
              <I.Plus size={13} />
            </button>
          </div>

          <div style={{ padding: "4px 4px", overflow: "auto", flex: 1 }}>
            {/* sticky root — AI papers 是当前 active 子树的祖先 */}
            <Row depth={0} isFolder open sticky>AI papers</Row>
            <Row depth={1} isFolder open>Transformers</Row>
            <Row depth={2} isFolder open>2024 papers</Row>
            <Row depth={3}>Attention is all you need (再读)</Row>
            <Row depth={3}>RoPE 笔记</Row>
            <Row depth={3} isFolder>FlashAttention</Row>
            <Row depth={2} isFolder>2025 papers</Row>
            <Row depth={1} isFolder open>RAG</Row>
            <Row depth={2}>RAG 检索策略</Row>
            <Row depth={2} active>检索增强生成(中文版)</Row>
            <Row depth={2}>FTS5 trigram 调优</Row>
            <Row depth={2}>向量召回的边缘 case</Row>
            <Row depth={2}>Cormack k=60</Row>
            <Row depth={1} isFolder>LLM serving</Row>
            <Row depth={1} isFolder>Evaluation</Row>

            <Row depth={0} isFolder>TOEFL</Row>
            <Row depth={0} isFolder open>Reading</Row>
            <Row depth={1} isFolder>2026-Q1</Row>
            <Row depth={1} isFolder open>2026-Q2</Row>
            <Row depth={2}>"Designing Data-Intensive…"</Row>
            <Row depth={2}>"How to Read a Book"</Row>
            <Row depth={2}>"思考,快与慢"</Row>

            <Row depth={0}>Personal energy</Row>
            <Row depth={0}>Balcony garden plan</Row>
            <Row depth={0}>Books · 2026 reading</Row>

            <div style={{ height: 8 }} />
          </div>

          {/* footer status */}
          <div style={{
            padding: "6px 10px",
            borderTop: "1px solid var(--line-soft)",
            fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <span>23 notes · 7 folders</span>
          </div>
        </aside>

        {/* annotation panel */}
        <section style={{ background: "var(--bg)", padding: "32px 40px", overflow: "auto" }}>
          <div style={{ maxWidth: 640 }}>
            <h2 className="serif" style={{ fontSize: 18, fontWeight: 600, color: "var(--ink)", marginTop: 0, marginBottom: 14, letterSpacing: "-0.008em" }}>
              递归树:240px 不够,设计上靠 guide + sticky 解决
            </h2>
            <div style={{ fontSize: 13, color: "var(--ink-soft)", lineHeight: 1.7 }}>
              <p>
                每级 <span className="mono" style={{ color: "var(--ink)" }}>12px</span>(从原方案 14px 缩 2px),
                折扣换 6 级深度仍能在 240px 里舒服展示。
              </p>
              <p>
                竖向 <strong style={{ color: "var(--ink)" }}>guide line</strong>:每级一条 1px <span className="mono">var(--line-soft)</span>,
                像 GitHub web 的文件树。视线追踪同级从上到下,代价是每级一条线。
              </p>
              <p>
                <strong style={{ color: "var(--ink)" }}>Sticky root</strong>:当前活跃子树的根行 sticky 到 tree 顶,
                深处滚动时仍知"我在 AI papers 里"。多层 sticky 不堆叠 —— 只 root,过多 sticky 会变成新层级,反而更糊。
              </p>
              <p>
                <strong style={{ color: "var(--ink)" }}>没做的</strong>:面包屑(M5 主题)、虚拟滚动(性能不卡前不上)、
                拖拽(拖到树里很容易误 drop,定 keyboard / 右键移动)。
              </p>

              <h3 className="serif" style={{ fontSize: 14, fontWeight: 600, marginTop: 24, marginBottom: 10 }}>
                还要解决的
              </h3>
              <ul style={{ paddingLeft: 18, color: "var(--ink-soft)" }}>
                <li>非常长 note 名:<span className="mono" style={{ fontSize: 11.5 }}>text-overflow: ellipsis</span> + hover 显示完整名
                  (现在 truncate 但还没浮窗)。</li>
                <li>Note 数 &gt; 200 时,FilesController 同步开销;改用增量重渲。</li>
                <li>当前 active note 自动滚到视区(开 vault 时 / 跳转后)。</li>
              </ul>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
};

window.RecursiveTreeScreen = RecursiveTreeScreen;
