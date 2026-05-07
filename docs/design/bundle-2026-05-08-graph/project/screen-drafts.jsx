// Knowlet — Drafts focus (replaces "Inbox" — matches ADR-0011 §6)

const DraftsScreen = () => (
  <div className="kn kn-paper" style={{ width: 1280, height: 820, display: "flex", flexDirection: "column", borderRadius: 10, overflow: "hidden", border: "1px solid var(--line)" }}>
    {/* header bar */}
    <header style={{ height: 44, padding: "0 16px", display: "flex", alignItems: "center", gap: 12, background: "var(--panel)", borderBottom: "1px solid var(--line)" }}>
      <I.Inbox size={14} style={{ color: "var(--accent-2)" }} />
      <span style={{ fontSize: 13, color: "var(--ink)", fontWeight: 500 }}>草稿审查</span>
      <span style={{ fontSize: 11.5, color: "var(--ink-mute)" }}>
        <span className="mono">3 / 12</span>
        <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>·</span>
        batch: HF blog daily · 今天剩余
      </span>
      <span style={{ flex: 1 }} />
      <button style={{ display: "inline-flex", alignItems: "center", gap: 6, padding: "4px 8px", borderRadius: 5, background: "transparent", border: 0, color: "var(--ink-soft)", fontSize: 12, cursor: "pointer" }}>
        <span className="kn-kbd">esc</span>
        <span>退出</span>
      </button>
    </header>

    {/* progress hairline */}
    <div style={{ height: 1, background: "var(--line-soft)" }}>
      <div style={{ width: "25%", height: "100%", background: "var(--accent)" }} />
    </div>

    {/* article body */}
    <div style={{ flex: 1, overflow: "auto", padding: "40px 24px" }}>
      <article style={{ maxWidth: 720, margin: "0 auto" }}>
        {/* meta */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, fontSize: 11.5, color: "var(--ink-mute)" }}>
          <span style={{ textTransform: "uppercase", letterSpacing: "0.08em", fontSize: 10 }}>source</span>
          <a className="mono" style={{ fontSize: 11.5, color: "var(--accent-2)", textDecoration: "none", display: "inline-flex", alignItems: "center", gap: 5, borderBottom: "1px solid transparent" }}>
            huggingface.co/blog/granite-4-1
            <I.ExtLink size={11} />
          </a>
          <span style={{ color: "var(--ink-faint)" }}>·</span>
          <span className="mono">task: HF blog daily</span>
          <span style={{ flex: 1 }} />
          <span className="mono" style={{ fontSize: 11 }}>fetched 06:14</span>
        </div>

        {/* tags */}
        <div style={{ display: "flex", gap: 6, marginBottom: 22 }}>
          <span className="kn-chip"><I.Tag size={9} stroke={1.7} />llm</span>
          <span className="kn-chip">release</span>
          <span className="kn-chip">reasoning</span>
        </div>

        <h1 className="serif" style={{ fontSize: 26, lineHeight: 1.2, fontWeight: 600, letterSpacing: "-0.012em", margin: "0 0 18px", color: "var(--ink)" }}>
          Granite 4.1 — IBM 的 reasoning-tuned 小模型族
        </h1>

        <p style={{ fontSize: 15, lineHeight: 1.75, color: "var(--ink)", margin: "0 0 12px" }}>
          IBM 发布了 Granite 4.1,一组 3B / 8B / 20B 的小型 reasoning 模型。训练管线重点是 <em>chain-of-thought
          蒸馏</em>,从 70B 教师模型蒸馏到学生。8B 在 GSM8K 上接近 Llama-3.3-70B,但服务成本约为后者的十分之一。
        </p>
        <p style={{ fontSize: 15, lineHeight: 1.75, color: "var(--ink-soft)", margin: "0 0 24px" }}>
          全套 Apache 2.0,评估 harness 与 safety appendix 都开源。值得跟最近 Qwen-3、Mistral 的 reasoning 系做横向比较 ——
          特别是 8B 这一档,直接关系到 self-host 的可行性。
        </p>

        <h2 className="serif" style={{ fontSize: 16, fontWeight: 600, margin: "0 0 10px" }}>Key points</h2>
        <ul style={{ margin: 0, paddingLeft: 22, fontSize: 14.5, lineHeight: 1.8 }}>
          <li>三个尺寸 <span className="mono" style={{ color: "var(--ink-soft)", fontSize: 12.5 }}>3B / 8B / 20B</span> 全部 Apache 2.0</li>
          <li>RLHF 管线侧重 chain-of-thought 蒸馏(70B 教师)</li>
          <li>8B 在 GSM8K(92.4)、HumanEval(78.1)接近 70B 量级</li>
          <li>Safety appendix 给出 refusal rate 与 red-team 覆盖率</li>
          <li>Eval harness 配置可复现</li>
        </ul>

        {/* link to attached note that will be created */}
        <div style={{ marginTop: 28, padding: "10px 14px", background: "var(--panel)", border: "1px solid var(--line-soft)", borderRadius: 6, fontSize: 12, color: "var(--ink-soft)" }}>
          通过后将保存到 <span className="mono" style={{ color: "var(--accent-2)" }}>notes/AI papers/Granite 4.1.md</span>
          <span style={{ color: "var(--ink-faint)", margin: "0 6px" }}>·</span>
          标签 <span className="mono">#llm #release</span>
        </div>
      </article>
    </div>

    {/* footer actions */}
    <footer style={{
      borderTop: "1px solid var(--line)",
      background: "var(--panel)",
      padding: "14px 24px",
      display: "flex", alignItems: "center", gap: 10,
    }}>
      <div style={{ width: 720, margin: "0 auto", display: "flex", alignItems: "center", gap: 10 }}>
        <button className="kn-btn lg">
          拒绝
          <span className="kn-kbd">X</span>
        </button>
        <button className="kn-btn lg">
          跳过
          <span className="kn-kbd">S</span>
        </button>
        <button className="kn-btn primary lg" style={{ flex: 1 }}>
          通过 → notes/
          <span className="kn-kbd" style={{ background: "rgba(22,24,33,0.18)", borderColor: "rgba(22,24,33,0.18)", color: "rgba(22,24,33,0.7)" }}>A</span>
        </button>
        <span style={{ flex: 0, fontSize: 11, color: "var(--ink-mute)", marginLeft: 8 }}>
          ← prev <span className="kn-kbd">J</span>  next <span className="kn-kbd">K</span> →
        </span>
      </div>
    </footer>
  </div>
);

window.DraftsScreen = DraftsScreen;
