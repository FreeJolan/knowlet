"""Desktop packaging regression tests."""

from __future__ import annotations

from pathlib import Path


def test_desktop_sidecar_build_installs_sync_extra() -> None:
    script = Path("scripts/desktop/build-backend-sidecars.sh").read_text(encoding="utf-8")

    assert '"$ROOT[sync]"' in script, (
        "The desktop backend sidecar must bundle Google Drive sync dependencies; "
        'install the project as "$ROOT[sync]" in build-backend-sidecars.sh.'
    )
