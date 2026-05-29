"""Raw Info anchored chat for Stage C v2 review mode."""

from __future__ import annotations

from knowlet.core.digest_items import RawInfo


def build_raw_info_grounded_turn(item: RawInfo, user_text: str) -> str:
    """Ground a user turn in one read-only Raw Info item.

    Raw Info is source material, not an editable note. The model can discuss,
    question, compare, and suggest what to do next, but draft creation lands in
    the later note-draft tool path.
    """
    key_points = "\n".join(f"- {point}" for point in item.key_points) or "- (none)"
    tags = ", ".join(item.suggested_tags) or "(none)"
    excerpt = item.content_excerpt or "(none)"
    why = item.why_it_matters or "(none)"
    return f"""\
You are discussing one read-only Raw Info item in Knowlet's digest review flow.
Do not claim that the item has been edited or saved as a note. If the user asks
to change it, explain that the next step is to settle it into an editable note
draft first.

Raw Info:
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

User message:
{user_text}
"""
