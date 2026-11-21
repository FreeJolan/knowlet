"""Found while dogfooding against a real model: asked to "edit X and apply it"
in one turn, the model proposed a diff and then called apply, which is
refused by design (only a user-reviewed diff can be applied). The refusal
told the model to "generate a diff proposal first", so it reported to the
user that the tool contradicted the proposal it had just made. The guidance
must say the proposal is waiting for the user's review instead."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from knowlet.chat.current_note_tools import _apply_current_note_edit


def test_apply_without_reviewed_diff_points_to_user_review(tmp_path: Path) -> None:
    ctx = SimpleNamespace(user_request_text="把这句改掉, 然后直接应用修改", pending_note_edit=None)

    result = _apply_current_note_edit({}, ctx)  # type: ignore[arg-type]

    assert result["error"] == "no pending note edit"
    suggestion = result["suggestion"].lower()
    assert "review" in suggestion
    assert "do not call" in suggestion
