#!/usr/bin/env bash
# install.sh - user-level TTS announcement hook installer.
#
# Installs a shared notify hook for Codex and Claude Code without replacing
# either runtime's executable. Generated config blocks are idempotent and
# unrelated user settings are preserved.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB="$SCRIPT_DIR/lib/install_hooks.sh"

# shellcheck source=lib/install_hooks.sh
source "$INSTALL_LIB"

main() {
  tts_msg "Installing Codex/Claude Code TTS announcement hooks"
  install_tts_hook_files
  configure_codex_notify_hook
  configure_claude_notify_hooks
  tts_msg "TTS announcement hooks installed."
}

main "$@"
