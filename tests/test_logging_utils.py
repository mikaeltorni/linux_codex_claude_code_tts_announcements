"""Tests for the centralized logging utility (tts_announcements.logging_utils)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from tts_announcements import logging_utils as log


def test_log_dir_honors_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COMMAND_CENTER_LOG_DIR", str(tmp_path / "custom"))
    assert log.log_dir() == tmp_path / "custom"


def test_log_dir_defaults_to_repo_log(monkeypatch, tmp_path):
    monkeypatch.delenv("AGENT_COMMAND_CENTER_LOG_DIR", raising=False)
    monkeypatch.delenv("ATTS_LOG_DIR", raising=False)
    resolved = log.log_dir(home=tmp_path)
    assert resolved == tmp_path / ".log"


def test_log_writes_leveled_tagged_line(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COMMAND_CENTER_LOG_DIR", str(tmp_path))
    log.error("tracker missing", component="install")
    contents = (tmp_path / log.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "ERROR" in contents
    assert "[install]" in contents
    assert "tracker missing" in contents


def test_level_helpers_use_their_level(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COMMAND_CENTER_LOG_DIR", str(tmp_path))
    log.info("started")
    log.warn("careful")
    contents = (tmp_path / log.LOG_FILE_NAME).read_text(encoding="utf-8")
    assert "INFO" in contents
    assert "WARNING" in contents


def test_log_never_raises_on_bad_directory(monkeypatch, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir", encoding="utf-8")
    monkeypatch.setenv("AGENT_COMMAND_CENTER_LOG_DIR", str(blocker / "sub"))
    # Parent is a file, so mkdir fails; the call must swallow the error.
    log.info("should not raise")


def test_get_logger_is_idempotent_and_writes_under_log_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COMMAND_CENTER_LOG_DIR", str(tmp_path))

    logger = log.get_logger("test-central", "central.log")
    again = log.get_logger("test-central", "central.log")
    logger.info("centralized")

    assert logger is again
    assert len(logger.handlers) == 1
    assert "centralized" in (tmp_path / "central.log").read_text(encoding="utf-8")


def test_log_call_records_arguments_and_return(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_COMMAND_CENTER_LOG_DIR", str(tmp_path))
    logger = log.get_logger("test-trace", "trace.log")

    @log.log_call(logger)
    def combine(left: str, right: str = "b") -> str:
        return left + right

    assert combine("a", right="c") == "ac"
    contents = (tmp_path / "trace.log").read_text(encoding="utf-8")
    assert "ENTER test_logging_utils.py:test_log_call_records_arguments_and_return.<locals>.combine" in contents
    assert "left='a'" in contents
    assert "right='c'" in contents
    assert "EXIT test_logging_utils.py:test_log_call_records_arguments_and_return.<locals>.combine -> 'ac'" in contents
