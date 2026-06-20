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

ISC_COMPONENTS=(
  "engine|Agent TTS (agent-tts) speech engine|on|install_agent_tts_engine"
  "hook_files|TTS notify hook files|on|install_tts_hook_files"
  "codex_hook|Codex notify hook configuration|on|configure_codex_notify_hook"
  "claude_hooks|Claude Code notify hooks configuration|on|configure_claude_notify_hooks"
)
