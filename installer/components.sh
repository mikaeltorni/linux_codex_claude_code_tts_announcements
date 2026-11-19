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
ISC_REPO_LABEL="Codex/Claude Code/Cline/Grok TTS announcements"

ISC_PREFLIGHT=tts_log_install_start
ISC_POSTFLIGHT=tts_log_install_finish

# Announce the start of component installation through the shared install lifecycle.
# Parameters: none. Returns: zero after reporting the start.
tts_log_install_start() {
  printf 'parameters=none\n' >&2
  tts_msg "Installing Codex/Claude Code TTS announcement hooks"
  printf '0\n' >&2
  return 0
}

# Announce the end of component installation through the shared install lifecycle.
# Parameters: none. Returns: zero after reporting the finish.
tts_log_install_finish() {
  printf 'parameters=none\n' >&2
  tts_msg "TTS announcement hooks installed."
  printf '0\n' >&2
  return 0
}

# Every individual notify hook is its own selectable, optional component so a
# user can wire up exactly the runtimes and lifecycle events they use. The
# `engine` and `hook_files` core stay default-on, and each hook component also
# self-installs that core (see ensure_tts_core in lib/install_hooks.sh), so the
# program works no matter which subset is selected.
ISC_COMPONENTS=(
  "codex_cli|Install native Codex CLI (optional)|off|tts_install_codex_cli|tts_detect_codex_cli||Native CLIs"
  "claude_cli|Install native Claude Code CLI (optional)|off|tts_install_claude_cli|tts_detect_claude_cli||Native CLIs"
  "engine|Agent TTS (agent-tts) speech engine|on|install_agent_tts_engine|detect_engine|uninstall_engine|Core"
  "speech_runtime|Kokoro speech runtime and verified voice models|on|tts_install_speech_runtime|||Core"
  "hook_files|TTS notify hook files|on|install_tts_hook_files|detect_hook_files|uninstall_hook_files|Core"
  "boot_prewarm|Boot-time Kokoro prewarm (systemd user service)|on|install_boot_prewarm|detect_boot_prewarm|uninstall_boot_prewarm|Core"
  "start_voice|Start voice announcements|on|install_start_voice|detect_start_voice|uninstall_start_voice|Voice events"
  "finish_voice|End voice announcements|on|install_finish_voice|detect_finish_voice|uninstall_finish_voice|Voice events"
  "attention_voice|Ask-for-further-changes voice announcements|on|install_attention_voice|detect_attention_voice|uninstall_attention_voice|Voice events"
  "codex_notify|Codex start/finish lifecycle hooks (hooks.json)|on|configure_codex_notify_block|detect_codex_notify|uninstall_codex_notify|Codex hooks"
  "codex_attention|Codex PermissionRequest attention hook (hooks.json)|on|configure_codex_attention_hook|detect_codex_attention|uninstall_codex_attention|Codex hooks"
  "grok_notify|Grok lifecycle and attention hooks (config.toml)|on|configure_grok_notify_hook|detect_grok_notify|uninstall_grok_notify|Grok hooks"
  "claude_session_start|Claude Code SessionStart hook|on|configure_claude_session_start_hook|detect_claude_session_start|uninstall_claude_session_start|Claude Code hooks"
  "claude_stop|Claude Code Stop hook|on|configure_claude_stop_hook|detect_claude_stop|uninstall_claude_stop|Claude Code hooks"
  "claude_subagent_stop|Claude Code SubagentStop hook|on|configure_claude_subagent_stop_hook|detect_claude_subagent_stop|uninstall_claude_subagent_stop|Claude Code hooks"
  "claude_user_prompt|Claude Code UserPromptSubmit title hook|on|configure_claude_user_prompt_hook|detect_claude_user_prompt|uninstall_claude_user_prompt|Claude Code hooks"
  "claude_notification|Claude Code ask-for-further-changes hook|on|configure_claude_notification_hook|detect_claude_notification|uninstall_claude_notification|Claude Code hooks"
  "cline_task_start|Cline TaskStart hook|on|configure_cline_task_start_hook|detect_cline_task_start|uninstall_cline_task_start|Cline hooks"
  "cline_task_resume|Cline TaskResume hook|on|configure_cline_task_resume_hook|detect_cline_task_resume|uninstall_cline_task_resume|Cline hooks"
  "cline_task_complete|Cline TaskComplete hook|on|configure_cline_task_complete_hook|detect_cline_task_complete|uninstall_cline_task_complete|Cline hooks"
  "cline_task_cancel|Cline TaskCancel hook|on|configure_cline_task_cancel_hook|detect_cline_task_cancel|uninstall_cline_task_cancel|Cline hooks"
  "cline_task_error|Cline TaskError hook|on|configure_cline_task_error_hook|detect_cline_task_error|uninstall_cline_task_error|Cline hooks"
  "cline_user_prompt|Cline UserPromptSubmit title hook|on|configure_cline_user_prompt_hook|detect_cline_user_prompt|uninstall_cline_user_prompt|Cline hooks"
  "cline_pre_tool_use|Cline ask-for-further-changes hook|on|configure_cline_pre_tool_use_hook|detect_cline_pre_tool_use|uninstall_cline_pre_tool_use|Cline hooks"
)
