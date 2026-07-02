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
