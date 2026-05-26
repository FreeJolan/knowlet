"""Note-anchored chat: a ``ChatSession`` grounded in one note.

Phase 3 Stage 4 (P1 — grounded discussion pane). This is the
"chat about this note" primitive (Cursor-style): the anchored note's
title + body are folded into the user turn so the user never
re-explains what they're discussing — that closes pain (a) ("每次都要
重新介绍上下文") from the redesign.

Logic lives here in ``knowlet/chat/`` (not the web layer) so the CLI /
future MCP can build the *same* grounded session; the web endpoint is a
thin SSE shell over :func:`build_note_chat_session` (ADR-0008 — one
source of streaming behavior, reachable from every interface).

Tone is inferred from the note's nature: emotional material gets a
warm mirror; formal material gets a sharper critic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from knowlet.chat.session import ChatSession
from knowlet.core.note import Note

# The AI infers its tone from the note's NATURE — there is no
# user-selected stance. We list a few illustrative cases (gentle for
# personal/emotional writing, sharp for formal/academic material) but
# explicitly do NOT restrict the model to them; it judges from the
# actual content. This block rides in the user turn alongside the note
# (build_grounded_turn), so the model always has the material to judge.
TONE_GUIDANCE = (
    "回答前,先判断这篇笔记是什么性质的材料,并据此调整你的口吻,不要千篇一律。"
    "几个参考(只是例子,不是固定选项——材料真实什么样就怎么来):\n"
    "- 日记、随笔、情绪或心理感受类的私人记录 → 像镜子一样先接住和映照具体感受:"
    "引用笔记里的具体处境/词语回应,少评价;不急着给建议、不纠错、不优化人生;"
    "不要诊断、贴标签或判断对错;不灌鸡汤,避免'一切都会好起来'、'你已经很棒了'"
    "这类空泛安慰。若需要推动,最多只问一个轻问题,或给一个很小的可选下一步。\n"
    "- 论文、技术、论证类的正式严肃材料 → 认真、严谨,该尖锐就尖锐,直接指出其中"
    "的错误、漏洞和站不住的推理,不必为照顾情绪而和稀泥。\n"
    "- 其它或介于之间 → 自行拿捏分寸,贴合材料本身。\n"
    "你可以灵活判断,不限于以上几类。无论何种口吻,都扣住笔记本身的内容,"
    "不臆造笔记里没有的东西。"
)


# Some OpenAI-compatible proxies drop the caller's `system` message
# (verified 2026-05-25 via local CLI proxy:
# note in system → model answers "缺少上下文"; note in the user turn →
# grounded). So the grounding + tone guidance ride in the USER turn
# (build_grounded_turn), and the system message stays minimal.
DISCUSS_SYSTEM = "你是 knowlet 里的笔记对谈助手,只围绕用户给你的这篇笔记跟他交流。"


def build_note_chat_session(*, llm: Any, registry: Any, ctx: Any) -> ChatSession:
    """A fresh :class:`ChatSession` for a note-anchored discussion.

    Reuses the runtime's ``llm`` / ``registry`` / ``ctx`` (same wiring as
    the ask-once path). The note grounding + tone guidance ride in the user
    turn via :func:`build_grounded_turn`, **not** the system message, so
    they survive proxies that ignore system. Ephemeral per call in P1;
    per-note persistence lands in P6.
    """
    return ChatSession(
        llm=llm, registry=registry, ctx=ctx, system_prompt=DISCUSS_SYSTEM
    )


def build_grounded_turn(note: Note, user_text: str) -> str:
    """Compose the user-turn text: tone guidance + the anchored note +
    the user's message, all in one user-role string. Everything the
    model must read lives here (not in system) because some proxies drop
    system messages. The AI picks its tone from the note's nature; there
    is no user-selected stance."""
    return (
        f"{TONE_GUIDANCE}\n\n"
        f"我们在讨论我的这篇笔记:\n"
        f"<anchored-note title={note.title!r}>\n{note.body}\n</anchored-note>\n\n"
        f"我的话:{user_text}"
    )


# ---------------------------------------------------- propose edit (P3)

# The note-edit posture: produce a MINIMAL, localized revision so the
# diff stays small and reviewable. A full rewrite makes the diff
# unreadable and defeats the point of review (B.3 stuck-point).
EDIT_SYSTEM = (
    "用户想根据下面的请求修改这篇笔记。产出修改后的**完整正文**,但改动"
    "必须**最小、局部**——只动需要动的地方,其余部分逐字保持不变(这样 diff "
    "才小、可审)。不要重写整篇,不要改写风格。\n"
    '只输出 JSON,形如:{"new_body": "<修改后的完整正文>"}。'
    "若判断无需改动,把原正文原样放进 new_body。"
)


@dataclass
class ProposedEdit:
    """A proposed revision to a note's body. ``changed`` is False when
    the model returned the body unchanged or produced no usable edit —
    the caller renders '无可应用改动' rather than an empty diff."""

    old_body: str
    new_body: str
    changed: bool
    reason: str = ""


def _extract_new_body(content: str) -> str | None:
    """Pull ``new_body`` out of the model's reply, tolerating ```json
    code fences. Returns None when the reply isn't usable JSON."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    new_body = data.get("new_body")
    return new_body if isinstance(new_body, str) else None


def propose_note_edit(*, llm: Any, note: Note, instruction: str) -> ProposedEdit:
    """Ask the LLM for a minimal revision of ``note``'s body following
    ``instruction``. One-shot (non-streaming); returns old + new body
    for the diff UI. **Never writes** — the user accepts the diff in
    P4 (ADR-0029 原则 1). A malformed reply degrades to
    ``changed=False`` (no corruption), not an exception."""
    # The edit instruction goes in the USER message (not system): same
    # dropped-system proxy reality as the discussion path. Keeping it in
    # system would let proxies strip the "minimal local edit + JSON only"
    # contract, producing full rewrites / non-JSON.
    messages = [
        {"role": "system", "content": "你帮用户对自己的笔记做最小化的局部修改。"},
        {
            "role": "user",
            "content": (
                EDIT_SYSTEM + "\n\n"
                f"<note title={note.title!r}>\n{note.body}\n</note>\n\n"
                f"修改请求:{instruction}"
            ),
        },
    ]
    resp = llm.chat(messages)
    new_body = _extract_new_body(getattr(resp, "content", "") or "")
    if new_body is None:
        return ProposedEdit(
            old_body=note.body,
            new_body=note.body,
            changed=False,
            reason="无法从 AI 回复中解析出可应用的修改",
        )
    changed = new_body.strip() != note.body.strip()
    return ProposedEdit(old_body=note.body, new_body=new_body, changed=changed)


# ---------------------------------------------------- draft internalize (C3)

INTERNALIZE_SYSTEM = (
    "用户正在 digest 里阅读一条来源资料,想决定是否把它内化成自己的知识笔记。"
    "请基于资料正文,起草一版更像用户个人知识库里的笔记正文:保留关键事实和出处线索,"
    "但用清晰的主题、要点、自己的理解/可复用结论组织起来。不要虚构资料没有的内容。"
    '只输出 JSON,形如:{"new_body": "<起草后的完整正文>"}。'
)


def propose_draft_internalization(
    *, llm: Any, note: Note, instruction: str
) -> ProposedEdit:
    """Ask the LLM to turn a draft/source item into a knowledge-note body.

    This is deliberately proposal-only, mirroring :func:`propose_note_edit`:
    C3's UI reviews the diff before writing the draft / approving it.
    """
    messages = [
        {"role": "system", "content": "你帮用户把来源资料内化成知识笔记。"},
        {
            "role": "user",
            "content": (
                INTERNALIZE_SYSTEM + "\n\n"
                f"<digest-draft title={note.title!r}>\n{note.body}\n</digest-draft>\n\n"
                f"用户额外要求:{instruction or '无'}"
            ),
        },
    ]
    resp = llm.chat(messages)
    new_body = _extract_new_body(getattr(resp, "content", "") or "")
    if new_body is None:
        return ProposedEdit(
            old_body=note.body,
            new_body=note.body,
            changed=False,
            reason="无法从 AI 回复中解析出可应用的内化草稿",
        )
    changed = new_body.strip() != note.body.strip()
    return ProposedEdit(old_body=note.body, new_body=new_body, changed=changed)
