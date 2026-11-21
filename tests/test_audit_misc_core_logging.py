"""Regression tests for the misc-core audit batch — shared knowlet.log.

Two processes on the same vault (desktop sidecar + a terminal
``knowlet web``) each attach a file handler to
``<vault>/.knowlet/knowlet.log``. With ``RotatingFileHandler`` the
process that did not rotate keeps writing into the renamed ``.1`` file
and its own later rollover clobbers the other's backup chain.

Each ``configure_logging`` call here stands in for one process: the
root handlers are cleared between calls so the second call builds an
independent handler (own file descriptor) on the same path.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from knowlet._logging import configure_logging


@pytest.fixture
def clean_root_logger() -> Iterator[None]:
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    yield
    for h in list(root.handlers):
        if h not in saved_handlers:
            root.removeHandler(h)
            h.close()
    root.setLevel(saved_level)


def _file_handler_for_new_process(vault: Path) -> logging.FileHandler:
    root = logging.getLogger()
    for h in [h for h in root.handlers if getattr(h, "_knowlet_configured", False)]:
        root.removeHandler(h)
    configure_logging(vault)
    handlers = [
        h
        for h in root.handlers
        if getattr(h, "_knowlet_configured", False) and isinstance(h, logging.FileHandler)
    ]
    assert len(handlers) == 1
    fh = handlers[0]
    root.removeHandler(fh)  # drive it directly; keep test output clean
    for h in [h for h in root.handlers if getattr(h, "_knowlet_configured", False)]:
        root.removeHandler(h)
    return fh


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("knowlet.test", logging.INFO, __file__, 1, msg, None, None)


def _all_log_lines(log_dir: Path) -> list[str]:
    lines: list[str] = []
    for p in sorted(log_dir.glob("knowlet.log*")):
        if p.suffix == ".lock":
            continue
        lines.extend(p.read_text(encoding="utf-8").splitlines())
    return lines


def test_two_processes_share_rotation_without_losing_or_misplacing_lines(
    tmp_path: Path, clean_root_logger: None
) -> None:
    (tmp_path / ".knowlet").mkdir()
    a = _file_handler_for_new_process(tmp_path)
    b = _file_handler_for_new_process(tmp_path)
    for h in (a, b):
        h.maxBytes = 400  # type: ignore[attr-defined]
        h.backupCount = 50  # type: ignore[attr-defined]

    emitted: list[str] = []
    try:
        for i in range(40):
            for name, h in (("A", a), ("B", b)):
                msg = f"{name}-{i:03d}-" + "x" * 40
                h.handle(_record(msg))
                emitted.append(msg)
    finally:
        a.close()
        b.close()

    log_dir = tmp_path / ".knowlet"
    lines = _all_log_lines(log_dir)
    found = [m for m in emitted if any(line.endswith(m) for line in lines)]
    assert found == emitted, "every record must survive both processes' rotations"
    assert len(lines) == len(emitted), "no record may be written twice"

    # The live file holds the newest records from BOTH processes — the
    # non-rotating process must have followed the rename.
    current = (log_dir / "knowlet.log").read_text(encoding="utf-8")
    assert emitted[-1] in current
    assert emitted[-2] in current


def test_backup_count_is_enforced(tmp_path: Path, clean_root_logger: None) -> None:
    (tmp_path / ".knowlet").mkdir()
    h = _file_handler_for_new_process(tmp_path)
    h.maxBytes = 200  # type: ignore[attr-defined]
    h.backupCount = 2  # type: ignore[attr-defined]
    try:
        for i in range(60):
            h.handle(_record(f"line-{i:03d}-" + "y" * 40))
    finally:
        h.close()
    log_dir = tmp_path / ".knowlet"
    names = sorted(p.name for p in log_dir.glob("knowlet.log*") if p.suffix != ".lock")
    assert names == ["knowlet.log", "knowlet.log.1", "knowlet.log.2"]
    assert "line-059" in (log_dir / "knowlet.log").read_text(encoding="utf-8")


def test_reconfigure_for_other_vault_retargets_file_handler(
    tmp_path: Path, clean_root_logger: None
) -> None:
    root = logging.getLogger()
    for h in [h for h in root.handlers if getattr(h, "_knowlet_configured", False)]:
        root.removeHandler(h)
    v1 = tmp_path / "v1"
    v2 = tmp_path / "v2"
    for v in (v1, v2):
        (v / ".knowlet").mkdir(parents=True)

    configure_logging(v1)
    configure_logging(v2)
    logging.getLogger("knowlet.test").warning("after-switch")
    for h in root.handlers:
        h.flush()

    assert "after-switch" in (v2 / ".knowlet" / "knowlet.log").read_text(encoding="utf-8")
    assert "after-switch" not in (v1 / ".knowlet" / "knowlet.log").read_text(encoding="utf-8")
    stderr_handlers = [
        h
        for h in root.handlers
        if getattr(h, "_knowlet_configured", False) and not isinstance(h, logging.FileHandler)
    ]
    assert len(stderr_handlers) == 1
