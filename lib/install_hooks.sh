#!/usr/bin/env bash
# install_hooks.sh - reusable installer helpers for generated notify hooks.

tts_msg() { printf '[TTS] %s\n' "$*"; }

tts_target_home() {
  printf '%s\n' "${TTS_TARGET_HOME:-$HOME}"
}

tts_install_root() {
  printf '%s\n' "${TTS_INSTALL_ROOT:-$(tts_target_home)/.local/share/codex-claude-tts-announcements}"
}

tts_hook_command() {
  printf 'python3 %s/scripts/notify_agent.py' "$(tts_install_root)"
}

install_tts_hook_files() {
  local root
  root="$(tts_install_root)"
  mkdir -p "$root/lib/tts_announcements" "$root/scripts"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/__init__.py" "$root/lib/tts_announcements/__init__.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/notify.py" "$root/lib/tts_announcements/notify.py"
  install -m 0755 "$SCRIPT_DIR/scripts/notify_agent.py" "$root/scripts/notify_agent.py"
}

configure_codex_notify_hook() {
  local home config_file command
  home="$(tts_target_home)"
  config_file="${CODEX_CONFIG_FILE:-$home/.codex/config.toml}"
  command="$(tts_hook_command)"
  mkdir -p "$(dirname "$config_file")"
  TTS_CODEX_CONFIG_FILE="$config_file" TTS_NOTIFY_COMMAND="$command" python3 - <<'PY'
import json
import os
import re
from pathlib import Path

config_file = Path(os.environ["TTS_CODEX_CONFIG_FILE"])
command = os.environ["TTS_NOTIFY_COMMAND"]
block = (
    "# BEGIN TTS ANNOUNCEMENTS NOTIFY (generated)\n"
    f"notify = {json.dumps(command.split())}\n"
    "# END TTS ANNOUNCEMENTS NOTIFY (generated)\n"
)
try:
    text = config_file.read_text(encoding="utf-8")
except FileNotFoundError:
    text = ""
text = re.sub(
    r"# BEGIN TTS ANNOUNCEMENTS NOTIFY(?: \(generated\))?.*?# END TTS ANNOUNCEMENTS NOTIFY(?: \(generated\))?\n*",
    "",
    text,
    flags=re.S,
)
text = re.sub(
    r"# BEGIN CODEX NOTIFY(?: \(generated\))?.*?# END CODEX NOTIFY(?: \(generated\))?\n*",
    "",
    text,
    flags=re.S,
)
text = re.sub(r"(?m)^notify = \[\"python3\", \".*notify_agent\.py\"\]\n+", "", text)
updated = block + ("\n" + text.lstrip() if text.strip() else "")
config_file.write_text(updated.rstrip() + "\n", encoding="utf-8")
PY
  tts_msg "Configured Codex notify hook in $config_file"
}

configure_claude_notify_hooks() {
  local home settings_file command
  home="$(tts_target_home)"
  settings_file="${CLAUDE_SETTINGS_FILE:-$home/.claude/settings.json}"
  command="$(tts_hook_command)"
  mkdir -p "$(dirname "$settings_file")"
  TTS_CLAUDE_SETTINGS_FILE="$settings_file" TTS_NOTIFY_COMMAND="$command" python3 - <<'PY'
import json
import os
from pathlib import Path

settings_file = Path(os.environ["TTS_CLAUDE_SETTINGS_FILE"])
command = os.environ["TTS_NOTIFY_COMMAND"]
legacy_acc_command = f"python3 {settings_file.parent / 'notify_agent.py'}"
generated_commands = {command, legacy_acc_command}

try:
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    if not isinstance(settings, dict):
        settings = {}
except Exception:
    settings = {}

hooks = settings.setdefault("hooks", {})
if not isinstance(hooks, dict):
    hooks = {}
    settings["hooks"] = hooks

def prune_generated(event):
    entries = hooks.get(event, [])
    if not isinstance(entries, list):
        hooks[event] = []
        return
    kept = []
    for entry in entries:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue
        entry_hooks = entry.get("hooks", [])
        if not isinstance(entry_hooks, list):
            kept.append(entry)
            continue
        filtered = [
            hook for hook in entry_hooks
            if not (isinstance(hook, dict) and hook.get("command") in generated_commands)
        ]
        if filtered:
            entry = dict(entry)
            entry["hooks"] = filtered
            kept.append(entry)
    hooks[event] = kept

def ensure_command(event, matcher=""):
    prune_generated(event)
    hooks.setdefault(event, []).append({
        "matcher": matcher,
        "hooks": [{"type": "command", "command": command}],
    })

ensure_command("SessionStart")
ensure_command("Stop")
ensure_command("SubagentStop")
ensure_command("UserPromptSubmit")
ensure_command("Notification")
ensure_command("PreToolUse", "Bash|Write|Edit|NotebookEdit")

settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
PY
  tts_msg "Configured Claude Code hooks in $settings_file"
}
