// Graph view — user-authored bilinks
//
// 设计判断:
// - 这是 ground-truth 用户写出来的连接,所以视觉默认就是它,不需要"突出"什么
// - 节点 = circle,半径与 (in+out)_degree 弱相关 — 让"中心 note"自然涌现而非强制 highlight
// - 边 = 1.4px solid --ink-mute,arrow 在 70% 位置(不在 endpoint,避免覆盖目标)
// - LLM-inferred 簇此 view 不画 — 是 M8.2 知识图的工作
// - layout 是 force-directed,这里用 hand-tuned 静态坐标模拟稳定状态
//
// 入口两个,同数据不同 scoping:
// 1. rail-tab → 永远 ego 1-hop,~380px wide,contextual
// 2. focus-mode (⌘⇧G) → <300 节点全图,≥300 默认 ego + "展开整库" 按钮

// ----- Mock data: 一个看起来真实的小型 vault -----
// 24 nodes, ~32 edges,模拟 force-directed 收敛后的位置
const NODES = [
  // RAG cluster (中心)
  { id: "rag",       title: "RAG 检索策略",            folder: "AI papers/",      x: 0,    y: 0,    deg: 11, hot: true },
  { id: "fts",       title: "FTS5 trigram 调优",       folder: "AI papers/",      x: -130, y: -80,  deg: 5 },
  { id: "rrf",       title: "Cormack k=60",            folder: "AI papers/",      x: 130,  y: -90,  deg: 4 },
  { id: "rerank",    title: "cross-encoder re-rank",   folder: "AI papers/",      x: 50,   y: 110,  deg: 3 },
  { id: "rag-cn",    title: "检索增强生成(中文版)",   folder: "AI papers/",      x: -90,  y: 70,   deg: 4 },
  { id: "ragas",     title: "RAG eval — Ragas 笔记",   folder: "AI papers/Eval/", x: 180,  y: 30,   deg: 2 },

  // Reading method cluster
  { id: "read3",     title: "读书三层级",              folder: "reading/",        x: -310, y: -180, deg: 5, hot: true },
  { id: "htrab",     title: "How to Read a Book 摘",   folder: "reading/",        x: -440, y: -120, deg: 3 },
  { id: "scan",      title: "速读 vs 精读",            folder: "reading/",        x: -360, y: -280, deg: 2 },
  { id: "marg",      title: "做笔记的边距体系",        folder: "reading/",        x: -240, y: -260, deg: 2 },

  // Energy cluster
  { id: "energy",    title: "Personal energy",         folder: "self/",           x: 320,  y: 200,  deg: 4, hot: true },
  { id: "afternoon", title: "下午精力管理",            folder: "self/",           x: 380,  y: 290,  deg: 3 },
  { id: "deep",      title: "深度工作 90 分钟节律",    folder: "self/",           x: 440,  y: 150,  deg: 2 },

  // TOEFL
  { id: "toefl",     title: "TOEFL writing 模板",      folder: "lang/",           x: -380, y: 230,  deg: 3 },
  { id: "toefl-sp",  title: "TOEFL speaking 套路",     folder: "lang/",           x: -460, y: 300,  deg: 1 },

  // Bridge / hub-ish
  { id: "trans",     title: "Transformer 内部",        folder: "AI papers/",      x: 100,  y: -210, deg: 3 },
  { id: "atten",     title: "注意力机制",              folder: "AI papers/",      x: 220,  y: -190, deg: 2 },

  // Orphans / weak
  { id: "garden",    title: "Balcony garden plan",     folder: "life/",           x: -100, y: 320,  deg: 0, orphan: true },
  { id: "books26",   title: "Books · 2026 reading",    folder: "reading/",        x: -480, y: 30,   deg: 0, orphan: true },
  { id: "router",    title: "家用网络的 router 选型",  folder: "tech/",           x: 380,  y: -260, deg: 0, orphan: true },
  { id: "spring",    title: "春耕日历",                folder: "life/",           x: 0,    y: 350,  deg: 0, orphan: true },

  // 边缘节点
  { id: "sqlite",    title: "SQLite FTS4 旧笔记",      folder: "tech/",           x: -170, y: 50,   deg: 1 },
  { id: "jieba",     title: "jieba vs hanlp 对比",     folder: "tech/",           x: -240, y: -10,  deg: 2 },
  { id: "whisper",   title: "Whisper.cpp 部署",        folder: "tech/",           x: 280,  y: 100,  deg: 1 },
];

const EDGES = [
  // RAG core
  ["rag", "fts"], ["rag", "rrf"], ["rag", "rerank"], ["rag", "rag-cn"],
  ["rag", "ragas"], ["rag", "trans"], ["rag-cn", "rag"], ["fts", "jieba"],
  ["fts", "sqlite"], ["rrf", "rag"], ["ragas", "rag"], ["rerank", "rag"],
  ["jieba", "fts"], ["sqlite", "fts"],

  // Reading
  ["read3", "htrab"], ["read3", "scan"], ["read3", "marg"], ["htrab", "read3"],
  ["scan", "read3"], ["marg", "read3"],

  // Energy
  ["energy", "afternoon"], ["energy", "deep"], ["afternoon", "energy"], ["deep", "energy"],

  // TOEFL
  ["toefl", "toefl-sp"], ["toefl-sp", "toefl"], ["toefl", "read3"],

  // Trans / atten bridge
  ["trans", "atten"], ["atten", "trans"], ["trans", "rag"],

  // weak
  ["whisper", "rag"],
];

// ----- Helpers -----
const findNode = (id) => NODES.find((n) => n.id === id);
const isEgoOf = (centerId, nodeId, hops = 1) => {
  if (centerId === nodeId) return true;
  const direct = EDGES.some(([s, t]) =>
    (s === centerId && t === nodeId) || (t === centerId && s === nodeId)
  );
  if (direct) return true;
  if (hops >= 2) {
    const neighbors = new Set();
    EDGES.forEach(([s, t]) => {
      if (s === centerId) neighbors.add(t);
      if (t === centerId) neighbors.add(s);
    });
    return [...neighbors].some((n) =>
      EDGES.some(([s, t]) => (s === n && t === nodeId) || (t === n && s === nodeId))
    );
  }
  return false;
};

// Node radius — based on degree
const nodeR = (n) => Math.max(4, Math.min(14, 4 + Math.sqrt(n.deg) * 2.4));

// ----- Tooltip -----
const NodeTooltip = ({ node, x, y, paneW, paneH }) => {
  if (!node) return null;
  const W = 220;
  const H = 78;
  const PAD = 12;
  let left = x + 16;
  let top = y + 12;
  if (left + W > paneW - PAD) left = x - W - 16;
  if (top + H > paneH - PAD) top = y - H - 16;

  const previews = {
    rag: "BM25 + 向量 + RRF 融合;k=60 是 Cormack 经验值",
    "read3": "Adler 的三层:elementary / inspectional / analytical",
    energy: "工程师的下午 14-17 点能量低谷,需要不同策略",
    fts: "Trigram 在中文不分词时仍能稳定召回短查询",
    rrf: "RRF 把 BM25 / 向量 rank 转 1/(k+r) 后相加",
    "rerank": "200ms p50 是 cross-encoder 的延迟预算",
    "rag-cn": "中文 vault 下 jieba / hanlp 选型",
  };
  const preview = previews[node.id] || "(无预览)";

  return (
    <div style={{
      position: "absolute", left, top,
      width: W,
      background: "var(--card)",
      border: "1px solid var(--line)",
      borderRadius: 6,
      padding: "10px 12px",
      boxShadow: "var(--shadow-md)",
      pointerEvents: "none",
      zIndex: 10,
    }}>
      <div className="serif" style={{
        fontSize: 13, fontWeight: 600, color: "var(--ink)",
        marginBottom: 4, letterSpacing: "-0.008em", lineHeight: 1.3,
      }}>
        {node.title}
      </div>
      <div style={{
        fontSize: 11.5, color: "var(--ink-soft)",
        lineHeight: 1.45, marginBottom: 4,
        textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap",
      }}>
        {preview}
      </div>
      <div className="mono" style={{
        fontSize: 10, color: "var(--ink-mute)",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <span>{node.folder}</span>
        <span style={{ color: "var(--ink-faint)" }}>·</span>
        <span>↘ {node.deg}</span>
      </div>
    </div>
  );
};

// ----- The actual SVG canvas -----
const GraphCanvas = ({
  width, height,
  centerId = null,    // ego mode if set
  hops = 1,
  hoveredId = null,
  hoveredXY = null,
  onHover = () => {},
  searchQuery = "",
  selectedIds = [],
  showFolderHint = false,
  zoom = 1,
  panX = 0,
  panY = 0,
}) => {
  // Filter to visible nodes
  let visibleNodes = NODES;
  if (centerId) {
    visibleNodes = NODES.filter((n) => isEgoOf(centerId, n.id, hops));
  }
  const visibleIds = new Set(visibleNodes.map((n) => n.id));
  const visibleEdges = EDGES.filter(([s, t]) => visibleIds.has(s) && visibleIds.has(t));

  // viewbox 中心化
  const xs = visibleNodes.map((n) => n.x);
  const ys = visibleNodes.map((n) => n.y);
  const minX = Math.min(...xs) - 60;
  const maxX = Math.max(...xs) + 60;
  const minY = Math.min(...ys) - 60;
  const maxY = Math.max(...ys) + 60;

  const matchesSearch = (n) => {
    if (!searchQuery) return true;
    return n.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
           n.folder.toLowerCase().includes(searchQuery.toLowerCase());
  };

  const dimmed = (n) => searchQuery && !matchesSearch(n);

  return (
    <svg width={width} height={height}
      viewBox={`${minX} ${minY} ${maxX - minX} ${maxY - minY}`}
      style={{ display: "block", background: "var(--bg)", cursor: "grab" }}
      preserveAspectRatio="xMidYMid meet"
    >
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5"
          markerWidth="5" markerHeight="5" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--ink-mute)" />
        </marker>
        <marker id="arrow-active" viewBox="0 0 10 10" refX="8" refY="5"
          markerWidth="5" markerHeight="5" orient="auto">
          <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--accent-2)" />
        </marker>
        {/* faint dotted bg grid */}
        <pattern id="dotgrid" x="0" y="0" width="32" height="32" patternUnits="userSpaceOnUse">
          <circle cx="16" cy="16" r="0.7" fill="var(--ink-faint)" opacity="0.3" />
        </pattern>
      </defs>

      <rect x={minX} y={minY} width={maxX - minX} height={maxY - minY} fill="url(#dotgrid)" />

      {/* Edges */}
      <g>
        {visibleEdges.map(([s, t], i) => {
          const ns = findNode(s);
          const nt = findNode(t);
          if (!ns || !nt) return null;
          const dx = nt.x - ns.x;
          const dy = nt.y - ns.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          // 70% point for arrow placement (回退节点半径)
          const tx = ns.x + dx * (1 - (nodeR(nt) + 6) / dist);
          const ty = ns.y + dy * (1 - (nodeR(nt) + 6) / dist);
          // 是否高亮:hovered 节点的相邻边
          const involvesHover = hoveredId && (s === hoveredId || t === hoveredId);
          const involvesSelected = selectedIds.includes(s) || selectedIds.includes(t);
          const dim = searchQuery && (dimmed(ns) || dimmed(nt));
          return (
            <line key={i}
              x1={ns.x} y1={ns.y} x2={tx} y2={ty}
              stroke={involvesHover ? "var(--accent-2)" : involvesSelected ? "var(--accent)" : "var(--ink-mute)"}
              strokeWidth={involvesHover ? 1.8 : 1.4}
              opacity={dim ? 0.18 : involvesHover ? 1 : 0.85}
              markerEnd={involvesHover ? "url(#arrow-active)" : "url(#arrow)"}
            />
          );
        })}
      </g>

      {/* Nodes */}
      <g>
        {visibleNodes.map((n) => {
          const r = nodeR(n);
          const isCenter = n.id === centerId;
          const isHover = n.id === hoveredId;
          const isSelected = selectedIds.includes(n.id);
          const dim = dimmed(n);
          // 节点颜色 — 默认 card,center 和 hover 用 accent
          let fill = "var(--card)";
          let stroke = "var(--ink-mute)";
          let strokeWidth = 1.5;
          if (n.orphan) {
            fill = "var(--bg-1)";
            stroke = "var(--ink-faint)";
            strokeWidth = 1;
          }
          if (isHover) {
            fill = "var(--accent)";
            stroke = "var(--accent-2)";
            strokeWidth = 1.8;
          } else if (isCenter) {
            fill = "var(--accent-soft)";
            stroke = "var(--accent)";
            strokeWidth = 2;
          } else if (isSelected) {
            stroke = "var(--accent)";
            strokeWidth = 2.2;
          }
          return (
            <g key={n.id}
              style={{ cursor: "pointer" }}
              onMouseEnter={(e) => onHover(n, e)}
              onMouseLeave={() => onHover(null, null)}
            >
              <circle
                cx={n.x} cy={n.y} r={r}
                fill={fill}
                stroke={stroke}
                strokeWidth={strokeWidth}
                opacity={dim ? 0.2 : 1}
              />
              {/* label — 仅 hot / center / hover 显示 */}
              {(n.hot || isCenter || isHover) && !dim && (
                <text
                  x={n.x} y={n.y - r - 7}
                  textAnchor="middle"
                  fontSize={isCenter || isHover ? 11.5 : 10.5}
                  fontFamily="var(--font-serif)"
                  fontWeight={isCenter || isHover ? 600 : 500}
                  fill="var(--ink)"
                  letterSpacing="-0.005em"
                  style={{ pointerEvents: "none" }}
                >
                  {n.title.length > 16 ? n.title.slice(0, 14) + "…" : n.title}
                </text>
              )}
              {/* search match — 标题始终显示 */}
              {searchQuery && matchesSearch(n) && !n.hot && !isCenter && !isHover && (
                <text
                  x={n.x} y={n.y - r - 6}
                  textAnchor="middle"
                  fontSize={10}
                  fontFamily="var(--font-sans)"
                  fill="var(--accent-2)"
                  style={{ pointerEvents: "none" }}
                >
                  {n.title.length > 18 ? n.title.slice(0, 16) + "…" : n.title}
                </text>
              )}
            </g>
          );
        })}
      </g>

      {/* Folder color hint legend (仅 focus mode 开 toggle 时) */}
      {showFolderHint && (
        <g>
          {visibleNodes.map((n) => (
            <circle key={`fh-${n.id}`}
              cx={n.x + nodeR(n) + 3} cy={n.y - nodeR(n) - 3} r={2}
              fill={folderTint(n.folder)}
              opacity={0.7}
              style={{ pointerEvents: "none" }}
            />
          ))}
        </g>
      )}
    </svg>
  );
};

const folderTint = (folder) => {
  // 不是 cluster coloring,只是 folder hint;低饱和
  if (folder.startsWith("AI papers")) return "#6b8aa8";
  if (folder.startsWith("reading")) return "#8a7548";
  if (folder.startsWith("self")) return "#7a8a6b";
  if (folder.startsWith("lang")) return "#9c6b78";
  if (folder.startsWith("tech")) return "#5e8783";
  return "#a0a0a0";
};

// ============================================================
// FRAME 1 — Rail-tab variant (ego, ~380px)
// ============================================================
const RailTabFrame = () => {
  const [hovered, setHovered] = React.useState(null);
  const [hoveredXY, setHoveredXY] = React.useState(null);

  return (
    <div className="kn kn-paper" style={{
      width: 1280, height: 780,
      display: "flex", flexDirection: "column",
      borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
    }}>
      {/* mini top chrome 让上下文真实一点 */}
      <header style={{
        height: 38, padding: "0 14px",
        display: "flex", alignItems: "center", gap: 10,
        background: "var(--panel)", borderBottom: "1px solid var(--line)",
      }}>
        <span className="serif" style={{
          fontSize: 13, fontWeight: 600, color: "var(--accent-2)",
          letterSpacing: "-0.006em",
        }}>knowlet</span>
        <span style={{ width: 1, height: 14, background: "var(--line)" }} />
        <I.Folder size={11} style={{ color: "var(--ink-mute)" }} />
        <span style={{ fontSize: 11.5, color: "var(--ink-soft)" }}>AI papers / RAG 检索策略.md</span>
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>23 notes</span>
      </header>

      <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
        {/* mini left tree */}
        <aside style={{
          width: 180, background: "var(--panel)",
          borderRight: "1px solid var(--line)",
          padding: "10px 0",
          fontSize: 12, color: "var(--ink-soft)",
        }}>
          {[
            { l: "AI papers/", indent: 0, open: true, soft: true },
            { l: "RAG 检索策略", indent: 1, active: true },
            { l: "FTS5 trigram 调优", indent: 1 },
            { l: "Cormack k=60", indent: 1 },
            { l: "cross-encoder re-rank", indent: 1 },
            { l: "reading/", indent: 0, soft: true },
            { l: "self/", indent: 0, soft: true },
            { l: "lang/", indent: 0, soft: true },
          ].map((r, i) => (
            <div key={i} style={{
              padding: `4px 12px 4px ${12 + r.indent * 14}px`,
              background: r.active ? "var(--accent-soft)" : "transparent",
              color: r.active ? "var(--accent-2)" : r.soft ? "var(--ink-mute)" : "var(--ink)",
              fontFamily: r.soft ? "var(--font-mono)" : "var(--font-sans)",
              fontSize: r.soft ? 11 : 12,
              cursor: "pointer",
              fontWeight: r.active ? 500 : 400,
            }}>{r.l}</div>
          ))}
        </aside>

        {/* center — fake editor */}
        <main style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          <div style={{
            padding: "20px 32px 12px",
            borderBottom: "1px solid var(--line-soft)",
            background: "var(--bg)",
          }}>
            <h1 className="serif" style={{
              fontSize: 22, fontWeight: 600, color: "var(--ink)",
              letterSpacing: "-0.012em", margin: 0,
            }}>RAG 检索策略</h1>
          </div>
          <div style={{
            flex: 1, padding: "16px 32px",
            background: "var(--bg)",
            fontSize: 14, color: "var(--ink)", lineHeight: 1.7,
            overflow: "auto",
          }}>
            <p>检索增强生成的核心问题是召回 vs 精度的折中。在 vault 这种规模下,
            走 <span style={{ color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)" }}>[[FTS5 trigram 调优]]</span>{" "}
            + 向量 + <span style={{ color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)" }}>[[Cormack k=60]]</span> RRF 融合是最稳的组合。</p>
            <p>关于 re-rank,见 <span style={{ color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)" }}>[[cross-encoder re-rank]]</span> —
            预算 200ms p50,超出就该牺牲精度...</p>
            <p style={{ color: "var(--ink-mute)", fontSize: 12.5, fontStyle: "italic", marginTop: 24 }}>
              ⋯⋯ 余下 8 段省略 ⋯⋯
            </p>
          </div>
        </main>

        {/* right rail — Graph tab active */}
        <aside style={{
          width: 380, background: "var(--panel)",
          borderLeft: "1px solid var(--line)",
          display: "flex", flexDirection: "column",
          minHeight: 0,
        }}>
          {/* tab strip */}
          <div style={{
            height: 36, padding: "0 4px",
            display: "flex", alignItems: "stretch", gap: 0,
            borderBottom: "1px solid var(--line)",
            background: "var(--panel-2)",
          }}>
            {[
              { l: "大纲", icon: <I.List size={11} /> },
              { l: "反链", icon: <I.Link size={11} />, count: 4 },
              { l: "Graph", icon: <I.Graph size={11} />, active: true },
              { l: "AI", icon: <I.AI size={11} /> },
            ].map((tab) => (
              <div key={tab.l} style={{
                padding: "0 12px",
                display: "inline-flex", alignItems: "center", gap: 6,
                fontSize: 12,
                color: tab.active ? "var(--ink)" : "var(--ink-soft)",
                background: tab.active ? "var(--card)" : "transparent",
                borderTop: tab.active ? "2px solid var(--accent)" : "2px solid transparent",
                marginTop: tab.active ? -1 : 0,
                fontWeight: tab.active ? 500 : 400,
                cursor: "pointer",
              }}>
                {tab.icon}{tab.l}
                {tab.count && <span className="mono" style={{
                  fontSize: 10, color: "var(--ink-mute)",
                }}>{tab.count}</span>}
              </div>
            ))}
          </div>

          {/* graph header */}
          <div style={{
            padding: "10px 14px 8px",
            borderBottom: "1px solid var(--line-soft)",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <I.Compass size={12} style={{ color: "var(--ink-mute)" }} />
            <span style={{ fontSize: 11.5, color: "var(--ink-soft)" }}>
              <strong style={{ color: "var(--ink)" }}>当前 Note ± 1 跳</strong>
            </span>
            <span style={{ flex: 1 }} />
            <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>7 / 24</span>
            <button className="kn-icon-btn" title="切到 2 跳" style={{ width: 22, height: 22 }}>
              <I.Plus size={11} />
            </button>
          </div>

          {/* the graph */}
          <div style={{
            flex: 1, position: "relative", minHeight: 0,
            background: "var(--bg)",
          }}
            onMouseLeave={() => { setHovered(null); setHoveredXY(null); }}>
            <GraphCanvas
              width={380} height={460}
              centerId="rag"
              hops={1}
              hoveredId={hovered?.id}
              onHover={(n, e) => {
                setHovered(n);
                if (e) {
                  const rect = e.currentTarget.closest("svg").getBoundingClientRect();
                  setHoveredXY({ x: e.clientX - rect.left, y: e.clientY - rect.top });
                }
              }}
            />

            {/* tooltip */}
            {hovered && hoveredXY && (
              <NodeTooltip node={hovered} x={hoveredXY.x} y={hoveredXY.y} paneW={380} paneH={460} />
            )}

            {/* hint chips bottom-left */}
            <div style={{
              position: "absolute", left: 10, bottom: 8,
              display: "flex", gap: 6,
              fontSize: 10, color: "var(--ink-mute)",
              fontFamily: "var(--font-mono)",
            }}>
              <span>scroll = zoom</span>
              <span style={{ color: "var(--ink-faint)" }}>·</span>
              <span>drag = pan</span>
              <span style={{ color: "var(--ink-faint)" }}>·</span>
              <span>⌘⇧G 全屏</span>
            </div>
          </div>

          {/* bottom: linked notes count strip */}
          <div style={{
            padding: "10px 14px",
            borderTop: "1px solid var(--line)",
            background: "var(--panel-2)",
            fontSize: 11, color: "var(--ink-soft)",
            display: "flex", alignItems: "center", gap: 12,
          }}>
            <span><strong className="mono" style={{ color: "var(--ink)" }}>6</strong> 出链</span>
            <span style={{ color: "var(--ink-faint)" }}>·</span>
            <span><strong className="mono" style={{ color: "var(--ink)" }}>4</strong> 入链</span>
            <span style={{ flex: 1 }} />
            <button className="kn-btn ghost" style={{ height: 22, fontSize: 11 }}>
              <I.Expand size={10} /> 全屏
            </button>
          </div>
        </aside>
      </div>
    </div>
  );
};

// ============================================================
// FRAME 2 — Focus mode (Cmd+Shift+G), full vault < 300 nodes
// ============================================================
const FocusFrame = ({ withSearch = false, withSelection = false }) => {
  const [hovered, setHovered] = React.useState(null);
  const [hoveredXY, setHoveredXY] = React.useState(null);

  const selectedIds = withSelection ? ["read3", "htrab", "scan", "marg"] : [];

  return (
    <div className="kn kn-paper" style={{
      width: 1440, height: 900,
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
          <I.Graph size={11} /> Graph · 全 vault
        </span>
        <span className="serif" style={{ fontSize: 14, color: "var(--ink)", fontWeight: 500 }}>
          24 notes · 32 user-authored bilinks
        </span>
        <span style={{ flex: 1 }} />

        {/* search */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: "0 10px",
          height: 28,
          background: "var(--card)",
          border: withSearch ? "1px solid var(--accent)" : "1px solid var(--line)",
          borderRadius: 4,
          width: 220,
        }}>
          <I.Search size={11} style={{ color: "var(--ink-mute)" }} />
          {withSearch ? (
            <>
              <span style={{ fontSize: 12, color: "var(--ink)" }}>read</span>
              <span style={{ display: "inline-block", width: 1.5, height: 12, background: "var(--accent)", animation: "kn-blink 1s steps(1) infinite" }} />
              <span style={{ flex: 1 }} />
              <span className="mono" style={{ fontSize: 10, color: "var(--accent-2)" }}>4 命中</span>
            </>
          ) : (
            <>
              <span style={{ fontSize: 12, color: "var(--ink-mute)" }}>按 / 搜索节点</span>
              <span style={{ flex: 1 }} />
              <span className="kn-kbd" style={{ background: "var(--bg-1)" }}>/</span>
            </>
          )}
        </div>

        {/* tools */}
        <button className="kn-btn ghost" style={{ height: 26, fontSize: 11 }} title="folder hint">
          <I.Tag size={10} /> Folder hint
        </button>
        <button className="kn-btn ghost" style={{ height: 26, fontSize: 11 }} title="重新跑 layout">
          <I.Refresh size={10} /> Re-layout
        </button>
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>⌘⇧G</span>
        <button className="kn-icon-btn" title="退出"><I.X /></button>
      </header>

      <div style={{ flex: 1, display: "flex", minHeight: 0, position: "relative" }}>
        {/* main canvas */}
        <div style={{ flex: 1, position: "relative", background: "var(--bg)" }}
          onMouseLeave={() => { setHovered(null); setHoveredXY(null); }}>
          <GraphCanvas
            width={1240} height={810}
            hoveredId={hovered?.id}
            searchQuery={withSearch ? "read" : ""}
            selectedIds={selectedIds}
            onHover={(n, e) => {
              setHovered(n);
              if (e) {
                const rect = e.currentTarget.closest("svg").getBoundingClientRect();
                setHoveredXY({ x: e.clientX - rect.left, y: e.clientY - rect.top });
              }
            }}
          />

          {/* tooltip */}
          {hovered && hoveredXY && (
            <NodeTooltip node={hovered} x={hoveredXY.x} y={hoveredXY.y} paneW={1240} paneH={810} />
          )}

          {/* lasso visual hint (装饰) */}
          {withSelection && (
            <svg style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
              <rect x="200" y="180" width="280" height="220"
                fill="rgba(91,122,156,0.05)"
                stroke="var(--accent)"
                strokeWidth="1"
                strokeDasharray="4 4"
                rx="4"
              />
            </svg>
          )}

          {/* selection action bar */}
          {withSelection && (
            <div style={{
              position: "absolute", left: "50%", bottom: 80,
              transform: "translateX(-50%)",
              background: "var(--card)",
              border: "1px solid var(--line)",
              borderRadius: 6,
              padding: "6px 10px",
              display: "flex", alignItems: "center", gap: 8,
              boxShadow: "var(--shadow-md)",
              fontSize: 12,
            }}>
              <span style={{ color: "var(--accent-2)", fontWeight: 500 }}>
                <strong>4</strong> 节点已选
              </span>
              <span style={{ width: 1, height: 14, background: "var(--line)" }} />
              <button className="kn-btn ghost" style={{ height: 22, fontSize: 11 }}>
                <I.Expand size={10} /> 全部打开 (split view)
              </button>
              <button className="kn-btn ghost" style={{ height: 22, fontSize: 11 }}>
                <I.Cluster size={10} /> 找共同邻居
              </button>
              <button className="kn-icon-btn" title="清除" style={{ width: 22, height: 22 }}>
                <I.X size={10} />
              </button>
            </div>
          )}

          {/* bottom-left status */}
          <div style={{
            position: "absolute", left: 16, bottom: 12,
            display: "flex", flexDirection: "column", gap: 4,
            fontSize: 10.5, color: "var(--ink-mute)",
            fontFamily: "var(--font-mono)",
          }}>
            <span>force · charge -180 · link 50+ · alpha 0.04</span>
            <span style={{ color: "var(--ink-faint)" }}>4 孤立 note · 2 弱连通分量</span>
          </div>

          {/* zoom controls */}
          <div style={{
            position: "absolute", right: 16, bottom: 16,
            background: "var(--card)",
            border: "1px solid var(--line)",
            borderRadius: 6,
            padding: 4,
            display: "flex", flexDirection: "column",
            boxShadow: "var(--shadow-sm)",
          }}>
            <button className="kn-icon-btn" title="放大" style={{ width: 26, height: 26 }}><I.Plus size={11} /></button>
            <button className="kn-icon-btn" title="缩小" style={{ width: 26, height: 26 }}><I.Down size={11} /></button>
            <button className="kn-icon-btn" title="适配窗口" style={{ width: 26, height: 26 }}><I.Compass size={11} /></button>
          </div>
        </div>

        {/* right info rail — degree-sorted list (a11y fallback + power-user list view) */}
        <aside style={{
          width: 240, background: "var(--panel)",
          borderLeft: "1px solid var(--line)",
          display: "flex", flexDirection: "column",
          fontSize: 11.5,
        }}>
          <div style={{
            padding: "10px 14px",
            borderBottom: "1px solid var(--line)",
            background: "var(--panel-2)",
            fontSize: 10.5, color: "var(--ink-mute)",
            fontFamily: "var(--font-mono)", letterSpacing: 0.4,
            display: "flex", alignItems: "center", gap: 6,
          }}>
            BY IN+OUT DEGREE
            <span style={{ flex: 1 }} />
            <span style={{ color: "var(--ink-faint)" }}>(Tab 循环)</span>
          </div>
          <div style={{ flex: 1, overflow: "auto" }}>
            {[...NODES].sort((a, b) => b.deg - a.deg).slice(0, 14).map((n) => (
              <div key={n.id} style={{
                padding: "7px 14px",
                borderBottom: "1px solid var(--line-soft)",
                display: "flex", alignItems: "center", gap: 8,
                cursor: "pointer",
                background: n.id === hovered?.id ? "var(--accent-soft)" : "transparent",
                color: n.id === hovered?.id ? "var(--accent-2)" : "var(--ink)",
              }}
                onMouseEnter={() => setHovered(n)}
                onMouseLeave={() => setHovered(null)}
              >
                <span className="mono" style={{
                  width: 22, fontSize: 10, color: "var(--ink-mute)",
                  textAlign: "right",
                }}>{n.deg}</span>
                <span style={{
                  flex: 1, minWidth: 0,
                  fontSize: 11.5,
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}>
                  {n.title}
                </span>
                {n.orphan && (
                  <span title="孤立" style={{
                    fontSize: 9, color: "var(--warn)",
                    fontFamily: "var(--font-mono)",
                  }}>orphan</span>
                )}
              </div>
            ))}
          </div>
          <div style={{
            padding: "8px 14px",
            borderTop: "1px solid var(--line)",
            fontSize: 10.5, color: "var(--ink-mute)",
            background: "var(--panel-2)",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <I.Lasso size={11} />
            <span>shift+drag = 多选</span>
          </div>
        </aside>
      </div>

      <style>{`@keyframes kn-blink { 50% { opacity: 0; } }`}</style>
    </div>
  );
};

// ============================================================
// FRAME 3 — Empty state
// ============================================================
const EmptyFrame = () => (
  <div className="kn kn-paper" style={{
    width: 1280, height: 700,
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
        <I.Graph size={11} /> Graph · 全 vault
      </span>
      <span className="serif" style={{ fontSize: 14, color: "var(--ink)", fontWeight: 500 }}>
        17 notes · 0 bilinks
      </span>
      <span style={{ flex: 1 }} />
      <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>⌘⇧G</span>
      <button className="kn-icon-btn" title="退出"><I.X /></button>
    </header>

    <div style={{
      flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
      background: "var(--bg)",
      flexDirection: "column", gap: 24,
      padding: "0 80px",
    }}>
      {/* SVG illustration — 三个孤立的圈,虚线指向彼此暗示"还没连起来" */}
      <svg width="180" height="120" viewBox="0 0 180 120">
        <defs>
          <marker id="ghost-arrow" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="5" markerHeight="5" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--ink-faint)" />
          </marker>
        </defs>
        <circle cx="40" cy="40" r="14" fill="var(--card)" stroke="var(--ink-faint)" strokeWidth="1.5" />
        <circle cx="140" cy="40" r="11" fill="var(--card)" stroke="var(--ink-faint)" strokeWidth="1.5" />
        <circle cx="90" cy="90" r="13" fill="var(--card)" stroke="var(--ink-faint)" strokeWidth="1.5" />
        <line x1="54" y1="42" x2="126" y2="42" stroke="var(--ink-faint)" strokeWidth="1" strokeDasharray="3 4" markerEnd="url(#ghost-arrow)" />
        <line x1="48" y1="52" x2="80" y2="80" stroke="var(--ink-faint)" strokeWidth="1" strokeDasharray="3 4" markerEnd="url(#ghost-arrow)" />
      </svg>

      <div style={{ textAlign: "center", maxWidth: 480 }}>
        <h2 className="serif" style={{
          fontSize: 22, fontWeight: 600, color: "var(--ink)",
          letterSpacing: "-0.012em", margin: "0 0 12px",
        }}>
          还没有连起来的 note
        </h2>
        <p style={{
          fontSize: 14, color: "var(--ink-soft)",
          lineHeight: 1.65, margin: "0 0 18px",
        }}>
          这个图只画<strong style={{ color: "var(--ink)" }}>你自己写的</strong> <code className="mono" style={{
            fontSize: 12.5, color: "var(--accent-2)", background: "var(--card)",
            padding: "1px 5px", borderRadius: 3, border: "1px solid var(--line-soft)",
          }}>[[Title]]</code> 链接 ——
          AI 自动推的相似度不在这里(那是<a style={{ color: "var(--accent-2)", borderBottom: "1px dashed var(--accent)" }}>知识图</a>的事)。
        </p>
        <p style={{
          fontSize: 12.5, color: "var(--ink-mute)",
          lineHeight: 1.65, margin: 0,
          fontStyle: "italic",
        }}>
          先打开一篇 note,用 <code className="mono" style={{
            fontSize: 11.5, fontStyle: "normal",
            color: "var(--ink)", background: "var(--card)",
            padding: "1px 5px", borderRadius: 3, border: "1px solid var(--line-soft)",
          }}>[[</code> 输入你想引用的标题,链好后再回来。
        </p>
      </div>

      <button className="kn-btn primary" style={{ height: 32, fontSize: 12.5 }}>
        <I.NewNote size={12} /> 打开最近一篇 note
      </button>
    </div>
  </div>
);

// ============================================================
// FRAME 4 — Edge state: 大 hub
// ============================================================
const HubEdgeFrame = () => (
  <div className="kn kn-paper" style={{
    width: 1280, height: 720,
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
        <I.Graph size={11} /> Graph · ego of 索引学
      </span>
      <span className="serif" style={{ fontSize: 13.5, color: "var(--ink)", fontWeight: 500 }}>
        显示前 24 个邻居 / 共 58 个
      </span>
      <span style={{ flex: 1 }} />
      <button className="kn-btn ghost" style={{ height: 26, fontSize: 11 }}>
        显示全部 58 个
      </button>
      <button className="kn-icon-btn" title="退出"><I.X /></button>
    </header>

    <div style={{
      flex: 1, position: "relative",
      background: "var(--bg)",
      display: "flex", alignItems: "center", justifyContent: "center",
    }}>
      {/* 中心 hub + 24 个 satellite,放射状 */}
      <svg width="900" height="620" viewBox="-300 -260 600 520">
        <defs>
          <marker id="arr" viewBox="0 0 10 10" refX="8" refY="5"
            markerWidth="5" markerHeight="5" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--ink-mute)" />
          </marker>
          <pattern id="grid2" x="0" y="0" width="32" height="32" patternUnits="userSpaceOnUse">
            <circle cx="16" cy="16" r="0.7" fill="var(--ink-faint)" opacity="0.3" />
          </pattern>
        </defs>
        <rect x="-300" y="-260" width="600" height="520" fill="url(#grid2)" />

        {/* satellite circles */}
        {Array.from({ length: 24 }).map((_, i) => {
          const angle = (i / 24) * Math.PI * 2;
          const ring = i < 8 ? 110 : i < 16 ? 170 : 230;
          const x = Math.cos(angle) * ring;
          const y = Math.sin(angle) * ring;
          // 外圈 fade
          const op = i < 8 ? 1 : i < 16 ? 0.8 : 0.45;
          return (
            <g key={i} opacity={op}>
              <line x1="0" y1="0" x2={x * 0.9} y2={y * 0.9}
                stroke="var(--ink-mute)" strokeWidth="1.4"
                opacity={i < 16 ? 1 : 0.6}
                markerEnd="url(#arr)" />
              <circle cx={x} cy={y} r={i < 8 ? 5 : 4}
                fill="var(--card)" stroke="var(--ink-mute)" strokeWidth="1.5" />
            </g>
          );
        })}

        {/* 模拟"还有更多"的 ghost ring */}
        <circle cx="0" cy="0" r="270" fill="none"
          stroke="var(--ink-faint)" strokeWidth="1" strokeDasharray="3 5" opacity="0.5" />
        <text x="190" y="-200" fontSize="10" fontFamily="var(--font-mono)"
          fill="var(--ink-mute)" textAnchor="middle">
          + 34 隐藏
        </text>

        {/* hub */}
        <circle cx="0" cy="0" r="14"
          fill="var(--accent-soft)" stroke="var(--accent)" strokeWidth="2.4" />
        <text x="0" y="-26" textAnchor="middle"
          fontSize="13" fontFamily="var(--font-serif)" fontWeight="600"
          fill="var(--ink)" letterSpacing="-0.005em">
          索引学
        </text>
      </svg>

      {/* 解释 */}
      <div style={{
        position: "absolute", left: 24, top: 24,
        maxWidth: 280,
        background: "var(--card)",
        border: "1px solid var(--line)",
        borderRadius: 6,
        padding: "12px 14px",
        boxShadow: "var(--shadow-sm)",
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          fontSize: 10.5, color: "var(--warn)",
          fontFamily: "var(--font-mono)", letterSpacing: 0.4,
          marginBottom: 8,
        }}>
          <I.Aging size={11} /> 大 HUB 检测
        </div>
        <div style={{ fontSize: 12.5, color: "var(--ink)", lineHeight: 1.6, marginBottom: 8 }}>
          <strong className="serif">索引学</strong> 有 58 个邻居。直接画会让其他 note 都被挤到边缘。
        </div>
        <div style={{ fontSize: 11.5, color: "var(--ink-soft)", lineHeight: 1.6 }}>
          默认<strong style={{ color: "var(--ink)" }}>限定显示前 24 个</strong>(按 deg 排序),
          外圈 fade 提示还有更多。<br />
          <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>
            一键展开全部 → 顶栏按钮
          </span>
        </div>
      </div>
    </div>
  </div>
);

// ============================================================
// FRAME 5 — Edge state: orphans pile
// ============================================================
const OrphanFrame = () => (
  <div className="kn kn-paper" style={{
    width: 1280, height: 720,
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
        <I.Graph size={11} /> Graph · 全 vault
      </span>
      <span className="serif" style={{ fontSize: 13.5, color: "var(--ink)", fontWeight: 500 }}>
        24 notes · 14 connected · <span style={{ color: "var(--warn)" }}>10 orphan</span>
      </span>
      <span style={{ flex: 1 }} />
      <button className="kn-btn ghost" style={{ height: 26, fontSize: 11 }}>
        <I.X size={10} /> 隐藏 orphans
      </button>
    </header>

    <div style={{
      flex: 1, display: "flex",
      background: "var(--bg)",
    }}>
      {/* main connected component */}
      <div style={{ flex: 1, position: "relative" }}>
        <div style={{
          position: "absolute", top: 12, left: 16,
          fontSize: 10.5, color: "var(--ink-mute)",
          fontFamily: "var(--font-mono)", letterSpacing: 0.4,
        }}>
          MAIN CONNECTED COMPONENT · 14
        </div>
        <svg width="100%" height="100%" viewBox="-280 -200 560 400">
          <defs>
            <marker id="arr3" viewBox="0 0 10 10" refX="8" refY="5"
              markerWidth="5" markerHeight="5" orient="auto">
              <path d="M 0 0 L 10 5 L 0 10 Z" fill="var(--ink-mute)" />
            </marker>
          </defs>
          {NODES.filter((n) => !n.orphan).slice(0, 14).map((n) => (
            <g key={n.id}>
              {n.hot && (
                <text x={n.x * 0.7} y={n.y * 0.7 - nodeR(n) - 7}
                  textAnchor="middle"
                  fontSize="10.5" fontFamily="var(--font-serif)"
                  fontWeight="500" fill="var(--ink)">
                  {n.title.length > 14 ? n.title.slice(0, 12) + "…" : n.title}
                </text>
              )}
              <circle cx={n.x * 0.7} cy={n.y * 0.7} r={nodeR(n)}
                fill="var(--card)" stroke="var(--ink-mute)" strokeWidth="1.5" />
            </g>
          ))}
          {EDGES.filter(([s, t]) => {
            const ns = findNode(s);
            const nt = findNode(t);
            return ns && nt && !ns.orphan && !nt.orphan;
          }).slice(0, 16).map(([s, t], i) => {
            const ns = findNode(s);
            const nt = findNode(t);
            return (
              <line key={i}
                x1={ns.x * 0.7} y1={ns.y * 0.7}
                x2={nt.x * 0.7} y2={nt.y * 0.7}
                stroke="var(--ink-mute)" strokeWidth="1.4" opacity="0.85"
                markerEnd="url(#arr3)" />
            );
          })}
        </svg>
      </div>

      {/* orphan pile — 一个独立的右栏,grid layout,不参与 force */}
      <aside style={{
        width: 360, padding: 16,
        borderLeft: "1px solid var(--line)",
        background: "var(--panel)",
        display: "flex", flexDirection: "column",
        minHeight: 0,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          fontSize: 10.5, color: "var(--warn)",
          fontFamily: "var(--font-mono)", letterSpacing: 0.4,
          marginBottom: 12,
        }}>
          <I.Orphan size={11} /> 孤立 NOTES · 10
        </div>
        <div style={{
          fontSize: 11.5, color: "var(--ink-soft)",
          lineHeight: 1.6,
          marginBottom: 14,
        }}>
          没有出链也没有入链。我们<strong style={{ color: "var(--ink)" }}>不</strong>把它们放进 force 里抢位置 —— 单独网格列出。
        </div>

        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 8,
          flex: 1,
          alignContent: "start",
          overflow: "auto",
        }}>
          {[
            "Balcony garden plan",
            "Books · 2026 reading",
            "家用网络的 router 选型",
            "春耕日历",
            "Postgres extensions 调研",
            "Streamlit 替代方案",
            "TOEFL 词频整理",
            "iOS 快捷指令笔记",
            "做饭节奏",
            "周末计划模板",
          ].map((t, i) => (
            <div key={i} style={{
              padding: "8px 10px",
              background: "var(--bg-1)",
              border: "1px dashed var(--line)",
              borderRadius: 5,
              fontSize: 11.5,
              color: "var(--ink-soft)",
              cursor: "pointer",
              display: "flex", alignItems: "center", gap: 6,
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: 3,
                background: "var(--ink-faint)",
                flexShrink: 0,
              }} />
              <span style={{
                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                minWidth: 0,
              }}>{t}</span>
            </div>
          ))}
        </div>
      </aside>
    </div>
  </div>
);

// ============================================================
// Q1/Q2/Q3 spec card
// ============================================================
const SpecCard = () => {
  const Sec = ({ q, title, children }) => (
    <div style={{ marginBottom: 28 }}>
      <div style={{
        display: "flex", alignItems: "baseline", gap: 10,
        marginBottom: 10,
      }}>
        <span style={{
          display: "inline-flex", alignItems: "center", justifyContent: "center",
          width: 28, height: 28, borderRadius: 14,
          background: "var(--accent)", color: "#faf7f0",
          fontSize: 12, fontWeight: 600, fontFamily: "var(--font-mono)",
        }}>{q}</span>
        <h2 className="serif" style={{
          fontSize: 19, fontWeight: 600, color: "var(--ink)",
          margin: 0, letterSpacing: "-0.012em",
        }}>{title}</h2>
      </div>
      <div style={{ paddingLeft: 38 }}>{children}</div>
    </div>
  );

  const Code = ({ children }) => (
    <pre className="mono" style={{
      background: "var(--card)",
      border: "1px solid var(--line-soft)",
      borderRadius: 4,
      padding: "10px 12px",
      fontSize: 11.5,
      lineHeight: 1.6,
      color: "var(--ink)",
      overflow: "auto",
      margin: "8px 0",
    }}>{children}</pre>
  );

  return (
    <div className="kn kn-paper" style={{
      width: 1280, height: 1100,
      display: "flex", flexDirection: "column",
      borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
    }}>
      <header style={{
        height: 44, padding: "0 22px",
        display: "flex", alignItems: "center", gap: 12,
        background: "var(--panel)", borderBottom: "1px solid var(--line)",
      }}>
        <span className="serif" style={{
          fontSize: 14, fontWeight: 600, color: "var(--ink)",
          letterSpacing: "-0.008em",
        }}>三个硬问题的判断</span>
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>graph view spec · v0.1</span>
      </header>

      <div style={{
        flex: 1, padding: "32px 48px",
        background: "var(--bg)",
        overflow: "auto",
      }}>
        <Sec q="Q1" title="默认 landing — 阈值切换,不是粗暴二选一">
          <p style={{ fontSize: 13.5, color: "var(--ink)", lineHeight: 1.7, margin: "0 0 10px" }}>
            选 <strong>(c) auto-pick by vault size,但阈值我建议 300 不是 200</strong>。
          </p>
          <ul style={{ fontSize: 13, color: "var(--ink-soft)", lineHeight: 1.75, paddingLeft: 18, margin: "0 0 12px" }}>
            <li><strong style={{ color: "var(--ink)" }}>rail-tab 永远 ego 1-hop</strong> — 它是 backlinks 的可视化版,服务于 navigation</li>
            <li><strong style={{ color: "var(--ink)" }}>focus-mode &lt;300 全图</strong> — force-directed 在 1440px viewport 上 ~250 节点 + 600 边仍 60fps 不重叠</li>
            <li><strong style={{ color: "var(--ink)" }}>focus-mode ≥300 默认 ego(2-hop),顶栏按钮一键展开</strong> — 节点数提示 "显示 24 / 1247"</li>
            <li>不选 <strong>(d) auto-zoom-to-recent</strong> — 把 navigation 决定权藏起来,空间记忆失效,每次进来位置不同</li>
          </ul>
        </Sec>

        <Sec q="Q2" title={`视觉差异 — 用户写出来的就是默认,不需要"突出"`}>
          <p style={{ fontSize: 13.5, color: "var(--ink)", lineHeight: 1.7, margin: "0 0 10px" }}>
            User-authored bilink <strong>就是这个 view 的全部</strong>,所以它是<em>默认状态</em>,不需要装饰来强调"我很重要"。要做的是让它<strong>看起来像被画出来的</strong>:
          </p>
          <ol style={{ fontSize: 13, color: "var(--ink-soft)", lineHeight: 1.75, paddingLeft: 22, margin: "0 0 12px" }}>
            <li><strong className="mono" style={{ color: "var(--ink)" }}>1.4px solid --ink-mute</strong> — 在 --bg 上 contrast 4.6:1, WCAG AA</li>
            <li>箭头 <strong className="mono" style={{ color: "var(--ink)" }}>5px</strong> 三角放在<strong>边长 70%</strong>,不在 endpoint(避免覆盖目标节点)</li>
            <li>节点 <strong className="mono" style={{ color: "var(--ink)" }}>circle r = clamp(4, 4 + √deg × 2.4, 14)</strong>,fill --card,stroke --ink-mute 1.5px</li>
          </ol>
          <div style={{
            background: "var(--card)",
            border: "1px solid var(--line-soft)",
            borderRadius: 6,
            padding: "12px 14px",
            margin: "10px 0",
            fontSize: 12, color: "var(--ink-soft)",
            lineHeight: 1.65,
          }}>
            <strong style={{ color: "var(--ink)" }}>留接口给未来的 LLM 边</strong>(不在这个 view 实现):
            <span className="mono" style={{ display: "block", marginTop: 4, fontSize: 11.5 }}>
              1px dashed --accent-tint · opacity 0.5 · default hidden · 通过 toggle 显示
            </span>
          </div>
        </Sec>

        <Sec q="Q3" title="Force-directed,runtime 计算 + session pin">
          <p style={{ fontSize: 13.5, color: "var(--ink)", lineHeight: 1.7, margin: "0 0 10px" }}>
            <strong>react-force-graph-2d 默认配置太弱</strong>,具体调:
          </p>
          <Code>{`d3Force('charge').strength(-180)
d3Force('link').distance(d => 50 + Math.min(d.source.deg + d.target.deg, 12) * 4)
d3Force('center').strength(0.04)
d3Force('x', forceX(0).strength(0.02))
d3Force('y', forceY(0).strength(0.02))
alphaDecay: 0.04        // 默认 0.0228 太慢,用户等不及
velocityDecay: 0.5      // 让停止干脆`}</Code>

          <div style={{
            display: "grid", gridTemplateColumns: "auto 1fr", gap: "8px 16px",
            margin: "16px 0",
            fontSize: 12.5, color: "var(--ink-soft)", lineHeight: 1.65,
          }}>
            <div className="mono" style={{ color: "var(--accent-2)" }}>&lt; 500 nodes</div>
            <div>runtime,每次进入重跑 ~200ms。vault state 变化时布局自然变,符合"vault 是活的"</div>
            <div className="mono" style={{ color: "var(--accent-2)" }}>500–2000</div>
            <div>runtime + <strong>session pin</strong>:用户拖过的节点 fix,刷新仍在。Backend 存 <span className="mono" style={{ fontSize: 11 }}>note_meta.graph_pin: {`{x, y}`}</span></div>
            <div className="mono" style={{ color: "var(--accent-2)" }}>&gt; 2000</div>
            <div>backend indexer 跑 d3-force off-thread,缓存 final positions + 增量更新。M7-M8 边界场景,不优先实现但 schema 留好</div>
          </div>

          <div style={{
            background: "var(--bg-1)",
            border: "1px solid var(--line-soft)",
            borderRadius: 6,
            padding: "12px 14px",
            fontSize: 12, color: "var(--ink-soft)",
            lineHeight: 1.65,
          }}>
            <strong style={{ color: "var(--ink)" }}>不用 hierarchical / radial</strong> — 笔记不是树,是图(允许环 + 多入口)。
            Hierarchical 强行选 root 会撒谎;radial 适合 ego 不适合全图。
            Force-directed 在 PKM 是对的,问题只在 tuning。
          </div>
        </Sec>
      </div>
    </div>
  );
};

// Export
window.GraphRailTabFrame = RailTabFrame;
window.GraphFocusFrame = FocusFrame;
window.GraphEmptyFrame = EmptyFrame;
window.GraphHubFrame = HubEdgeFrame;
window.GraphOrphanFrame = OrphanFrame;
window.GraphSpecCard = SpecCard;
