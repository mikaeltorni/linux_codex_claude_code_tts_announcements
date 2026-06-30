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

# Register one Cline lifecycle event as an executable global hook. Cline's
# documented Linux hook contract uses extensionless event-named files under
# ~/.cline/hooks and exchanges JSON over stdin/stdout.
configure_cline_event_hook() {
  local event="$1" filter_tool="${2:-}" home hooks_dir hook_file command
  home="$(tts_target_home)"
  hooks_dir="${CLINE_HOOKS_DIR:-$home/.cline/hooks}"
  hook_file="$hooks_dir/$event"
  command="$(tts_hook_command)"
  ensure_tts_core
  mkdir -p "$hooks_dir"
  local py_args=(cline "$hook_file" "$command")
  [ -n "$filter_tool" ] && py_args+=(--filter-tool "$filter_tool")
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks \
    "${py_args[@]}"
  tts_msg "Configured Cline $event hook in $hook_file"
}

configure_cline_task_start_hook()   { configure_cline_event_hook TaskStart; }
configure_cline_task_resume_hook()  { configure_cline_event_hook TaskResume; }
configure_cline_task_complete_hook(){ configure_cline_event_hook TaskComplete; }
configure_cline_task_cancel_hook()  { configure_cline_event_hook TaskCancel; }
configure_cline_task_error_hook()   { configure_cline_event_hook TaskError; }
configure_cline_user_prompt_hook()  { configure_cline_event_hook UserPromptSubmit; }
configure_cline_pre_tool_use_hook() { configure_cline_event_hook PreToolUse ask_question; }

###############################################################################
# Detection and uninstall (component lifecycle)
###############################################################################
# detect_* report live state for --detect; uninstall_* reverse each component.
# The config-block components delegate removal to the symmetric remove-* CLI in
# tts_announcements.install_hooks so the exact generated content (and only that)
# is stripped, preserving user-authored config.

# tts_config_has - true when $1 (a config file) references the notify hook.
tts_config_has() {
  [ -f "$1" ] && grep -q 'notify_agent.py' "$1" 2>/dev/null
}

detect_engine()       { [ -e "$(tts_bin_dir)/agent-tts" ] || [ -f "$(tts_install_root)/scripts/agent-tts" ]; }
detect_hook_files()   { [ -f "$(tts_install_root)/scripts/notify_agent.py" ]; }
detect_codex_notify() { tts_config_has "${CODEX_CONFIG_FILE:-$(tts_target_home)/.codex/config.toml}"; }
detect_codex_attention() {
  local f="${CODEX_HOOKS_FILE:-$(tts_target_home)/.codex/hooks.json}"
  [ -f "$f" ] && grep -q 'PermissionRequest' "$f" 2>/dev/null && grep -q 'notify_agent.py' "$f" 2>/dev/null
}
# A Claude event hook is present when settings.json registers our command under
# that event. The pruning is event-specific, so detection greps the event name.
_tts_claude_has_event() {
  local event="$1" f="${CLAUDE_SETTINGS_FILE:-$(tts_target_home)/.claude/settings.json}"
  [ -f "$f" ] || return 1
  PYTHONPATH="$SCRIPT_DIR/lib" python3 - "$f" "$event" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(1)
event = sys.argv[2]
entries = (data.get("hooks") or {}).get(event) or []
for entry in entries if isinstance(entries, list) else []:
    for h in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
        if isinstance(h, dict) and "notify_agent.py" in str(h.get("command", "")):
            sys.exit(0)
sys.exit(1)
PY
}
detect_claude_session_start() { _tts_claude_has_event SessionStart; }
detect_claude_stop()          { _tts_claude_has_event Stop; }
detect_claude_subagent_stop() { _tts_claude_has_event SubagentStop; }
detect_claude_user_prompt()   { _tts_claude_has_event UserPromptSubmit; }
detect_claude_notification()  { _tts_claude_has_event Notification; }

_tts_cline_has_event() {
  local event="$1" home hooks_dir file
  home="$(tts_target_home)"
  hooks_dir="${CLINE_HOOKS_DIR:-$home/.cline/hooks}"
  file="$hooks_dir/$event"
  [ -x "$file" ] && grep -q 'TTS ANNOUNCEMENTS CLINE HOOK' "$file" 2>/dev/null
}
detect_cline_task_start()    { _tts_cline_has_event TaskStart; }
detect_cline_task_resume()   { _tts_cline_has_event TaskResume; }
detect_cline_task_complete() { _tts_cline_has_event TaskComplete; }
detect_cline_task_cancel()   { _tts_cline_has_event TaskCancel; }
detect_cline_task_error()    { _tts_cline_has_event TaskError; }
detect_cline_user_prompt()   { _tts_cline_has_event UserPromptSubmit; }
detect_cline_pre_tool_use()  { _tts_cline_has_event PreToolUse; }

uninstall_engine() {
  tts_msg "Removing agent-tts engine"
  rm -f "$(tts_bin_dir)/agent-tts"
  rm -rf "$(tts_install_root)/lib/agent_tts" "$(tts_install_root)/scripts/agent-tts"
}
uninstall_hook_files() {
  tts_msg "Removing TTS notify hook files"
  rm -rf "$(tts_install_root)/lib/tts_announcements" "$(tts_install_root)/scripts/notify_agent.py"
}
uninstall_codex_notify() {
  local f="${CODEX_CONFIG_FILE:-$(tts_target_home)/.codex/config.toml}"
  tts_msg "Removing Codex notify block from $f"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks remove-codex "$f"
}
uninstall_codex_attention() {
  local f="${CODEX_HOOKS_FILE:-$(tts_target_home)/.codex/hooks.json}"
  tts_msg "Removing Codex attention hook from $f"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks remove-codex-hooks "$f"
}
_tts_remove_claude_event() {
  local event="$1" f="${CLAUDE_SETTINGS_FILE:-$(tts_target_home)/.claude/settings.json}"
  tts_msg "Removing Claude $event notify hook from $f"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks \
    remove-claude "$f" "$(tts_hook_command)" "$event"
}
uninstall_claude_session_start() { _tts_remove_claude_event SessionStart; }
uninstall_claude_stop()          { _tts_remove_claude_event Stop; }
uninstall_claude_subagent_stop() { _tts_remove_claude_event SubagentStop; }
uninstall_claude_user_prompt()   { _tts_remove_claude_event UserPromptSubmit; }
uninstall_claude_notification()  { _tts_remove_claude_event Notification; }

_tts_remove_cline_event() {
  local event="$1" home hooks_dir file
  home="$(tts_target_home)"
  hooks_dir="${CLINE_HOOKS_DIR:-$home/.cline/hooks}"
  file="$hooks_dir/$event"
  tts_msg "Removing Cline $event notify hook from $file"
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks remove-cline "$file"
}
uninstall_cline_task_start()    { _tts_remove_cline_event TaskStart; }
uninstall_cline_task_resume()   { _tts_remove_cline_event TaskResume; }
uninstall_cline_task_complete() { _tts_remove_cline_event TaskComplete; }
uninstall_cline_task_cancel()   { _tts_remove_cline_event TaskCancel; }
uninstall_cline_task_error()    { _tts_remove_cline_event TaskError; }
uninstall_cline_user_prompt()   { _tts_remove_cline_event UserPromptSubmit; }
uninstall_cline_pre_tool_use()  { _tts_remove_cline_event PreToolUse; }
