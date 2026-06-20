"""Behavioral tests for the Agent TTS (ATTS) command-line interface.

The CLI is exercised end to end with audio suppressed (``ATTS_NO_AUDIO``).
``speak`` is monkeypatched where a test asserts on the composed text so the
verbs are validated without touching synthesis.
"""

import importlib
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """Reload engine + cli with a private state dir and no real audio."""
    for name in (
        "ATTS_SPEED",
        "ATTS_VOLUME_PERCENT",
        "ATTS_SILENT",
        "ATTS_VOICE",
        "ATTS_ANNOUNCE_WORKSPACE",
        "ATTS_NO_AUDIO",
        "AGENT_COMMAND_CENTER_TTS_SPEED",
        "AGENT_COMMAND_CENTER_TTS_VOLUME_PERCENT",
        "ACC_SILENT",
        "CODEX__TTS_VOICE",
        "CLAUDE_TTS_VOICE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ATTS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ATTS_LOG_DIR", str(tmp_path / "log"))
    monkeypatch.setenv("ATTS_ANNOUNCE_WORKSPACE", "0")
    monkeypatch.setenv("ATTS_NO_AUDIO", "1")
    import agent_tts.engine as e
    importlib.reload(e)
    import agent_tts.cli as c
    importlib.reload(c)
    return c


def test_speed_status_and_set(cli, capsys):
    """`speed` with no value prints the current speed; a value persists it."""
    assert cli.main(["speed"]) == 0
    assert capsys.readouterr().out.strip() == cli.engine.format_tts_speed(cli.engine.DEFAULT_TTS_SPEED)
    assert cli.main(["speed", "2"]) == 0
    assert capsys.readouterr().out.strip() == "2"
    assert cli.engine.current_tts_speed() == 2.0


def test_volume_invalid_returns_2(cli, capsys):
    """A non-positive volume is rejected with exit code 2."""
    assert cli.main(["volume", "0"]) == 2
    assert "invalid volume" in capsys.readouterr().err


def test_silent_status_toggle(cli, capsys):
    """`silent` toggles and reports the persisted state."""
    assert cli.main(["silent", "status"]) == 0
    assert capsys.readouterr().out.strip() == "off"
    assert cli.main(["silent", "on"]) == 0
    assert capsys.readouterr().out.strip() == "on"
    assert cli.engine.acc_silent_enabled() is True


def test_voice_speaks_composed_text(cli, monkeypatch):
    """`voice` forwards the literal text to the engine speak primitive."""
    spoken = {}
    monkeypatch.setattr(cli.engine, "speak", lambda text, voice, *a, **k: spoken.update(text=text, voice=voice) or True)
    assert cli.main(["voice", "--text", "hello there", "--voice", "af_sky"]) == 0
    assert spoken == {"text": "hello there", "voice": "af_sky"}


def test_announce_composes_finish_wording(cli, monkeypatch):
    """`announce` composes the shared wording before speaking."""
    spoken = {}
    monkeypatch.setattr(cli.engine, "speak", lambda text, voice, *a, **k: spoken.update(text=text) or True)
    assert (
        cli.main(
            [
                "announce",
                "--event",
                "finish",
                "--voice",
                "af_sky",
                "--completion-message",
                "shipped the feature",
            ]
        )
        == 0
    )
    assert spoken["text"] == "shipped the feature"


def test_clarify_accepts_question_for_compat(cli, monkeypatch):
    """`clarify` accepts (and ignores) --question for hook compatibility."""
    spoken = {}
    monkeypatch.setattr(cli.engine, "speak", lambda text, voice, *a, **k: spoken.update(text=text) or True)
    assert cli.main(["clarify", "--voice", "af_jessica", "--project-name", "demo", "--question", "anything"]) == 0
    assert spoken["text"].startswith("Project demo needs your input")
