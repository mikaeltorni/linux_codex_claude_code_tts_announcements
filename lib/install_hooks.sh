#!/usr/bin/env bash
# install_hooks.sh - reusable installer helpers for generated notify hooks.

# Resolve the directory for best-effort Bash installer diagnostics.
tts_log_dir() {
  printf '%s\n' "${TTS_LOG_DIR:-$SCRIPT_DIR/.log}"
}

# Mirror installer status to a file without changing stdout contracts.
tts_log() {
  local dir
  dir="$(tts_log_dir)"
  mkdir -p "$dir" 2>/dev/null || return 0
  printf '%s [install] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$dir/install.log" 2>/dev/null || true
}

tts_msg() {
  printf '[TTS] %s\n' "$*"
  tts_log "$*"
}

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

# Ensure the runtime core a notify hook depends on is present.
#
# The per-runtime hook components (codex_hook, claude_hooks) write config that
# points at notify_agent.py and, through the tracker, at the agent-tts engine.
# The shared component runtime has no dependency resolution, so a user may run a
# hook component without selecting `engine`/`hook_files`. Both installers below
# are idempotent, so calling them here guarantees the core works no matter which
# components are selected without disturbing repeated full installs.
ensure_tts_core() {
  install_agent_tts_engine
  install_tts_hook_files
}

# Write the generated Codex lifecycle notify block in config.toml.
configure_codex_notify_block() {
  local home config_file command
  home="$(tts_target_home)"
  config_file="${CODEX_CONFIG_FILE:-$home/.codex/config.toml}"
  command="$(tts_hook_command)"
  ensure_tts_core
  mkdir -p "$(dirname "$config_file")"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks codex "$config_file" "$command"
  tts_msg "Configured Codex notify block in $config_file"
}

# Merge the Codex PermissionRequest attention hook in hooks.json.
configure_codex_attention_hook() {
  local home hooks_file command attention_command
  home="$(tts_target_home)"
  hooks_file="${CODEX_HOOKS_FILE:-$home/.codex/hooks.json}"
  command="$(tts_hook_command)"
  attention_command="env CODEX_AGENT_KIND=codex CODEX_AGENT_LABEL=codex $command"
  ensure_tts_core
  mkdir -p "$(dirname "$hooks_file")"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks codex-hooks "$hooks_file" "$attention_command"
  tts_msg "Configured Codex attention hook in $hooks_file"
}

# Register one Claude Code lifecycle event's notify hook. Each event is its own
# selectable component; the writer prunes/re-adds only the named event so the
# components compose without clobbering each other.
configure_claude_event_hook() {
  local event="$1" home settings_file command
  home="$(tts_target_home)"
  settings_file="${CLAUDE_SETTINGS_FILE:-$home/.claude/settings.json}"
  command="$(tts_hook_command)"
  ensure_tts_core
  mkdir -p "$(dirname "$settings_file")"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks claude "$settings_file" "$command" "$event"
  tts_msg "Configured Claude Code $event hook in $settings_file"
}

configure_claude_session_start_hook() { configure_claude_event_hook SessionStart; }
configure_claude_stop_hook()          { configure_claude_event_hook Stop; }
configure_claude_subagent_stop_hook() { configure_claude_event_hook SubagentStop; }
configure_claude_user_prompt_hook()   { configure_claude_event_hook UserPromptSubmit; }
configure_claude_notification_hook()  { configure_claude_event_hook Notification; }
