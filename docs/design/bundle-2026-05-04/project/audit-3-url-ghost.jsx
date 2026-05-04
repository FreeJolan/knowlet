// Audit Surface 3 — URL ghost capsule (no banner, no layout shift)
// 设计判断:
// - 粘贴 URL 后,输入框 *上方* capsule strip 直接出现一颗 ghost capsule
// - ghost = 半透明、虚线边、loading spinner、mono URL 缩写
// - 解析完成 → ghost 平滑变为 solid capsule(同位同形,无 shift)
// - 解析失败 → ghost 变红虚线 + "重试 / 当作纯文本"
//
// 三态并排展示:loading / loaded / failed

const UrlGhostScreen = () => (
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
      <span>URL 粘贴 — capsule 同位同形 ghost → solid,无 layout shift</span>
    </header>

    <div style={{ flex: 1, padding: "32px 40px", display: "flex", flexDirection: "column", gap: 28, overflow: "auto" }}>
      {[
        { state: "loading", title: "粘贴瞬间 → ghost capsule 出现", note: "fetch 中,虚线边 + spinner;输入光标停在 URL 后" },
        { state: "loaded", title: "解析成功 → 变 solid capsule", note: "0.3s ease-out 过渡,边框/底色/icon 三层 cross-fade" },
        { state: "failed", title: "解析失败 → 红虚线 + 重试", note: "保留为纯文本仍可发送;不阻塞" },
      ].map((scene, idx) => (
        <div key={scene.state} style={{
          display: "flex", gap: 24, alignItems: "flex-start",
        }}>
          {/* label 列 */}
          <div style={{ width: 240, flexShrink: 0, paddingTop: 8 }}>
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 6,
              fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
              marginBottom: 4,
            }}>
              <I.Dot size={10} style={{ color: scene.state === "failed" ? "var(--danger)" : scene.state === "loaded" ? "var(--good)" : "var(--accent)" }} />
              <span>state {idx + 1} · {scene.state}</span>
            </div>
            <div style={{ fontSize: 13, color: "var(--ink)", marginBottom: 4, fontWeight: 500 }}>{scene.title}</div>
            <div style={{ fontSize: 11.5, color: "var(--ink-soft)", lineHeight: 1.55 }}>{scene.note}</div>
          </div>

          {/* AI input 浮窗 */}
          <div style={{
            flex: 1, maxWidth: 560,
            background: "var(--panel)",
            border: "1px solid var(--line)",
            borderRadius: 8,
          }}>
            {/* capsule strip */}
            <div style={{
              padding: "8px 12px 6px",
              background: "var(--panel-2)",
              borderTopLeftRadius: 8, borderTopRightRadius: 8,
            }}>
              <div style={{
                fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)",
                marginBottom: 6,
              }}>
                引用 · {scene.state === "failed" ? "1 个失败" : "1"}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4, minHeight: 22 }}>
                {scene.state === "loading" && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    height: 22, padding: "0 8px 0 6px",
                    borderRadius: 4,
                    border: "1px dashed var(--line)",
                    color: "var(--ink-mute)",
                    fontSize: 11.5,
                    opacity: 0.75,
                  }}>
                    <I.Loader size={10} style={{ animation: "kn-spin 1.2s linear infinite" }} />
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5 }}>arxiv.org/abs/2312.10997</span>
                  </span>
                )}
                {scene.state === "loaded" && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    height: 22, padding: "0 8px 0 6px",
                    borderRadius: 4,
                    border: "1px solid transparent",
                    background: "var(--bg-1)",
                    color: "var(--ink)",
                    fontSize: 11.5,
                  }}>
                    <span style={{ width: 2, height: 12, background: "var(--ink-mute)", borderRadius: 1 }} />
                    <I.ExtLink size={10} />
                    <span>Retrieval-Augmented Generation for Large Language Models: A Survey</span>
                  </span>
                )}
                {scene.state === "failed" && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", gap: 6,
                    height: 22, padding: "0 8px 0 6px",
                    borderRadius: 4,
                    border: "1px dashed var(--danger)",
                    color: "var(--danger)",
                    fontSize: 11.5,
                    opacity: 0.85,
                  }}>
                    <I.X size={10} />
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: 10.5 }}>arxiv.org/abs/2312.10997</span>
                    <span style={{ width: 1, height: 12, background: "rgba(184,85,77,0.3)", margin: "0 2px" }} />
                    <button style={{
                      background: "transparent", border: 0, color: "var(--danger)",
                      fontSize: 10.5, padding: 0, cursor: "pointer", fontWeight: 500,
                    }}>重试</button>
                    <span style={{ color: "var(--ink-faint)" }}>·</span>
                    <button style={{
                      background: "transparent", border: 0, color: "var(--ink-soft)",
                      fontSize: 10.5, padding: 0, cursor: "pointer",
                    }}>当纯文本</button>
                  </span>
                )}
              </div>
            </div>

            {/* input */}
            <div style={{
              padding: "10px 12px 12px",
              borderTop: "1px solid var(--line)",
            }}>
              <div style={{
                background: "var(--card)",
                border: "1px solid var(--line-soft)",
                borderRadius: 6,
                padding: "10px 12px",
                minHeight: 56,
                fontSize: 13,
                color: "var(--ink)",
                fontFamily: "var(--font-mono)",
                fontSize: 11.5,
                lineHeight: 1.5,
              }}>
                <span style={{ color: "var(--ink-soft)" }}>https://arxiv.org/abs/2312.10997</span>
                <span style={{
                  display: "inline-block", width: 1.5, height: 14,
                  background: "var(--accent)", marginLeft: 1, verticalAlign: "middle",
                  animation: "kn-blink 1s steps(1) infinite",
                }} />
              </div>
              <div style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                marginTop: 6,
              }}>
                <span style={{ fontSize: 10.5, color: "var(--ink-mute)", fontFamily: "var(--font-mono)" }}>
                  {scene.state === "loading" && "解析中…"}
                  {scene.state === "loaded" && "已解析 · 标题、首段、URL 已取"}
                  {scene.state === "failed" && "fetch failed · 不阻塞发送"}
                </span>
                <button style={{
                  height: 24, padding: "0 10px", fontSize: 11.5,
                  background: scene.state === "loading" ? "var(--bg-1)" : "var(--accent)",
                  color: scene.state === "loading" ? "var(--ink-mute)" : "#faf7f0",
                  border: 0, borderRadius: 4,
                  cursor: "pointer", fontWeight: 500,
                  display: "inline-flex", alignItems: "center", gap: 5,
                }}>
                  <I.Send2 size={10} /> 发送
                </button>
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>

    <style>{`
      @keyframes kn-spin { to { transform: rotate(360deg); } }
      @keyframes kn-blink { 50% { opacity: 0; } }
    `}</style>
  </div>
);

window.UrlGhostScreen = UrlGhostScreen;
