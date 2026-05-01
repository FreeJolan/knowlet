"""get_user_profile — read the user's `<vault>/users/me.md` profile.

Provided as an atomic tool (in addition to system-prompt embedding) so that
backends which ignore role:'system' instructions can still reach the profile
on demand. See ADR-0008 for the rationale.
"""

from __future__ import annotations

from typing import Any

from knowlet.core.tools._registry import ToolContext, ToolDef
from knowlet.core.user_profile import read_profile


def _handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    profile = read_profile(ctx.vault.profile_path)
    if profile is None:
        return {
            "exists": False,
            "suggestion": (
                "User has not created a profile yet. Tell them they can run "
                "`knowlet user edit` (or `:user edit` inside the chat) to write one."
            ),
        }
    return {
        "exists": True,
        "name": profile.name,
        "body": profile.truncated_for_prompt(),
        "updated_at": profile.updated_at,
    }


TOOL = ToolDef(
    name="get_user_profile",
    description=(
        "Fetch the user's personal profile (goals, expertise, preferences, "
        "current focus areas) from <vault>/users/me.md. Call this when the "
        "user asks something that depends on knowing who they are, when you "
        "need to tailor tone or depth, or when the user mentions 'my profile' "
        "or 'who I am'."
    ),
    input_schema={
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    handler=_handler,
)
