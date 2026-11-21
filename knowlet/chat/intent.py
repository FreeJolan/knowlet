"""Deterministic command detection for chat turns that skip the model.

Some note / draft chat turns are routed straight to a write tool before the
LLM sees them. A false positive there is an unrequested write (a note
overwritten, a draft committed), while a false negative only falls through
to the model, which has the same tools and can still call them. Matching is
therefore narrow on purpose:

- the command phrase must open the message, optionally after a polite or
  affirmative lead-in ("请", "好的,", "please", ...);
- what follows the phrase must be a single short clause (no compound
  "do X, then Y" requests);
- any question or negation anywhere in the message disqualifies it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_LEAD_INS = (
    "麻烦帮我",
    "麻烦你",
    "麻烦",
    "请帮我",
    "请你",
    "请",
    "帮我",
    "那就",
    "那",
    "就",
    "直接",
    "现在",
    "好的",
    "好",
    "行",
    "可以",
    "嗯",
    "没问题",
    "go ahead and",
    "please",
    "okay",
    "ok",
    "yes",
    "sure",
    "now",
    "just",
    "then",
    "let's",
)

# Full-width CJK punctuation (question mark, comma, semicolon, ...) is
# written as \uXXXX escapes.
_QUESTION_MARKERS = (
    "?",
    "\uff1f",
    "吗",
    "呢",
    "如何",
    "为什么",
    "为何",
    "怎么",
    "怎样",
    "什么",
    "是否",
    "能否",
    "可否",
    "有没有",
    "哪",
    "should i",
    "should we",
    "what",
    "why",
    "how",
    "whether",
    "can you",
    "could you",
    "would you",
    "do i",
    "is it",
    "is this",
)

# "要不要" / "对不对" / "可不可以": the A-不-A question form.
_A_NOT_A_QUESTION = re.compile(r"([\u4e00-\u9fff])不\1")

_NEGATION_MARKERS = (
    "不要",
    "不用",
    "不需要",
    "不必",
    "无需",
    "别",
    "先不",
    "暂不",
    "暂时不",
    "不想",
    "不打算",
    "取消",
    "算了",
    "等等",
    "等一下",
    "稍等",
    "don't",
    "dont",
    "do not",
    "not",
    "never",
    "no",
    "stop",
    "wait",
    "cancel",
    "hold on",
)

_CLAUSE_BREAKS = ",\uff0c;\uff1b\u3002.!\uff01\u3001\n"
_TRAILING = " \t,\uff0c.\u3002!\uff01~\uff5e;\uff1b:\uff1a\u3001吧了啊呀哦啦嘛"
_MAX_TAIL_CHARS = 24


def _is_ascii_word_char(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch in "_'")


def _marker_pattern(marker: str) -> re.Pattern[str]:
    escaped = re.escape(marker)
    if marker[0].isascii() and marker[0].isalnum():
        escaped = r"(?<![a-z0-9_'])" + escaped
    if marker[-1].isascii() and marker[-1].isalnum():
        escaped = escaped + r"(?![a-z0-9_'])"
    return re.compile(escaped)


_QUESTION_PATTERNS = [_marker_pattern(m) for m in _QUESTION_MARKERS]
_NEGATION_PATTERNS = [_marker_pattern(m) for m in _NEGATION_MARKERS]


def normalize(text: str) -> str:
    return " ".join(text.lower().split())


def is_question(text: str) -> bool:
    t = normalize(text)
    return bool(_A_NOT_A_QUESTION.search(t)) or any(p.search(t) for p in _QUESTION_PATTERNS)


def has_negation(text: str) -> bool:
    t = normalize(text)
    return any(p.search(t) for p in _NEGATION_PATTERNS)


def _starts_with_token(text: str, token: str) -> bool:
    if not text.startswith(token):
        return False
    if _is_ascii_word_char(token[-1]) and len(text) > len(token):
        return not _is_ascii_word_char(text[len(token)])
    return True


def _strip_lead_ins(text: str) -> str:
    stripped = True
    while stripped:
        stripped = False
        text = text.lstrip(" " + _CLAUSE_BREAKS)
        for lead in _LEAD_INS:
            if _starts_with_token(text, lead):
                text = text[len(lead) :]
                stripped = True
                break
    return text


def _is_single_short_clause(tail: str) -> bool:
    rest = tail.rstrip(_TRAILING)
    if len(rest) > _MAX_TAIL_CHARS:
        return False
    return not any(ch in _CLAUSE_BREAKS for ch in rest)


def is_leading_command(text: str, phrases: Iterable[str]) -> bool:
    """True when ``text`` is an imperative that opens with one of
    ``phrases`` (lower-case), per the module rules above."""
    t = normalize(text)
    if not t or is_question(t) or has_negation(t):
        return False
    body = _strip_lead_ins(t)
    for phrase in sorted(phrases, key=len, reverse=True):
        if _starts_with_token(body, phrase):
            return _is_single_short_clause(body[len(phrase) :])
    return False
