"""Behavioral tests for the Agent TTS (ATTS) speech engine.

These cover the config resolution, env precedence (ATTS_* over legacy ACC
names), persistence round-trips, silent toggle, voice selection, workspace
suffixing, and the spoken wording — without ever producing real audio
(``ATTS_NO_AUDIO`` is forced on).
"""

import importlib
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

_ATTS_ENV = (
    "ATTS_SPEED",
    "ATTS_VOLUME_PERCENT",
    "ATTS_SILENT",
    "ATTS_VOICE",
    "ATTS_CODEX_VOICE",
    "ATTS_CLAUDE_VOICE",
    "ATTS_QWEN_VOICE",
    "ATTS_ANNOUNCE_WORKSPACE",
    "ATTS_NO_AUDIO",
    "AGENT_COMMAND_CENTER_TTS_SPEED",
    "AGENT_COMMAND_CENTER_TTS_VOLUME_PERCENT",
    "ACC_SILENT",
    "CODEX__TTS_VOICE",
    "CODEX_TTS_VOICE",
    "CLAUDE_TTS_VOICE",
    "QWEN_CODEX_TTS_VOICE",
)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """Reload the engine with a private state dir and no real audio."""
    for name in _ATTS_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ATTS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ATTS_LOG_DIR", str(tmp_path / "log"))
    monkeypatch.setenv("ATTS_ANNOUNCE_WORKSPACE", "0")
    monkeypatch.setenv("ATTS_NO_AUDIO", "1")
    import agent_tts.engine as e
    importlib.reload(e)
    return e


def test_speed_round_trip(engine):
    """A persisted speed is read back and overrides the default."""
    assert engine.current_tts_speed() == engine.DEFAULT_TTS_SPEED
    engine.set_tts_speed(2.0)
    assert engine.current_tts_speed() == 2.0


def test_speed_env_overrides_persisted(engine, monkeypatch):
    """ATTS_SPEED wins over a persisted value."""
    engine.set_tts_speed(2.0)
    monkeypatch.setenv("ATTS_SPEED", "0.75")
    assert engine.current_tts_speed() == 0.75


def test_speed_legacy_env_fallback(engine, monkeypatch):
    """The legacy ACC speed env still applies when ATTS_SPEED is unset."""
    monkeypatch.setenv("AGENT_COMMAND_CENTER_TTS_SPEED", "1.25")
    assert engine.current_tts_speed() == 1.25


def test_volume_round_trip_and_percent_format(engine):
    """Volume persists and formats as a percent string."""
    assert engine.current_tts_volume_percent() == engine.DEFAULT_TTS_VOLUME_PERCENT
    engine.set_tts_volume_percent(250.0)
    assert engine.current_tts_volume_percent() == 250.0
    assert engine.format_tts_volume_percent(250.0) == "250%"


def test_volume_legacy_default_125_is_ignored_when_saved(engine, monkeypatch):
    """The stale legacy default export (125) defers to a saved value."""
    engine.set_tts_volume_percent(400.0)
    monkeypatch.setenv("ATTS_VOLUME_PERCENT", engine.LEGACY_DEFAULT_TTS_VOLUME_ENV)
    assert engine.current_tts_volume_percent() == 400.0


def test_volume_to_db_monotonic(engine):
    """Louder percentages map to larger decibel gains; 100% is 0 dB."""
    assert engine.tts_volume_percent_to_db(100.0) == pytest.approx(0.0)
    assert engine.tts_volume_percent_to_db(200.0) > engine.tts_volume_percent_to_db(100.0)


def test_silent_toggle_persists(engine):
    """The silent flag round-trips through the state file."""
    assert engine.acc_silent_enabled() is False
    engine.set_acc_silent(True)
    assert engine.acc_silent_enabled() is True


def test_silent_env_override(engine, monkeypatch):
    """ATTS_SILENT overrides the persisted flag for one invocation."""
    engine.set_acc_silent(False)
    monkeypatch.setenv("ATTS_SILENT", "1")
    assert engine.acc_silent_enabled() is True


def test_silent_legacy_env(engine, monkeypatch):
    """The legacy ACC_SILENT env is still honored."""
    monkeypatch.setenv("ACC_SILENT", "yes")
    assert engine.acc_silent_enabled() is True


def test_voice_for_kind_precedence(engine, monkeypatch):
    """ATTS_VOICE wins; otherwise per-kind defaults apply."""
    assert engine.voice_for_kind("claude", {}) == "af_sky"
    assert engine.voice_for_kind("qwen", {}) == "af_heart"
    assert engine.voice_for_kind("codex", {"ATTS_VOICE": "af_custom"}) == "af_custom"
    assert engine.voice_for_kind("codex", {"CODEX__TTS_VOICE": "af_legacy"}) == "af_legacy"


def test_voice_for_kind_claude_legacy_env(engine, monkeypatch):
    """The legacy CLAUDE_TTS_VOICE still selects the Claude voice."""
    monkeypatch.setenv("CLAUDE_TTS_VOICE", "af_river")
    assert engine.voice_for_kind("claude", {}) == "af_river"


def test_voice_for_kind_supports_runtime_specific_variables(engine):
    """Codex, Claude, and Qwen each honor their ATTS and legacy voice names."""
    assert engine.voice_for_kind("codex", {"ATTS_CODEX_VOICE": "af_codex"}) == "af_codex"
    assert engine.voice_for_kind("claude", {"ATTS_CLAUDE_VOICE": "af_claude"}) == "af_claude"
    assert engine.voice_for_kind("qwen", {"ATTS_QWEN_VOICE": "af_qwen"}) == "af_qwen"
    assert engine.voice_for_kind("codex", {"CODEX_TTS_VOICE": "af_legacy_codex"}) == "af_legacy_codex"
    assert engine.voice_for_kind("qwen", {"QWEN_CODEX_TTS_VOICE": "af_legacy_qwen"}) == "af_legacy_qwen"


def test_workspace_suffix_disabled(engine):
    """ATTS_ANNOUNCE_WORKSPACE=0 (set by the fixture) returns text unchanged."""
    assert engine.with_workspace_suffix("Project X started") == "Project X started"


def test_announcement_wording(engine):
    """Start/finish/clarify wording matches the shared phrasing."""
    assert engine.agent_announcement_text("codex", "demo", "start") == "Project demo started"
    assert (
        engine.agent_announcement_text("codex", "demo", "finish", completion_message="did a thing")
        == "did a thing"
    )
    assert engine.clarify_announcement_text("demo").startswith("Project demo needs your input")
    assert engine.clarify_announcement_text("").startswith("I need your input")


def test_play_audio_suppressed_returns_true(engine):
    """With ATTS_NO_AUDIO set, playback is suppressed but reports success."""
    assert engine.play_audio(Path("/nonexistent.wav")) is True


def test_state_file_read_errors_are_logged(engine, monkeypatch):
    """Unreadable persisted state falls back cleanly with a diagnostic log."""
    messages = []

    def fail_read_text(self, encoding=None):
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_text", fail_read_text)
    monkeypatch.setattr(engine, "append_voice_log", messages.append)

    assert engine._read_state_file("tts-speed") == ""
    assert any("state read failed" in message for message in messages)


def test_capture_command_timeout_is_logged(engine, monkeypatch):
    """Workspace helper command timeouts are observable but non-fatal."""
    messages = []

    def fake_run(*args, **kwargs):
        raise engine.subprocess.TimeoutExpired(cmd=["xprop"], timeout=1.0)

    monkeypatch.setattr(engine.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(engine.subprocess, "run", fake_run)
    monkeypatch.setattr(engine, "append_voice_log", messages.append)

    assert engine._capture_command(["xprop", "-root"]) == ""
    assert any("command timed out" in message for message in messages)


def test_fallback_speak_logs_missing_synthesizer(engine, monkeypatch):
    """If no desktop fallback exists, the skipped speech path is logged."""
    messages = []

    monkeypatch.delenv("ATTS_NO_AUDIO", raising=False)
    monkeypatch.setattr(engine.shutil, "which", lambda command: None)
    monkeypatch.setattr(engine, "append_voice_log", messages.append)

    engine.fallback_speak("hello")

    assert "fallback_speak skipped: no fallback synthesizer found" in messages
