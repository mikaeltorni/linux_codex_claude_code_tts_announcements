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
        "ATTS_ANNOUNCE_START",
        "ATTS_ANNOUNCE_FINISH",
        "ATTS_ANNOUNCE_ATTENTION",
        "ATTS_EVENT_CONFIG_FILE",
        "ATTS_NO_AUDIO",
        "ATTS_SUPPRESS_ANNOUNCEMENTS",
        "AGENT_COMMAND_CENTER_TTS_SPEED",
        "AGENT_COMMAND_CENTER_TTS_VOLUME_PERCENT",
        "ACC_SILENT",
        "CODEX__TTS_VOICE",
        "CLAUDE_TTS_VOICE",
        "CLAUDE_CODE_TTS_VOICE",
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


def test_silent_default_voice_honors_claude_code_alias(cli, monkeypatch, capsys):
    """`silent` uses the Claude Code voice alias when no generic voice is set."""
    spoken = {}
    monkeypatch.setenv("CODEX__TTS_VOICE", "af_wrapper")
    monkeypatch.setenv("CLAUDE_CODE_TTS_VOICE", "af_claude_code")
    monkeypatch.setattr(
        cli.engine,
        "speak",
        lambda text, voice, *a, **k: spoken.update(text=text, voice=voice) or True,
    )

    assert cli.main(["silent", "on"]) == 0

    assert capsys.readouterr().out.strip() == "on"
    assert spoken["voice"] == "af_claude_code"


def test_voice_speaks_composed_text(cli, monkeypatch):
    """`voice` forwards the literal text to the engine speak primitive."""
    spoken = {}
    monkeypatch.setattr(cli.engine, "speak", lambda text, voice, *a, **k: spoken.update(text=text, voice=voice) or True)
    assert cli.main(["voice", "--text", "hello there", "--voice", "af_sky"]) == 0
    assert spoken == {"text": "hello there", "voice": "af_sky"}


@pytest.mark.parametrize("command, expected", [
    (["announce", "--event", "start"], "Project demo project started on workspace 1"),
    (["announce", "--event", "finish", "--completion-message", "Demo project done"],
     "Demo project done on workspace 1"),
    (["clarify"], "Project demo project needs your input. What should we do next? on workspace 1"),
])
def test_lifecycle_cli_uses_attached_tmux_terminal_workspace(cli, monkeypatch, command, expected):
    """Public announcement verbs resolve workspace 1 despite stale workspace-2 env."""
    monkeypatch.setenv("TMUX", "/tmp/test-tmux/default,10,0")
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setenv("WINDOWID", "100")
    monkeypatch.setenv("ATTS_ANNOUNCE_WORKSPACE", "1")
    responses = {
        ("tmux", "display-message", "-p", "-t", "%7", "#{session_id}"): "$3",
        ("tmux", "list-clients", "-t", "$3", "-F", "#{client_pid}"): "123",
        ("xprop", "-id", "200", "_NET_WM_DESKTOP"): "_NET_WM_DESKTOP(CARDINAL) = 0",
        ("xprop", "-id", "100", "_NET_WM_DESKTOP"): "_NET_WM_DESKTOP(CARDINAL) = 1",
    }
    monkeypatch.setattr(cli.engine, "_capture_command", lambda cmd, timeout=1.0: responses.get(tuple(cmd), ""))
    monkeypatch.setattr(Path, "read_bytes", lambda path: b"WINDOWID=200\0")
    spoken = []
    monkeypatch.setattr(cli.engine, "speak_with_kokoro", lambda text, *args, **kwargs: spoken.append(text) or True)

    assert cli.main([*command, "--voice", "af_test", "--project-name", "demo project"]) == 0
    assert spoken == [expected]


def test_speech_verbs_report_engine_failure(cli, monkeypatch):
    """Direct callers must receive a nonzero status when no speech path works."""
    monkeypatch.setattr(cli.engine, "speak", lambda *args, **kwargs: False)

    assert cli.main(["voice", "--text", "hello", "--voice", "af_sky"]) == 1
    assert cli.main(["announce", "--event", "start", "--voice", "af_sky"]) == 1
    assert cli.main(["clarify", "--voice", "af_sky"]) == 1


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


@pytest.mark.parametrize(
    "command",
    [
        ["announce", "--event", "finish", "--voice", "af_sky"],
        ["clarify", "--voice", "af_sky"],
    ],
)
def test_suppress_env_silences_direct_lifecycle_commands(cli, monkeypatch, command):
    """The global suppression contract also covers direct agent-tts callers."""
    spoken = []
    monkeypatch.setenv("ATTS_SUPPRESS_ANNOUNCEMENTS", "1")
    monkeypatch.setattr(
        cli.engine,
        "speak",
        lambda *args, **kwargs: spoken.append((args, kwargs)) or True,
    )

    assert cli.main(command) == 0
    assert spoken == []


def test_lifecycle_and_attention_events_can_be_disabled(cli, monkeypatch, tmp_path):
    """Installed settings independently suppress start, finish, and attention."""
    config = tmp_path / "announcements.env"
    config.write_text(
        "ATTS_ANNOUNCE_START=0\n"
        "ATTS_ANNOUNCE_FINISH=1\n"
        "ATTS_ANNOUNCE_ATTENTION=0\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ATTS_EVENT_CONFIG_FILE", str(config))
    spoken = []
    monkeypatch.setattr(
        cli.engine,
        "speak",
        lambda text, voice, *args, **kwargs: spoken.append(text) or True,
    )

    assert cli.main(["announce", "--event", "start", "--voice", "af_sky"]) == 0
    assert cli.main(["announce", "--event", "finish", "--voice", "af_sky"]) == 0
    assert cli.main(["clarify", "--voice", "af_sky", "--project-name", "demo"]) == 0

    assert len(spoken) == 1
    assert spoken[0] == "Agent ended"


def test_clarify_accepts_question_for_compat(cli, monkeypatch):
    """`clarify` accepts (and ignores) --question for hook compatibility."""
    spoken = {}
    monkeypatch.setattr(cli.engine, "speak", lambda text, voice, *a, **k: spoken.update(text=text) or True)
    assert cli.main(["clarify", "--voice", "af_jessica", "--project-name", "demo", "--question", "anything"]) == 0
    assert spoken["text"].startswith("Project demo needs your input")
