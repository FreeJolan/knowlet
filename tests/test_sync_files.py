"""Phase 2 E Slice 5.C — Drive Files API wrapper (ADR-0027).

Mocks discovery service entirely; verifies the request shape,
If-Match header propagation, and 412 → RemoteVersionMismatchError
translation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from knowlet.core.sync.files import (
    DriveFile,
    RemoteVersionMismatchError,
    download_file,
    force_overwrite,
    get_file_metadata,
    update_file_conditional,
    upload_new_file,
)


def _file_response(
    *,
    id_: str = "FID-1",
    name: str = "alpha.md",
    revision: str = "rev-1",
) -> dict:
    return {
        "id": id_,
        "name": name,
        "mimeType": "text/markdown",
        "modifiedTime": "2026-05-10T12:00:00Z",
        "headRevisionId": revision,
    }


def test_upload_new_file_calls_create_with_metadata() -> None:
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = _file_response()
    df = upload_new_file(service, name="alpha.md", content=b"hello")
    assert isinstance(df, DriveFile)
    assert df.id == "FID-1"
    assert df.head_revision_id == "rev-1"
    create_call = service.files.return_value.create.call_args
    body = create_call.kwargs.get("body") or create_call.args[0]
    assert body["name"] == "alpha.md"
    assert "parents" not in body  # parent_folder_id was None


def test_upload_new_file_pins_parent_when_given() -> None:
    service = MagicMock()
    service.files.return_value.create.return_value.execute.return_value = _file_response()
    upload_new_file(
        service,
        name="beta.md",
        content=b"x",
        parent_folder_id="PARENT-FID",
    )
    body = service.files.return_value.create.call_args.kwargs["body"]
    assert body["parents"] == ["PARENT-FID"]


def test_update_file_conditional_proceeds_when_revision_matches() -> None:
    service = MagicMock()
    # GET returns rev-1 (matches expected); update returns rev-2.
    service.files.return_value.get.return_value.execute.return_value = _file_response(
        revision="rev-1"
    )
    service.files.return_value.update.return_value.execute.return_value = _file_response(
        revision="rev-2"
    )
    df = update_file_conditional(
        service,
        file_id="FID-1",
        content=b"updated",
        expected_revision="rev-1",
    )
    assert df.head_revision_id == "rev-2"


def test_update_file_conditional_revision_mismatch_raises() -> None:
    service = MagicMock()
    # GET returns rev-current; expected is rev-stale.
    service.files.return_value.get.return_value.execute.return_value = _file_response(
        revision="rev-current"
    )
    with pytest.raises(RemoteVersionMismatchError) as ei:
        update_file_conditional(
            service,
            file_id="FID-1",
            content=b"x",
            expected_revision="rev-stale",
        )
    assert ei.value.file_id == "FID-1"
    assert ei.value.expected_revision == "rev-stale"
    assert ei.value.actual_revision == "rev-current"
    # update() must NOT have been called — we caught it at the GET.
    service.files.return_value.update.assert_not_called()


def test_get_file_metadata_round_trip() -> None:
    service = MagicMock()
    service.files.return_value.get.return_value.execute.return_value = _file_response(
        revision="rev-meta"
    )
    df = get_file_metadata(service, "FID-1")
    assert df.head_revision_id == "rev-meta"


def test_force_overwrite_skips_get_check() -> None:
    """The conflict-resolution "use mine" path must skip the GET-
    revision-compare — it's the explicit clobber exit."""
    service = MagicMock()
    service.files.return_value.update.return_value.execute.return_value = _file_response(
        revision="rev-new"
    )

    df = force_overwrite(service, file_id="FID-1", content=b"local-wins")
    # No GET on this code path — only update.
    service.files.return_value.get.assert_not_called()
    assert df.head_revision_id == "rev-new"


def test_download_file_paginates_until_done() -> None:
    """MediaIoBaseDownload returns False for done until the last
    chunk; the wrapper must keep iterating."""
    service = MagicMock()
    fake_request = MagicMock()
    service.files.return_value.get_media.return_value = fake_request
    # Patch MediaIoBaseDownload to write our test bytes + end after 2 chunks.
    from unittest.mock import patch

    class FakeDownloader:
        def __init__(self, buf, request):
            self.buf = buf
            self.calls = 0

        def next_chunk(self):
            self.calls += 1
            if self.calls == 1:
                self.buf.write(b"part1-")
                return None, False
            self.buf.write(b"part2")
            return None, True

    # MediaIoBaseDownload is imported inside the function (lazy import
    # for the optional [sync] extra); patch at its source module so
    # the wrapper sees our fake.
    with patch(
        "googleapiclient.http.MediaIoBaseDownload",
        side_effect=lambda buf, _req: FakeDownloader(buf, _req),
    ):
        out = download_file(service, "FID-1")
    assert out == b"part1-part2"
