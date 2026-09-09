import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from tts_announcements import notify


def test_codex_lifecycle_hooks_start_and_finish_tracker_turn(monkeypatch):
    calls = []
    monkeypatch.setenv("ATTS_LIFECYCLE_TRACKED", "1")
    monkeypatch.setenv("CODEX_AGENT_RUN_ID", "codex-123")
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert notify.handle_codex(
        {
            "hook_event_name": "UserPromptSubmit",
            "turn_id": "turn-1",
            "prompt": "fix the race",
            "cwd": "/repo",
        }
    ) == 0
    assert notify.handle_codex(
        {"hook_event_name": "Stop", "turn_id": "turn-1", "cwd": "/repo"}
    ) == 0

    assert calls[0] == [
        "turn-start",
        "--token",
        "codex-123",
        "--turn-id",
        "turn-1",
        "--prompt",
        "fix the race",
    ]
    assert calls[1][:2] == ["title", "--prompt"]
    assert calls[2] == [
        "turn-complete",
        "--status",
        "0",
        "--token",
        "codex-123",
        "--turn-id",
        "turn-1",
    ]


def test_codex_legacy_notify_completion_is_ignored(monkeypatch):
    """The response-level notify callback can fire between tool calls."""
    calls = []
    monkeypatch.setenv("CODEX_AGENT_RUN_ID", "codex-123")
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert notify.handle_codex({"type": "agent-turn-complete", "status": 0}) == 0

    assert calls == []


def test_main_routes_codex_hook_payload_by_runtime_kind(monkeypatch):
    calls = []
    monkeypatch.setenv("CODEX_AGENT_KIND", "codex")
    monkeypatch.setenv("ATTS_CODEX_HOOK_BACKGROUND", "1")
    monkeypatch.setenv("ATTS_LIFECYCLE_TRACKED", "1")
    monkeypatch.setenv("CODEX_AGENT_RUN_ID", "codex-123")
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    payload = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "turn_id": "turn-9",
            "prompt": "start now",
            "cwd": "/repo",
        }
    )
    assert notify.main(["notify_agent.py"], stdin_text=payload) == 0

    assert calls[0] == [
        "turn-start",
        "--token",
        "codex-123",
        "--turn-id",
        "turn-9",
        "--prompt",
        "start now",
    ]


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

    assert notify.handle_claude(
        {
            "hook_event_name": "Stop",
            "session_id": "claude-session-1",
            "cwd": "/repo/demo",
            "transcript_path": str(transcript),
        }
    ) == 0
    assert calls[0][:2] == ["announce", "--event"]
    assert "finish" in calls[0]
    assert calls[0][calls[0].index("--feature-key") + 1] == "claude-session-1"
    assert calls[0][-2:] == ["--task-description", "ship hooks"]


def test_claude_prompt_and_stop_forward_the_same_session_feature_key(monkeypatch, tmp_path):
    """Concurrent Claude sessions in one project must not share title labels."""
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "remove dock favourites"}}),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    common = {
        "session_id": "claude-dock-session",
        "cwd": "/repo/demo",
        "transcript_path": str(transcript),
    }
    assert notify.handle_claude(
        {**common, "hook_event_name": "UserPromptSubmit", "prompt": "remove dock favourites"}
    ) == 0
    assert notify.handle_claude({**common, "hook_event_name": "Stop"}) == 0

    for args in calls:
        assert args[args.index("--feature-key") + 1] == "claude-dock-session"


def test_cline_documented_and_cli_payloads_route_all_tts_events(monkeypatch):
    """Cline hooks support both public names and 3.x internal event names."""
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert notify.handle_cline(
        {
            "hookName": "agent_start",
            "workspaceRoots": ["/repo/demo"],
            "taskStart": {"task": "build it"},
        }
    ) == 0
    assert calls[-1][:3] == ["announce", "--event", "start"]

    assert notify.handle_cline(
        {
            "hookName": "UserPromptSubmit",
            "workspaceRoots": ["/repo/demo"],
            "userPromptSubmit": {"prompt": "ship it"},
        }
    ) == 0
    assert calls[-1][:2] == ["title", "--prompt"]
    assert calls[-1][2] == "ship it"

    assert notify.handle_cline(
        {
            "hookName": "agent_end",
            "workspaceRoots": ["/repo/demo"],
            "taskComplete": {"task": "ship it"},
        }
    ) == 0
    assert calls[-1][:3] == ["announce", "--event", "finish"]
    assert calls[-1][-2:] == ["--task-description", "ship it"]

    assert notify.handle_cline(
        {
            "hookName": "agent_error",
            "workspaceRoots": ["/repo/demo"],
            "taskError": {"task": "ship it"},
        }
    ) == 0
    assert calls[-1][:3] == ["announce", "--event", "finish"]
    assert calls[-1][-2:] == ["--task-description", "ship it"]


def test_cline_context_uses_cline_home_voice_and_workspace_roots(monkeypatch):
    """Cline hook context should not inherit Codex or Claude defaults."""
    monkeypatch.setenv("CODEX_AGENT_KIND", "cline")
    monkeypatch.setenv("CLINE_TTS_VOICE", "af_cline")
    monkeypatch.delenv("CODEX_AGENT_LABEL", raising=False)
    monkeypatch.delenv("CODEX_AGENT_PROJECT_PATH", raising=False)
    monkeypatch.delenv("CODEX_AGENT_PROJECT_NAME", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CODEX__TTS_VOICE", raising=False)

    context = notify.context_for({"workspaceRoots": ["/repo/demo"]}, "cline")

    assert context.label == "cline"
    assert context.project_name == "demo"
    assert context.project_path == "/repo/demo"
    assert context.voice == "af_cline"
    assert context.codex_home == Path.home() / ".cline"


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


def test_suppress_env_silences_all_hook_styles(monkeypatch):
    """ATTS_SUPPRESS_ANNOUNCEMENTS=1 must silence every hook without erroring.

    Monitoring surfaces (the agentic-cli-status tmux console) run real CLI TUIs
    whose lifecycle hooks would otherwise announce fake sessions such as
    "Project mk started" at login.
    """
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    monkeypatch.setenv("ATTS_SUPPRESS_ANNOUNCEMENTS", "1")

    claude = json.dumps(
        {"hook_event_name": "SessionStart", "source": "startup", "cwd": "/home/mk"}
    )
    assert notify.main(["notify_agent.py"], stdin_text=claude) == 0
    monkeypatch.setenv("GROK_EVENT", "session_ready")
    assert notify.main(["notify_agent.py", "--grok"]) == 0
    codex = json.dumps({"type": "agent-turn-complete", "status": 0})
    assert notify.main(["notify_agent.py", codex]) == 0
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


def test_context_falls_back_to_default_claude_voice(monkeypatch):
    """Bare ``claude`` (no voice env) must still resolve a concrete Kokoro voice.

    Returning the engine default (``af_sky``) instead of an empty string is what
    keeps the bare-binary hook on Kokoro: an empty voice makes the engine drop to
    the desktop synthesizer fallback. This is the same voice the ACC ``cca``
    wrapper produces, so both launch paths sound identical.
    """
    for name in (
        "ATTS_VOICE",
        "ATTS_CLAUDE_VOICE",
        "CLAUDE_TTS_VOICE",
        "CLAUDE_CODE_TTS_VOICE",
        "CODEX__TTS_VOICE",
        "CODEX_AGENT_KIND",
        "CODEX_AGENT_LABEL",
    ):
        monkeypatch.delenv(name, raising=False)

    assert notify.context_for({"cwd": "/repo/demo"}, "claude").voice == "af_sky"


def test_context_uses_claude_code_tts_voice_alias(monkeypatch):
    """The ``CLAUDE_CODE_TTS_VOICE`` alias overrides the claude default."""
    for name in ("ATTS_VOICE", "ATTS_CLAUDE_VOICE", "CLAUDE_TTS_VOICE", "CODEX__TTS_VOICE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_TTS_VOICE", "am_onyx")

    assert notify.context_for({"cwd": "/repo/demo"}, "claude").voice == "am_onyx"


def test_tracker_managed_lifecycle_hooks_do_not_duplicate_voices(monkeypatch):
    """ACC-managed Claude/Cline/Grok children skip native start/end hook speech."""
    calls = []
    tracker_calls = []
    monkeypatch.setenv("ATTS_LIFECYCLE_TRACKED", "1")
    monkeypatch.setenv("CODEX_AGENT_RUN_ID", "claude-1-1")
    monkeypatch.setattr(notify, "announce", lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(notify, "run_tracker", lambda args: tracker_calls.append(args) or True)

    notify.handle_claude({"hook_event_name": "SessionStart", "source": "startup"})
    notify.handle_claude({"hook_event_name": "Stop"})
    notify.handle_cline({"hookName": "TaskStart"})
    notify.handle_cline({"hookName": "TaskComplete"})
    notify.handle_grok({"GROK_EVENT": "session_ready"})
    notify.handle_grok({"GROK_EVENT": "turn_complete"})

    assert calls == []
    # The per-turn Claude Stop is forwarded to the tracker instead of spoken
    # natively, so tracked interactive sessions still announce each finish.
    assert tracker_calls == [["turn-complete", "--status", "0", "--token", "claude-1-1"]]


def test_tracker_managed_claude_stop_falls_back_without_run_token(monkeypatch):
    """A tracked Claude Stop with no run token still speaks a finish natively."""
    calls = []
    monkeypatch.setenv("ATTS_LIFECYCLE_TRACKED", "1")
    monkeypatch.delenv("CODEX_AGENT_RUN_ID", raising=False)
    monkeypatch.setattr(notify, "announce", lambda *args, **kwargs: calls.append((args, kwargs)))

    notify.handle_claude({"hook_event_name": "Stop"})

    assert len(calls) == 1
    assert calls[0][0][0] == "finish"


def test_tracker_managed_claude_prompt_submit_forwards_turn_start(monkeypatch):
    """Each tracked user prompt re-arms the tracker's finish announcement."""
    tracker_calls = []
    monkeypatch.setenv("ATTS_LIFECYCLE_TRACKED", "1")
    monkeypatch.setenv("CODEX_AGENT_RUN_ID", "claude-1-1")
    monkeypatch.setattr(notify, "run_tracker", lambda args: tracker_calls.append(args) or True)
    monkeypatch.setattr(notify, "update_title", lambda *args, **kwargs: True)

    notify.handle_claude({"hook_event_name": "UserPromptSubmit", "prompt": "next task"})

    assert tracker_calls == [
        ["turn-start", "--token", "claude-1-1", "--prompt", "next task"]
    ]


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


@pytest.mark.parametrize(
    ("kind", "voice", "home_name"),
    (
        ("openrouter", "af_jessica", ".codex-openrouter"),
        ("nvidia", "af_sarah", ".codex-nvidia"),
    ),
)
def test_context_routes_new_codex_variants_to_distinct_voice_and_home(
    monkeypatch, kind, voice, home_name
):
    """Codex-compatible variants must not collapse onto Codex TTS metadata."""
    monkeypatch.setenv("CODEX_AGENT_KIND", kind)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CODEX__TTS_VOICE", raising=False)

    context = notify.context_for({"cwd": "/repo/demo"}, "codex")

    assert notify.runtime_kind("codex", "codex") == kind
    assert context.voice == voice
    assert context.codex_home == Path.home() / home_name


def test_context_normalized_wrapper_voice_is_runtime_fallback(monkeypatch):
    """ACC's normalized wrapper voice remains a compatibility fallback."""
    monkeypatch.setenv("CODEX_AGENT_KIND", "qwen")
    monkeypatch.setenv("CODEX__TTS_VOICE", "af_wrapper")

    assert notify.context_for({}, "codex").voice == "af_wrapper"


def test_cline_pre_tool_use_ask_question_routes_clarify(monkeypatch):
    """PreToolUse for the ask_question tool speaks an attention prompt."""
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert (
        notify.handle_cline(
            {
                "hookName": "tool_call",
                "workspaceRoots": ["/repo/demo"],
                "tool_call": {
                    "id": "call_1",
                    "name": "ask_question",
                    "input": {"question": "Which framework?", "options": ["a", "b"]},
                },
            }
        )
        == 0
    )
    assert calls, "ask_question should route to the tracker"
    assert calls[-1][:1] == ["clarify"]
    assert "Which framework?" in calls[-1]


def test_cline_pre_tool_use_file_hook_name_routes_clarify(monkeypatch):
    """The PreToolUse file-hook name is accepted alongside the tool_call event."""
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert (
        notify.handle_cline(
            {
                "hookName": "PreToolUse",
                "workspaceRoots": ["/repo/demo"],
                "tool_call": {"name": "ask_question", "input": {"question": "pick one"}},
            }
        )
        == 0
    )
    assert calls[-1][:1] == ["clarify"]
    assert "pick one" in calls[-1]


def test_cline_pre_tool_use_other_tool_is_silent(monkeypatch):
    """PreToolUse for routine tools must not invoke the tracker."""
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert (
        notify.handle_cline(
            {
                "hookName": "tool_call",
                "workspaceRoots": ["/repo/demo"],
                "tool_call": {"name": "read_files", "input": {}},
            }
        )
        == 0
    )
    assert calls == []


def test_cline_pre_tool_use_ask_question_without_question_uses_default(monkeypatch):
    """An ask_question call with no question text falls back to the attention label."""
    calls = []
    monkeypatch.delenv("CODEX_AGENT_LABEL", raising=False)
    monkeypatch.delenv("CODEX_AGENT_KIND", raising=False)
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert (
        notify.handle_cline(
            {
                "hookName": "tool_call",
                "workspaceRoots": ["/repo/demo"],
                "tool_call": {"name": "ask_question", "input": {}},
            }
        )
        == 0
    )
    assert calls[-1][:1] == ["clarify"]
    assert "Cline needs your attention" in calls[-1]


def test_grok_events_route_start_finish_and_attention(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    monkeypatch.chdir("/tmp")
    for name in ("CODEX_AGENT_LABEL", "CODEX_AGENT_KIND", "CODEX_HOME"):
        monkeypatch.delenv(name, raising=False)

    env = {"GROK_EVENT": "session_ready", "GROK_SESSION_ID": "grok-1", "GROK_MESSAGE": ""}
    assert notify.handle_grok(env) == 0
    assert calls[-1][:3] == ["announce", "--event", "start"]
    assert "--feature-key" in calls[-1] and "grok-1" in calls[-1]

    for finish_event in ("turn_complete", "task_complete", "agent_error"):
        env["GROK_EVENT"] = finish_event
        assert notify.handle_grok(env) == 0
        assert calls[-1][:3] == ["announce", "--event", "finish"]

    env["GROK_EVENT"] = "approval_required"
    env["GROK_MESSAGE"] = "Approve rm -rf?"
    assert notify.handle_grok(env) == 0
    assert calls[-1][0] == "clarify"
    assert "Approve rm -rf?" in calls[-1]


def test_grok_context_defaults_to_grok_home_and_voice(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    for name in ("CODEX_AGENT_LABEL", "CODEX_AGENT_KIND", "CODEX_HOME",
                 "ATTS_VOICE", "ATTS_GROK_VOICE", "GROK_TTS_VOICE", "CODEX__TTS_VOICE"):
        monkeypatch.delenv(name, raising=False)

    assert notify.handle_grok({"GROK_EVENT": "turn_complete"}) == 0
    args = calls[-1]
    home = args[args.index("--codex-home") + 1]
    voice = args[args.index("--voice") + 1]
    assert home.endswith("/.grok")
    assert voice == "af_kore"


def test_grok_unmapped_event_is_silent(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    assert notify.handle_grok({"GROK_EVENT": "session_start"}) == 0
    assert calls == []


def test_main_routes_grok_flag_to_env_handler(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    monkeypatch.setenv("GROK_EVENT", "turn_complete")
    assert notify.main(["notify_agent.py", "--grok"]) == 0
    assert calls[-1][:3] == ["announce", "--event", "finish"]


def test_claude_hooks_prefer_the_tracker_launch_feature_key(monkeypatch, tmp_path):
    """Tracked launches key title/finish labels by the exported launch key.

    ACC launchers export CODEX_AGENT_FEATURE_KEY; hooks inherit it from the
    agent process. Using it instead of the Claude session id keeps the title
    hook and the tracker's finish announcement on the same stored feature
    label, so a tracked session's finish never speaks a label another
    concurrent session stored (the "done with <other session's task>" bug).
    """
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "reconnect keyboards"}}),
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    monkeypatch.setenv("CODEX_AGENT_FEATURE_KEY", "launch-777")

    common = {
        "session_id": "claude-session-9",
        "cwd": "/repo/demo",
        "transcript_path": str(transcript),
    }
    assert notify.handle_claude(
        {**common, "hook_event_name": "UserPromptSubmit", "prompt": "reconnect keyboards"}
    ) == 0
    assert notify.handle_claude({**common, "hook_event_name": "Stop"}) == 0

    for args in calls:
        assert args[args.index("--feature-key") + 1] == "launch-777"


def test_parse_payload_ignores_flag_arguments():
    """Flag-style argv entries must not be mistaken for a Codex JSON payload.

    Regression: invoking the hook as ``notify_agent.py --claude`` logged
    ``invalid payload '--claude'`` and dropped the real stdin payload.
    """
    payload = notify.parse_payload(
        ["notify_agent.py", "--claude"],
        stdin_text='{"hook_event_name": "Stop"}',
    )
    assert payload == {"hook_event_name": "Stop"}


def test_parse_payload_still_prefers_positional_json():
    payload = notify.parse_payload(
        ["notify_agent.py", '{"type": "agent-turn-complete"}'],
        stdin_text=None,
    )
    assert payload == {"type": "agent-turn-complete"}


def test_main_detaches_codex_stop_before_tracker_work(monkeypatch):
    """A cached foreground Stop hook must return before tracker/TTS work runs."""
    launches = []

    class Child:
        pid = 4321

    def launch(command, **kwargs):
        launches.append((command, kwargs))
        return Child()

    monkeypatch.setenv("CODEX_AGENT_KIND", "codex")
    monkeypatch.delenv("ATTS_CODEX_HOOK_BACKGROUND", raising=False)
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    monkeypatch.setattr(
        notify,
        "handle_codex",
        lambda payload: pytest.fail("foreground process handled Codex Stop"),
    )

    payload = {"hook_event_name": "Stop", "turn_id": "turn-stale"}
    assert notify.main(["/installed/notify_agent.py"], json.dumps(payload)) == 0

    command, kwargs = launches[0]
    assert command == [
        sys.executable,
        "/installed/notify_agent.py",
        json.dumps(payload, separators=(",", ":")),
    ]
    assert kwargs["stdin"] is notify.subprocess.DEVNULL
    assert kwargs["stdout"] is notify.subprocess.DEVNULL
    assert kwargs["stderr"] is notify.subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True
    assert kwargs["env"]["ATTS_CODEX_HOOK_BACKGROUND"] == "1"


def test_main_detaches_codex_prompt_before_slow_title_work(monkeypatch):
    """Prompt submission must return before title summarization can consume its budget."""
    launches = []

    class Child:
        pid = 4322

    def launch(command, **kwargs):
        launches.append((command, kwargs))
        return Child()

    monkeypatch.setenv("CODEX_AGENT_KIND", "codex")
    monkeypatch.delenv("ATTS_CODEX_HOOK_BACKGROUND", raising=False)
    monkeypatch.setattr(notify.subprocess, "Popen", launch)
    monkeypatch.setattr(
        notify,
        "handle_codex",
        lambda payload: pytest.fail("foreground process waited for Codex prompt work"),
    )

    payload = {
        "hook_event_name": "UserPromptSubmit",
        "turn_id": "turn-complex",
        "prompt": "analyze a complex prompt before producing a concise terminal title",
    }
    assert notify.main(["/installed/notify_agent.py"], json.dumps(payload)) == 0

    command, kwargs = launches[0]
    assert command[:2] == [sys.executable, "/installed/notify_agent.py"]
    assert json.loads(command[2]) == payload
    assert kwargs["stdin"] is notify.subprocess.DEVNULL
    assert kwargs["stdout"] is notify.subprocess.DEVNULL
    assert kwargs["stderr"] is notify.subprocess.DEVNULL
    assert kwargs["start_new_session"] is True
    assert kwargs["close_fds"] is True
    assert kwargs["env"]["ATTS_CODEX_HOOK_BACKGROUND"] == "1"


def test_detached_codex_prompt_clips_payload_before_exec(monkeypatch):
    """Detaching must not reintroduce exec-size failures for pasted prompts."""
    launches = []

    class Child:
        pid = 4323

    monkeypatch.setenv("CODEX_AGENT_KIND", "codex")
    monkeypatch.delenv("ATTS_CODEX_HOOK_BACKGROUND", raising=False)
    monkeypatch.setattr(
        notify.subprocess,
        "Popen",
        lambda command, **kwargs: launches.append(command) or Child(),
    )

    payload = {"hook_event_name": "UserPromptSubmit", "prompt": "word " * 100_000}
    assert notify.main(["/installed/notify_agent.py"], json.dumps(payload)) == 0

    background_payload = json.loads(launches[0][2])
    assert len(background_payload["prompt"]) <= notify.SPOKEN_TEXT_MAX
    assert background_payload["prompt"].endswith("…")


def test_codex_prompt_entrypoint_returns_before_slow_title(monkeypatch, tmp_path):
    """A slow title subprocess must not consume the foreground hook budget."""
    home = tmp_path / "home"
    tracker = home / ".local/bin/codex-agent-tracker"
    events = home / "tracker-events.log"
    tracker.parent.mkdir(parents=True)
    tracker.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, time\n"
        "from pathlib import Path\n"
        "event = sys.argv[1]\n"
        "if event == 'title':\n"
        "    time.sleep(1)\n"
        "with (Path.home() / 'tracker-events.log').open('a') as handle:\n"
        "    handle.write(event + '\\n')\n",
        encoding="utf-8",
    )
    tracker.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "ATTS_LIFECYCLE_TRACKED": "1",
            "ATTS_LOG_DIR": str(tmp_path / "log"),
            "ATTS_NO_AUDIO": "1",
            "CODEX_AGENT_KIND": "codex",
            "CODEX_AGENT_LABEL": "Codex Luna low",
            "CODEX_AGENT_RUN_ID": "benchmark-luna-low",
        }
    )
    env.pop("ATTS_CODEX_HOOK_BACKGROUND", None)
    env.pop("ATTS_CODEX_STOP_BACKGROUND", None)
    payload = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "turn_id": "complex-luna-low",
            "prompt": "analyze this complex multi-part startup request " * 2_000,
            "cwd": str(ROOT),
        }
    )

    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/notify_agent.py")],
        input=payload,
        text=True,
        capture_output=True,
        timeout=0.8,
        check=False,
        env=env,
    )
    foreground_seconds = time.monotonic() - started

    assert result.returncode == 0, result.stderr
    assert foreground_seconds < 0.8
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if events.is_file() and events.read_text(encoding="utf-8").splitlines() == [
            "turn-start",
            "title",
        ]:
            break
        time.sleep(0.02)
    assert events.read_text(encoding="utf-8").splitlines() == ["turn-start", "title"]


@pytest.mark.parametrize("event", ["UserPromptSubmit", "Stop"])
def test_detached_codex_child_handles_payload_without_recursing(monkeypatch, event):
    """The detached child marker must route lifecycle work without re-forking."""
    handled = []
    monkeypatch.setenv("CODEX_AGENT_KIND", "codex")
    monkeypatch.setenv("ATTS_CODEX_HOOK_BACKGROUND", "1")
    monkeypatch.setattr(notify, "handle_codex", lambda payload: handled.append(payload) or 0)
    monkeypatch.setattr(
        notify.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("detached child attempted to re-fork"),
    )

    payload = {"hook_event_name": event, "turn_id": "turn-child"}
    assert notify.main(["/installed/notify_agent.py"], json.dumps(payload)) == 0
    assert handled == [payload]


def test_legacy_codex_stop_worker_marker_still_prevents_refork(monkeypatch):
    """A Stop child launched by pre-upgrade code must survive an in-place install."""
    handled = []
    monkeypatch.setenv("CODEX_AGENT_KIND", "codex")
    monkeypatch.delenv("ATTS_CODEX_HOOK_BACKGROUND", raising=False)
    monkeypatch.setenv("ATTS_CODEX_STOP_BACKGROUND", "1")
    monkeypatch.setattr(notify, "handle_codex", lambda payload: handled.append(payload) or 0)
    monkeypatch.setattr(
        notify.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("legacy Stop worker attempted to re-fork"),
    )

    payload = {"hook_event_name": "Stop", "turn_id": "legacy-stop-child"}
    assert notify.main(["/installed/notify_agent.py"], json.dumps(payload)) == 0
    assert handled == [payload]


def test_codex_prompt_detach_failure_logs_and_falls_back(monkeypatch):
    """A worker launch failure must remain observable without dropping prompt work."""
    handled = []
    errors = []

    def fail_to_launch(*args, **kwargs):
        raise OSError("fork unavailable")

    monkeypatch.setenv("CODEX_AGENT_KIND", "codex")
    monkeypatch.delenv("ATTS_CODEX_HOOK_BACKGROUND", raising=False)
    monkeypatch.setattr(notify.subprocess, "Popen", fail_to_launch)
    monkeypatch.setattr(notify.log, "error", lambda message, **kwargs: errors.append(message))
    monkeypatch.setattr(notify, "handle_codex", lambda payload: handled.append(payload) or 0)

    payload = {"hook_event_name": "UserPromptSubmit", "turn_id": "turn-fallback"}
    assert notify.main(["/installed/notify_agent.py"], json.dumps(payload)) == 0
    assert handled == [payload]
    assert errors == ["failed to detach Codex UserPromptSubmit worker: fork unavailable"]


def _context(**overrides):
    base = dict(
        label="claude",
        project_name="demo",
        project_path="/repo/demo",
        voice="af_sky",
        codex_home=Path("/home/user/.claude"),
    )
    base.update(overrides)
    return notify.RuntimeContext(**base)


def test_announce_clips_oversized_task_description(monkeypatch):
    """Huge transcript prompts must not exceed the exec argv limit.

    Regression: a multi-hundred-KB task description raised
    ``[Errno 7] Argument list too long`` and the finish announcement died.
    """
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    assert notify.announce("finish", _context(), task_description="word " * 100_000)
    spoken = calls[0][calls[0].index("--task-description") + 1]
    assert len(spoken) <= notify.SPOKEN_TEXT_MAX
    assert spoken.startswith("word word")


def test_update_title_and_clarify_clip_oversized_text(monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)

    notify.update_title("p " * 200_000, _context())
    notify.clarify(_context(), "q " * 200_000)
    title = calls[0][calls[0].index("--prompt") + 1]
    question = calls[1][calls[1].index("--question") + 1]
    assert len(title) <= notify.SPOKEN_TEXT_MAX
    assert len(question) <= notify.SPOKEN_TEXT_MAX


def test_run_tracker_logs_arg_bytes_when_launch_fails(monkeypatch):
    """An exec failure must record the payload size that caused it."""
    logged = []
    monkeypatch.setattr(notify.log, "error", lambda msg, **kw: logged.append(msg))

    def boom(*args, **kwargs):
        raise OSError(7, "Argument list too long")

    monkeypatch.setattr(notify.subprocess, "run", boom)

    assert notify.run_tracker(["announce", "--task-description", "x" * 64]) is False
    assert logged and "arg bytes" in logged[0]


@pytest.mark.parametrize("event,action", [("UserPromptSubmit", "start"), ("Stop", "finish")])
@pytest.mark.parametrize("kind,model,spoken", [
    ("codex", "GPT 6 Astra", "Astra"),
    ("codex", "gpt-6-astra", "Astra"),
    ("claude", "Opus 5", "Opus 5"),
])
def test_hook_preserves_runtime_model_in_spoken_announcement(monkeypatch, event, action, kind, model, spoken):
    """Hook-owned speech carries the wrapper model through the shared wording path."""
    calls = []
    monkeypatch.setenv("CODEX_AGENT_KIND", kind)
    monkeypatch.setenv("CODEX_AGENT_LABEL", kind)
    monkeypatch.setenv("CODEX_AGENT_MODEL_NAME", model)
    monkeypatch.setenv("CODEX_AGENT_LMSTUDIO_MODEL", "stale-legacy-model")
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    handler = notify.handle_codex if kind == "codex" else notify.handle_claude
    hook_event = "SessionStart" if kind == "claude" and action == "start" else event
    handler({"hook_event_name": hook_event, "cwd": "/repo/demo", "prompt": "fix speech"})
    announcement = next(args for args in calls if args[0] == "announce")
    assert announcement[announcement.index("--event") + 1] == action
    forwarded_model = announcement[announcement.index("--model-name") + 1]
    assert forwarded_model == model
    text = notify.tts_engine.agent_announcement_text(kind, "demo", action, model_name=forwarded_model)
    assert notify.tts_engine.short_model_announcement(text).startswith(spoken + ". ")


@pytest.mark.parametrize("env,expected", [
    ({}, ""),
    ({"CODEX_AGENT_LMSTUDIO_MODEL": "legacy-model"}, "legacy-model"),
    ({"CODEX_AGENT_KIND": "qwen", "QWEN_CODEX_LMSTUDIO_MODEL": "local-model"}, "local-model"),
])
def test_hook_model_fallbacks(monkeypatch, env, expected):
    """Bare hooks and legacy Local launches retain their existing model fallback."""
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert notify.context_for({}, "codex").model_name == expected


@pytest.mark.parametrize("tracked", [False, True])
def test_grok_planner_stop_does_not_complete_parent(monkeypatch, tracked):
    """Grok's inherited Claude hook must ignore a goal planner finishing."""
    monkeypatch.setenv("ATTS_LIFECYCLE_TRACKED", "1" if tracked else "0")
    monkeypatch.setenv("CODEX_AGENT_RUN_ID", "grok-parent")
    monkeypatch.setenv("CODEX_AGENT_KIND", "grok")
    calls = []
    monkeypatch.setattr(notify, "run_tracker", lambda args: calls.append(args) or True)
    payload = {"hook_event_name": "SubagentStop", "cwd": "/repo",
               "session_id": "parent", "agent_id": "goal-planner"}
    assert notify.handle_claude(payload) == 0
    assert calls == []
    assert notify.handle_claude({**payload, "hook_event_name": "Stop"}) == 0
    assert len(calls) == 1
    assert calls[0][0] == ("turn-complete" if tracked else "announce")
