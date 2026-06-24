#!/usr/bin/env bash
# components.sh - Component manifest for linux_codex_claude_code_tts_announcements.
#
# Maps each TTS announcement component to the function (defined in
# lib/install_hooks.sh) that installs it. install.sh sources that library and
# this manifest, then routes execution through component_main from the shared
# component runtime.
#
# Entry format: "id|label|default(on/off)|function".

ISC_REPO_NAME="linux_codex_claude_code_tts_announcements"
ISC_REPO_LABEL="Codex/Claude Code TTS announcements"

# Every individual notify hook is its own selectable, optional component so a
# user can wire up exactly the runtimes and lifecycle events they use. The
# `engine` and `hook_files` core stay default-on, and each hook component also
# self-installs that core (see ensure_tts_core in lib/install_hooks.sh), so the
# program works no matter which subset is selected.
ISC_COMPONENTS=(
  "engine|Agent TTS (agent-tts) speech engine|on|install_agent_tts_engine"
  "hook_files|TTS notify hook files|on|install_tts_hook_files"
  "codex_notify|Codex lifecycle notify block (config.toml)|on|configure_codex_notify_block"
  "codex_attention|Codex PermissionRequest attention hook (hooks.json)|on|configure_codex_attention_hook"
  "claude_session_start|Claude Code SessionStart hook|on|configure_claude_session_start_hook"
  "claude_stop|Claude Code Stop hook|on|configure_claude_stop_hook"
  "claude_subagent_stop|Claude Code SubagentStop hook|on|configure_claude_subagent_stop_hook"
  "claude_user_prompt|Claude Code UserPromptSubmit hook|on|configure_claude_user_prompt_hook"
  "claude_notification|Claude Code Notification hook|on|configure_claude_notification_hook"
)
