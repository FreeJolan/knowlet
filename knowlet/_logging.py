"""Logging configuration for long-running knowlet processes.

Short-lived CLI commands print to Rich console and don't need this. The
`knowlet web` server, however, runs APScheduler in the background — if the
user has closed the terminal, a scheduler exception with no log output is
invisible. This module wires:

- a stderr handler (visible while the terminal is open), and
- a rotating file handler under `<vault>/.knowlet/knowlet.log` (recoverable
  later).

Call `configure_logging(vault_root)` once at process startup.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def configure_logging(vault_root: Path | None = None, level: str = "INFO") -> None:
    """Wire root logger handlers exactly once. Idempotent."""
    root = logging.getLogger()
    if any(getattr(h, "_knowlet_configured", False) for h in root.handlers):
        return
    root.setLevel(level)
    fmt = logging.Formatter(_FORMAT)

    stderr_h = logging.StreamHandler(sys.stderr)
    stderr_h.setFormatter(fmt)
    stderr_h._knowlet_configured = True  # type: ignore[attr-defined]
    root.addHandler(stderr_h)

    if vault_root is not None:
        log_dir = vault_root / ".knowlet"
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_h = RotatingFileHandler(
                log_dir / "knowlet.log",
                maxBytes=1_000_000,  # 1 MB before rotation
                backupCount=3,
                encoding="utf-8",
            )
            file_h.setFormatter(fmt)
            file_h._knowlet_configured = True  # type: ignore[attr-defined]
            root.addHandler(file_h)
        except OSError:
            # Read-only vault / permission error — don't crash startup; stderr
            # handler is enough.
            pass

    # Tone down noisy third-party loggers; they tend to log INFO-level things
    # that aren't useful in our context.
    for name in ("apscheduler", "httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)
