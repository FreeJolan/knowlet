"""Phase 2 E Slice 5.B — Drive Changes API wrapper (ADR-0027).

Mocks the discovery service entirely. The real Changes API is
already exercised by Slice 5.A's manual OAuth flow + `sync pull`
smoke; here we lock down the parsing + pagination logic.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from knowlet.core.sync.changes import (
    ChangesPage,
    DriveChange,
    get_initial_start_page_token,
    list_all_changes,
    list_changes,
)


def _make_client_with_service(service: object) -> object:
    """Build a fake DriveClient whose .service() returns the mock."""
    client = MagicMock()
    client.service.return_value = service
    return client


def test_get_initial_start_page_token_returns_token() -> None:
    service = MagicMock()
    service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
        "startPageToken": "INITIAL-123"
    }
    token = get_initial_start_page_token(_make_client_with_service(service))
    assert token == "INITIAL-123"


def test_list_changes_parses_response() -> None:
    service = MagicMock()
    service.changes.return_value.list.return_value.execute.return_value = {
        "newStartPageToken": "FINAL-999",
        "changes": [
            {
                "fileId": "FID-1",
                "removed": False,
                "file": {
                    "name": "alpha.md",
                    "modifiedTime": "2026-05-10T12:00:00Z",
                    "mimeType": "text/markdown",
                    "trashed": False,
                },
            },
            {
                "fileId": "FID-2",
                "removed": True,
                "file": None,
            },
            {
                "fileId": "FID-3",
                "removed": False,
                "file": {
                    "name": "trashed.md",
                    "trashed": True,
                },
            },
        ],
    }
    page = list_changes(
        _make_client_with_service(service), page_token="START"
    )
    # 5.C.1: list must scope to the hidden appDataFolder; under
    # drive.appdata we have no business reading the main Drive.
    list_kwargs = service.changes.return_value.list.call_args.kwargs
    assert list_kwargs.get("spaces") == "appDataFolder"
    assert page.next_token is None
    assert page.new_start_page_token == "FINAL-999"
    assert len(page.changes) == 3
    a, b, c = page.changes
    assert a == DriveChange(
        file_id="FID-1",
        removed=False,
        trashed=False,
        file={
            "name": "alpha.md",
            "modifiedTime": "2026-05-10T12:00:00Z",
            "mimeType": "text/markdown",
            "trashed": False,
        },
    )
    assert b.removed is True and b.file is None
    assert c.trashed is True and c.removed is False


def test_list_all_changes_paginates_to_completion() -> None:
    service = MagicMock()
    # First page: nextPageToken='P2', no newStartPageToken → keep going.
    # Second page: nextPageToken=None, newStartPageToken='FINAL'.
    service.changes.return_value.list.return_value.execute.side_effect = [
        {
            "nextPageToken": "P2",
            "changes": [
                {"fileId": "A", "removed": False, "file": {"name": "a.md"}},
            ],
        },
        {
            "newStartPageToken": "FINAL",
            "changes": [
                {"fileId": "B", "removed": False, "file": {"name": "b.md"}},
                {"fileId": "C", "removed": True, "file": None},
            ],
        },
    ]
    all_changes, final_token = list_all_changes(
        _make_client_with_service(service), page_token="P1"
    )
    assert final_token == "FINAL"
    assert [c.file_id for c in all_changes] == ["A", "B", "C"]


def test_list_all_changes_empty_response() -> None:
    """No changes since last poll — Drive still returns
    newStartPageToken so we advance the cursor."""
    service = MagicMock()
    service.changes.return_value.list.return_value.execute.return_value = {
        "newStartPageToken": "ADVANCED",
        "changes": [],
    }
    all_changes, token = list_all_changes(
        _make_client_with_service(service), page_token="START"
    )
    assert all_changes == []
    assert token == "ADVANCED"


def test_changes_page_dataclass_immutable() -> None:
    """Smoke that the wrapper types are constructible + comparable."""
    p1 = ChangesPage(changes=[], next_token=None, new_start_page_token="T")
    p2 = ChangesPage(changes=[], next_token=None, new_start_page_token="T")
    assert p1 == p2
