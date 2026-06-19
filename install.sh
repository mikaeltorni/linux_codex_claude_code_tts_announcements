#!/usr/bin/env bash
# install.sh — TTS Announcement Hooks Installer for Codex/Claude Code
#
# This script checks if codex and/or claudecode are installed, then installs
# TTS announcement hooks into those locations.
#
# Usage:
#   bash install.sh              # user-level install; apt steps skipped
#   sudo bash install.sh         # full install including apt packages

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

msg() { printf '[TTS] %s\n' "$*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

# Install TTS announcement hooks for codex if installed.
install_codex_tts_hooks() {
  local codex_bin=""
  
  # Try to find codex binary
  codex_bin="$(command -v codex 2>/dev/null || true)"
  [ -z "$codex_bin" ] && return 0
  
  msg "Found codex at $codex_bin — installing TTS announcement hooks"
  
  local hooks_dir="$HOME/.config/codex-tts-hooks"
  mkdir -p "$hooks_dir"
  
  # Create a wrapper that adds TTS announcements on top of codex calls
  cat > "$hooks_dir/tts-wrapper.sh" << 'WRAPPER_EOF'
#!/usr/bin/env bash
# codex TTS announcement wrapper — intercepts codex calls and announces them

set -euo pipefail

CODEX_BIN="${1:-codex}"
shift

# Determine if we're in a tracking context (agent tracker will handle this)
if [ -n "${CODEX_AGENT_TRACKER_ACTIVE:-}" ]; then
  exec "$CODEX_BIN" "$@"
fi

# Check for TTS voice configuration  
local tts_voice="${CODEX__TTS_VOICE:-${CLAUDE_TTS_VOICE:-}}"
if [ -z "$tts_voice" ] || [ ! -x "$(command -v codex-agent-tracker 2>/dev/null)" ]; then
  exec "$CODEX_BIN" "$@"
fi

# Parse the command to determine announcement type
local subcommand="${1:-help}"
shift 2>/dev/null || true

case "$subcommand" in
  start|run)
    local tts_text="Starting Codex agent..."
    if [ -n "${CODEX_AGENT_LABEL:-}" ]; then
      tts_text="Starting Codex agent: $CODEX_AGENT_LABEL"
    fi
    codex-agent-tracker announce --text "$tts_text" --voice "$tts_voice" 2>/dev/null || true
    ;;
  stop|kill)
    local tts_text="Codex agent stopped"
    codex-agent-tracker announce --text "$tts_text" --voice "$tts_voice" 2>/dev/null || true
    ;;
esac

exec "$CODEX_BIN" "$@"
WRAPPER_EOF
  
  chmod +x "$hooks_dir/tts-wrapper.sh"
  
  # Create a wrapper that replaces the codex binary
  local original_path
  original_path="$(which codex)"
  if [ -n "$original_path" ] && [ ! -L "$original_path" ]; then
    mv "$original_path" "${original_path}.real"
    ln -sf "$(readlink -f "$hooks_dir/tts-wrapper.sh")" "$original_path"
    msg "Replaced codex binary with TTS-aware wrapper at $original_path"
  fi
  
  return 0
}

# Install TTS announcement hooks for claudecode if installed.  
install_claudecode_tts_hooks() {
  local claudecode_bin=""
  
  # Try to find claudecode binary
  claudecode_bin="$(command -v claude 2>/dev/null || true)"
  [ -z "$claudecode_bin" ] && return 0
  
  msg "Found Claude Code at $claudecode_bin — installing TTS announcement hooks"
  
  local hooks_dir="$HOME/.config/claude-tts-hooks"
  mkdir -p "$hooks_dir"
  
  # Create wrapper for claude code TTS announcements
  cat > "$hooks_dir/tts-wrapper.sh" << 'WRAPPER_EOF'
#!/usr/bin/env bash
# Claude Code TTS announcement wrapper — intercepts claude calls and announces them

set -euo pipefail

CLAUDE_BIN="${1:-claude}"
shift

# Check for TTS voice configuration  
local tts_voice="${CLAUDE_TTS_VOICE:-${CODEX__TTS_VOICE:-}}"
if [ -z "$tts_voice" ] || [ ! -x "$(command -v codex-agent-tracker 2>/dev/null)" ]; then
  exec "$CLAUDE_BIN" "$@"
fi

# Parse the command to determine announcement type  
local subcommand="${1:--h}"
shift 2>/dev/null || true

case "$subcommand" in
  --help|-h)
    ;; # Don't announce help commands
  *)
    local tts_text="Starting Claude Code agent..."
    codex-agent-tracker announce --text "$tts_text" --voice "$tts_voice" 2>/dev/null || true
    ;;
esac

exec "$CLAUDE_BIN" "$@"
WRAPPER_EOF
  
  chmod +x "$hooks_dir/tts-wrapper.sh"
  
  # Create a wrapper that replaces the claude binary
  local original_path
  original_path="$(which claude)"
  if [ -n "$original_path" ] && [ ! -L "$original_path" ]; then
    mv "$original_path" "${original_path}.real"
    ln -sf "$(readlink -f "$hooks_dir/tts-wrapper.sh")" "$original_path"
    msg "Replaced claude binary with TTS-aware wrapper at $original_path"
  fi
  
  return 0
}

# Main entry point.
main() {
  msg "TTS Announcement Hooks Installer"
  
  install_codex_tts_hooks || true
  install_claudecode_tts_hooks || true
  
  if ! need_cmd codex && ! need_cmd claude; then
    msg "No Codex or Claude Code installation found — nothing to configure."
  else
    msg "TTS announcement hooks installed successfully."
    echo ""
    echo "Hooks location: $HOME/.config/{codex,claude}-tts-hooks/"
    echo "To update hooks after changes, run this script again."
  fi
  
  return 0
}

main "$@"
