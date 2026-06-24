"""Install-time config writers for Codex and Claude Code TTS hooks.

Components:
  - configure_codex_notify: Write the generated Codex notify block.
  - configure_codex_hooks: Merge the Codex attention lifecycle hook.
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


@log.log_call(LOGGER)
def configure_codex_notify(config_file: Path, command: str) -> None:
    """Write a generated notify block while preserving unrelated TOML.

    Removes any current or legacy generated block, then prepends a fresh block,
    leaving all other TOML untouched. Safe to run repeatedly (idempotent).

    Args:
        config_file: Path to the Codex ``config.toml`` to update; created along
            with parent directories if missing.
        command: The notify command string; split on whitespace to form the
            ``notify = [...]`` array.

    Returns:
        None.
    """
    block = (
        "# BEGIN TTS ANNOUNCEMENTS NOTIFY (generated)\n"
        f"notify = {json.dumps(command.split())}\n"
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
def configure_codex_hooks(hooks_file: Path, command: str) -> None:
    """Merge a Codex ``PermissionRequest`` attention hook.

    Existing hook events and user-authored handlers are preserved. A previously
    generated attention handler is replaced so repeated installs remain
    idempotent.

    Args:
        hooks_file: User-level Codex ``hooks.json`` path.
        command: Hook command that reads the lifecycle payload from stdin.
    """
    settings = _read_settings(hooks_file)
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        settings["hooks"] = hooks

    event = "PermissionRequest"
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
                and isinstance(handler.get("command"), str)
                and "codex-claude-tts-announcements/scripts/notify_agent.py" in handler["command"]
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
    log.info(f"merged Codex attention hook into {hooks_file}", component=LOG_COMPONENT)


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

    claude = subcommands.add_parser("claude")
    claude.add_argument("settings_file", type=Path)
    claude.add_argument("command")
    claude.add_argument(
        "events",
        nargs="*",
        help="Lifecycle events to register; defaults to the full set when omitted.",
    )

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
        configure_codex_hooks(args.hooks_file, args.command)
    elif args.command_name == "claude":
        configure_claude_hooks(args.settings_file, args.command, args.events)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
