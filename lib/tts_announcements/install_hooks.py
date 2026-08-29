"""Install-time config writers for Codex and Claude Code TTS hooks.

Components:
  - configure_codex_notify: Remove or migrate the legacy Codex notify block.
  - configure_codex_hooks: Merge named Codex lifecycle hooks.
  - configure_claude_hooks: Merge generated Claude hook commands.
  - build_parser: Construct the install-hook CLI argument parser.
  - main: CLI entrypoint used by lib/install_hooks.sh.

Each mutation is idempotent and preserves unrelated user configuration.
Diagnostic logging is delegated to :mod:`tts_announcements.logging_utils` under
the ``"install"`` component tag.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path
from typing import Any

from . import logging_utils as log

#: Component tag applied to every log line emitted by this module.
LOG_COMPONENT = "install"
LOGGER = log.get_logger("tts_install", log.LOG_FILE_NAME)


#: Matches the current generated Codex notify block (for idempotent replacement).
CODEX_TTS_BLOCK_RE = re.compile(
    r"# BEGIN TTS ANNOUNCEMENTS NOTIFY(?: \(generated\))?.*?# END TTS ANNOUNCEMENTS NOTIFY(?: \(generated\))?\n*",
    flags=re.S,
)
#: Matches the retired Codex notify block name so old installs are cleaned up.
CODEX_LEGACY_BLOCK_RE = re.compile(
    r"# BEGIN CODEX NOTIFY(?: \(generated\))?.*?# END CODEX NOTIFY(?: \(generated\))?\n*",
    flags=re.S,
)
#: Matches a bare legacy ``notify = [...notify_agent.py]`` line left by old installs.
LEGACY_NOTIFY_LINE_RE = re.compile(r'(?m)^notify = \["python3", ".*notify_agent\.py"\]\n+')
#: Marker proving an event-named Cline hook is owned by this installer.
CLINE_HOOK_MARKER = "TTS ANNOUNCEMENTS CLINE HOOK"
#: Matches the generated Grok notification-hook block (for idempotent replacement).
GROK_TTS_BLOCK_RE = re.compile(
    r"\n*# BEGIN TTS ANNOUNCEMENTS GROK HOOKS \(generated\).*?# END TTS ANNOUNCEMENTS GROK HOOKS \(generated\)\n*",
    flags=re.S,
)
#: Matches one bare ``[[ui.notifications.hooks]]`` table (header up to the next
#: table header or comment marker). Grok rewrites its config.toml when settings
#: change and may strip our comment markers, so idempotent replacement must also
#: recognize an unmarked table that carries the generated notify command.
GROK_HOOK_TABLE_RE = re.compile(
    r"\[\[ui\.notifications\.hooks\]\]\n(?:(?!\[|# BEGIN|# END)[^\n]*\n?)*",
)
#: Grok notification events the generated hook subscribes to. The single hook
#: command branches on ``$GROK_EVENT`` (see tts_announcements.notify.handle_grok).
GROK_HOOK_EVENTS = (
    "session_ready",
    "turn_complete",
    "task_complete",
    "agent_error",
    "approval_required",
)


@log.log_call(LOGGER)
def configure_codex_notify(config_file: Path, command: str) -> None:
    """Write a generated notify block while preserving unrelated TOML.

    Removes any current or legacy generated block, then prepends a fresh block,
    leaving all other TOML untouched. Safe to run repeatedly (idempotent).

    Args:
        config_file: Path to the Codex ``config.toml`` to update; created along
            with parent directories if missing.
        command: Shell-formatted notify command string; parsed with
            :func:`shlex.split` to form the ``notify = [...]`` array.

    Returns:
        None.
    """
    block = (
        "# BEGIN TTS ANNOUNCEMENTS NOTIFY (generated)\n"
        f"notify = {json.dumps(shlex.split(command))}\n"
        "# END TTS ANNOUNCEMENTS NOTIFY (generated)\n"
    )
    try:
        text = config_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    text = CODEX_TTS_BLOCK_RE.sub("", text)
    text = CODEX_LEGACY_BLOCK_RE.sub("", text)
    text = LEGACY_NOTIFY_LINE_RE.sub("", text)
    updated = block + ("\n" + text.lstrip() if text.strip() else "")
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(updated.rstrip() + "\n", encoding="utf-8")
    log.info(f"wrote Codex notify block to {config_file}", component=LOG_COMPONENT)


@log.log_call(LOGGER)
def configure_codex_hooks(
    hooks_file: Path, command: str, events: tuple[str, ...] | list[str] | None = None
) -> None:
    """Merge generated handlers for named Codex lifecycle events.

    Existing hook events and user-authored handlers are preserved. A previously
    generated attention handler is replaced so repeated installs remain
    idempotent.

    Args:
        hooks_file: User-level Codex ``hooks.json`` path.
        command: Hook command that reads the lifecycle payload from stdin.
        events: Event names to update; defaults to ``PermissionRequest`` for
            backward compatibility with the original attention-only writer.
    """
    settings = _read_settings(hooks_file)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks

    selected_events = tuple(events or ("PermissionRequest",))
    for event in selected_events:
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            entries = []
        kept = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                kept.append(entry)
                continue
            handlers = [
                handler
                for handler in entry["hooks"]
                if not (
                    isinstance(handler, dict)
                    and _is_generated_notify_command(handler.get("command"))
                )
            ]
            if handlers:
                updated = dict(entry)
                updated["hooks"] = handlers
                kept.append(updated)

        kept.append(
            {
                "matcher": "",
                "hooks": [{"type": "command", "command": command, "timeout": 10}],
            }
        )
        hooks[event] = kept
    hooks_file.parent.mkdir(parents=True, exist_ok=True)
    hooks_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    log.info(
        f"merged Codex hooks events={','.join(selected_events)} into {hooks_file}",
        component=LOG_COMPONENT,
    )


@log.log_call(LOGGER)
def configure_grok_notify(config_file: Path, command: str) -> None:
    """Append the generated Grok notification-hook block, preserving user TOML.

    Grok's hook contract is ``[[ui.notifications.hooks]]`` tables whose command
    receives ``GROK_EVENT``/``GROK_MESSAGE``/``GROK_SESSION_ID`` in the
    environment. The block is *appended* (unlike the prepended Codex ``notify``
    key) because a TOML array-of-tables header would otherwise capture any
    top-level keys that follow it. Safe to run repeatedly (idempotent).

    Args:
        config_file: Path to the Grok ``config.toml``; created with parents if
            missing.
        command: The notify command string, invoked with ``--grok`` so the
            notifier reads the event from the environment.
    """
    events = ", ".join(json.dumps(event) for event in GROK_HOOK_EVENTS)
    block = (
        "# BEGIN TTS ANNOUNCEMENTS GROK HOOKS (generated)\n"
        "[[ui.notifications.hooks]]\n"
        f"command = {json.dumps(command + ' --grok')}\n"
        f"events = [{events}]\n"
        "only_unfocused = false\n"
        "timeout_secs = 30\n"
        "# END TTS ANNOUNCEMENTS GROK HOOKS (generated)\n"
    )
    try:
        text = config_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = ""
    text = _strip_generated_grok_tables(text)
    text = text.rstrip()
    updated = (text + "\n\n" + block) if text else block
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(updated, encoding="utf-8")
    log.info(f"wrote Grok notification hooks to {config_file}", component=LOG_COMPONENT)


@log.log_call(LOGGER)
def remove_grok_notify(config_file: Path) -> None:
    """Strip the generated Grok hook block, leaving unrelated TOML intact.

    The inverse of :func:`configure_grok_notify`; safe when the file or block
    is absent.

    Args:
        config_file: Path to the Grok ``config.toml`` to clean.
    """
    try:
        text = config_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    text = _strip_generated_grok_tables(text)
    config_file.write_text(text.strip() + "\n" if text.strip() else "", encoding="utf-8")
    log.info(f"removed Grok notification hooks from {config_file}", component=LOG_COMPONENT)


def _strip_generated_grok_tables(text: str) -> str:
    """Remove every generated Grok hook table, marked or not.

    Strips the marker-delimited block, then any bare
    ``[[ui.notifications.hooks]]`` table whose command references
    ``notify_agent.py`` — Grok's own config rewrites can drop the comment
    markers while keeping the table. User-authored hook tables are preserved.
    """
    text = GROK_TTS_BLOCK_RE.sub("\n", text)
    return GROK_HOOK_TABLE_RE.sub(
        lambda match: "" if "notify_agent.py" in match.group(0) else match.group(0),
        text,
    )


def _read_settings(settings_file: Path) -> dict[str, Any]:
    """Read and JSON-decode a Claude settings file, tolerating absence/corruption.

    Args:
        settings_file: Path to the Claude ``settings.json`` file.

    Returns:
        dict[str, Any]: The decoded settings object, or an empty dict when the
        file is missing, unreadable, or not a JSON object.
    """
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
        if isinstance(settings, dict):
            return settings
    except FileNotFoundError:
        log.debug(f"no existing settings at {settings_file}", component=LOG_COMPONENT)
    except ValueError:
        log.warn(f"unparseable settings at {settings_file}; recreating", component=LOG_COMPONENT)
    except OSError as exc:
        log.error(f"could not read settings {settings_file}: {exc}", component=LOG_COMPONENT)
    return {}


def _is_generated_notify_command(command: Any) -> bool:
    """Return whether a hook command belongs to this installer.

    Args:
        command: Candidate hook command value from a settings file.

    Returns:
        bool: True for generated ``notify_agent.py`` command strings.
    """
    return isinstance(command, str) and "notify_agent.py" in command


def _prune_generated(hooks: dict[str, Any], event: str, generated_commands: set[str]) -> None:
    """Remove previously generated hook commands for one event, in place.

    Preserves user-authored hooks and any structurally unexpected entries; only
    command entries whose ``command`` is in ``generated_commands`` are dropped.

    Args:
        hooks: The mutable ``hooks`` mapping from the settings object.
        event: Event name (e.g. ``"Stop"``) whose entry list is pruned.
        generated_commands: Command strings considered generated and removable.

    Returns:
        None.
    """
    entries = hooks.get(event, [])
    if not isinstance(entries, list):
        hooks[event] = []
        return

    kept = []
    for entry in entries:
        if not isinstance(entry, dict):
            kept.append(entry)
            continue
        entry_hooks = entry.get("hooks", [])
        if not isinstance(entry_hooks, list):
            kept.append(entry)
            continue
        filtered = [
            hook
            for hook in entry_hooks
            if not (isinstance(hook, dict) and hook.get("command") in generated_commands)
        ]
        if filtered:
            updated_entry = dict(entry)
            updated_entry["hooks"] = filtered
            kept.append(updated_entry)
    hooks[event] = kept


#: Claude lifecycle events the notify hook registers on when none are named.
#: Each event is independently selectable as its own installer component, so a
#: caller may register exactly one event instead of the full set.
DEFAULT_CLAUDE_EVENTS = (
    "SessionStart",
    "Stop",
    "SubagentStop",
    "UserPromptSubmit",
    "Notification",
)
#: Events whose previously generated wiring is always pruned (and dropped when
#: empty) so reruns clean up retired hooks regardless of which event is selected.
RETIRED_CLAUDE_EVENTS = ("PreToolUse",)


@log.log_call(LOGGER)
def configure_claude_hooks(
    settings_file: Path, command: str, events: tuple[str, ...] | list[str] | None = None
) -> None:
    """Merge generated Claude Code hook commands while preserving user hooks.

    Registers the notify command on the requested Claude lifecycle events,
    pruning any previously generated entries (current and legacy) first so reruns
    stay idempotent and user-authored hooks are preserved.

    Args:
        settings_file: Path to the Claude ``settings.json`` to update; created
            along with parent directories if missing.
        command: The notify hook command string to register on each event.
        events: Specific lifecycle events to register; defaults to
            :data:`DEFAULT_CLAUDE_EVENTS` when ``None``/empty. Passing a single
            event lets each event be installed as its own component.

    Returns:
        None.
    """
    legacy_acc_command = f"python3 {settings_file.parent / 'notify_agent.py'}"
    generated_commands = {command, legacy_acc_command}
    settings = _read_settings(settings_file)

    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks

    def ensure_command(event: str, matcher: str = "") -> None:
        _prune_generated(hooks, event, generated_commands)
        hooks.setdefault(event, []).append(
            {
                "matcher": matcher,
                "hooks": [{"type": "command", "command": command}],
            }
        )

    for event in events or DEFAULT_CLAUDE_EVENTS:
        ensure_command(event)

    # Retired events: prune any previously generated command and drop the event
    # key when nothing else uses it, so reruns clean up the old wiring. The
    # destructive-command PreToolUse warning was removed by request.
    for retired in RETIRED_CLAUDE_EVENTS:
        _prune_generated(hooks, retired, generated_commands)
        if not hooks.get(retired):
            hooks.pop(retired, None)

    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    log.info(f"merged Claude hooks into {settings_file}", component=LOG_COMPONENT)


@log.log_call(LOGGER)
def configure_cline_hook(hook_file: Path, command: str, filter_tool: str = "") -> None:
    """Write one executable Cline lifecycle hook without clobbering user code.

    When ``filter_tool`` is set, the generated hook reads stdin once and only
    invokes the notify command when the payload contains that tool name. This
    keeps ``PreToolUse`` (which fires for every tool call) cheap and silent for
    routine tools, spawning the Python notifier only for attention tools such as
    ``ask_question``.

    Args:
        hook_file: Canonical extensionless global hook path, such as
            ``~/.cline/hooks/TaskStart``.
        command: Notify command that consumes Cline's JSON payload from stdin.
        filter_tool: Optional tool name that gates the notify command. When
            non-empty the hook body guards on a substring match so unrelated
            tool calls skip the notifier entirely.

    Raises:
        RuntimeError: If an existing file is not managed by this installer.
    """
    if hook_file.exists():
        existing = hook_file.read_text(encoding="utf-8")
        if CLINE_HOOK_MARKER not in existing:
            raise RuntimeError(f"refusing to replace unmanaged Cline hook: {hook_file}")
    if filter_tool:
        body = f"""#!/usr/bin/env bash
# {CLINE_HOOK_MARKER} (generated)
# Receives one Cline hook JSON object on stdin and must emit JSON on stdout.
# PreToolUse fires for every tool call; only invoke the notifier for the
# attention tool so routine tool execution stays cheap and silent.
export CODEX_AGENT_KIND=cline
export CODEX_AGENT_LABEL=cline
export CODEX_HOME="${{CODEX_HOME:-$HOME/.cline}}"
input=$(cat)
case "$input" in
  *{filter_tool}*) printf '%s' "$input" | {command} >/dev/null || true ;;
esac
printf '%s\\n' '{{"cancel":false,"contextModification":"","errorMessage":""}}'
"""
    else:
        body = f"""#!/usr/bin/env bash
# {CLINE_HOOK_MARKER} (generated)
# Receives one Cline hook JSON object on stdin and must emit JSON on stdout.
export CODEX_AGENT_KIND=cline
export CODEX_AGENT_LABEL=cline
export CODEX_HOME="${{CODEX_HOME:-$HOME/.cline}}"
{command} >/dev/null || true
printf '%s\\n' '{{"cancel":false,"contextModification":"","errorMessage":""}}'
"""
    hook_file.parent.mkdir(parents=True, exist_ok=True)
    hook_file.write_text(body, encoding="utf-8")
    hook_file.chmod(0o755)
    log.info(f"wrote Cline hook to {hook_file}", component=LOG_COMPONENT)


@log.log_call(LOGGER)
def remove_cline_hook(hook_file: Path) -> None:
    """Remove one installer-managed Cline hook and preserve any other file.

    Args:
        hook_file: Event-named Cline hook path to inspect and possibly remove.
    """
    try:
        existing = hook_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    if CLINE_HOOK_MARKER not in existing:
        log.warn(f"preserving unmanaged Cline hook {hook_file}", component=LOG_COMPONENT)
        return
    hook_file.unlink()
    log.info(f"removed Cline hook from {hook_file}", component=LOG_COMPONENT)


@log.log_call(LOGGER)
def remove_codex_notify(config_file: Path) -> None:
    """Strip the generated Codex notify block, leaving unrelated TOML intact.

    The inverse of :func:`configure_codex_notify`; safe when the file or block is
    absent.

    Args:
        config_file: Path to the Codex ``config.toml`` to clean.
    """
    try:
        text = config_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        return
    text = CODEX_TTS_BLOCK_RE.sub("", text)
    text = CODEX_LEGACY_BLOCK_RE.sub("", text)
    text = LEGACY_NOTIFY_LINE_RE.sub("", text)
    config_file.write_text(text.lstrip("\n"), encoding="utf-8")
    log.info(f"removed Codex notify block from {config_file}", component=LOG_COMPONENT)


@log.log_call(LOGGER)
def remove_codex_hooks(
    hooks_file: Path, events: tuple[str, ...] | list[str] | None = None
) -> None:
    """Remove generated handlers for named Codex lifecycle events.

    Preserves user-authored handlers and other events; drops the event key when
    nothing else uses it. The inverse of :func:`configure_codex_hooks`.

    Args:
        hooks_file: User-level Codex ``hooks.json`` path.
        events: Event names to clean; defaults to ``PermissionRequest`` for
            backward compatibility with the original attention-only remover.
    """
    try:
        settings = _read_settings(hooks_file)
    except FileNotFoundError:
        return
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    selected_events = tuple(events or ("PermissionRequest",))
    for event in selected_events:
        entries = hooks.get(event, [])
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
                kept.append(entry)
                continue
            handlers = [
                handler
                for handler in entry["hooks"]
                if not (
                    isinstance(handler, dict)
                    and _is_generated_notify_command(handler.get("command"))
                )
            ]
            if handlers:
                updated = dict(entry)
                updated["hooks"] = handlers
                kept.append(updated)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    hooks_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    log.info(
        f"removed Codex hooks events={','.join(selected_events)} from {hooks_file}",
        component=LOG_COMPONENT,
    )


@log.log_call(LOGGER)
def remove_claude_hooks(
    settings_file: Path, command: str, events: tuple[str, ...] | list[str] | None = None
) -> None:
    """Remove generated Claude hook commands for the named events.

    The inverse of :func:`configure_claude_hooks`: prunes only generated command
    entries (preserving user-authored hooks), drops emptied event keys, and drops
    the ``hooks`` map when empty.

    Args:
        settings_file: Path to the Claude ``settings.json`` to clean.
        command: The generated notify command string to prune.
        events: Lifecycle events to clean; defaults to the full set when empty.
    """
    try:
        settings = _read_settings(settings_file)
    except FileNotFoundError:
        return
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return
    legacy_acc_command = f"python3 {settings_file.parent / 'notify_agent.py'}"
    generated_commands = {command, legacy_acc_command}
    for event in events or DEFAULT_CLAUDE_EVENTS:
        _prune_generated(hooks, event, generated_commands)
        if not hooks.get(event):
            hooks.pop(event, None)
    if not hooks:
        settings.pop("hooks", None)
    settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    log.info(f"removed Claude hooks from {settings_file}", component=LOG_COMPONENT)


def build_parser() -> argparse.ArgumentParser:
    """Create the install hook config CLI parser.

    Returns:
        argparse.ArgumentParser: Parser exposing two subcommands — ``codex``
        (``config_file``, ``command``) and ``claude`` (``settings_file``,
        ``command``).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command_name", required=True)

    codex = subcommands.add_parser("codex")
    codex.add_argument("config_file", type=Path)
    codex.add_argument("command")

    codex_hooks = subcommands.add_parser("codex-hooks")
    codex_hooks.add_argument("hooks_file", type=Path)
    codex_hooks.add_argument("command")
    codex_hooks.add_argument("events", nargs="*")

    claude = subcommands.add_parser("claude")
    claude.add_argument("settings_file", type=Path)
    claude.add_argument("command")
    claude.add_argument(
        "events",
        nargs="*",
        help="Lifecycle events to register; defaults to the full set when omitted.",
    )

    cline = subcommands.add_parser("cline")
    cline.add_argument("hook_file", type=Path)
    cline.add_argument("command")
    cline.add_argument(
        "--filter-tool",
        default="",
        help="Tool name that gates the notify command (PreToolUse attention hook).",
    )

    grok = subcommands.add_parser("grok")
    grok.add_argument("config_file", type=Path)
    grok.add_argument("command")

    # Symmetric removal subcommands (used by the component uninstall path).
    rm_grok = subcommands.add_parser("remove-grok")
    rm_grok.add_argument("config_file", type=Path)

    rm_codex = subcommands.add_parser("remove-codex")
    rm_codex.add_argument("config_file", type=Path)

    rm_codex_hooks = subcommands.add_parser("remove-codex-hooks")
    rm_codex_hooks.add_argument("hooks_file", type=Path)
    rm_codex_hooks.add_argument("events", nargs="*")

    rm_claude = subcommands.add_parser("remove-claude")
    rm_claude.add_argument("settings_file", type=Path)
    rm_claude.add_argument("command")
    rm_claude.add_argument("events", nargs="*")

    rm_cline = subcommands.add_parser("remove-cline")
    rm_cline.add_argument("hook_file", type=Path)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one install hook config mutation.

    Args:
        argv: Argument vector to parse; defaults to ``sys.argv[1:]`` when
            ``None``.

    Returns:
        int: ``0`` on success.
    """
    args = build_parser().parse_args(argv)
    if args.command_name == "codex":
        configure_codex_notify(args.config_file, args.command)
    elif args.command_name == "codex-hooks":
        configure_codex_hooks(args.hooks_file, args.command, args.events)
    elif args.command_name == "claude":
        configure_claude_hooks(args.settings_file, args.command, args.events)
    elif args.command_name == "cline":
        configure_cline_hook(args.hook_file, args.command, args.filter_tool)
    elif args.command_name == "grok":
        configure_grok_notify(args.config_file, args.command)
    elif args.command_name == "remove-grok":
        remove_grok_notify(args.config_file)
    elif args.command_name == "remove-codex":
        remove_codex_notify(args.config_file)
    elif args.command_name == "remove-codex-hooks":
        remove_codex_hooks(args.hooks_file, args.events)
    elif args.command_name == "remove-claude":
        remove_claude_hooks(args.settings_file, args.command, args.events)
    elif args.command_name == "remove-cline":
        remove_cline_hook(args.hook_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
