#!/usr/bin/env bash
# install.sh - user-level TTS announcement hook installer.
#
# Installs shared notify hooks for Codex, Claude Code, and Cline without replacing
# either runtime's executable. Generated config blocks are idempotent and
# unrelated user settings are preserved.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB="$SCRIPT_DIR/lib/install_hooks.sh"

# Edit this list to change the voices offered by the manual arrow-key picker.
# Keep runtime defaults separate: reordering this catalog never changes them.
TTS_VOICES=(af_bella af_sky af_heart af_aoede af_kore af_jessica af_sarah)

# shellcheck source=lib/install_hooks.sh
source "$INSTALL_LIB"

# Load the shared installer component framework. Its single source of truth is
# the linux_installation_scripts_functions repository (cloned as a sibling by
# installation_scripts, cloned non-interactively into the user cache for a
# private standalone checkout, or downloaded from a public raw mirror) -- no
# per-repo vendored copy.
for __isc_d in "${ISC_FUNCTIONS_DIR:-}" \
               "$SCRIPT_DIR/../linux_installation_scripts_functions" \
               "$HOME/projects/linux_installation_scripts_functions"; do
  if [ -n "$__isc_d" ] && [ -f "$__isc_d/component_loader.sh" ]; then
    ISC_FUNCTIONS_DIR="$__isc_d"
    export ISC_FUNCTIONS_DIR
    # shellcheck source=/dev/null
    source "$__isc_d/component_loader.sh"
    break
  fi
done

# Both setup repositories are private. A developer who cloned this repository
# already has Git credentials, so use a prompt-free shallow clone before trying
# the unauthenticated raw URL (which correctly returns 404 for private repos).
if ! declare -F isc_activate_components >/dev/null 2>&1; then
  __isc_ref="${ISC_FUNCTIONS_REF:-master}"
  __isc_safe_ref="$(printf '%s' "$__isc_ref" | tr -c 'A-Za-z0-9._-' '_')"
  __isc_cache="${XDG_CACHE_HOME:-$HOME/.cache}/installation_scripts/functions-checkouts/$__isc_safe_ref"
  if [ ! -f "$__isc_cache/component_loader.sh" ] && command -v git >/dev/null 2>&1; then
    mkdir -p "$(dirname "$__isc_cache")"
    # An interrupted older clone is cache-only state and cannot be sourced.
    [ ! -e "$__isc_cache" ] || rm -rf "$__isc_cache"
    __isc_clone_tmp="${__isc_cache}.tmp.$$"
    rm -rf "$__isc_clone_tmp"
    __isc_git_url="${ISC_FUNCTIONS_GIT_URL:-https://github.com/mikaeltorni/linux_installation_scripts_functions.git}"
    if GIT_TERMINAL_PROMPT=0 git clone --quiet --depth 1 --branch "$__isc_ref" \
         "$__isc_git_url" "$__isc_clone_tmp" >/dev/null 2>&1; then
      if ! mv -T "$__isc_clone_tmp" "$__isc_cache" 2>/dev/null; then
        # Another concurrent installer may have populated the same cache first.
        rm -rf "$__isc_clone_tmp"
      fi
    else
      rm -rf "$__isc_clone_tmp"
    fi
  fi
  if [ -f "$__isc_cache/component_loader.sh" ]; then
    ISC_FUNCTIONS_DIR="$__isc_cache"
    export ISC_FUNCTIONS_DIR
    # shellcheck source=/dev/null
    source "$__isc_cache/component_loader.sh"
  fi
fi

# Public deployments and explicit mirrors can still bootstrap from raw files.
if ! declare -F isc_activate_components >/dev/null 2>&1; then
  __isc_raw="${ISC_FUNCTIONS_RAW:-https://raw.githubusercontent.com/mikaeltorni/linux_installation_scripts_functions/${ISC_FUNCTIONS_REF:-master}}"
  if __isc_loader_tmp="$(mktemp 2>/dev/null)"; then
    if command -v curl >/dev/null 2>&1 && \
       curl -fsSL "$__isc_raw/component_loader.sh" -o "$__isc_loader_tmp"; then
      # shellcheck source=/dev/null
      source "$__isc_loader_tmp"
    elif command -v wget >/dev/null 2>&1 && \
         wget -qO "$__isc_loader_tmp" "$__isc_raw/component_loader.sh"; then
      # shellcheck source=/dev/null
      source "$__isc_loader_tmp"
    fi
    rm -f "$__isc_loader_tmp"
  fi
fi

if ! declare -F isc_activate_components >/dev/null 2>&1; then
  printf 'ERROR: unable to load linux_installation_scripts_functions.\n' >&2
  printf 'Clone it beside this repository, set ISC_FUNCTIONS_DIR, or configure authenticated Git access.\n' >&2
  exit 1
fi
isc_activate_components
unset __isc_d __isc_ref __isc_safe_ref __isc_cache __isc_clone_tmp __isc_git_url __isc_raw __isc_loader_tmp
source "$SCRIPT_DIR/installer/components.sh"

# Install detected harnesses with a per-family voice choice on a real terminal.
# Parameters: positional arguments - component runtime options.
# Returns: zero after successful installation or cancellation.
main() {
  printf 'parameters=%s\n' "$*" >&2
  if [ "${1:-}" = --sync-harnesses ]; then
    if [ "$#" -ne 1 ]; then printf 'Usage: bash install.sh --sync-harnesses\n' >&2; return 2; fi
    if [ ! -f "$(tts_event_config_file)" ]; then export TTS_MANUAL_EVENTS_NEW=1; fi
    ensure_tts_core
    PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.installation \
      --home "$(tts_target_home)" --command "$(tts_hook_command)" --sync
    printf '0\n' >&2
    return 0
  fi
  if [ "$#" -eq 0 ] && [ -t 0 ] && [ -t 1 ]; then
    if [ ! -f "$(tts_event_config_file)" ]; then export TTS_MANUAL_EVENTS_NEW=1; fi
    ensure_tts_core
    PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.installation \
      --home "$(tts_target_home)" --command "$(tts_hook_command)" --voices "${TTS_VOICES[@]}"
    printf '0\n' >&2
    return 0
  fi
  tts_msg "Installing Codex/Claude Code TTS announcement hooks"
  component_main "$@"
  tts_msg "TTS announcement hooks installed."
  printf '0\n' >&2
}

# Listing/help must print only their own output (the master installer parses
# --list-components); bypass the surrounding messages for those.
case "${1:-}" in
  --list-components|--export-selection|--detect|--help|-h|--uninstall|--uninstall=*) component_main "$@"; exit $? ;;
esac

main "$@"
