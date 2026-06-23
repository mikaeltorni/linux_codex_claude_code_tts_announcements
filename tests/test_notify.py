import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from tts_announcements import notify


def test_codex_turn_complete_uses_tracker_token(monkeypatch):
    calls = []
    monkeypatch.setenv("CODEX_AGENT_RUN_ID", "codex-123")
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert notify.handle_codex({"type": "agent-turn-complete", "status": 0}) == 0
    assert calls == [["turn-complete", "--status", "0", "--token", "codex-123"]]


def test_claude_stop_routes_finish_announcement(monkeypatch, tmp_path):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "message": {"role": "user", "content": "first task"}}),
                json.dumps({"type": "user", "message": {"role": "user", "content": "ship hooks"}}),
            ]
        ),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert notify.handle_claude({"hook_event_name": "Stop", "cwd": "/repo/demo", "transcript_path": str(transcript)}) == 0
    assert calls[0][:2] == ["announce", "--event"]
    assert "finish" in calls[0]
    assert calls[0][-2:] == ["--task-description", "ship hooks"]


def test_session_start_startup_announces(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    payload = {"hook_event_name": "SessionStart", "source": "startup", "cwd": "/repo/demo"}
    assert notify.handle_claude(payload) == 0
    assert calls and calls[0][:3] == ["announce", "--event", "start"]


def test_session_start_resume_or_compact_is_silent(monkeypatch):
    """Resume/compact/clear re-fire SessionStart and must not replay the start chime."""
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    for source in ("resume", "compact", "clear"):
        payload = {"hook_event_name": "SessionStart", "source": source, "cwd": "/repo/demo"}
        assert notify.handle_claude(payload) == 0
    assert calls == []


def test_pre_tool_use_is_silent(monkeypatch):
    """The destructive-command warning was removed; PreToolUse must do nothing."""
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_input": {"command": "rm -rf $HOME"},
    }
    assert notify.handle_claude(payload) == 0
    assert calls == []


def test_main_accepts_claude_stdin_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    payload = json.dumps({"hook_event_name": "Notification", "message": "waiting", "cwd": "/repo"})

    assert notify.main(["notify_agent.py"], stdin_text=payload) == 0
    assert calls[0][0] == "clarify"


def test_clarify_uses_only_supported_tracker_arguments(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    context = notify.RuntimeContext(
        label="claude",
        project_name="demo",
        project_path="/repo/demo",
        voice="",
        codex_home=Path("/home/test/.claude"),
    )

    assert notify.clarify(context, "needs input") is True
    assert "--label" not in calls[0]


def test_idle_waiting_notification_does_not_clarify(monkeypatch):
    """The idle "waiting for your input" timeout must not re-speak at turn end."""
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    payload = {
        "hook_event_name": "Notification",
        "message": "Claude is waiting for your input",
        "cwd": "/repo/demo",
    }

    assert notify.handle_claude(payload) == 0
    assert calls == []


def test_permission_notification_still_clarifies(monkeypatch):
    """A genuine permission Notification must still raise the attention prompt."""
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    payload = {
        "hook_event_name": "Notification",
        "message": "Claude needs your permission to use Bash",
        "cwd": "/repo/demo",
    }

    assert notify.handle_claude(payload) == 0
    assert calls[0][0] == "clarify"
    assert calls[0][calls[0].index("--question") + 1] == "Claude needs your permission to use Bash"


def test_codex_permission_request_routes_attention_announcement(monkeypatch):
    calls = []
    monkeypatch.setenv("CODEX_AGENT_LABEL", "codex")
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    payload = {
        "hook_event_name": "PermissionRequest",
        "cwd": "/repo/demo",
        "tool_name": "Bash",
    }

    assert notify.handle_claude(payload) == 0
    assert calls[0][0] == "clarify"
    assert calls[0][calls[0].index("--question") + 1] == "Codex needs your attention"


def test_context_uses_codex_variables_for_codex_attention_hook(monkeypatch):
    """Claude-shaped Codex attention events must not inherit Claude defaults."""
    monkeypatch.setenv("CODEX_AGENT_LABEL", "codex")
    monkeypatch.setenv("CODEX_TTS_VOICE", "af_codex")
    monkeypatch.delenv("CODEX_AGENT_KIND", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CODEX__TTS_VOICE", raising=False)
    monkeypatch.delenv("CLAUDE_TTS_VOICE", raising=False)

    context = notify.context_for({"cwd": "/repo/demo"}, "claude")

    assert context.label == "codex"
    assert context.voice == "af_codex"
    assert context.codex_home == Path.home() / ".codex"


def test_context_uses_claude_variables_for_direct_claude_hook(monkeypatch):
    """Direct Claude hooks should use Claude's voice and config home."""
    monkeypatch.setenv("CLAUDE_TTS_VOICE", "af_claude")
    monkeypatch.setenv("CODEX__TTS_VOICE", "af_wrapper")
    monkeypatch.delenv("CODEX_AGENT_KIND", raising=False)
    monkeypatch.delenv("CODEX_AGENT_LABEL", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)

    context = notify.context_for({"cwd": "/repo/demo"}, "claude")

    assert context.label == "claude"
    assert context.voice == "af_claude"
    assert context.codex_home == Path.home() / ".claude"


def test_context_uses_qwen_variables_for_direct_qwen_hook(monkeypatch):
    """Qwen's Local label should select its own voice, model, and config home."""
    monkeypatch.setenv("CODEX_AGENT_LABEL", "Local")
    monkeypatch.setenv("QWEN_CODEX_TTS_VOICE", "af_qwen")
    monkeypatch.setenv("QWEN_CODEX_LMSTUDIO_MODEL", "qwen-model")
    monkeypatch.delenv("CODEX_AGENT_KIND", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CODEX__TTS_VOICE", raising=False)
    monkeypatch.delenv("CODEX_AGENT_LMSTUDIO_MODEL", raising=False)

    context = notify.context_for({"cwd": "/repo/demo"}, "codex")

    assert context.label == "Local"
    assert context.voice == "af_qwen"
    assert context.codex_home == Path.home() / ".codex-qwen"
    assert context.model_name == "qwen-model"


def test_context_normalized_wrapper_voice_is_runtime_fallback(monkeypatch):
    """ACC's normalized wrapper voice remains a compatibility fallback."""
    monkeypatch.setenv("CODEX_AGENT_KIND", "qwen")
    monkeypatch.setenv("CODEX__TTS_VOICE", "af_wrapper")

    assert notify.context_for({}, "codex").voice == "af_wrapper"
