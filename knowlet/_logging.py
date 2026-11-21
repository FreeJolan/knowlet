"""Logging configuration for long-running knowlet processes.

Short-lived CLI commands print to Rich console and don't need this. The
`knowlet web` server, however, runs APScheduler in the background — if the
user has closed the terminal, a scheduler exception with no log output is
invisible. This module wires:

- a stderr handler (visible while the terminal is open), and
- a size-rotated file handler under `<vault>/.knowlet/knowlet.log`
  (recoverable later), safe to share between several processes on the
  same vault (desktop sidecar + a terminal `knowlet web`, say).

Call `configure_logging(vault_root)` once at process startup.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import suppress
from logging.handlers import WatchedFileHandler
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX
    fcntl = None  # type: ignore[assignment]

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_FILENAME = "knowlet.log"
_MAX_BYTES = 1_000_000  # 1 MB before rotation
_BACKUP_COUNT = 3


class SharedRotatingFileHandler(WatchedFileHandler):
    """Size-rotated log file that several processes may append to.

    ``RotatingFileHandler`` assumes a single writer: after another
    process renames ``knowlet.log`` away, it keeps writing to the
    renamed file and later rotates over the other process's backups.
    Here the size check looks at the *path*, rotation happens under an
    exclusive ``flock`` on a sibling ``.lock`` file and re-checks the
    size after acquiring it, and ``WatchedFileHandler`` makes every
    process reopen the path once it notices the inode changed.
    """

    def __init__(
        self,
        filename: Path,
        *,
        maxBytes: int = _MAX_BYTES,
        backupCount: int = _BACKUP_COUNT,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__(filename, encoding=encoding)
        self.maxBytes = maxBytes
        self.backupCount = backupCount
        self._lock_path = f"{self.baseFilename}.lock"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.maxBytes > 0 and self.backupCount > 0:
                pending = len(self.format(record)) + len(self.terminator)
                if self._path_size() + pending > self.maxBytes:
                    self._rotate_shared(pending)
        except Exception:
            self.handleError(record)
            return
        super().emit(record)

    def _path_size(self) -> int:
        try:
            return os.stat(self.baseFilename).st_size
        except FileNotFoundError:
            return 0

    def _rotate_shared(self, pending: int) -> None:
        with open(self._lock_path, "a") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                # Another process may have rotated while we waited.
                size = self._path_size()
                if size == 0 or size + pending <= self.maxBytes:
                    return
                for i in range(self.backupCount - 1, 0, -1):
                    src = f"{self.baseFilename}.{i}"
                    if os.path.exists(src):
                        os.replace(src, f"{self.baseFilename}.{i + 1}")
                os.replace(self.baseFilename, f"{self.baseFilename}.1")
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        # Our own stream now points at `.1`; WatchedFileHandler.emit
        # reopens the path on the next write.


def configure_logging(vault_root: Path | None = None, level: str = "INFO") -> None:
    """Wire root logger handlers exactly once. Idempotent.

    Calling again with a different ``vault_root`` moves the file handler
    to that vault's log instead of leaving it on the old one."""
    root = logging.getLogger()
    ours = [h for h in root.handlers if getattr(h, "_knowlet_configured", False)]
    if ours:
        if vault_root is not None:
            _retarget_file_handler(root, ours, vault_root)
        return
    root.setLevel(level)
    fmt = logging.Formatter(_FORMAT)

    stderr_h = logging.StreamHandler(sys.stderr)
    stderr_h.setFormatter(fmt)
    stderr_h._knowlet_configured = True  # type: ignore[attr-defined]
    root.addHandler(stderr_h)

    if vault_root is not None:
        _add_file_handler(root, vault_root, fmt)

    # Tone down noisy third-party loggers; they tend to log INFO-level things
    # that aren't useful in our context.
    for name in ("apscheduler", "httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _add_file_handler(root: logging.Logger, vault_root: Path, fmt: logging.Formatter) -> None:
    log_dir = vault_root / ".knowlet"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_h = SharedRotatingFileHandler(log_dir / _LOG_FILENAME)
    except OSError:
        # Read-only vault / permission error — don't crash startup; stderr
        # handler is enough.
        return
    file_h.setFormatter(fmt)
    file_h._knowlet_configured = True  # type: ignore[attr-defined]
    root.addHandler(file_h)


def _retarget_file_handler(
    root: logging.Logger, ours: list[logging.Handler], vault_root: Path
) -> None:
    target = os.path.abspath(vault_root / ".knowlet" / _LOG_FILENAME)
    file_handlers = [h for h in ours if isinstance(h, logging.FileHandler)]
    if any(h.baseFilename == target for h in file_handlers):
        return
    fmt: logging.Formatter | None = None
    for h in file_handlers:
        fmt = fmt or h.formatter
        root.removeHandler(h)
        with suppress(Exception):
            h.close()
    _add_file_handler(root, vault_root, fmt or logging.Formatter(_FORMAT))
