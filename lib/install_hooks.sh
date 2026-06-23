#!/usr/bin/env bash
# install_hooks.sh - reusable installer helpers for generated notify hooks.

tts_msg() { printf '[TTS] %s\n' "$*"; }

# Resolve the home directory that receives user-level config during install.
# Tests and parent installers override TTS_TARGET_HOME for clean-home runs.
tts_target_home() {
  printf '%s\n' "${TTS_TARGET_HOME:-$HOME}"
}

# Resolve the share directory that receives the hook and bundled Python modules.
tts_install_root() {
  printf '%s\n' "${TTS_INSTALL_ROOT:-$(tts_target_home)/.local/share/codex-claude-tts-announcements}"
}

# Build the command string written into Codex and Claude hook config.
tts_hook_command() {
  printf 'python3 %s/scripts/notify_agent.py' "$(tts_install_root)"
}

# Resolve the user bin directory where the agent-tts launcher symlink is placed.
tts_bin_dir() {
  printf '%s\n' "${TTS_BIN_DIR:-$(tts_target_home)/.local/bin}"
}

# Install the standalone Agent TTS (ATTS) speech engine and its `agent-tts`
# launcher. The engine owns all speech (synthesis, playback, speed/volume/silent
# tunables, voice selection, wording); runtimes such as agent_command_center
# delegate to the installed `agent-tts` binary.
install_agent_tts_engine() {
  local root bin
  root="$(tts_install_root)"
  bin="$(tts_bin_dir)"
  mkdir -p "$root/lib/agent_tts" "$root/scripts" "$bin"
  install -m 0644 "$SCRIPT_DIR/lib/agent_tts/__init__.py" "$root/lib/agent_tts/__init__.py"
  install -m 0644 "$SCRIPT_DIR/lib/agent_tts/engine.py" "$root/lib/agent_tts/engine.py"
  install -m 0644 "$SCRIPT_DIR/lib/agent_tts/cli.py" "$root/lib/agent_tts/cli.py"
  install -m 0755 "$SCRIPT_DIR/scripts/agent-tts" "$root/scripts/agent-tts"
  # The entrypoint resolves its bundled package relative to its real path, so a
  # symlink in PATH keeps finding `$root/lib`.
  ln -sf "$root/scripts/agent-tts" "$bin/agent-tts"
  tts_msg "Installed agent-tts engine to $root and linked $bin/agent-tts"
}

# Install the notify hook package and script without mutating any agent config.
install_tts_hook_files() {
  local root
  root="$(tts_install_root)"
  mkdir -p "$root/lib/tts_announcements" "$root/scripts"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/__init__.py" "$root/lib/tts_announcements/__init__.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/logging_utils.py" "$root/lib/tts_announcements/logging_utils.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/install_hooks.py" "$root/lib/tts_announcements/install_hooks.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/notify.py" "$root/lib/tts_announcements/notify.py"
  install -m 0755 "$SCRIPT_DIR/scripts/notify_agent.py" "$root/scripts/notify_agent.py"
}

# Merge the generated Codex notify command and PermissionRequest attention hook.
configure_codex_notify_hook() {
  local home config_file hooks_file command attention_command
  home="$(tts_target_home)"
  config_file="${CODEX_CONFIG_FILE:-$home/.codex/config.toml}"
  hooks_file="${CODEX_HOOKS_FILE:-$home/.codex/hooks.json}"
  command="$(tts_hook_command)"
  attention_command="env CODEX_AGENT_KIND=codex CODEX_AGENT_LABEL=codex $command"
  mkdir -p "$(dirname "$config_file")"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks codex "$config_file" "$command"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks codex-hooks "$hooks_file" "$attention_command"
  tts_msg "Configured Codex notify hooks in $config_file and $hooks_file"
}

# Merge generated Claude Code hook commands while preserving user-authored hooks.
configure_claude_notify_hooks() {
  local home settings_file command
  home="$(tts_target_home)"
  settings_file="${CLAUDE_SETTINGS_FILE:-$home/.claude/settings.json}"
  command="$(tts_hook_command)"
  mkdir -p "$(dirname "$settings_file")"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks claude "$settings_file" "$command"
  tts_msg "Configured Claude Code hooks in $settings_file"
}
