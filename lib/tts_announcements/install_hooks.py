"""Install-time config writers for Codex and Claude Code TTS hooks.

Components:
  - configure_codex_notify: Write the generated Codex notify block.
  - configure_claude_hooks: Merge generated Claude hook commands.
  - main: CLI entrypoint used by lib/install_hooks.sh.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


CODEX_TTS_BLOCK_RE = re.compile(
    r"# BEGIN TTS ANNOUNCEMENTS NOTIFY(?: \(generated\))?.*?# END TTS ANNOUNCEMENTS NOTIFY(?: \(generated\))?\n*",
    flags=re.S,
)
CODEX_LEGACY_BLOCK_RE = re.compile(
    r"# BEGIN CODEX NOTIFY(?: \(generated\))?.*?# END CODEX NOTIFY(?: \(generated\))?\n*",
    flags=re.S,
)
LEGACY_NOTIFY_LINE_RE = re.compile(r'(?m)^notify = \["python3", ".*notify_agent\.py"\]\n+')


def configure_codex_notify(config_file: Path, command: str) -> None:
    """Write a generated notify block while preserving unrelated TOML."""
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


def _read_settings(settings_file: Path) -> dict[str, Any]:
    try:
        settings = json.loads(settings_file.read_text(encoding="utf-8"))
        if isinstance(settings, dict):
            return settings
    except Exception:
        pass
    return {}


def _prune_generated(hooks: dict[str, Any], event: str, generated_commands: set[str]) -> None:
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


def configure_claude_hooks(settings_file: Path, command: str) -> None:
    """Merge generated Claude Code hook commands while preserving user hooks."""
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

    ensure_command("SessionStart")
    ensure_command("Stop")
    ensure_command("SubagentStop")
    ensure_command("UserPromptSubmit")
    ensure_command("Notification")
    ensure_command("PreToolUse", "Bash|Write|Edit|NotebookEdit")

    settings_file.parent.mkdir(parents=True, exist_ok=True)
    settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Create the install hook config CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command_name", required=True)

    codex = subcommands.add_parser("codex")
    codex.add_argument("config_file", type=Path)
    codex.add_argument("command")

    claude = subcommands.add_parser("claude")
    claude.add_argument("settings_file", type=Path)
    claude.add_argument("command")

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one install hook config mutation."""
    args = build_parser().parse_args(argv)
    if args.command_name == "codex":
        configure_codex_notify(args.config_file, args.command)
    elif args.command_name == "claude":
        configure_claude_hooks(args.settings_file, args.command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
