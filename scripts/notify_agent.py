#!/usr/bin/env python3
"""CLI entrypoint for Codex and Claude Code TTS announcement hooks."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from tts_announcements.notify import main


if __name__ == "__main__":
    raise SystemExit(main())
