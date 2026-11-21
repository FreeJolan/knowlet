"""Desktop packaging regression tests."""

from __future__ import annotations

from pathlib import Path


def test_desktop_sidecar_build_installs_sync_extra() -> None:
    script = Path("scripts/desktop/build-backend-sidecars.sh").read_text(encoding="utf-8")

    export_cmd = script.split("uv export", 1)[1].split("\n\n", 1)[0]
    assert "--extra sync" in export_cmd, (
        "The desktop backend sidecar must bundle Google Drive sync dependencies; "
        "export the locked requirements with `--extra sync` in "
        "build-backend-sidecars.sh."
    )
