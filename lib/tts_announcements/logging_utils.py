"""Centralized logging utility for the TTS announcement hooks.

This module is the single source of truth for diagnostic logging across the
notify hook (:mod:`tts_announcements.notify`) and the install-time config
writers (:mod:`tts_announcements.install_hooks`). It provides leveled,
timestamped, context-tagged log lines written to a single rotating-free log
file, and it deliberately never raises: logging must not break a hook that an
AI agent runtime is waiting on.

Components:
  - LogLevel: Ordered severity levels (VERBOSE, DEBUG, INFO, WARN, ERROR).
  - log_dir: Resolve the directory that receives generated log files.
  - log: Write one leveled, timestamped line for a component.
  - verbose / debug / info / warn / error: Convenience wrappers around ``log``.

Usage:
    >>> from tts_announcements import logging_utils as log
    >>> log.info("hook fired", component="notify")
    >>> log.error("tracker missing", component="install")

Log destination:
    Logs are written to ``<log_dir>/notify.log``. ``log_dir`` honors the
    ``AGENT_COMMAND_CENTER_LOG_DIR`` environment variable (the canonical project
    override) and otherwise defaults to the Agent Command Center ``.log``
    directory so every repo in that ecosystem shares one searchable log file.
"""

from __future__ import annotations

import os
from datetime import datetime
from enum import IntEnum
from pathlib import Path

#: Name of the single log file all components append to, under :func:`log_dir`.
LOG_FILE_NAME = "notify.log"


class LogLevel(IntEnum):
    """Ordered severity levels for emitted log lines.

    Lower numeric values are less severe. The integer ordering lets callers and
    future filters compare levels (e.g. ``level >= LogLevel.WARN``) while the
    member ``name`` is used verbatim as the bracketed tag in each log line.
    """

    VERBOSE = 10
    DEBUG = 20
    INFO = 30
    WARN = 40
    ERROR = 50


def log_dir(home: Path | None = None) -> Path:
    """Resolve the directory that receives generated log files.

    Args:
        home: Base home directory to resolve the default location against. When
            ``None``, the current user's home directory (``Path.home()``) is
            used. Primarily an injection point for tests.

    Returns:
        Path: The log directory. If ``AGENT_COMMAND_CENTER_LOG_DIR`` is set in
        the environment, its expanded value is returned; otherwise the Agent
        Command Center ``.log`` directory under ``home`` is returned.
    """
    configured = os.environ.get("AGENT_COMMAND_CENTER_LOG_DIR", "")
    if configured:
        return Path(configured).expanduser()
    return (home or Path.home()) / "projects" / "agent_command_center" / ".log"


def log(
    level: LogLevel,
    message: str,
    *,
    component: str = "notify",
    home: Path | None = None,
) -> None:
    """Write one leveled, timestamped, context-tagged line to the log file.

    The line format is ``"<ISO-8601 timestamp> [<LEVEL>] [<component>] <message>"``.
    The function is best-effort and never raises: any filesystem or encoding
    failure is swallowed so a logging problem cannot break the calling hook.

    Args:
        level: Severity of the entry; its ``name`` becomes the bracketed level
            tag in the written line.
        message: Human-readable log text. Newlines are not stripped, so keep
            messages to a single line for searchability.
        component: Short tag identifying the emitting component (e.g.
            ``"notify"`` or ``"install"``). Defaults to ``"notify"``.
        home: Base home directory forwarded to :func:`log_dir`. Defaults to
            ``None`` (current user's home).

    Returns:
        None.
    """
    try:
        path = log_dir(home) / LOG_FILE_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} [{level.name}] [{component}] {message}\n")
    except Exception:
        # Logging must never break a hook the agent runtime is blocking on.
        pass


def verbose(message: str, *, component: str = "notify", home: Path | None = None) -> None:
    """Log a :attr:`LogLevel.VERBOSE` message. See :func:`log` for parameters."""
    log(LogLevel.VERBOSE, message, component=component, home=home)


def debug(message: str, *, component: str = "notify", home: Path | None = None) -> None:
    """Log a :attr:`LogLevel.DEBUG` message. See :func:`log` for parameters."""
    log(LogLevel.DEBUG, message, component=component, home=home)


def info(message: str, *, component: str = "notify", home: Path | None = None) -> None:
    """Log a :attr:`LogLevel.INFO` message. See :func:`log` for parameters."""
    log(LogLevel.INFO, message, component=component, home=home)


def warn(message: str, *, component: str = "notify", home: Path | None = None) -> None:
    """Log a :attr:`LogLevel.WARN` message. See :func:`log` for parameters."""
    log(LogLevel.WARN, message, component=component, home=home)


def error(message: str, *, component: str = "notify", home: Path | None = None) -> None:
    """Log a :attr:`LogLevel.ERROR` message. See :func:`log` for parameters."""
    log(LogLevel.ERROR, message, component=component, home=home)
