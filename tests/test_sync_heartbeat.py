from __future__ import annotations

from unittest.mock import MagicMock

from knowlet.core.sync.heartbeat import list_alive_devices, write_my_heartbeat


def test_list_alive_devices_filters_trashed_heartbeats() -> None:
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {"files": []}

    assert list_alive_devices(service) == []

    list_kwargs = service.files.return_value.list.call_args.kwargs
    assert list_kwargs["spaces"] == "appDataFolder"
    assert list_kwargs["q"] == "name contains '.heartbeat.json' and trashed=false"


def test_write_my_heartbeat_does_not_reuse_trashed_heartbeat(monkeypatch) -> None:
    service = MagicMock()
    service.files.return_value.list.return_value.execute.return_value = {"files": []}
    captured: dict[str, object] = {}

    def fake_upload_new_file(
        _service,
        *,
        name,
        content,
        mime_type,
        parent_folder_id=None,
    ):
        captured["name"] = name
        captured["content"] = content
        captured["mime_type"] = mime_type
        captured["parent_folder_id"] = parent_folder_id

    monkeypatch.setattr(
        "knowlet.core.sync.heartbeat.upload_new_file",
        fake_upload_new_file,
    )

    write_my_heartbeat(service, device_id="DEVICE-1", device_label="Studio Mac")

    list_kwargs = service.files.return_value.list.call_args.kwargs
    assert list_kwargs["spaces"] == "appDataFolder"
    assert list_kwargs["q"] == "name = 'DEVICE-1.heartbeat.json' and trashed=false"
    assert captured["name"] == "DEVICE-1.heartbeat.json"
