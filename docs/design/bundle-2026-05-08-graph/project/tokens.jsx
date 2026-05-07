// Tokens screen — 七色系统的完整文档
// 设计判断:
// - 不是 dashboard,是 design system spec
// - 三栏:Surface tokens / Ink tokens / Accent + state
// - 每个 token 一行:swatch + name + hex + role + 用例
// - Dark 镜像并排,绝对一一对应
// - 底部 before/after:同一个 capsule 在 light 和 dark 下的呈现

const TokensScreen = () => {
  const Row = ({ token, light, dark, role, example }) => (
    <div style={{
      display: "grid",
      gridTemplateColumns: "auto 160px 1fr 1fr 1.4fr",
      alignItems: "center", gap: 14,
      padding: "10px 16px",
      borderTop: "1px solid var(--line-soft)",
      fontSize: 11.5,
    }}>
      <div style={{ display: "flex", gap: 4 }}>
        <span style={{
          width: 26, height: 26, borderRadius: 4,
          background: light, border: "1px solid var(--line)",
        }} />
        <span style={{
          width: 26, height: 26, borderRadius: 4,
          background: dark, border: "1px solid #2a2c33",
        }} />
      </div>
      <span className="mono" style={{ color: "var(--ink-soft)", fontSize: 11 }}>{token}</span>
      <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)", lineHeight: 1.5 }}>
        <div>{light}</div>
        <div style={{ color: "var(--ink-faint)" }}>{dark}</div>
      </div>
      <span style={{ color: "var(--ink-soft)" }}>{role}</span>
      <span style={{ color: "var(--ink-mute)", fontSize: 11 }}>{example}</span>
    </div>
  );

  const Section = ({ title, hint, children }) => (
    <div>
      <div style={{
        display: "flex", alignItems: "baseline", gap: 12,
        padding: "12px 16px",
        borderBottom: "1px solid var(--line)",
        background: "var(--panel-2)",
      }}>
        <span className="serif" style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)" }}>
          {title}
        </span>
        <span style={{ fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)" }}>
          {hint}
        </span>
      </div>
      <div style={{
        display: "grid", gridTemplateColumns: "auto 160px 1fr 1fr 1.4fr",
        gap: 14,
        padding: "8px 16px",
        background: "var(--bg-1)",
        fontSize: 10, color: "var(--ink-mute)",
        fontFamily: "var(--font-mono)",
        textTransform: "uppercase", letterSpacing: 0.4,
      }}>
        <span>L · D</span>
        <span>token</span>
        <span>hex</span>
        <span>角色</span>
        <span>用例</span>
      </div>
      {children}
    </div>
  );

  // 应用示例 — 同一个 capsule 在 light / dark 下
  const CapsuleDemo = ({ dark }) => {
    const t = dark ? {
      bg: "#1c1d22", panel: "#1f2025", card: "#272930",
      ink: "#dcdee5", inkSoft: "#a0a4b0", inkMute: "#73798a",
      accent: "#8aa9c9", accent2: "#a3c0dc", accentSoft: "rgba(138,169,201,0.16)",
      line: "#34363d", warn: "#caa15f", good: "#7eaf78",
    } : {
      bg: "#f4f0e8", panel: "#ede7d9", card: "#fbf8f1",
      ink: "#2a2823", inkSoft: "#5e5b53", inkMute: "#8a8678",
      accent: "#5b7a9c", accent2: "#4d6a8a", accentSoft: "rgba(91,122,156,0.14)",
      line: "#d6cfbd", warn: "#a47a3a", good: "#5e8757",
    };
    return (
      <div style={{
        background: t.bg, border: `1px solid ${t.line}`,
        borderRadius: 8, padding: 18,
        fontFamily: "var(--font-sans)",
        flex: 1, minWidth: 0,
      }}>
        <div style={{
          fontSize: 10.5, color: t.inkMute,
          fontFamily: "var(--font-mono)", letterSpacing: 0.4,
          marginBottom: 10,
        }}>
          {dark ? "DARK · 同一组件" : "LIGHT · 同一组件"}
        </div>

        {/* mock capsule */}
        <div style={{
          background: t.card, border: `1px solid ${t.line}`,
          borderRadius: 6, padding: "10px 12px",
          marginBottom: 10,
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <span style={{
            width: 16, height: 16, borderRadius: 3,
            background: t.accentSoft, color: t.accent2,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            fontSize: 9, fontWeight: 600, fontFamily: "var(--font-mono)",
          }}>N</span>
          <span style={{ fontSize: 12, color: t.ink, flex: 1 }}>
            RAG 检索策略
          </span>
          <span style={{ fontSize: 10.5, color: t.inkMute, fontFamily: "var(--font-mono)" }}>
            note
          </span>
        </div>

        <div style={{
          background: t.card, border: `1px solid ${t.line}`,
          borderRadius: 6, padding: "10px 12px",
          marginBottom: 10,
          display: "flex", alignItems: "center", gap: 10,
        }}>
          <span style={{
            width: 16, height: 16, borderRadius: 3,
            background: t.warn, color: t.bg,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            fontSize: 9, fontWeight: 600, fontFamily: "var(--font-mono)",
          }}>U</span>
          <span style={{ fontSize: 12, color: t.ink, flex: 1 }}>
            Pinecone serverless docs
          </span>
          <span style={{ fontSize: 10.5, color: t.inkMute, fontFamily: "var(--font-mono)" }}>
            url
          </span>
        </div>

        {/* score row */}
        <div style={{
          display: "flex", gap: 14, paddingTop: 8,
          borderTop: `1px solid ${t.line}`,
          fontSize: 11, color: t.inkSoft,
        }}>
          <span><span style={{ color: t.good, fontFamily: "var(--font-mono)" }}>92%</span> 复习 OK</span>
          <span><span style={{ color: t.warn, fontFamily: "var(--font-mono)" }}>3</span> 近重复</span>
          <span style={{ color: t.accent2, fontFamily: "var(--font-mono)" }}>0.91 cosine</span>
        </div>
      </div>
    );
  };

  return (
    <div className="kn kn-paper" style={{
      width: 1440, height: 980,
      display: "flex", flexDirection: "column",
      borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
    }}>
      <header style={{
        height: 50, padding: "0 22px",
        display: "flex", alignItems: "center", gap: 14,
        background: "var(--panel)", borderBottom: "1px solid var(--line)",
      }}>
        <span className="serif" style={{
          fontSize: 16, fontWeight: 600, color: "var(--ink)",
          letterSpacing: "-0.012em",
        }}>
          Knowlet · Token spec
        </span>
        <span style={{ fontSize: 11, color: "var(--ink-mute)" }}>七色系统 + Dark 镜像</span>
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>
          v0.4 · 4月 28 日 锁定
        </span>
      </header>

      <div style={{ flex: 1, overflow: "auto" }}>
        {/* 顶部 manifesto */}
        <div style={{
          padding: "24px 32px",
          background: "var(--bg)",
          borderBottom: "1px solid var(--line)",
          display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 28,
        }}>
          {[
            {
              t: "纸感为底",
              p: "默认主题不是白,是 #f4f0e8 暖纸。屏幕看久了眼睛不累,印出来也是纸。",
            },
            {
              t: "七个角色,不是 50 个色",
              p: "surface · ink · accent · good · warn · danger · line。每个 token 必须能说清「为什么需要它」。",
            },
            {
              t: "Dark 严格镜像",
              p: "不发明 dark 专属色。light 七色一一对应到 dark,accent 在 OKLCH 中 +20 lightness 保感知一致。",
            },
          ].map((m) => (
            <div key={m.t}>
              <div className="serif" style={{
                fontSize: 15, fontWeight: 600, color: "var(--ink)",
                marginBottom: 6, letterSpacing: "-0.008em",
              }}>{m.t}</div>
              <div style={{ fontSize: 12, color: "var(--ink-soft)", lineHeight: 1.65 }}>
                {m.p}
              </div>
            </div>
          ))}
        </div>

        {/* Surface */}
        <Section title="Surface" hint="纸面与面板的层叠 — 每层 ΔL 约 1–2%,层级感弱但可感知">
          <Row token="--bg" light="#f4f0e8" dark="#1c1d22"
            role="主背景 · 纸 / 深石"
            example="编辑器画布、focus mode 全屏" />
          <Row token="--bg-1" light="#efe9dd" dark="#222328"
            role="recessed 背景"
            example="侧栏底色、status bar" />
          <Row token="--bg-2" light="#e8e1d2" dark="#262830"
            role="二级 recessed"
            example="rail 顶栏分组" />
          <Row token="--panel" light="#ede7d9" dark="#1f2025"
            role="面板 / sidebar"
            example="文件树面板、AI 右栏" />
          <Row token="--panel-2" light="#e3dcca" dark="#2a2c33"
            role="hover / inset"
            example="hover 高亮、按钮 inset" />
          <Row token="--card" light="#fbf8f1" dark="#272930"
            role="lifted card / popover"
            example="tooltip、capsule、modal" />
        </Section>

        {/* Line */}
        <Section title="Line" hint="分隔线 — 主线略重,软线只为结构提示">
          <Row token="--line" light="#d6cfbd" dark="#34363d"
            role="主分隔线"
            example="面板边界、列分隔" />
          <Row token="--line-soft" light="#e0d9c8" dark="#2c2e35"
            role="软分隔线"
            example="列表项之间、表格行" />
        </Section>

        {/* Ink */}
        <Section title="Ink" hint="文字四级 — 主 / 次 / 弱 / 极弱,WCAG AA 全部达标">
          <Row token="--ink" light="#2a2823" dark="#dcdee5"
            role="正文 · 暖近黑"
            example="主体段落、note 标题" />
          <Row token="--ink-soft" light="#5e5b53" dark="#a0a4b0"
            role="次要文字"
            example="按钮、面板说明" />
          <Row token="--ink-mute" light="#8a8678" dark="#73798a"
            role="弱文字 / 标签"
            example="时间戳、mono 数据" />
          <Row token="--ink-faint" light="#b3ad9c" dark="#5a5d68"
            role="极弱 / 占位"
            example="placeholder、disabled" />
        </Section>

        {/* Accent */}
        <Section title="Accent — Dusk Blue" hint="选中、链接、所有「被点击」的东西。OKLCH dark = light +20% L">
          <Row token="--accent" light="#5b7a9c" dark="#8aa9c9"
            role="主 accent · dusk 蓝"
            example="链接、focus ring" />
          <Row token="--accent-2" light="#4d6a8a" dark="#a3c0dc"
            role="次 accent · 深一档"
            example="strong 链接、active tab" />
          <Row token="--accent-soft" light="rgba(91,122,156,0.14)" dark="rgba(138,169,201,0.16)"
            role="14% alpha 软背景"
            example="capsule note 类、selection" />
          <Row token="--accent-tint" light="rgba(91,122,156,0.08)" dark="rgba(138,169,201,0.10)"
            role="8% alpha 极淡"
            example="hover、 quote 段落底" />
        </Section>

        {/* Semantic */}
        <Section title="Semantic — good / warn / danger" hint="三个 status 色,不混用 — 复习对错、近重复、错误">
          <Row token="--good" light="#5e8757" dark="#7eaf78"
            role="正确 / 通过 · 暖绿"
            example="复习正确、状态 OK" />
          <Row token="--warn" light="#a47a3a" dark="#caa15f"
            role="警告 / 草稿 · 赭石"
            example="近重复、URL 类、aging" />
          <Row token="--danger" light="#b8554d" dark="#d97e74"
            role="错误 · 砖红"
            example="错答、删除、解析失败" />
          <Row token="--user" light="#a87a3a" dark="#c89c5e"
            role="user 高亮 · 偏暖赭"
            example="user 评论、question 类" />
        </Section>

        {/* Type */}
        <Section title="Type · 三栈" hint="sans 正文、serif 标题与 prose、mono 数据">
          <div style={{
            padding: "16px 16px 4px",
            display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 18,
          }}>
            {[
              { fam: "Inter", role: "--font-sans", use: "UI 主字体、按钮、列表",
                sample: "RAG 检索策略 · 23 notes",
                stack: "PingFang SC fallback 自动接中文" },
              { fam: "Source Serif 4", role: "--font-serif", use: "标题、长读体、quote",
                sample: "这一周,你在 RAG 上花了最多时间。",
                stack: "Noto Serif SC fallback 接中文" },
              { fam: "JetBrains Mono", role: "--font-mono", use: "代码、数据、token",
                sample: "0.91 cosine · k≈60 · 92%",
                stack: "tabular-nums 默认开" },
            ].map((s) => (
              <div key={s.role} style={{
                background: "var(--card)",
                border: "1px solid var(--line)",
                borderRadius: 6,
                padding: "14px 16px",
              }}>
                <div className="mono" style={{
                  fontSize: 10.5, color: "var(--ink-mute)",
                  letterSpacing: 0.4,
                  marginBottom: 8,
                }}>{s.role}</div>
                <div style={{
                  fontFamily: s.fam === "Source Serif 4" ? "var(--font-serif)" : s.fam === "JetBrains Mono" ? "var(--font-mono)" : "var(--font-sans)",
                  fontSize: 19, fontWeight: 500, color: "var(--ink)",
                  lineHeight: 1.35,
                  marginBottom: 8,
                  letterSpacing: s.fam === "Source Serif 4" ? "-0.012em" : 0,
                }}>{s.sample}</div>
                <div style={{ fontSize: 11.5, color: "var(--ink-soft)", marginBottom: 4 }}>
                  <strong style={{ color: "var(--ink)" }}>{s.fam}</strong> · {s.use}
                </div>
                <div style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>{s.stack}</div>
              </div>
            ))}
          </div>
        </Section>

        {/* Before / after — 同组件两套主题 */}
        <Section title="应用示例 · light → dark" hint="同一组件,两套主题。token 一一对应,布局零差异。">
          <div style={{ padding: 16, display: "flex", gap: 14 }}>
            <CapsuleDemo dark={false} />
            <CapsuleDemo dark={true} />
          </div>
        </Section>

        {/* Spacing & radius */}
        <Section title="Spacing · Radius · Shadow" hint="保守:8px 网格、4 / 6 / 8 圆角、三档 shadow 用于 card 抬升">
          <div style={{
            padding: "16px 16px 22px",
            display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 18,
          }}>
            {/* spacing */}
            <div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)", letterSpacing: 0.4, marginBottom: 10 }}>SPACING · 8PX 网格</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {[4, 8, 12, 16, 24, 32, 48].map((s) => (
                  <div key={s} style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <span style={{ width: 36, fontSize: 11, color: "var(--ink-mute)", fontFamily: "var(--font-mono)" }}>{s}px</span>
                    <span style={{ height: 8, width: s, background: "var(--accent)", borderRadius: 1 }} />
                  </div>
                ))}
              </div>
            </div>

            {/* radius */}
            <div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)", letterSpacing: 0.4, marginBottom: 10 }}>RADIUS · 三档</div>
              <div style={{ display: "flex", gap: 12 }}>
                {[
                  { r: 3, l: "3px", use: "tag / chip" },
                  { r: 4, l: "4px", use: "input / button" },
                  { r: 6, l: "6px", use: "card / capsule" },
                  { r: 8, l: "8px", use: "panel / modal" },
                ].map((r) => (
                  <div key={r.r} style={{ textAlign: "center" }}>
                    <div style={{
                      width: 48, height: 48,
                      background: "var(--card)",
                      border: "1px solid var(--line)",
                      borderRadius: r.r,
                      marginBottom: 6,
                    }} />
                    <div className="mono" style={{ fontSize: 10.5, color: "var(--ink)" }}>{r.l}</div>
                    <div style={{ fontSize: 10, color: "var(--ink-mute)" }}>{r.use}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* shadow */}
            <div>
              <div className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)", letterSpacing: 0.4, marginBottom: 10 }}>SHADOW · 三档</div>
              <div style={{ display: "flex", gap: 14 }}>
                {[
                  { name: "sm", sh: "var(--shadow-sm)", use: "hover lift" },
                  { name: "md", sh: "var(--shadow-md)", use: "popover" },
                  { name: "lg", sh: "var(--shadow-lg)", use: "modal" },
                ].map((s) => (
                  <div key={s.name} style={{ textAlign: "center" }}>
                    <div style={{
                      width: 56, height: 56,
                      background: "var(--card)",
                      border: "1px solid var(--line-soft)",
                      borderRadius: 6,
                      boxShadow: s.sh,
                      marginBottom: 8,
                    }} />
                    <div className="mono" style={{ fontSize: 10.5, color: "var(--ink)" }}>{s.name}</div>
                    <div style={{ fontSize: 10, color: "var(--ink-mute)" }}>{s.use}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Section>
      </div>

      <footer style={{
        height: 32, padding: "0 22px",
        display: "flex", alignItems: "center", gap: 14,
        background: "var(--panel)", borderTop: "1px solid var(--line)",
        fontSize: 10.5, color: "var(--ink-mute)",
        fontFamily: "var(--font-mono)",
      }}>
        <span>22 tokens · 3 type stacks · 4 radii · 3 shadows</span>
        <span style={{ flex: 1 }} />
        <span>所有 token 在 styles.css :root 中可改</span>
      </footer>
    </div>
  );
};

window.TokensScreen = TokensScreen;
