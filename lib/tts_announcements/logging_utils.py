"""Centralized logging utility for the TTS announcement hooks.

This module is the single source of truth for diagnostic logging across the TTS
engine, notify hook (:mod:`tts_announcements.notify`), and install-time config
writers (:mod:`tts_announcements.install_hooks`). It provides standard
``logging`` loggers, call tracing, and compatibility leveled helpers, and it
deliberately never raises: logging must not break a hook that an AI agent
runtime is waiting on.

Components:
  - LogLevel: Ordered severity levels (VERBOSE, DEBUG, INFO, WARN, ERROR).
  - log_dir: Resolve the directory that receives generated log files.
  - get_logger: Return an idempotent standard logger for one log file.
  - log_call: Trace function arguments and return values.
  - log: Write one leveled, timestamped line for compatibility call sites.
  - verbose / debug / info / warn / error: Convenience wrappers around ``log``.

Usage:
    >>> from tts_announcements import logging_utils as log
    >>> log.info("hook fired", component="notify")
    >>> log.error("tracker missing", component="install")

Log destination:
    Logs are written under ``<log_dir>``. ``log_dir`` honors ``ATTS_LOG_DIR`` and
    ``AGENT_COMMAND_CENTER_LOG_DIR`` for installed integrations, and otherwise
    defaults to this repository's ``.log`` directory.
"""

from __future__ import annotations

import functools
import inspect
import logging
import os
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, TypeVar

#: Name of the single log file all components append to, under :func:`log_dir`.
LOG_FILE_NAME = "notify.log"
LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
F = TypeVar("F", bound=Callable[..., Any])


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


PYTHON_LEVELS = {
    LogLevel.VERBOSE: logging.DEBUG,
    LogLevel.DEBUG: logging.DEBUG,
    LogLevel.INFO: logging.INFO,
    LogLevel.WARN: logging.WARNING,
    LogLevel.ERROR: logging.ERROR,
}


def log_dir(home: Path | None = None) -> Path:
    """Resolve the directory that receives generated log files.

    Args:
        home: Base home directory to resolve the default location against. When
            ``None``, the current user's home directory (``Path.home()``) is
            used. Primarily an injection point for tests.

    Returns:
        Path: The log directory. If ``ATTS_LOG_DIR`` or
        ``AGENT_COMMAND_CENTER_LOG_DIR`` is set in the environment, its expanded
        value is returned. Otherwise ``home/.log`` is returned when ``home`` is
        provided, or the repository ``.log`` directory is returned.
    """
    configured = os.environ.get("ATTS_LOG_DIR", "") or os.environ.get("AGENT_COMMAND_CENTER_LOG_DIR", "")
    if configured:
        return Path(configured).expanduser()
    if home is not None:
        return home / ".log"
    return Path(__file__).resolve().parents[2] / ".log"


def get_logger(name: str, log_file: str, *, home: Path | None = None) -> logging.Logger:
    """Return an idempotent project logger writing inside :func:`log_dir`.

    Args:
        name: Logger name included in each record.
        log_file: File name created inside the resolved log directory.
        home: Optional home override forwarded to :func:`log_dir`.

    Returns:
        logging.Logger: A configured logger. If the sink cannot be opened, the
        logger receives a ``NullHandler`` so logging never aborts callers.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    target = log_dir(home) / log_file
    if logger.handlers and all(
        getattr(handler, "_tts_log_path", target) == target for handler in logger.handlers
    ):
        return logger
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    try:
        directory = target.parent
        directory.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(
            target,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
    except OSError:
        handler = logging.NullHandler()
    setattr(handler, "_tts_log_path", target)
    logger.addHandler(handler)
    return logger


def log_call(logger: logging.Logger, level: int = logging.DEBUG) -> Callable[[F], F]:
    """Trace a function by logging all arguments on entry and return on exit.

    Each record carries the wrapped function's ``file:qualname``. The decorator
    intentionally logs only entry arguments and the returned value.

    Args:
        logger: Centralized project logger returned by :func:`get_logger`.
        level: Logging level used for both trace records.

    Returns:
        Callable[[F], F]: Decorator for the target callable.
    """

    def decorator(func: F) -> F:
        location = f"{Path(func.__code__.co_filename).name}:{func.__qualname__}"
        signature = inspect.signature(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            rendered = ", ".join(
                f"{name}={value!r}" for name, value in bound.arguments.items()
            )
            logger.log(level, "ENTER %s(%s)", location, rendered)
            result = func(*args, **kwargs)
            logger.log(level, "EXIT %s -> %r", location, result)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


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
    logger = get_logger("tts_announcements", LOG_FILE_NAME, home=home)
    logger.log(PYTHON_LEVELS[level], "[%s] %s", component, message)


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
