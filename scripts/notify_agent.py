#!/usr/bin/env python3
"""CLI entrypoint for Codex and Claude Code TTS announcement hooks.

This thin wrapper puts the repository ``lib`` directory on ``sys.path`` and
delegates to :func:`tts_announcements.notify.main`. It is the script configured
as the ``notify`` command for Codex and as the hook command for Claude Code.

Usage:
    # Codex passes its notify JSON as argv[1]:
    python3 notify_agent.py '{"type": "agent-turn-complete", "status": 0}'

    # Claude Code passes its hook JSON on stdin:
    echo '{"hook_event_name": "Stop"}' | python3 notify_agent.py
"""

from pathlib import Path
import sys

#: Repository root, two levels up from this script (``<root>/scripts/notify_agent.py``).
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from tts_announcements.notify import main


if __name__ == "__main__":
    raise SystemExit(main())
