"""Single-note calibration ("查这篇") for Stage D.

This is the narrow, user-triggered successor to the old full-vault linter
idea: check one note against an optional standard answer, return a structured
report, and never write to the vault. Fixes go through the existing diff
review path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

from knowlet.core.note import Note

Severity = Literal["high", "medium", "low"]


CHECK_SYSTEM = (
    "你是 knowlet 的单篇笔记校准助手。你的任务是帮用户检查这篇笔记相对"
    "标准答案/校准依据有哪些事实错误、推理漏洞或关键遗漏。只报告你能指向"
    "具体段落的问题;不要改正文,不要替用户重写。若没有足够依据,宁可少报。"
)

CHECK_USER_RULES = (
    "请只输出 JSON,形如:\n"
    '{"summary":"一句话总结","findings":[{"severity":"high|medium|low",'
    '"paragraph":1,"quote":"原文短引","finding":"错漏是什么",'
    '"why":"为什么这是问题","suggestion":"应该补/改什么",'
    '"fix_instruction":"给后续 diff 编辑器的一句话修改指令","confidence":0.0}]}\n'
    "规则:\n"
    "- findings 最多 5 条,按重要性排序。\n"
    '- paragraph 必须对应下方 <paragraph n="..."> 的编号;无法定位就填 null。\n'
    "- quote 必须来自笔记原文,短而具体。\n"
    "- fix_instruction 要可直接交给编辑助手生成最小 diff。\n"
    "- confidence 低于 0.5 的问题不要输出。\n"
)

NO_STANDARD_FALLBACK = "(用户没有提供标准答案;只检查笔记自洽性和明显事实错漏)"


@dataclass
class CheckNoteFinding:
    severity: Severity
    paragraph: int | None
    quote: str
    finding: str
    why: str
    suggestion: str
    fix_instruction: str
    confidence: float = 0.0


@dataclass
class CheckNoteReport:
    summary: str
    findings: list[CheckNoteFinding] = field(default_factory=list)


def _extract_json_object(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _numbered_paragraphs(body: str) -> list[tuple[int, str]]:
    chunks = [p.strip() for p in body.split("\n\n") if p.strip()]
    if not chunks and body.strip():
        chunks = [body.strip()]
    return [(idx, text) for idx, text in enumerate(chunks, start=1)]


def _render_numbered_note(note: Note) -> str:
    paragraphs = _numbered_paragraphs(note.body)
    if not paragraphs:
        return '<paragraph n="1">\n\n</paragraph>'
    return "\n\n".join(f'<paragraph n="{idx}">\n{text}\n</paragraph>' for idx, text in paragraphs)


def _coerce_severity(value: Any) -> Severity:
    return value if value in {"high", "medium", "low"} else "medium"


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _parse_report(content: str) -> CheckNoteReport:
    data = _extract_json_object(content)
    if data is None:
        return CheckNoteReport(
            summary="无法从 AI 回复中解析出可用报告",
            findings=[],
        )
    findings: list[CheckNoteFinding] = []
    raw_findings = data.get("findings")
    if isinstance(raw_findings, list):
        for item in raw_findings[:5]:
            if not isinstance(item, dict):
                continue
            confidence = _coerce_confidence(item.get("confidence"))
            paragraph_raw = item.get("paragraph")
            try:
                paragraph = int(paragraph_raw) if paragraph_raw is not None else None
            except (TypeError, ValueError):
                paragraph = None
            findings.append(
                CheckNoteFinding(
                    severity=_coerce_severity(item.get("severity")),
                    paragraph=paragraph,
                    quote=str(item.get("quote") or "").strip(),
                    finding=str(item.get("finding") or "").strip(),
                    why=str(item.get("why") or "").strip(),
                    suggestion=str(item.get("suggestion") or "").strip(),
                    fix_instruction=str(item.get("fix_instruction") or "").strip(),
                    confidence=confidence,
                )
            )
    summary = str(data.get("summary") or "").strip()
    return CheckNoteReport(summary=summary or "未发现明确错漏", findings=findings)


def check_note(
    *,
    llm: Any,
    note: Note,
    standard_answer: str = "",
    instruction: str = "",
) -> CheckNoteReport:
    """Check a single note and return a structured report.

    No writes. The note body is paragraph-numbered so findings can point
    back to concrete locations, and the prompt rides in the user message
    so OpenAI-compatible proxies that drop system still preserve the task.
    """
    standard = standard_answer.strip()
    task = instruction.strip()
    standard_block = standard or NO_STANDARD_FALLBACK
    messages = [
        {"role": "system", "content": CHECK_SYSTEM},
        {
            "role": "user",
            "content": (
                CHECK_USER_RULES + "\n"
                f"<note title={note.title!r}>\n"
                f"{_render_numbered_note(note)}\n"
                "</note>\n\n"
                f"<standard-answer>\n{standard_block}\n"
                "</standard-answer>\n\n"
                f"<extra-instruction>\n{task or '无'}\n</extra-instruction>"
            ),
        },
    ]
    resp = llm.chat(messages)
    return _parse_report(getattr(resp, "content", "") or "")
