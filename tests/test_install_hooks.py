import json
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))


def test_standalone_checkout_clones_private_component_framework(tmp_path):
    """A checkout without siblings can bootstrap the private framework via Git."""
    checkout = tmp_path / "standalone/tts-announcements"
    shutil.copytree(
        ROOT,
        checkout,
        ignore=shutil.ignore_patterns(".git", ".log", ".pytest_cache", "__pycache__"),
    )
    framework = tmp_path / "private-framework"
    framework.mkdir()
    (framework / "component_loader.sh").write_text(
        "#!/usr/bin/env bash\n"
        "isc_activate_components() { source \"$ISC_FUNCTIONS_DIR/component_runtime.sh\"; }\n",
        encoding="utf-8",
    )
    (framework / "component_runtime.sh").write_text(
        "#!/usr/bin/env bash\n"
        "component_main() {\n"
        "  local entry id label default rest\n"
        "  case \"${1:-}\" in\n"
        "    --list-components)\n"
        "      for entry in \"${ISC_COMPONENTS[@]}\"; do\n"
        "        IFS='|' read -r id label default rest <<<\"$entry\"\n"
        "        printf '%s\\t%s\\t%s\\n' \"$id\" \"$label\" \"$default\"\n"
        "      done\n"
        "      ;;\n"
        "  esac\n"
        "}\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "init", "-q", "-b", "master"],
        cwd=framework,
        check=True,
    )
    subprocess.run(
        ["git", "add", "component_loader.sh", "component_runtime.sh"],
        cwd=framework,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=TTS Test",
            "-c",
            "user.email=tts-test@example.invalid",
            "commit",
            "-qm",
            "test framework",
        ],
        cwd=framework,
        check=True,
    )
    home = tmp_path / "home"
    home.mkdir()
    cache = tmp_path / "cache"

    result = subprocess.run(
        ["bash", str(checkout / "install.sh"), "--list-components"],
        cwd=checkout,
        env={
            "HOME": str(home),
            "XDG_CACHE_HOME": str(cache),
            "ISC_FUNCTIONS_GIT_URL": str(framework),
            "PATH": "/usr/bin:/bin",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "engine\tAgent TTS (agent-tts) speech engine\ton" in result.stdout
    assert list(cache.rglob("component_loader.sh"))


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
    assert "BEGIN TTS ANNOUNCEMENTS NOTIFY" not in written_codex
    assert "notify =" not in written_codex
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
    for event in ("UserPromptSubmit", "Stop"):
        lifecycle_commands = [
            hook["command"]
            for entry in installed_codex_hooks["hooks"][event]
            for hook in entry["hooks"]
        ]
        assert any("CODEX_AGENT_KIND=codex" in command for command in lifecycle_commands)
        assert any("notify_agent.py" in command for command in lifecycle_commands)

    prompt_handler = installed_codex_hooks["hooks"]["UserPromptSubmit"][-1]["hooks"][0]
    stop_handler = installed_codex_hooks["hooks"]["Stop"][-1]["hooks"][0]
    assert "async" not in prompt_handler
    assert prompt_handler["timeout"] == 10
    assert stop_handler["async"] is True
    assert stop_handler["timeout"] == 120

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


def test_codex_hooks_migrate_every_existing_account_home(tmp_path):
    """Primary and numbered Codex homes must share the lifecycle contract."""
    home = tmp_path / "home"
    primary = home / ".codex"
    secondary = home / ".codex-account-2"
    for codex_home in (primary, secondary):
        codex_home.mkdir(parents=True)
        (codex_home / "config.toml").write_text(
            '# BEGIN TTS ANNOUNCEMENTS NOTIFY (generated)\n'
            'notify = ["python3", "/old/notify_agent.py"]\n'
            '# END TTS ANNOUNCEMENTS NOTIFY (generated)\n\n'
            '[tui]\nstatus_line = ["keep"]\n',
            encoding="utf-8",
        )

    result = subprocess.run(
        [
            "bash",
            str(ROOT / "install.sh"),
            "--select",
            "codex_notify,codex_attention",
        ],
        cwd=ROOT,
        env={
            "HOME": str(home),
            "TTS_TARGET_HOME": str(home),
            "TTS_SKIP_SYSTEMD": "1",
            "ATTS_INSTALL_GPU_RUNTIME": "0",
            "TTS_LOG_DIR": str(tmp_path / "install-log"),
            "PATH": "/usr/bin:/bin",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    for codex_home in (primary, secondary):
        config = (codex_home / "config.toml").read_text(encoding="utf-8")
        assert "notify_agent.py" not in config
        assert 'status_line = ["keep"]' in config
        hooks = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))
        assert set(hooks["hooks"]) == {"UserPromptSubmit", "Stop", "PermissionRequest"}

    secondary_hooks_file = secondary / "hooks.json"
    secondary_hooks = json.loads(secondary_hooks_file.read_text(encoding="utf-8"))
    secondary_hooks["hooks"].pop("PermissionRequest")
    secondary_hooks_file.write_text(
        json.dumps(secondary_hooks, indent=2) + "\n", encoding="utf-8"
    )
    detected = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--detect"],
        cwd=ROOT,
        env={
            "HOME": str(home),
            "TTS_TARGET_HOME": str(home),
            "TTS_SKIP_SYSTEMD": "1",
            "TTS_LOG_DIR": str(tmp_path / "detect-log"),
            "PATH": "/usr/bin:/bin",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert detected.returncode == 0, detected.stderr
    assert "codex_notify\tinstalled" in detected.stdout
    assert "codex_attention\tabsent" in detected.stdout


def test_boot_prewarm_installs_enabled_systemd_user_unit(tmp_path):
    """The boot prewarm component lands an enable-ready systemd --user unit.

    The unit must self-install the core (so `agent-tts prewarm` exists), target
    the installed launcher, and be wired into the default login target. systemctl
    is skipped here so the test never touches the real user manager; uninstall
    must remove the unit again.
    """
    home = tmp_path / "home"
    home.mkdir()
    unit_dir = home / ".config/systemd/user"
    env = {
        "HOME": str(home),
        "TTS_TARGET_HOME": str(home),
        "TTS_SYSTEMD_USER_DIR": str(unit_dir),
        "TTS_SKIP_SYSTEMD": "1",
        "TTS_LOG_DIR": str(tmp_path / "install-log"),
        "PATH": "/usr/bin:/bin",
    }

    install = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--select", "boot_prewarm"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )
    assert install.returncode == 0, install.stderr

    unit = unit_dir / "agent-tts-prewarm.service"
    launcher = home / ".local/bin/agent-tts"
    assert launcher.exists(), "core engine must self-install for prewarm to run"
    body = unit.read_text(encoding="utf-8")
    assert f'ExecStart="{launcher}" prewarm' in body
    assert "WantedBy=default.target" in body

    detect = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--detect"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )
    assert "boot_prewarm\tinstalled" in detect.stdout

    remove = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--uninstall=boot_prewarm"],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )
    assert remove.returncode == 0, remove.stderr
    assert not unit.exists()


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


def test_engine_installs_hash_locked_gpu_runtime_idempotently(tmp_path):
    """NVIDIA installs sync the locked CUDA target once and preserve CPU fallback."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv_log = tmp_path / "uv.log"
    uv = bin_dir / "uv"
    uv.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$UV_CALL_LOG\"\n"
        "target=''\n"
        "while [ $# -gt 0 ]; do\n"
        "  if [ \"$1\" = '--target' ]; then target=$2; break; fi\n"
        "  shift\n"
        "done\n"
        "mkdir -p \"$target/onnxruntime\" \"$target/nvidia/cudnn/lib\"\n",
        encoding="utf-8",
    )
    uv.chmod(0o755)
    nvidia_smi = bin_dir / "nvidia-smi"
    nvidia_smi.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    nvidia_smi.chmod(0o755)
    env = {
        "HOME": str(home),
        "TTS_TARGET_HOME": str(home),
        "TTS_LOG_DIR": str(tmp_path / "install-log"),
        "UV_CALL_LOG": str(uv_log),
        "PATH": f"{bin_dir}:/usr/bin:/bin",
    }

    for _ in range(2):
        result = subprocess.run(
            ["bash", str(ROOT / "install.sh"), "--select", "engine"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    runtime = home / ".local/share/codex-claude-tts-announcements/gpu-runtime"
    assert (runtime / "onnxruntime").is_dir()
    assert (runtime / "nvidia/cudnn/lib").is_dir()
    assert (runtime / "python/onnxruntime").exists()
    assert "pip sync --require-hashes --target" in uv_log.read_text(encoding="utf-8")
    assert len(uv_log.read_text(encoding="utf-8").splitlines()) == 1
    installed_requirements = runtime.parent / "requirements-gpu.txt"
    assert "--hash=sha256:" in installed_requirements.read_text(encoding="utf-8")


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


def test_detect_rejects_stale_grok_and_codex_attention_hook_paths(tmp_path):
    """Old notify paths must remain absent so a default run migrates them."""
    home = tmp_path / "home"
    home.mkdir()
    grok_config = home / ".grok/config.toml"
    codex_hooks = home / ".codex/hooks.json"
    grok_config.parent.mkdir(parents=True)
    codex_hooks.parent.mkdir(parents=True)
    grok_config.write_text(
        "[[ui.notifications.hooks]]\n"
        'command = "python3 /old/notify_agent.py --grok"\n'
        'events = ["turn_complete"]\n',
        encoding="utf-8",
    )
    codex_hooks.write_text(
        json.dumps(
            {
                "hooks": {
                    "PermissionRequest": [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "python3 /old/notify_agent.py",
                                }
                            ],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    env = {
        "HOME": str(home),
        "TTS_TARGET_HOME": str(home),
        "TTS_LOG_DIR": str(tmp_path / "install-log"),
        "GROK_CONFIG_FILE": str(grok_config),
        "CODEX_HOOKS_FILE": str(codex_hooks),
        "PATH": "/usr/bin:/bin",
    }

    detected = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--detect"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert detected.returncode == 0, detected.stderr
    assert "grok_notify\tabsent" in detected.stdout
    assert "codex_attention\tabsent" in detected.stdout


def test_codex_lifecycle_hook_removal_preserves_attention_and_user_hooks(tmp_path):
    """Start/finish and attention components must uninstall independently."""
    from tts_announcements import install_hooks

    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "UserPromptSubmit": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": "echo keep"}],
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    lifecycle = "env CODEX_AGENT_KIND=codex python3 /managed/notify_agent.py"
    attention = "env CODEX_AGENT_LABEL=codex python3 /managed/notify_agent.py"

    install_hooks.configure_codex_hooks(
        hooks_file, lifecycle, ["UserPromptSubmit", "Stop"]
    )
    install_hooks.configure_codex_hooks(hooks_file, attention, ["PermissionRequest"])
    install_hooks.remove_codex_hooks(hooks_file, ["UserPromptSubmit", "Stop"])

    hooks = json.loads(hooks_file.read_text(encoding="utf-8"))["hooks"]
    prompt_commands = [
        hook["command"]
        for entry in hooks["UserPromptSubmit"]
        for hook in entry["hooks"]
    ]
    assert prompt_commands == ["echo keep"]
    assert "Stop" not in hooks
    assert "PermissionRequest" in hooks


def test_hook_commands_preserve_install_paths_with_spaces(tmp_path):
    """Every hook format must keep a spaced notify-script path as one argument."""
    home = tmp_path / "home with spaces"
    home.mkdir()
    env = {
        "HOME": str(home),
        "TTS_TARGET_HOME": str(home),
        "TTS_SKIP_SYSTEMD": "1",
        "ATTS_INSTALL_GPU_RUNTIME": "0",
        "TTS_LOG_DIR": str(tmp_path / "install-log"),
        "PATH": "/usr/bin:/bin",
    }
    selected = "codex_notify,codex_attention,grok_notify,claude_stop,cline_task_start,boot_prewarm"

    installed = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--select", selected],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert installed.returncode == 0, installed.stderr
    notify_script = home / ".local/share/codex-claude-tts-announcements/scripts/notify_agent.py"
    codex_config = home / ".codex/config.toml"
    assert not codex_config.exists() or "notify =" not in codex_config.read_text(encoding="utf-8")

    codex_hooks = json.loads((home / ".codex/hooks.json").read_text(encoding="utf-8"))
    for event in ("UserPromptSubmit", "Stop", "PermissionRequest"):
        codex_command = codex_hooks["hooks"][event][0]["hooks"][0]["command"]
        assert str(notify_script) in shlex.split(codex_command)

    claude = json.loads((home / ".claude/settings.json").read_text(encoding="utf-8"))
    claude_command = claude["hooks"]["Stop"][0]["hooks"][0]["command"]
    assert shlex.split(claude_command) == ["python3", str(notify_script)]

    grok = tomllib.loads((home / ".grok/config.toml").read_text(encoding="utf-8"))
    grok_command = grok["ui"]["notifications"]["hooks"][0]["command"]
    assert str(notify_script) in shlex.split(grok_command)

    cline_hook = home / ".cline/hooks/TaskStart"
    hook_result = subprocess.run(
        [str(cline_hook)],
        input=json.dumps({"hookName": "agent_start", "workspaceRoots": [str(home)]}),
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "ATTS_NO_AUDIO": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert hook_result.returncode == 0, hook_result.stderr
    assert json.loads(hook_result.stdout)["cancel"] is False

    unit = (home / ".config/systemd/user/agent-tts-prewarm.service").read_text(encoding="utf-8")
    assert f'ExecStart="{home / ".local/bin/agent-tts"}" prewarm' in unit

    detected = subprocess.run(
        ["bash", str(ROOT / "install.sh"), "--detect"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert detected.returncode == 0, detected.stderr
    for component in selected.split(","):
        assert f"{component}\tinstalled" in detected.stdout
