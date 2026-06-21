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
