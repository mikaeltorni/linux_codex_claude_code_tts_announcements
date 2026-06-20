#!/usr/bin/env python3
"""Command-line interface for the Agent TTS (ATTS) speech engine.

Exposes the speech verbs that runtimes (Agent Command Center's tracker, the
Codex/Claude notify hooks, and direct users) call to speak agent activity:

  * ``voice``/``say`` — speak a literal line of text.
  * ``announce``      — speak the shared start/finish wording for an agent turn.
  * ``clarify``       — speak the shared "needs your input" question.
  * ``speed``         — read or set the persisted speed multiplier.
  * ``volume``        — read or set the persisted volume percentage.
  * ``silent``        — mute/unmute every announcement (persisted toggle).

Wording, synthesis, playback, and the speed/volume/silent tunables all live in
:mod:`agent_tts.engine`; this module is only the argument surface.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import engine


def _codex_home(args) -> Path:
    """Resolve the Kokoro-asset home for a parsed command."""
    value = getattr(args, "codex_home", "") or ""
    if value:
        return Path(value).expanduser()
    return engine.default_codex_home()


def cmd_voice(args) -> int:
    """Speak a literal line of text (the ``voice``/``say`` verb)."""
    engine.speak(args.text, args.voice, _codex_home(args), play=not getattr(args, "no_play", False))
    return 0


def cmd_announce(args) -> int:
    """Speak the shared start/finish wording for an agent turn.

    Wording composition (and the optional spoken completion message) lives here
    so every runtime sounds identical. Prompt summarization and cross-turn
    de-duplication remain the caller's responsibility; this verb speaks exactly
    the announcement described by its arguments.
    """
    text = engine.agent_announcement_text(
        args.label or "",
        args.project_name or "",
        args.event,
        current_project_path=args.project_path or "",
        task_description=args.task_description or "",
        completion_message=args.completion_message or "",
        model_name=getattr(args, "model_name", "") or "",
    )
    if not text:
        return 0
    engine.speak(text, args.voice, _codex_home(args), play=True)
    return 0


def cmd_clarify(args) -> int:
    """Speak the shared clarification question for an agent turn."""
    text = engine.clarify_announcement_text(
        args.project_name or "",
        current_project_path=args.project_path or "",
    )
    if not text:
        return 0
    engine.speak(text, args.voice, _codex_home(args), play=True)
    return 0


def cmd_speed(args) -> int:
    """Read or update the persisted TTS speed multiplier."""
    value = getattr(args, "value", None)
    if value is None or value == "status":
        print(engine.format_tts_speed(engine.current_tts_speed()))
        return 0
    try:
        speed = engine.parse_tts_speed(value)
    except ValueError as exc:
        print(f"invalid speed: {exc}", file=sys.stderr)
        return 2
    engine.set_tts_speed(speed)
    speed_text = engine.format_tts_speed(speed)
    engine.append_voice_log(f"tts speed set to {speed_text}")
    print(speed_text)
    return 0


def cmd_volume(args) -> int:
    """Read or update the persisted TTS volume percentage."""
    value = getattr(args, "value", None)
    if value is None or value == "status":
        print(engine.format_tts_volume_percent(engine.current_tts_volume_percent()))
        return 0
    try:
        percent = engine.parse_tts_volume_percent(value)
    except ValueError as exc:
        print(f"invalid volume: {exc}", file=sys.stderr)
        return 2
    engine.set_tts_volume_percent(percent)
    percent_text = engine.format_tts_volume_percent(percent)
    gain_text = engine.format_gain_db(engine.tts_volume_percent_to_db(percent))
    engine.append_voice_log(f"tts volume set to {percent_text} ({gain_text}dB)")
    print(percent_text)
    return 0


def cmd_silent(args) -> int:
    """Mute or unmute every announcement via a persisted toggle.

    Supports ``on``, ``off``, ``toggle`` (default) and ``status``. Switching
    state speaks a confirmation that bypasses the suppression it controls.
    """
    action = (getattr(args, "action", None) or "toggle").lower()
    current = engine.acc_silent_enabled()

    if action == "status":
        print("on" if current else "off")
        return 0
    if action == "on":
        target = True
    elif action == "off":
        target = False
    elif action == "toggle":
        target = not current
    else:
        print(f"unknown silent action: {action}", file=sys.stderr)
        return 2

    engine.set_acc_silent(target)
    engine.append_voice_log(f"silent toggled -> {'on' if target else 'off'}")
    print("on" if target else "off")

    text = engine.SILENT_ENABLED_TEXT if target else engine.SILENT_DISABLED_TEXT
    engine.speak(text, args.voice, _codex_home(args), play=True, ignore_silent=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the ``agent-tts`` argument parser."""
    parser = argparse.ArgumentParser(prog="agent-tts", description="Agent TTS (ATTS) speech engine.")
    sub = parser.add_subparsers(dest="command", required=True)

    default_home = os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))
    default_voice = os.environ.get("ATTS_VOICE", os.environ.get("CODEX__TTS_VOICE", "af_sky"))

    for name in ("voice", "say"):
        voice = sub.add_parser(name, help="speak a literal line of text")
        voice.add_argument("--text", required=True)
        voice.add_argument("--voice", required=True)
        voice.add_argument("--codex-home", default=default_home)
        voice.add_argument("--no-play", action="store_true")
        voice.set_defaults(func=cmd_voice)

    announce = sub.add_parser("announce", help="speak the shared start/finish wording")
    announce.add_argument("--event", required=True, choices=["start", "finish"])
    announce.add_argument("--voice", required=True)
    announce.add_argument("--codex-home", default=default_home)
    announce.add_argument("--label", default="")
    announce.add_argument("--project-name", default="")
    announce.add_argument("--project-path", default="")
    announce.add_argument("--task-description", default="")
    announce.add_argument("--completion-message", default="")
    announce.add_argument("--model-name", default="")
    announce.set_defaults(func=cmd_announce)

    clarify = sub.add_parser("clarify", help="speak the shared clarification question")
    clarify.add_argument("--voice", required=True)
    clarify.add_argument("--codex-home", default=default_home)
    clarify.add_argument("--project-name", default="")
    clarify.add_argument("--project-path", default="")
    clarify.add_argument("--task-description", default="")
    # Accepted for hook compatibility; the spoken question is project-based and
    # never echoes raw attention text, so this value is intentionally ignored.
    clarify.add_argument("--question", default="")
    clarify.set_defaults(func=cmd_clarify)

    silent = sub.add_parser("silent", help="mute/unmute all agent TTS announcements")
    silent.add_argument("action", nargs="?", choices=["on", "off", "toggle", "status"], default="toggle")
    silent.add_argument("--voice", default=default_voice)
    silent.add_argument("--codex-home", default=default_home)
    silent.set_defaults(func=cmd_silent)

    speed = sub.add_parser("speed", help="read/update the agent TTS speed multiplier")
    speed.add_argument("value", nargs="?", default=None, help="positive speed multiplier, or status")
    speed.set_defaults(func=cmd_speed)

    volume = sub.add_parser("volume", help="read/update the agent TTS volume percentage")
    volume.add_argument("value", nargs="?", default=None, help="positive volume percentage, or status")
    volume.set_defaults(func=cmd_volume)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected command."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
