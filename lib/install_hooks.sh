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

# Resolve the notify program written into hook config.
# Cargo installs the notify-agent ELF. A PATH that hides cargo keeps the
# Python script so clean-home tests still configure hooks.
tts_notify_program() {
  local elf
  elf="$(tts_install_root)/scripts/notify-agent"
  if [ "${TTS_RUST_BUILT:-}" = 1 ] && [ -x "$elf" ]; then
    printf '%s\n' "$elf"
    return
  fi
  if command -v cargo >/dev/null 2>&1 && [ -x "$elf" ]; then
    printf '%s\n' "$elf"
    return
  fi
  printf '%s\n' "$(tts_install_root)/scripts/notify_agent.py"
}

# Build the command string written into Codex and Claude hook config.
tts_hook_command() {
  local program
  program="$(tts_notify_program)"
  case "$program" in
    *.py) printf 'python3 %q' "$program" ;;
    *) printf '%q' "$program" ;;
  esac
}

# Run the hook-config writer. The release binary is used after a successful
# cargo build; otherwise the Python module remains the writer.
tts_run_hooks() {
  local bin="$SCRIPT_DIR/target/release/tts-hooks"
  if [ "${TTS_RUST_BUILT:-}" = 1 ] && [ -x "$bin" ]; then
    "$bin" "$@"
    return
  fi
  if command -v cargo >/dev/null 2>&1 && tts_build_agent_tts && [ -x "$bin" ]; then
    TTS_RUST_BUILT=1
    "$bin" "$@"
    return
  fi
  PYTHONPATH="$SCRIPT_DIR/lib" python3 -m tts_announcements.install_hooks "$@"
}

# Resolve the user bin directory where the agent-tts launcher symlink is placed.
tts_bin_dir() {
  printf '%s\n' "${TTS_BIN_DIR:-$(tts_target_home)/.local/bin}"
}

# Resolve the systemd user unit directory (override for clean-home tests).
tts_systemd_user_dir() {
  printf '%s\n' "${TTS_SYSTEMD_USER_DIR:-$(tts_target_home)/.config/systemd/user}"
}

# Resolve uv without assuming the target user's local bin directory is on PATH.
tts_resolve_uv() {
  local candidate
  for candidate in "$(command -v uv 2>/dev/null || true)" \
                   "$(tts_target_home)/.local/bin/uv" \
                   "$(tts_target_home)/.cargo/bin/uv"; do
    [ -n "$candidate" ] && [ -x "$candidate" ] && { printf '%s\n' "$candidate"; return 0; }
  done
  return 1
}

# Install the hash-locked CUDA execution provider into an isolated Python
# target. Kokoro's normal uvx environment keeps its CPU ONNX Runtime; agent-tts
# prepends this target only for CUDA attempts, avoiding the upstream wheel-file
# collision while retaining a clean CPU fallback.
install_agent_tts_gpu_runtime() {
  local root runtime requirements marker fingerprint uv
  [ "${ATTS_INSTALL_GPU_RUNTIME:-1}" != 0 ] || {
    tts_log "Skipping optional GPU runtime (ATTS_INSTALL_GPU_RUNTIME=0)"
    return 0
  }
  command -v nvidia-smi >/dev/null 2>&1 || {
    tts_log "Skipping optional GPU runtime: nvidia-smi is unavailable"
    return 0
  }
  nvidia-smi -L >/dev/null 2>&1 || {
    tts_log "Skipping optional GPU runtime: no usable NVIDIA GPU"
    return 0
  }
  uv="$(tts_resolve_uv 2>/dev/null || true)"
  [ -n "$uv" ] || {
    tts_log "Skipping optional GPU runtime: uv is unavailable; CPU remains enabled"
    return 0
  }
  requirements="$SCRIPT_DIR/requirements-gpu.txt"
  [ -f "$requirements" ] || {
    tts_log "Skipping optional GPU runtime: missing $requirements; CPU remains enabled"
    return 0
  }
  root="$(tts_install_root)"
  runtime="$root/gpu-runtime"
  marker="$runtime/.requirements.sha256"
  fingerprint="$(sha256sum "$requirements" | awk '{print $1}')"
  mkdir -p "$runtime"
  install -m 0644 "$requirements" "$root/requirements-gpu.txt"
  if [ -d "$runtime/onnxruntime" ] && [ -d "$runtime/python/onnxruntime" ] && \
     [ -d "$runtime/nvidia" ] && \
     [ "$(cat "$marker" 2>/dev/null || true)" = "$fingerprint" ]; then
    tts_log "GPU runtime already matches locked requirements"
    return 0
  fi
  tts_msg "Installing hash-locked ONNX Runtime GPU support"
  if "$uv" pip sync --require-hashes --target "$runtime" \
       --python 3.12 "$root/requirements-gpu.txt"; then
    mkdir -p "$runtime/python"
    rm -rf "$runtime/python/onnxruntime"
    ln -s ../onnxruntime "$runtime/python/onnxruntime"
    printf '%s\n' "$fingerprint" >"$marker"
    tts_log "Installed GPU runtime in $runtime"
  else
    tts_log "GPU runtime installation failed; CPU synthesis remains enabled"
  fi
  return 0
}

# Resolve the persistent event-category settings consumed by agent-tts.
tts_event_config_file() {
  printf '%s\n' "${ATTS_EVENT_CONFIG_FILE:-$(tts_target_home)/.config/agent-tts/announcements.env}"
}

# Create an explicit all-off baseline. Event components enable only the
# categories selected by the standalone or master installer.
initialize_tts_event_settings() {
  local file
  file="$(tts_event_config_file)"
  [ -f "$file" ] && return 0
  mkdir -p "$(dirname "$file")"
  printf '%s\n' \
    'ATTS_ANNOUNCE_START=0' \
    'ATTS_ANNOUNCE_FINISH=0' \
    'ATTS_ANNOUNCE_ATTENTION=0' >"$file"
  tts_log "Initialized event settings in $file"
}

# Read one event setting, defaulting off when the file/key is absent.
tts_event_setting() {
  local key="$1" file value
  file="$(tts_event_config_file)"
  value="$(sed -n "s/^${key}=//p" "$file" 2>/dev/null | tail -n 1)"
  printf '%s\n' "${value:-0}"
}

# Persist one event setting while preserving the other two categories.
tts_set_event_setting() {
  local key="$1" value="$2" file start finish attention tmp
  initialize_tts_event_settings
  file="$(tts_event_config_file)"
  start="$(tts_event_setting ATTS_ANNOUNCE_START)"
  finish="$(tts_event_setting ATTS_ANNOUNCE_FINISH)"
  attention="$(tts_event_setting ATTS_ANNOUNCE_ATTENTION)"
  case "$key" in
    ATTS_ANNOUNCE_START) start="$value" ;;
    ATTS_ANNOUNCE_FINISH) finish="$value" ;;
    ATTS_ANNOUNCE_ATTENTION) attention="$value" ;;
    *) tts_msg "Unknown event setting: $key"; return 2 ;;
  esac
  tmp="${file}.tmp.$$"
  printf '%s\n' \
    "ATTS_ANNOUNCE_START=$start" \
    "ATTS_ANNOUNCE_FINISH=$finish" \
    "ATTS_ANNOUNCE_ATTENTION=$attention" >"$tmp"
  mv "$tmp" "$file"
  tts_msg "Set $key=$value in $file"
}

# Build the Rust agent-tts command when cargo is already available.
# A missing toolchain keeps the Python launcher so a PATH-limited test install
# still speaks through the engine. run_as_target is not used: it would hide
# rustup by pointing HOME at the target home.
tts_build_agent_tts() {
  command -v cargo >/dev/null 2>&1 || return 1
  local cargo_bin cargo_home rustup_home
  cargo_bin="$(command -v cargo)"
  cargo_home="$(cd "$(dirname "$cargo_bin")/.." && pwd)"
  rustup_home="$(dirname "$cargo_home")/.rustup"
  env CARGO_HOME="${CARGO_HOME:-$cargo_home}" RUSTUP_HOME="${RUSTUP_HOME:-$rustup_home}" \
    cargo build --manifest-path "$SCRIPT_DIR/Cargo.toml" --locked --release
}

# Install the standalone Agent TTS (ATTS) speech engine and its `agent-tts`
# launcher. The engine owns all speech (synthesis, playback, speed/volume/silent
# tunables, voice selection, wording); runtimes such as agent_command_center
# delegate to the installed `agent-tts` binary.
install_agent_tts_engine() {
  # Install the speech engine and shared persistent voice reader.
  # Parameters: none.
  # Returns: zero after installing the engine.
  printf 'parameters=none\n' >&2
  local root bin
  root="$(tts_install_root)"
  bin="$(tts_bin_dir)"
  mkdir -p "$root/lib/agent_tts" "$root/lib/tts_announcements" "$root/scripts" "$bin"
  install -m 0644 "$SCRIPT_DIR/lib/agent_tts/__init__.py" "$root/lib/agent_tts/__init__.py"
  install -m 0644 "$SCRIPT_DIR/lib/agent_tts/engine.py" "$root/lib/agent_tts/engine.py"
  install -m 0644 "$SCRIPT_DIR/lib/agent_tts/cli.py" "$root/lib/agent_tts/cli.py"
  install -m 0644 "$SCRIPT_DIR/lib/agent_tts/voices.py" "$root/lib/agent_tts/voices.py"
  # agent_tts imports the repository's one centralized logging module even when
  # no notify hooks were selected.
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/__init__.py" "$root/lib/tts_announcements/__init__.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/logging_utils.py" "$root/lib/tts_announcements/logging_utils.py"
  if tts_build_agent_tts; then
    TTS_RUST_BUILT=1
    install -m 0755 "$SCRIPT_DIR/target/release/agent-tts" "$root/scripts/agent-tts"
  else
    install -m 0755 "$SCRIPT_DIR/scripts/agent-tts" "$root/scripts/agent-tts"
  fi
  # The entrypoint resolves its bundled package relative to its real path, so a
  # symlink in PATH keeps finding `$root/lib`.
  ln -sf "$root/scripts/agent-tts" "$bin/agent-tts"
  install_agent_tts_gpu_runtime
  initialize_tts_event_settings
  tts_msg "Installed agent-tts engine to $root and linked $bin/agent-tts"
  printf '0\n' >&2
}

# Enable independently selectable spoken event categories.
install_start_voice()     { install_agent_tts_engine; tts_set_event_setting ATTS_ANNOUNCE_START 1; }
install_finish_voice()    { install_agent_tts_engine; tts_set_event_setting ATTS_ANNOUNCE_FINISH 1; }
install_attention_voice() { install_agent_tts_engine; tts_set_event_setting ATTS_ANNOUNCE_ATTENTION 1; }

# Install the notify hook package and script without mutating any agent config.
install_tts_hook_files() {
  # Install reusable notification programs and the lifecycle reconciler.
  # Parameters: none.
  # Returns: zero after installing the hook runtime.
  printf 'parameters=none\n' >&2
  local root
  root="$(tts_install_root)"
  mkdir -p "$root/lib/tts_announcements" "$root/scripts"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/__init__.py" "$root/lib/tts_announcements/__init__.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/logging_utils.py" "$root/lib/tts_announcements/logging_utils.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/install_hooks.py" "$root/lib/tts_announcements/install_hooks.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/notify.py" "$root/lib/tts_announcements/notify.py"
  install -m 0644 "$SCRIPT_DIR/lib/tts_announcements/installation.py" "$root/lib/tts_announcements/installation.py"
  install -m 0755 "$SCRIPT_DIR/scripts/tts-reconcile" "$root/scripts/tts-reconcile"
  mkdir -p "$(tts_bin_dir)"
  ln -sf "$root/scripts/tts-reconcile" "$(tts_bin_dir)/tts-reconcile"
  install -m 0755 "$SCRIPT_DIR/scripts/notify_agent.py" "$root/scripts/notify_agent.py"
  if [ "${TTS_RUST_BUILT:-}" = 1 ] || { command -v cargo >/dev/null 2>&1 && tts_build_agent_tts; }; then
    TTS_RUST_BUILT=1
    install -m 0755 "$SCRIPT_DIR/target/release/notify-agent" "$root/scripts/notify-agent"
    install -m 0755 "$SCRIPT_DIR/target/release/tts-hooks" "$root/scripts/tts-hooks"
  fi
  printf '0\n' >&2
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

_tts_configure_codex_lifecycle_home() {
  local codex_home="$1" command="$2" config_file hooks_file lifecycle_command
  config_file="$codex_home/config.toml"
  hooks_file="$codex_home/hooks.json"
  lifecycle_command="env CODEX_AGENT_KIND=codex CODEX_AGENT_LABEL=codex $command"
  mkdir -p "$codex_home"
  tts_run_hooks \
    remove-codex "$config_file"
  tts_run_hooks \
    codex-hooks "$hooks_file" "$lifecycle_command" UserPromptSubmit Stop
  tts_msg "Configured Codex UserPromptSubmit/Stop hooks in $hooks_file"
}

# Migrate Codex from the response-level notify callback to lifecycle hooks.
configure_codex_notify_block() {
  local home command codex_home config_file hooks_file lifecycle_command
  home="$(tts_target_home)"
  ensure_tts_core
  command="$(tts_hook_command)"
  if [ -n "${CODEX_CONFIG_FILE:-}${CODEX_HOOKS_FILE:-}" ]; then
    config_file="${CODEX_CONFIG_FILE:-$home/.codex/config.toml}"
    hooks_file="${CODEX_HOOKS_FILE:-$home/.codex/hooks.json}"
    lifecycle_command="env CODEX_AGENT_KIND=codex CODEX_AGENT_LABEL=codex $command"
    mkdir -p "$(dirname "$config_file")" "$(dirname "$hooks_file")"
    tts_run_hooks \
      remove-codex "$config_file"
    tts_run_hooks \
      codex-hooks "$hooks_file" "$lifecycle_command" UserPromptSubmit Stop
    tts_msg "Configured Codex UserPromptSubmit/Stop hooks in $hooks_file"
    return
  fi
  _tts_configure_codex_lifecycle_home "$home/.codex" "$command"
  for codex_home in "$home"/.codex-account-*; do
    [ -d "$codex_home" ] || continue
    _tts_configure_codex_lifecycle_home "$codex_home" "$command"
  done
}

_tts_configure_codex_attention_home() {
  local codex_home="$1" command="$2" hooks_file attention_command
  hooks_file="$codex_home/hooks.json"
  attention_command="env CODEX_AGENT_KIND=codex CODEX_AGENT_LABEL=codex $command"
  mkdir -p "$codex_home"
  tts_run_hooks \
    codex-hooks "$hooks_file" "$attention_command" PermissionRequest
  tts_msg "Configured Codex attention hook in $hooks_file"
}

# Merge the Codex PermissionRequest attention hook in hooks.json.
configure_codex_attention_hook() {
  local home hooks_file command attention_command codex_home
  home="$(tts_target_home)"
  ensure_tts_core
  command="$(tts_hook_command)"
  if [ -n "${CODEX_HOOKS_FILE:-}" ]; then
    hooks_file="$CODEX_HOOKS_FILE"
    attention_command="env CODEX_AGENT_KIND=codex CODEX_AGENT_LABEL=codex $command"
    mkdir -p "$(dirname "$hooks_file")"
    tts_run_hooks \
      codex-hooks "$hooks_file" "$attention_command" PermissionRequest
    tts_msg "Configured Codex attention hook in $hooks_file"
    return
  fi
  _tts_configure_codex_attention_home "$home/.codex" "$command"
  for codex_home in "$home"/.codex-account-*; do
    [ -d "$codex_home" ] || continue
    _tts_configure_codex_attention_home "$codex_home" "$command"
  done
}

# Register one Claude Code lifecycle event's notify hook. Each event is its own
# selectable component; the writer prunes/re-adds only the named event so the
# components compose without clobbering each other.
configure_claude_event_hook() {
  local event="$1" home settings_file command
  home="$(tts_target_home)"
  settings_file="${CLAUDE_SETTINGS_FILE:-$home/.claude/settings.json}"
  ensure_tts_core
  command="$(tts_hook_command)"
  mkdir -p "$(dirname "$settings_file")"
  tts_run_hooks claude "$settings_file" "$command" "$event"
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
  ensure_tts_core
  command="$(tts_hook_command)"
  mkdir -p "$hooks_dir"
  local py_args=(cline "$hook_file" "$command")
  [ -n "$filter_tool" ] && py_args+=(--filter-tool "$filter_tool")
  tts_run_hooks \
    "${py_args[@]}"
  tts_msg "Configured Cline $event hook in $hook_file"
}

# Write the generated Grok notification-hook block in ~/.grok/config.toml.
# Grok's [[ui.notifications.hooks]] contract passes GROK_EVENT / GROK_MESSAGE /
# GROK_SESSION_ID in the environment, so the notifier runs with --grok and no
# stdin payload.
configure_grok_notify_hook() {
  local home config_file command
  home="$(tts_target_home)"
  config_file="${GROK_CONFIG_FILE:-$home/.grok/config.toml}"
  ensure_tts_core
  command="env CODEX_AGENT_KIND=grok CODEX_AGENT_LABEL=grok $(tts_hook_command)"
  mkdir -p "$(dirname "$config_file")"
  tts_run_hooks grok "$config_file" "$command"
  tts_msg "Configured Grok notification hooks in $config_file"
}

configure_cline_task_start_hook()   { configure_cline_event_hook TaskStart; }
configure_cline_task_resume_hook()  { configure_cline_event_hook TaskResume; }
configure_cline_task_complete_hook(){ configure_cline_event_hook TaskComplete; }
configure_cline_task_cancel_hook()  { configure_cline_event_hook TaskCancel; }
configure_cline_task_error_hook()   { configure_cline_event_hook TaskError; }
configure_cline_user_prompt_hook()  { configure_cline_event_hook UserPromptSubmit; }
configure_cline_pre_tool_use_hook() { configure_cline_event_hook PreToolUse ask_question; }

###############################################################################
# Install a systemd --user oneshot that warms Kokoro at login so the first agent
# announcement does not pay the cold ~6s uvx/model-load startup. Enabling is
# best-effort: a console/clean-home install without a live user manager still
# lands the unit and succeeds, and the unit runs at the next graphical login.
install_boot_prewarm() {
  ensure_tts_core
  local unit_dir unit bin
  unit_dir="$(tts_systemd_user_dir)"
  bin="$(tts_bin_dir)"
  mkdir -p "$unit_dir"
  unit="$unit_dir/agent-tts-prewarm.service"
  cat >"$unit" <<EOF
[Unit]
Description=Warm Agent TTS (Kokoro) synthesis so the first announcement is fast
After=graphical-session.target

[Service]
Type=oneshot
ExecStart="$bin/agent-tts" prewarm
# Warming is best-effort; never let a slow/failed synthesis stall the session.
TimeoutStartSec=180
Nice=10

[Install]
WantedBy=default.target
EOF
  chmod 0644 "$unit"
  if [ -z "${TTS_SKIP_SYSTEMD:-}" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
    systemctl --user enable --now agent-tts-prewarm.service >/dev/null 2>&1 \
      || systemctl --user enable agent-tts-prewarm.service >/dev/null 2>&1 || true
  fi
  tts_msg "Installed boot prewarm service to $unit"
}

###############################################################################
# Detection and uninstall (component lifecycle)
###############################################################################
# detect_* report live state for --detect; uninstall_* reverse each component.
# The config-block components delegate removal to the symmetric remove-* CLI in
# tts_announcements.install_hooks so the exact generated content (and only that)
# is stripped, preserving user-authored config.

detect_engine()       { [ -e "$(tts_bin_dir)/agent-tts" ] || [ -f "$(tts_install_root)/scripts/agent-tts" ]; }
detect_boot_prewarm() { [ -f "$(tts_systemd_user_dir)/agent-tts-prewarm.service" ]; }
detect_hook_files()   { [ -f "$(tts_install_root)/scripts/notify_agent.py" ]; }
detect_start_voice()     { [ "$(tts_event_setting ATTS_ANNOUNCE_START)" = 1 ]; }
detect_finish_voice()    { [ "$(tts_event_setting ATTS_ANNOUNCE_FINISH)" = 1 ]; }
detect_attention_voice() { [ "$(tts_event_setting ATTS_ANNOUNCE_ATTENTION)" = 1 ]; }
# Codex start/finish is installed only when both authoritative lifecycle events
# use the current notify script and no legacy response-level notify remains.
_tts_detect_codex_lifecycle_files() {
  local config_file="$1" hooks_file="$2"
  if [ -f "$config_file" ] && grep -q 'notify_agent\.py' "$config_file" 2>/dev/null; then
    return 1
  fi
  _tts_json_has_event "$hooks_file" UserPromptSubmit \
    && _tts_json_has_event "$hooks_file" Stop
}

detect_codex_notify() {
  local home config_file hooks_file codex_home
  home="$(tts_target_home)"
  if [ -n "${CODEX_CONFIG_FILE:-}${CODEX_HOOKS_FILE:-}" ]; then
    config_file="${CODEX_CONFIG_FILE:-$home/.codex/config.toml}"
    hooks_file="${CODEX_HOOKS_FILE:-$home/.codex/hooks.json}"
    _tts_detect_codex_lifecycle_files "$config_file" "$hooks_file"
    return
  fi
  _tts_detect_codex_lifecycle_files "$home/.codex/config.toml" "$home/.codex/hooks.json" \
    || return 1
  for codex_home in "$home"/.codex-account-*; do
    [ -d "$codex_home" ] || continue
    _tts_detect_codex_lifecycle_files "$codex_home/config.toml" "$codex_home/hooks.json" \
      || return 1
  done
}
# Grok rewrites its config.toml and may strip our comment markers, so detection
# parses the live TOML and compares shell arguments with the current managed
# path instead of relying on either serialized escaping or a comment marker.
detect_grok_notify() {
  local f="${GROK_CONFIG_FILE:-$(tts_target_home)/.grok/config.toml}"
  local managed; managed="$(tts_notify_program)"
  [ -f "$f" ] || return 1
  python3 - "$f" "$managed" <<'PY'
import shlex, sys, tomllib
try:
    with open(sys.argv[1], "rb") as handle:
        data = tomllib.load(handle)
except Exception:
    sys.exit(1)
entries = (((data.get("ui") or {}).get("notifications") or {}).get("hooks") or [])
for entry in entries if isinstance(entries, list) else []:
    if not isinstance(entry, dict):
        continue
    try:
        arguments = shlex.split(str(entry.get("command", "")))
    except ValueError:
        continue
    if sys.argv[2] in arguments:
        sys.exit(0)
sys.exit(1)
PY
}

# Return true when one JSON hook event contains the exact current managed
# notify-script path as a shell argument. Parsing avoids false negatives from
# JSON escaping and false positives from a retired install path.
_tts_json_has_event() {
  local f="$1" event="$2" managed
  managed="$(tts_notify_program)"
  [ -f "$f" ] || return 1
  python3 - "$f" "$event" "$managed" <<'PY'
import json, shlex, sys
try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        data = json.load(handle)
except Exception:
    sys.exit(1)
entries = ((data.get("hooks") or {}).get(sys.argv[2]) or [])
for entry in entries if isinstance(entries, list) else []:
    for hook in (entry.get("hooks") or []) if isinstance(entry, dict) else []:
        if not isinstance(hook, dict):
            continue
        try:
            arguments = shlex.split(str(hook.get("command", "")))
        except ValueError:
            continue
        if sys.argv[3] in arguments:
            sys.exit(0)
sys.exit(1)
PY
}

detect_codex_attention() {
  local home hooks_file codex_home
  home="$(tts_target_home)"
  if [ -n "${CODEX_HOOKS_FILE:-}" ]; then
    _tts_json_has_event "$CODEX_HOOKS_FILE" PermissionRequest
    return
  fi
  hooks_file="$home/.codex/hooks.json"
  _tts_json_has_event "$hooks_file" PermissionRequest || return 1
  for codex_home in "$home"/.codex-account-*; do
    [ -d "$codex_home" ] || continue
    _tts_json_has_event "$codex_home/hooks.json" PermissionRequest || return 1
  done
}
# A Claude event hook is present when settings.json registers *our managed*
# command under that event. Match the current install-root notify_agent.py path
# rather than a bare notify_agent.py reference: a settings file carrying an older
# hook (e.g. a hand-written or previously-relocated "/old/notify_agent.py")
# otherwise reads as installed, so the runtime skips the event and never prunes
# and re-registers it. The pruning is event-specific, so detection greps the
# event name.
_tts_claude_has_event() {
  local event="$1" f="${CLAUDE_SETTINGS_FILE:-$(tts_target_home)/.claude/settings.json}"
  _tts_json_has_event "$f" "$event"
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
  rm -rf "$(tts_install_root)/lib/agent_tts" \
         "$(tts_install_root)/scripts/agent-tts" \
         "$(tts_install_root)/gpu-runtime"
  rm -f "$(tts_install_root)/requirements-gpu.txt"
}
uninstall_boot_prewarm() {
  tts_msg "Removing boot prewarm service"
  local unit
  unit="$(tts_systemd_user_dir)/agent-tts-prewarm.service"
  if [ -z "${TTS_SKIP_SYSTEMD:-}" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user disable --now agent-tts-prewarm.service >/dev/null 2>&1 || true
  fi
  rm -f "$unit"
  if [ -z "${TTS_SKIP_SYSTEMD:-}" ] && command -v systemctl >/dev/null 2>&1; then
    systemctl --user daemon-reload >/dev/null 2>&1 || true
  fi
}
uninstall_start_voice()     { tts_set_event_setting ATTS_ANNOUNCE_START 0; }
uninstall_finish_voice()    { tts_set_event_setting ATTS_ANNOUNCE_FINISH 0; }
uninstall_attention_voice() { tts_set_event_setting ATTS_ANNOUNCE_ATTENTION 0; }
uninstall_hook_files() {
  tts_msg "Removing TTS notify hook files"
  # Keep __init__.py + logging_utils.py: agent-tts imports the repository's
  # centralized logger even when no runtime notify hooks are installed.
  rm -f "$(tts_install_root)/lib/tts_announcements/install_hooks.py" \
        "$(tts_install_root)/lib/tts_announcements/notify.py" \
        "$(tts_install_root)/scripts/notify_agent.py"
}
uninstall_codex_notify() {
  local home config_file hooks_file codex_home
  home="$(tts_target_home)"
  if [ -n "${CODEX_CONFIG_FILE:-}${CODEX_HOOKS_FILE:-}" ]; then
    config_file="${CODEX_CONFIG_FILE:-$home/.codex/config.toml}"
    hooks_file="${CODEX_HOOKS_FILE:-$home/.codex/hooks.json}"
    tts_msg "Removing Codex lifecycle hooks from $hooks_file"
    tts_run_hooks remove-codex "$config_file"
    tts_run_hooks \
      remove-codex-hooks "$hooks_file" UserPromptSubmit Stop
    return
  fi
  for codex_home in "$home/.codex" "$home"/.codex-account-*; do
    [ -d "$codex_home" ] || continue
    tts_msg "Removing Codex lifecycle hooks from $codex_home/hooks.json"
    tts_run_hooks \
      remove-codex "$codex_home/config.toml"
    tts_run_hooks \
      remove-codex-hooks "$codex_home/hooks.json" UserPromptSubmit Stop
  done
}
uninstall_codex_attention() {
  local home hooks_file codex_home
  home="$(tts_target_home)"
  if [ -n "${CODEX_HOOKS_FILE:-}" ]; then
    hooks_file="$CODEX_HOOKS_FILE"
    tts_msg "Removing Codex attention hook from $hooks_file"
    tts_run_hooks \
      remove-codex-hooks "$hooks_file" PermissionRequest
    return
  fi
  for codex_home in "$home/.codex" "$home"/.codex-account-*; do
    [ -d "$codex_home" ] || continue
    tts_msg "Removing Codex attention hook from $codex_home/hooks.json"
    tts_run_hooks \
      remove-codex-hooks "$codex_home/hooks.json" PermissionRequest
  done
}
uninstall_grok_notify() {
  local f="${GROK_CONFIG_FILE:-$(tts_target_home)/.grok/config.toml}"
  tts_msg "Removing Grok notification hooks from $f"
  tts_run_hooks remove-grok "$f"
}
_tts_remove_claude_event() {
  local event="$1" f="${CLAUDE_SETTINGS_FILE:-$(tts_target_home)/.claude/settings.json}"
  tts_msg "Removing Claude $event notify hook from $f"
  tts_run_hooks \
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
  tts_run_hooks remove-cline "$file"
}
uninstall_cline_task_start()    { _tts_remove_cline_event TaskStart; }
uninstall_cline_task_resume()   { _tts_remove_cline_event TaskResume; }
uninstall_cline_task_complete() { _tts_remove_cline_event TaskComplete; }
uninstall_cline_task_cancel()   { _tts_remove_cline_event TaskCancel; }
uninstall_cline_task_error()    { _tts_remove_cline_event TaskError; }
uninstall_cline_user_prompt()   { _tts_remove_cline_event UserPromptSubmit; }
uninstall_cline_pre_tool_use()  { _tts_remove_cline_event PreToolUse; }
