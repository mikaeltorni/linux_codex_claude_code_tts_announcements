import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_installer_writes_config_hooks_without_replacing_binaries(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    codex_config = home / ".codex/config.toml"
    codex_hooks = home / ".codex/hooks.json"
    claude_settings = home / ".claude/settings.json"
    codex_config.parent.mkdir(parents=True)
    claude_settings.parent.mkdir(parents=True)
    codex_config.write_text(
        '# BEGIN CODEX NOTIFY (generated)\nnotify = ["python3", "/old/notify_agent.py"]\n# END CODEX NOTIFY (generated)\n\n[tui]\nstatus_line = ["old"]\n',
        encoding="utf-8",
    )
    codex_hooks.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo keep"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    claude_settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {"matcher": "", "hooks": [{"type": "command", "command": "python3 /old/notify_agent.py"}]},
                        {"matcher": "", "hooks": [{"type": "command", "command": "echo keep"}]},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        ["bash", str(ROOT / "install.sh")],
        cwd=ROOT,
        env={
            "HOME": str(home),
            "TTS_TARGET_HOME": str(home),
            "TTS_LOG_DIR": str(tmp_path / "install-log"),
            "CODEX_CONFIG_FILE": str(codex_config),
            "CODEX_HOOKS_FILE": str(codex_hooks),
            "CLAUDE_SETTINGS_FILE": str(claude_settings),
            "PATH": "/usr/bin:/bin",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    second_result = subprocess.run(
        ["bash", str(ROOT / "install.sh")],
        cwd=ROOT,
        env={
            "HOME": str(home),
            "TTS_TARGET_HOME": str(home),
            "TTS_LOG_DIR": str(tmp_path / "install-log"),
            "CODEX_CONFIG_FILE": str(codex_config),
            "CODEX_HOOKS_FILE": str(codex_hooks),
            "CLAUDE_SETTINGS_FILE": str(claude_settings),
            "PATH": "/usr/bin:/bin",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert second_result.returncode == 0, second_result.stderr
    install_log = tmp_path / "install-log/install.log"
    assert "Installing Codex/Claude Code TTS announcement hooks" in install_log.read_text(encoding="utf-8")
    install_root = home / ".local/share/codex-claude-tts-announcements"
    assert (install_root / "scripts/notify_agent.py").is_file()
    # logging_utils backs the relative import in notify.py; it must ship too.
    assert (install_root / "lib/tts_announcements/logging_utils.py").is_file()
    written_codex = codex_config.read_text(encoding="utf-8")
    assert "BEGIN TTS ANNOUNCEMENTS NOTIFY" in written_codex
    assert "/old/notify_agent.py" not in written_codex
    assert "[tui]" in written_codex
    assert not (tmp_path / "codex.real").exists()

    installed_codex_hooks = json.loads(codex_hooks.read_text(encoding="utf-8"))
    assert installed_codex_hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "echo keep"
    permission_hooks = installed_codex_hooks["hooks"]["PermissionRequest"]
    permission_commands = [hook["command"] for entry in permission_hooks for hook in entry["hooks"]]
    assert any("CODEX_AGENT_LABEL=codex" in command for command in permission_commands)
    assert any("CODEX_AGENT_KIND=codex" in command for command in permission_commands)
    assert any("notify_agent.py" in command for command in permission_commands)

    settings = json.loads(claude_settings.read_text(encoding="utf-8"))
    stop_commands = [hook["command"] for entry in settings["hooks"]["Stop"] for hook in entry["hooks"]]
    assert "echo keep" in stop_commands
    managed_stop_commands = [
        command
        for command in stop_commands
        if "codex-claude-tts-announcements/scripts/notify_agent.py" in command
    ]
    assert len(managed_stop_commands) == 1
    assert "/old/notify_agent.py" not in stop_commands


def test_single_hook_component_installs_core_and_only_that_hook(tmp_path):
    """Selecting one hook must self-install the core and wire only that hook.

    Guarantees the 'core works no matter what the user chooses' contract: a lone
    per-hook component pulls in the engine + notify files it depends on, writes
    only its own lifecycle event, and leaves every other runtime untouched.
    """
    home = tmp_path / "home"
    home.mkdir()
    claude_settings = home / ".claude/settings.json"
    codex_config = home / ".codex/config.toml"

    result = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--select", "claude_stop"],
        cwd=ROOT,
        env={
            "HOME": str(home),
            "TTS_TARGET_HOME": str(home),
            "TTS_LOG_DIR": str(tmp_path / "install-log"),
            "CLAUDE_SETTINGS_FILE": str(claude_settings),
            "CODEX_CONFIG_FILE": str(codex_config),
            "PATH": "/usr/bin:/bin",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    install_root = home / ".local/share/codex-claude-tts-announcements"
    # Core auto-installed despite engine/hook_files not being selected.
    assert (install_root / "scripts/notify_agent.py").is_file()
    assert (home / ".local/bin/agent-tts").exists()
    # Only the requested Claude event is registered; no Codex config is created.
    settings = json.loads(claude_settings.read_text(encoding="utf-8"))
    assert list(settings["hooks"].keys()) == ["Stop"]
    assert not codex_config.exists()


def test_lifecycle_voice_components_persist_independent_event_settings(tmp_path):
    """The standalone installer exposes independent start/end/attention toggles."""
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "TTS_TARGET_HOME": str(home),
        "TTS_LOG_DIR": str(tmp_path / "install-log"),
        "PATH": "/usr/bin:/bin",
    }

    engine_only = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--select", "engine"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert engine_only.returncode == 0, engine_only.stderr
    settings = home / ".config/agent-tts/announcements.env"
    assert settings.read_text(encoding="utf-8").splitlines() == [
        "ATTS_ANNOUNCE_START=0",
        "ATTS_ANNOUNCE_FINISH=0",
        "ATTS_ANNOUNCE_ATTENTION=0",
    ]

    selected = subprocess.run(
        [
            "bash",
            str(ROOT / "install.sh"),
            "--select",
            "start_voice,finish_voice,attention_voice",
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert selected.returncode == 0, selected.stderr
    assert settings.read_text(encoding="utf-8").splitlines() == [
        "ATTS_ANNOUNCE_START=1",
        "ATTS_ANNOUNCE_FINISH=1",
        "ATTS_ANNOUNCE_ATTENTION=1",
    ]

    listing = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--list-components"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert listing.returncode == 0, listing.stderr
    assert "start_voice\tStart voice announcements\ton" in listing.stdout
    assert "finish_voice\tEnd voice announcements\ton" in listing.stdout
    assert "attention_voice\tAsk-for-further-changes voice announcements\ton" in listing.stdout


def test_uninstalling_hook_files_keeps_engine_logging_dependency(tmp_path):
    """Removing notify hooks must leave a separately selected agent-tts usable."""
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "TTS_TARGET_HOME": str(home),
        "TTS_LOG_DIR": str(tmp_path / "install-log"),
        "ATTS_STATE_DIR": str(tmp_path / "state"),
        "ATTS_LOG_DIR": str(tmp_path / "runtime-log"),
        "PATH": "/usr/bin:/bin",
    }
    installed = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--select", "engine,hook_files"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stderr
    removed = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--uninstall", "hook_files"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert removed.returncode == 0, removed.stderr

    engine = subprocess.run(
        [str(home / ".local/bin/agent-tts"), "speed", "status"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert engine.returncode == 0, engine.stderr
    assert engine.stdout.strip() == "1.5"


def test_install_hook_shell_delegates_config_mutation_to_python_module():
    helper = (ROOT / "lib/install_hooks.sh").read_text(encoding="utf-8")

    assert "tts_announcements.install_hooks" in helper
    assert "python3 - <<'PY'" not in helper


def test_cline_hook_components_install_executable_global_hooks(tmp_path):
    """Cline lifecycle components should use its documented global hook path."""
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "install.sh"),
            "--select",
            "cline_task_start,cline_task_resume,cline_task_complete,cline_task_cancel,cline_task_error,cline_user_prompt",
        ],
        cwd=ROOT,
        env={
            "HOME": str(home),
            "TTS_TARGET_HOME": str(home),
            "TTS_LOG_DIR": str(tmp_path / "install-log"),
            "PATH": "/usr/bin:/bin",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    hooks = home / ".cline/hooks"
    for event in (
        "TaskStart",
        "TaskResume",
        "TaskComplete",
        "TaskCancel",
        "TaskError",
        "UserPromptSubmit",
    ):
        hook = hooks / event
        assert hook.is_file()
        assert hook.stat().st_mode & 0o111
        body = hook.read_text(encoding="utf-8")
        assert "TTS ANNOUNCEMENTS CLINE HOOK" in body
        assert "notify_agent.py" in body
        assert "CODEX_AGENT_KIND=cline" in body
        assert '{"cancel":false' in body

    hook_result = subprocess.run(
        [str(hooks / "TaskStart")],
        input=json.dumps(
            {
                "hookName": "agent_start",
                "workspaceRoots": ["/repo/demo"],
                "taskStart": {"task": "test hooks"},
            }
        ),
        env={
            "HOME": str(home),
            "PATH": f"{home / '.local/bin'}:/usr/bin:/bin",
            "ATTS_NO_AUDIO": "1",
            "ATTS_LOG_DIR": str(tmp_path / "runtime-log"),
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert hook_result.returncode == 0, hook_result.stderr
    assert json.loads(hook_result.stdout) == {
        "cancel": False,
        "contextModification": "",
        "errorMessage": "",
    }


def test_cline_hook_writer_refuses_to_clobber_user_hook(tmp_path):
    """An unmanaged hook at the canonical event path must be preserved."""
    hook = tmp_path / "TaskStart"
    hook.write_text("#!/bin/sh\necho user-hook\n", encoding="utf-8")
    result = subprocess.run(
        [
            "python3",
            "-m",
            "tts_announcements.install_hooks",
            "cline",
            str(hook),
            "python3 /managed/notify_agent.py",
        ],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "lib"), "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert hook.read_text(encoding="utf-8") == "#!/bin/sh\necho user-hook\n"


def test_cline_pre_tool_use_hook_gates_notifier_on_ask_question(tmp_path):
    """The PreToolUse hook only invokes the notifier for the ask_question tool."""
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [
            "bash",
            str(ROOT / "install.sh"),
            "--select",
            "cline_pre_tool_use",
        ],
        cwd=ROOT,
        env={
            "HOME": str(home),
            "TTS_TARGET_HOME": str(home),
            "TTS_LOG_DIR": str(tmp_path / "install-log"),
            "PATH": "/usr/bin:/bin",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    hook = home / ".cline/hooks/PreToolUse"
    assert hook.is_file()
    assert hook.stat().st_mode & 0o111
    body = hook.read_text(encoding="utf-8")
    assert "TTS ANNOUNCEMENTS CLINE HOOK" in body
    assert "notify_agent.py" in body
    assert "CODEX_AGENT_KIND=cline" in body
    # The bash guard gates the notifier on the ask_question tool name.
    assert "ask_question" in body
    assert "case" in body
    assert '{"cancel":false' in body

    # A routine tool call must still emit the Cline control JSON without
    # invoking the notifier (the guard skips it).
    routine = subprocess.run(
        [str(hook)],
        input=json.dumps(
            {"hookName": "tool_call", "tool_call": {"name": "read_files", "input": {}}}
        ),
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert routine.returncode == 0, routine.stderr
    assert json.loads(routine.stdout) == {
        "cancel": False,
        "contextModification": "",
        "errorMessage": "",
    }


def test_grok_notify_block_is_appended_and_idempotent(tmp_path):
    from tts_announcements import install_hooks

    config = tmp_path / ".grok" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('hints = { project_picker_disabled = true }\n', encoding="utf-8")
    command = "env CODEX_AGENT_KIND=grok CODEX_AGENT_LABEL=grok python3 /x/notify_agent.py"

    install_hooks.configure_grok_notify(config, command)
    install_hooks.configure_grok_notify(config, command)

    text = config.read_text(encoding="utf-8")
    assert text.count("[[ui.notifications.hooks]]") == 1
    assert text.count("BEGIN TTS ANNOUNCEMENTS GROK HOOKS") == 1
    # User TOML stays first so the appended table array cannot capture it.
    assert text.startswith("hints = ")
    assert '"--grok"' not in text  # --grok is inside the command string
    assert "notify_agent.py --grok" in text
    for event in install_hooks.GROK_HOOK_EVENTS:
        assert f'"{event}"' in text
    assert "only_unfocused = false" in text

    install_hooks.remove_grok_notify(config)
    cleaned = config.read_text(encoding="utf-8")
    assert "GROK HOOKS" not in cleaned
    assert cleaned.strip() == 'hints = { project_picker_disabled = true }'


def test_grok_writer_replaces_unmarked_table_after_grok_config_rewrite(tmp_path):
    from tts_announcements import install_hooks

    config = tmp_path / "config.toml"
    # Simulate Grok rewriting its config: markers stripped, table kept, and a
    # user-authored hook table present.
    config.write_text(
        "[ui]\nyolo = false\n\n"
        "[[ui.notifications.hooks]]\n"
        'command = "curl -s -d msg ntfy.sh/mine"\n'
        'events = ["turn_complete"]\n\n'
        "[[ui.notifications.hooks]]\n"
        'command = "env CODEX_AGENT_KIND=grok python3 /old/notify_agent.py --grok"\n'
        'events = ["turn_complete"]\n',
        encoding="utf-8",
    )
    install_hooks.configure_grok_notify(config, "python3 /new/notify_agent.py")
    text = config.read_text(encoding="utf-8")
    assert text.count("[[ui.notifications.hooks]]") == 2
    assert "ntfy.sh/mine" in text
    assert "/old/notify_agent.py" not in text
    assert "/new/notify_agent.py --grok" in text
