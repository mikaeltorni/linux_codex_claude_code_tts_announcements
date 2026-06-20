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
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/install_hooks.py" "$root/lib/tts_announcements/install_hooks.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/notify.py" "$root/lib/tts_announcements/notify.py"
  install -m 0755 "$SCRIPT_DIR/scripts/notify_agent.py" "$root/scripts/notify_agent.py"
}

configure_codex_notify_hook() {
  local home config_file command
  home="$(tts_target_home)"
  config_file="${CODEX_CONFIG_FILE:-$home/.codex/config.toml}"
  command="$(tts_hook_command)"
  mkdir -p "$(dirname "$config_file")"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks codex "$config_file" "$command"
  tts_msg "Configured Codex notify hook in $config_file"
}

configure_claude_notify_hooks() {
  local home settings_file command
  home="$(tts_target_home)"
  settings_file="${CLAUDE_SETTINGS_FILE:-$home/.claude/settings.json}"
  command="$(tts_hook_command)"
  mkdir -p "$(dirname "$settings_file")"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks claude "$settings_file" "$command"
  tts_msg "Configured Claude Code hooks in $settings_file"
}
