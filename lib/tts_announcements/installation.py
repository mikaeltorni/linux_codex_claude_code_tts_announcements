"""Discover installed harnesses and configure their existing notification APIs."""

import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import termios
import tty

from . import install_hooks

from agent_tts.voices import DEFAULT_VOICES, read_preferences

HARNESS_HOMES = {
    'codex': ('.codex', ('codex',)), 'claude': ('.claude', ('claude',)),
    'qwen': ('.codex-qwen', ('qwen',)), 'cline': ('.cline', ('cline',)),
    'grok': ('.grok', ('grok',)), 'openrouter': ('.codex-openrouter', ('openr', 'openrouter')),
    'nvidia': ('.codex-nvidia', ('nvidia', 'nvi')),
    'opencode': ('.config/opencode', ('opencode',)),
}


def discover_harnesses(home):
    """Find configured homes or available CLI commands without creating homes.

    Parameters: home - target user's home directory.
    Returns: mapping from harness family to its detected configuration homes.
    """
    print(f'home={home}', file=sys.stderr)
    found = {}
    for kind, (relative, commands) in HARNESS_HOMES.items():
        location = home / relative
        homes = [location] if location.is_dir() or any(shutil.which(c) for c in commands) else []
        if kind == 'codex':
            homes.extend(sorted(p for p in home.glob('.codex-account-*')
                                if p.is_dir() and p.name.removeprefix('.codex-account-').isdigit()))
        if homes:
            found[kind] = homes
    print(found, file=sys.stderr)
    return found


def choose_voice(kind, current, voices):
    """Choose one voice with arrow keys, preserving terminal state on exit.

    Parameters: kind - harness family; current - saved/default choice; voices - offered voice ids.
    Returns: selected voice id, or None when the whole selection is cancelled.
    """
    print(f'kind={kind}, current={current}, voices={voices}', file=sys.stderr)
    options = list(dict.fromkeys((*voices, current)))
    index = options.index(current)
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    result = None
    try:
        tty.setraw(descriptor)
        print(f'Voice for {kind}: ↑/↓ to choose, Enter to confirm, q to cancel', flush=True)
        while True:
            print('\r\033[K' + '  '.join(('> ' if i == index else '') + value
                                        for i, value in enumerate(options)), end='', flush=True)
            key = os.read(descriptor, 1)
            if key in (b'\r', b'\n'):
                result = options[index]
                break
            if key in (b'q', b'\x03', b'\x04', b''):
                break
            if key == b'\x1b':
                sequence = os.read(descriptor, 2)
                if sequence in (b'[A', b'[D'):
                    index = (index - 1) % len(options)
                elif sequence in (b'[B', b'[C'):
                    index = (index + 1) % len(options)
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
        print()
    print(result, file=sys.stderr)
    return result


def configure_harness(kind, homes, voice, command):
    """Apply managed hooks through the existing config writers.

    Parameters: kind - harness family; homes - configuration directories; voice - selected id; command - installed notifier command.
    Returns: None.
    """
    print(f'kind={kind}, homes={homes}, voice={voice}, command={command}', file=sys.stderr)
    hook = f'env CODEX_AGENT_KIND={kind} CODEX_AGENT_LABEL={kind} ATTS_{kind.upper()}_VOICE={shlex.quote(voice)} CODEX__TTS_VOICE={shlex.quote(voice)} {command}'
    for home in homes:
        if kind in ('codex', 'qwen', 'openrouter', 'nvidia'):
            install_hooks.remove_codex_notify(home / 'config.toml')
            install_hooks.configure_codex_hooks(home / 'hooks.json', hook,
                                                ('UserPromptSubmit', 'Stop', 'PermissionRequest'))
        elif kind == 'claude':
            install_hooks.configure_claude_hooks(home / 'settings.json', hook)
        elif kind == 'grok':
            install_hooks.configure_grok_notify(home / 'config.toml', hook)
        elif kind == 'cline':
            for event in ('TaskStart', 'TaskResume', 'TaskComplete', 'TaskCancel',
                          'TaskError', 'UserPromptSubmit', 'PreToolUse'):
                install_hooks.configure_cline_hook(home / 'hooks' / event, hook,
                                                   'ask_question' if event == 'PreToolUse' else '')
        # OpenCode announcements are tracker-driven; it has no supported native hook writer here.
    print(None, file=sys.stderr)


def configure_installation(home, command, voices, interactive=True, require_enabled=False):
    """Reuse or collect choices before configuring discovered harnesses.

    Parameters: home - target home; command - installed notifier command; voices - offered voice ids; interactive - prompt for changes; require_enabled - skip when hook integration is disabled.
    Returns: None.
    """
    print(f'home={home}, command={command}, voices={voices}, interactive={interactive}, require_enabled={require_enabled}', file=sys.stderr)
    enabled = home / '.config/agent-tts/harness-hooks.enabled'
    if require_enabled and not enabled.is_file():
        print(None, file=sys.stderr)
        return
    harnesses = discover_harnesses(home)
    preferences = read_preferences(home)
    selected = dict(preferences)
    for kind in harnesses:
        voice = preferences.get(kind, DEFAULT_VOICES[kind])
        if interactive:
            voice = choose_voice(kind, voice, voices)
        if voice is None:
            print('Selection cancelled; harness hooks and voice choices unchanged.')
            print(None, file=sys.stderr)
            return
        selected[kind] = voice
    if harnesses:
        path = home / '.config/agent-tts/voices.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        if interactive:
            temporary = path.with_suffix(f'.tmp.{os.getpid()}')
            temporary.write_text(json.dumps(selected, indent=2) + '\n')
            temporary.replace(path)
        enabled.touch()
        if os.environ.get('TTS_MANUAL_EVENTS_NEW') == '1':
            event_file = Path(os.environ.get('ATTS_EVENT_CONFIG_FILE') or home / '.config/agent-tts/announcements.env')
            event_file.parent.mkdir(parents=True, exist_ok=True)
            event_file.write_text('ATTS_ANNOUNCE_START=1\nATTS_ANNOUNCE_FINISH=1\nATTS_ANNOUNCE_ATTENTION=1\n')
        for kind, homes in harnesses.items():
            configure_harness(kind, homes, selected[kind], command)
    else:
        if not interactive:
            enabled.parent.mkdir(parents=True, exist_ok=True)
            enabled.touch()
        print('No supported harnesses found; voice choices unchanged.')
    print(None, file=sys.stderr)


def disable_installation(home):
    """Remove managed hooks and stop automatic reconciliation, retaining voice choices.

    Parameters: home - target user's home directory.
    Returns: None.
    """
    print(f'home={home}', file=sys.stderr)
    (home / '.config/agent-tts/harness-hooks.enabled').unlink(missing_ok=True)
    for kind, homes in discover_harnesses(home).items():
        for directory in homes:
            if kind in ('codex', 'qwen', 'openrouter', 'nvidia'):
                install_hooks.remove_codex_hooks(directory / 'hooks.json',
                                                 ('UserPromptSubmit', 'Stop', 'PermissionRequest'))
            elif kind == 'claude':
                install_hooks.remove_claude_hooks(directory / 'settings.json', '')
            elif kind == 'grok':
                install_hooks.remove_grok_notify(directory / 'config.toml')
            elif kind == 'cline':
                for event in ('TaskStart', 'TaskResume', 'TaskComplete', 'TaskCancel',
                              'TaskError', 'UserPromptSubmit', 'PreToolUse'):
                    install_hooks.remove_cline_hook(directory / 'hooks' / event)
    print(None, file=sys.stderr)


def parse_arguments(argv):
    """Parse installer syntax once before dispatching operations.

    Parameters: argv - raw command-line arguments.
    Returns: parsed target home, notifier command, catalog and operation flags.
    """
    print(f'argv={argv}', file=sys.stderr)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--command', required=True)
    parser.add_argument('--voices', nargs='+', default=list(DEFAULT_VOICES.values()))
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--sync', action='store_true')
    modes.add_argument('--disable', action='store_true')
    parser.add_argument('--require-enabled', action='store_true')
    result = parser.parse_args(argv)
    print(result, file=sys.stderr)
    return result


def main(argv=None):
    """Dispatch interactive selection or noninteractive reconciliation.

    Parameters: argv - optional raw argument vector.
    Returns: zero after success or user cancellation.
    """
    print(f'argv={argv}', file=sys.stderr)
    args = parse_arguments(argv)
    if args.disable:
        disable_installation(args.home)
    else:
        configure_installation(args.home, args.command, args.voices, not args.sync, args.require_enabled)
    print(0, file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
