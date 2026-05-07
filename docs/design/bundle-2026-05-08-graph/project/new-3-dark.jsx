// New Surface 3 — Dark toggle (设置 + Cmd+K · 不在 top bar)
// 设计判断:
// - 主入口 = 设置 → 外观
// - 次入口 = Cmd+K → "dark / light / system"
// - 不进 top bar 占地
// - dark token 严格镜像 light 七色
//
// 同屏展示:设置面板 + Cmd+K 命令片段 + light/dark token 镜像表

const DarkToggleScreen = () => {
  const Swatch = ({ token, light, dark, note }) => (
    <div style={{
      display: "grid", gridTemplateColumns: "180px 1fr 1fr 1fr",
      alignItems: "center", gap: 12,
      padding: "8px 12px",
      borderTop: "1px solid var(--line-soft)",
      fontSize: 11.5,
    }}>
      <span className="mono" style={{ color: "var(--ink-soft)", fontSize: 11 }}>{token}</span>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 22, height: 22, borderRadius: 4, background: light, border: "1px solid var(--line)" }} />
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>{light}</span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 22, height: 22, borderRadius: 4, background: dark, border: "1px solid #2a2c33" }} />
        <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>{dark}</span>
      </div>
      <span style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>{note}</span>
    </div>
  );

  return (
    <div className="kn kn-paper" style={{
      width: 1440, height: 920,
      display: "flex", flexDirection: "column",
      borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)",
    }}>
      <header style={{
        height: 40, padding: "0 18px",
        display: "flex", alignItems: "center", gap: 12,
        background: "var(--panel)", borderBottom: "1px solid var(--line)",
        fontSize: 11.5, color: "var(--ink-mute)",
      }}>
        <span className="serif" style={{ fontSize: 13.5, fontWeight: 600, color: "var(--accent-2)" }}>knowlet</span>
        <span style={{ flex: 1 }} />
        <span>主题切换 — 设置主入口 + ⌘K 次入口 + dark token 镜像</span>
      </header>

      <div style={{
        flex: 1, padding: "32px",
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 28,
        overflow: "auto", background: "var(--bg)",
      }}>
        {/* LEFT — 设置面板 + Cmd+K */}
        <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
          {/* 设置 */}
          <div>
            <div style={{
              fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
              marginBottom: 6, display: "flex", alignItems: "center", gap: 6,
            }}>
              <I.Dot size={10} style={{ color: "var(--accent)" }} />
              <span>主入口 · 设置 → 外观</span>
            </div>

            <div style={{
              background: "var(--card)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              overflow: "hidden",
            }}>
              {/* settings header */}
              <div style={{
                padding: "10px 16px",
                display: "flex", alignItems: "center", gap: 8,
                borderBottom: "1px solid var(--line-soft)",
                background: "var(--panel-2)",
                fontSize: 11.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
              }}>
                <I.Cog size={11} />
                设置 / 外观
              </div>

              <div style={{ padding: "20px 24px" }}>
                <div style={{ marginBottom: 18 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "var(--ink)", marginBottom: 4 }}>主题</div>
                  <div style={{ fontSize: 11.5, color: "var(--ink-soft)", lineHeight: 1.55 }}>
                    Light 是默认。Dark 严格镜像 light 的七色 token,纸感 → 深石,蓝 → 蓝。
                  </div>
                </div>

                {/* 3-way pill */}
                <div style={{
                  display: "flex", alignItems: "stretch",
                  background: "var(--bg-1)",
                  border: "1px solid var(--line)",
                  borderRadius: 6,
                  padding: 3,
                  marginBottom: 18,
                }}>
                  {[
                    { id: "light", label: "Light", icon: <I.Sun size={13} />, active: true },
                    { id: "dark", label: "Dark", icon: <I.Moon size={13} /> },
                    { id: "system", label: "跟随系统", icon: <I.Monitor size={13} /> },
                  ].map((opt) => (
                    <button key={opt.id} style={{
                      flex: 1,
                      display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 6,
                      height: 32, padding: "0 10px",
                      background: opt.active ? "var(--card)" : "transparent",
                      color: opt.active ? "var(--ink)" : "var(--ink-soft)",
                      border: opt.active ? "1px solid var(--line)" : "1px solid transparent",
                      borderRadius: 4,
                      fontSize: 12, fontWeight: opt.active ? 500 : 400,
                      cursor: "pointer",
                    }}>
                      {opt.icon}
                      {opt.label}
                    </button>
                  ))}
                </div>

                {/* sub-options */}
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {[
                    { label: "代码块用反色高亮", desc: "在 dark 下,code block 用 #f4f0e8 底", on: true },
                    { label: "纸纹理在 dark 下保留", desc: "用极低对比的 grain 替代,默认关", on: false },
                    { label: "降低纸面饱和度", desc: "OLED 友好;dark 下 -8% saturation", on: true },
                  ].map((opt, i) => (
                    <div key={i} style={{
                      display: "flex", alignItems: "center", gap: 12,
                      padding: "8px 0",
                      borderTop: i ? "1px solid var(--line-soft)" : "none",
                    }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontSize: 12.5, color: "var(--ink)" }}>{opt.label}</div>
                        <div style={{ fontSize: 11, color: "var(--ink-mute)", marginTop: 2 }}>{opt.desc}</div>
                      </div>
                      {/* switch */}
                      <span style={{
                        position: "relative", display: "inline-block",
                        width: 32, height: 18, borderRadius: 10,
                        background: opt.on ? "var(--accent)" : "var(--line)",
                        transition: "background .15s",
                      }}>
                        <span style={{
                          position: "absolute", top: 2, left: opt.on ? 16 : 2,
                          width: 14, height: 14, borderRadius: 7,
                          background: "var(--card)",
                          boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
                          transition: "left .15s",
                        }} />
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Cmd+K 片段 */}
          <div>
            <div style={{
              fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
              marginBottom: 6, display: "flex", alignItems: "center", gap: 6,
            }}>
              <I.Dot size={10} style={{ color: "var(--accent)" }} />
              <span>次入口 · ⌘K → "dark"</span>
            </div>

            <div style={{
              background: "var(--card)",
              border: "1px solid var(--line)",
              borderRadius: 8,
              overflow: "hidden",
              boxShadow: "var(--shadow-md)",
            }}>
              <div style={{
                padding: "10px 14px",
                display: "flex", alignItems: "center", gap: 8,
                borderBottom: "1px solid var(--line-soft)",
              }}>
                <I.Search size={13} style={{ color: "var(--ink-mute)" }} />
                <span style={{ fontSize: 13, color: "var(--ink)" }}>dark</span>
                <span style={{ display: "inline-block", width: 1.5, height: 14, background: "var(--accent)", animation: "kn-blink 1s steps(1) infinite" }} />
                <span style={{ flex: 1 }} />
                <span className="mono" style={{ fontSize: 10.5, color: "var(--ink-mute)" }}>3 commands</span>
              </div>
              {[
                { icon: <I.Moon size={12} />, label: "切换到 Dark", kbd: "↵", active: true },
                { icon: <I.Sun size={12} />, label: "切换到 Light", kbd: "" },
                { icon: <I.Monitor size={12} />, label: "跟随系统主题", kbd: "" },
              ].map((cmd, i) => (
                <div key={i} style={{
                  padding: "9px 14px",
                  display: "flex", alignItems: "center", gap: 10,
                  background: cmd.active ? "var(--accent-soft)" : "transparent",
                  fontSize: 12.5,
                  color: cmd.active ? "var(--accent-2)" : "var(--ink)",
                  borderTop: "1px solid var(--line-soft)",
                }}>
                  <span style={{ color: cmd.active ? "var(--accent-2)" : "var(--ink-mute)" }}>{cmd.icon}</span>
                  <span style={{ flex: 1 }}>{cmd.label}</span>
                  {cmd.kbd && <span className="kn-kbd" style={{ background: "var(--card)" }}>{cmd.kbd}</span>}
                </div>
              ))}
            </div>
            <div style={{ fontSize: 11, color: "var(--ink-soft)", marginTop: 8, lineHeight: 1.55 }}>
              ⌘K 是次入口。<strong style={{ color: "var(--ink)" }}>top bar 不放 toggle</strong> ——
              主题不是高频切换,占 top bar 的 24px 不值得。
            </div>
          </div>
        </div>

        {/* RIGHT — token 镜像表 */}
        <div>
          <div style={{
            fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
            marginBottom: 6, display: "flex", alignItems: "center", gap: 6,
          }}>
            <I.Dot size={10} style={{ color: "var(--accent)" }} />
            <span>Dark token · 严格镜像 light 七色</span>
          </div>

          <div style={{
            background: "var(--card)",
            border: "1px solid var(--line)",
            borderRadius: 8,
            overflow: "hidden",
          }}>
            <div style={{
              padding: "10px 12px",
              borderBottom: "1px solid var(--line)",
              background: "var(--panel-2)",
              display: "grid", gridTemplateColumns: "180px 1fr 1fr 1fr", gap: 12,
              fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
              fontWeight: 500,
            }}>
              <span>token</span>
              <span>light</span>
              <span>dark (镜像)</span>
              <span>角色</span>
            </div>
            <Swatch token="--bg" light="#f4f0e8" dark="#1c1d22" note="主背景 / 纸 vs 深石" />
            <Swatch token="--bg-1" light="#efe9dd" dark="#222328" note="recessed" />
            <Swatch token="--panel" light="#ede7d9" dark="#1f2025" note="侧栏 / 面板" />
            <Swatch token="--panel-2" light="#e3dcca" dark="#2a2c33" note="hover / inset" />
            <Swatch token="--card" light="#fbf8f1" dark="#272930" note="lifted card" />
            <Swatch token="--line" light="#d6cfbd" dark="#34363d" note="主分隔线" />
            <Swatch token="--line-soft" light="#e0d9c8" dark="#2c2e35" note="软分隔" />
            <Swatch token="--ink" light="#2a2823" dark="#dcdee5" note="正文" />
            <Swatch token="--ink-soft" light="#5e5b53" dark="#a0a4b0" note="次要" />
            <Swatch token="--ink-mute" light="#8a8678" dark="#73798a" note="标签 / 时间戳" />
            <Swatch token="--accent" light="#5b7a9c" dark="#8aa9c9" note="dusk 蓝(亮版)" />
            <Swatch token="--accent-2" light="#4d6a8a" dark="#a3c0dc" note="深蓝 → 浅蓝" />
            <Swatch token="--good" light="#5e8757" dark="#7eaf78" note="复习 OK" />
            <Swatch token="--warn" light="#a47a3a" dark="#caa15f" note="近重复 / 草稿" />
            <Swatch token="--danger" light="#b8554d" dark="#d97e74" note="错答" />
          </div>

          <div style={{
            marginTop: 14,
            background: "var(--bg-1)",
            border: "1px solid var(--line-soft)",
            borderRadius: 6,
            padding: "10px 14px",
            fontSize: 11.5, color: "var(--ink-soft)",
            lineHeight: 1.6,
          }}>
            <strong style={{ color: "var(--ink)" }}>原则</strong> · 不发明 dark 专属色;每个 light token 一一对应。
            accent 在 dark 下 +20 OKLCH lightness,保持感知一致。Code block 在 dark 下用反色 = light --bg(#f4f0e8 在深色背景里突显,接近 e-ink)。
          </div>
        </div>
      </div>

      <style>{`@keyframes kn-blink { 50% { opacity: 0; } }`}</style>
    </div>
  );
};

window.DarkToggleScreen = DarkToggleScreen;
