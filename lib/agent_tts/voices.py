"""Persistent installer voice choices shared by hooks and ACC."""

import json
from pathlib import Path
import sys

DEFAULT_VOICES = {
    'codex': 'af_bella', 'claude': 'af_sky', 'qwen': 'af_heart',
    'cline': 'af_aoede', 'grok': 'af_kore', 'openrouter': 'af_jessica',
    'nvidia': 'af_sarah', 'opencode': 'af_heart',
}


def require_preferences(preferences):
    """Reject malformed saved voice data before changing user files.

    Parameters: preferences - decoded persistent configuration.
    Returns: None.
    """
    print(f'preferences={preferences}', file=sys.stderr)
    if not isinstance(preferences, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) or not value.strip()
        for key, value in preferences.items()
    ):
        raise ValueError('voices.json must contain a mapping of harness names to voice names')
    print(None, file=sys.stderr)


def read_preferences(home):
    """Read saved choices without accepting malformed configuration.

    Parameters: home - target user's home directory.
    Returns: saved harness-to-voice mapping, or an empty mapping when absent.
    """
    print(f'home={home}', file=sys.stderr)
    path = home / '.config/agent-tts/voices.json'
    try:
        result = json.loads(path.read_text())
    except FileNotFoundError:
        result = {}
    require_preferences(result)
    print(result, file=sys.stderr)
    return result


def saved_voice(kind):
    """Resolve an installed choice while allowing runtime fallback on damaged files.

    Parameters: kind - harness family.
    Returns: saved voice id, or an empty string when none is usable.
    """
    print(f'kind={kind}', file=sys.stderr)
    try:
        result = read_preferences(Path.home()).get(kind, '')
    except (ValueError, OSError):
        result = ''
    print(result, file=sys.stderr)
    return result
