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
    assert any("codex-claude-tts-announcements/scripts/notify_agent.py" in command for command in stop_commands)
    assert "/old/notify_agent.py" not in stop_commands


def test_install_hook_shell_delegates_config_mutation_to_python_module():
    helper = (ROOT / "lib/install_hooks.sh").read_text(encoding="utf-8")

    assert "tts_announcements.install_hooks" in helper
    assert "python3 - <<'PY'" not in helper
