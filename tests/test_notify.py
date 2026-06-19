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


def test_pre_tool_use_warns_for_destructive_command(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_input": {"command": "rm -rf $HOME"},
    }
    assert notify.handle_claude(payload) == 0
    assert calls[0][0] == "voice"
    assert "rm -rf $HOME" in calls[0][2]


def test_main_accepts_claude_stdin_payload(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    payload = json.dumps({"hook_event_name": "Notification", "message": "waiting", "cwd": "/repo"})

    assert notify.main(["notify_agent.py"], stdin_text=payload) == 0
    assert calls[0][0] == "clarify"
