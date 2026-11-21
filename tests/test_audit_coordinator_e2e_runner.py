"""frontend/scripts/e2e/run-all.mjs must honour SKIP_BUILD=1 (CI builds dist
in its own step and passes SKIP_BUILD so the frontend isn't built twice)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RUN_ALL = Path("frontend/scripts/e2e/run-all.mjs")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_run_all_skips_build_when_skip_build_is_set(tmp_path: Path) -> None:
    # A copy in an empty directory: no suites to run and no frontend/ to
    # build, so the only way to exit 0 is to skip the build entirely.
    e2e_dir = tmp_path / "a" / "b" / "e2e"
    e2e_dir.mkdir(parents=True)
    script = e2e_dir / "run-all.mjs"
    script.write_text(RUN_ALL.read_text(encoding="utf-8"), encoding="utf-8")

    proc = subprocess.run(
        ["node", str(script)],
        env={**os.environ, "SKIP_BUILD": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0/0 suites passed" in proc.stdout
