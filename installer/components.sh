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

# Every individual notify hook is its own selectable, optional component so a
# user can wire up exactly the runtimes and lifecycle events they use. The
# `engine` and `hook_files` core stay default-on, and each hook component also
# self-installs that core (see ensure_tts_core in lib/install_hooks.sh), so the
# program works no matter which subset is selected.
ISC_COMPONENTS=(
  "engine|Agent TTS (agent-tts) speech engine|on|install_agent_tts_engine|detect_engine|uninstall_engine"
  "hook_files|TTS notify hook files|on|install_tts_hook_files|detect_hook_files|uninstall_hook_files"
  "codex_notify|Codex lifecycle notify block (config.toml)|on|configure_codex_notify_block|detect_codex_notify|uninstall_codex_notify"
  "codex_attention|Codex PermissionRequest attention hook (hooks.json)|on|configure_codex_attention_hook|detect_codex_attention|uninstall_codex_attention"
  "grok_notify|Grok lifecycle notification hooks (config.toml)|on|configure_grok_notify_hook|detect_grok_notify|uninstall_grok_notify"
  "claude_session_start|Claude Code SessionStart hook|on|configure_claude_session_start_hook|detect_claude_session_start|uninstall_claude_session_start"
  "claude_stop|Claude Code Stop hook|on|configure_claude_stop_hook|detect_claude_stop|uninstall_claude_stop"
  "claude_subagent_stop|Claude Code SubagentStop hook|on|configure_claude_subagent_stop_hook|detect_claude_subagent_stop|uninstall_claude_subagent_stop"
  "claude_user_prompt|Claude Code UserPromptSubmit hook|on|configure_claude_user_prompt_hook|detect_claude_user_prompt|uninstall_claude_user_prompt"
  "claude_notification|Claude Code Notification hook|on|configure_claude_notification_hook|detect_claude_notification|uninstall_claude_notification"
  "cline_task_start|Cline TaskStart hook|on|configure_cline_task_start_hook|detect_cline_task_start|uninstall_cline_task_start"
  "cline_task_resume|Cline TaskResume hook|on|configure_cline_task_resume_hook|detect_cline_task_resume|uninstall_cline_task_resume"
  "cline_task_complete|Cline TaskComplete hook|on|configure_cline_task_complete_hook|detect_cline_task_complete|uninstall_cline_task_complete"
  "cline_task_cancel|Cline TaskCancel hook|on|configure_cline_task_cancel_hook|detect_cline_task_cancel|uninstall_cline_task_cancel"
  "cline_task_error|Cline TaskError hook|on|configure_cline_task_error_hook|detect_cline_task_error|uninstall_cline_task_error"
  "cline_user_prompt|Cline UserPromptSubmit hook|on|configure_cline_user_prompt_hook|detect_cline_user_prompt|uninstall_cline_user_prompt"
  "cline_pre_tool_use|Cline PreToolUse (ask_question attention) hook|on|configure_cline_pre_tool_use_hook|detect_cline_pre_tool_use|uninstall_cline_pre_tool_use"
)
