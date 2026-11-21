"""Raw Info anchored chat for Stage C v2 review mode."""

from __future__ import annotations

from knowlet.chat.intent import is_leading_command
from knowlet.core.digest_items import RawInfo
from knowlet.core.drafts import Draft


def build_raw_info_grounded_turn(
    item: RawInfo,
    user_text: str,
    *,
    draft: Draft | None = None,
) -> str:
    """Ground a user turn in one read-only Raw Info item.

    Raw Info is source material, not an editable note. The model can discuss,
    question, compare, and suggest what to do next, but draft creation lands in
    the later note-draft tool path.
    """
    key_points = "\n".join(f"- {point}" for point in item.key_points) or "- (none)"
    tags = ", ".join(item.suggested_tags) or "(none)"
    excerpt = item.content_excerpt or "(none)"
    why = item.why_it_matters or "(none)"
    draft_block = ""
    if draft is not None:
        draft_block = f"""
Current editable note Draft:
- Draft ID: {draft.id}
- Title: {draft.title}
- Kind: {draft.kind}
- Folder: {draft.folder or "(root)"}
- Tags: {", ".join(draft.tags) or "(none)"}
- Has pending diff: {"yes" if draft.pending_diff_body is not None else "no"}
<current-draft-body>
{draft.body}
</current-draft-body>

If the user asks to revise/fix/polish/modify this draft, call
propose_current_draft_edit. If the user asks to accept/apply all draft changes,
call accept_all_draft_diff. If the user asks to reject/discard/撤回 the draft
diff, call reject_all_draft_diff. If the user asks to commit/save/落库 the draft
as a formal note, call commit_note_draft. These operations affect the Draft or
final Note; the Raw Info item itself remains read-only.
"""
    return f"""\
You are discussing one read-only Raw Info item in Knowlet's digest review flow.
Do not claim that the item has been edited or saved as a note. If the user asks
to change it, explain that the next step is to settle it into an editable note
draft first. If the user asks to settle/save/turn this item into a note draft,
call the create_note_draft_from_info tool. That tool creates a Draft only; it
does not commit a formal Note.
If the user explicitly asks to discard/drop/舍弃/丢弃 this Raw Info item from
the review queue, call discard_raw_info instead of editing the Raw Info.

Raw Info:
- ID: {item.id}
- Title: {item.title}
- Source: {item.source_name} ({item.source_kind})
- Original URL: {item.url}
- Status: {item.status}
- Published: {item.published_at or "unknown"}
- Fetched: {item.fetched_at}
- Summary: {item.summary}
- Key points:
{key_points}
- Why it matters: {why}
- Suggested tags: {tags}
- Excerpt:
{excerpt}
{draft_block}

User message:
{user_text}
"""


def wants_current_draft_edit_proposal(text: str) -> bool:
    lowered = text.lower()
    needles = (
        "revise",
        "rewrite",
        "edit",
        "polish",
        "fix",
        "diff",
        "修改",
        "修正",
        "改写",
        "润色",
        "整理",
        "更清晰",
        "提案",
    )
    return any(needle in lowered for needle in needles)


# The routers below run write tools without asking the model, so they only
# fire for sentence-initial commands; questions / negations / compound
# requests fall through to the model (see knowlet.chat.intent).

_ACCEPT_ALL_PHRASES = (
    "accept all",
    "apply all",
    "apply the changes",
    "接受所有",
    "接受全部",
    "应用所有",
    "应用全部",
    "全部接受",
    "全部应用",
    "应用修改",
    "接受修改",
)

_REJECT_ALL_PHRASES = (
    "reject all",
    "discard",
    "revert",
    "withdraw",
    "拒绝所有",
    "全部撤回",
    "撤回",
    "放弃修改",
)

_COMMIT_PHRASES = (
    "commit",
    "save as note",
    "save as a note",
    "save it as a note",
    "add to knowledge base",
    "add to the knowledge base",
    "add it to the knowledge base",
    "add this to the knowledge base",
    "落库",
    "入库",
    "保存为正式笔记",
    "保存为笔记",
    "存为正式笔记",
    "存为笔记",
    "转为正式笔记",
    "转成正式笔记",
    "纳入知识库",
)

_DISCARD_RAW_INFO_PHRASES = (
    "discard this item",
    "discard this raw info",
    "drop this item",
    "remove this item from review",
    "舍弃这条",
    "丢弃这条",
    "放弃这条资讯",
)


def wants_accept_all_draft_diff(text: str) -> bool:
    return is_leading_command(text, _ACCEPT_ALL_PHRASES)


def wants_reject_all_draft_diff(text: str) -> bool:
    return is_leading_command(text, _REJECT_ALL_PHRASES)


def wants_commit_note_draft(text: str) -> bool:
    return is_leading_command(text, _COMMIT_PHRASES)


def wants_discard_raw_info(text: str) -> bool:
    return is_leading_command(text, _DISCARD_RAW_INFO_PHRASES)
