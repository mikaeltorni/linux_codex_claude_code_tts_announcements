#!/usr/bin/env python3
"""Agent TTS (ATTS) speech engine.

This module is the single owner of agent text-to-speech: Kokoro synthesis,
playback, ffmpeg volume amplification, the speed/volume/silent tunables, voice
selection, terminal-workspace suffixing, and the spoken start/finish/clarify
wording. It used to live inside Agent Command Center's ``codex-agent-tracker``;
it now lives here so the tracker (and any other runtime) can delegate *all*
speech to the standalone ``agent-tts`` binary.

Configuration is owned here under the ``ATTS_`` ("agent TTS") environment
namespace and a dedicated state directory. The previous Agent Command Center
names are still honored as fallbacks so existing installs keep working:

  * ``ATTS_SPEED``            (was ``AGENT_COMMAND_CENTER_TTS_SPEED``)
  * ``ATTS_VOLUME_PERCENT``   (was ``AGENT_COMMAND_CENTER_TTS_VOLUME_PERCENT``)
  * ``ATTS_SILENT``           (was ``ACC_SILENT``)
  * ``ATTS_VOICE``            (was ``CODEX__TTS_VOICE``)
  * ``ATTS_CLAUDE_VOICE``     (was ``CLAUDE_TTS_VOICE``)
  * ``ATTS_ANNOUNCE_WORKSPACE`` (was ``AGENT_COMMAND_CENTER_ANNOUNCE_WORKSPACE``)
  * ``ATTS_NO_AUDIO``         (was ``CODEX_AGENT_TRACKER_NO_AUDIO``)
  * ``ATTS_STATE_DIR``        (was ``CODEX_AGENT_TRACKER_STATE_DIR``)

The engine has no dependency on Agent Command Center.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── State and configuration locations ────────────────────────────────────────
STATE_DIR = Path(
    os.environ.get(
        "ATTS_STATE_DIR",
        os.environ.get(
            "CODEX_AGENT_TRACKER_STATE_DIR",
            Path.home() / ".local/state/agent-tts",
        ),
    )
)
# Legacy Agent Command Center state directory, read as a migration fallback so
# an existing saved speed/volume/silent value keeps applying until overwritten.
LEGACY_STATE_DIR = Path(Path.home() / ".local/state/codex-agent-tracker")
LOG_DIR = Path(
    os.environ.get(
        "ATTS_LOG_DIR",
        os.environ.get("AGENT_COMMAND_CENTER_LOG_DIR", STATE_DIR / "log"),
    )
)

SILENT_FLAG_FILE = STATE_DIR / "silent"
TTS_SPEED_FILE = STATE_DIR / "tts-speed"
TTS_VOLUME_FILE = STATE_DIR / "tts-volume"
VOICE_LOG_FILE = LOG_DIR / "voice.log"

TRUTHY = {"1", "true", "yes", "y", "on", "shutdown", "poweroff"}
DEFAULT_TTS_SPEED = 1.5
DEFAULT_TTS_VOLUME_PERCENT = 1000.0
LEGACY_DEFAULT_TTS_VOLUME_ENV = "125"

SILENT_ENABLED_TEXT = "Agent command center silent mode enabled. Announcements muted."
SILENT_DISABLED_TEXT = "Agent command center silent mode unmuted. Announcements restored."


def _first_env(*names: str) -> str | None:
    """Return the first set, non-empty environment value among ``names``."""
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip() != "":
            return value
    return None


def _read_state_file(filename: str) -> str:
    """Read a state file from the ATTS dir, falling back to the legacy ACC dir."""
    for base in (STATE_DIR, LEGACY_STATE_DIR):
        try:
            text = (base / filename).read_text(encoding="utf-8").strip()
        except Exception:
            text = ""
        if text:
            return text
    return ""


def project_folder_name(project_path: str = "") -> str:
    """Return the trailing folder name of a project path (spoken fallback)."""
    path = (project_path or "").strip()
    if not path:
        return ""
    return os.path.basename(os.path.normpath(path))


# ── Verbatim engine helpers (moved from codex-agent-tracker) ──────────────────
def now() -> str:
    """Return the current local timestamp."""
    return datetime.now(timezone.utc).isoformat()


def append_voice_log(message: str) -> None:
    """Append a timestamped voice event."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with VOICE_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{now()} {message}\n")
    except Exception:
        pass


def parse_tts_speed(value: str) -> float:
    """Validate and normalize a TTS speed multiplier."""
    try:
        speed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("speed must be a positive number") from exc
    if speed <= 0:
        raise ValueError("speed must be greater than 0")
    return speed


def format_tts_speed(speed: float) -> str:
    """Return a compact, stable string for a TTS speed multiplier."""
    return f"{speed:.3f}".rstrip("0").rstrip(".")


def set_tts_speed(speed: float) -> None:
    """Persist the TTS speed multiplier for all agent announcements."""
    TTS_SPEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TTS_SPEED_FILE.with_suffix(".tmp")
    tmp.write_text(format_tts_speed(speed) + "\n", encoding="utf-8")
    tmp.replace(TTS_SPEED_FILE)


def parse_tts_volume_percent(value: str) -> float:
    """Validate and normalize a TTS volume percentage."""
    raw = str(value).strip()
    if raw.endswith("%"):
        raw = raw[:-1].strip()
    try:
        percent = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("volume must be a positive percentage") from exc
    if percent <= 0:
        raise ValueError("volume must be greater than 0%")
    return percent


def format_tts_volume_percent(percent: float) -> str:
    """Return a compact percentage string for a TTS volume setting."""
    text = f"{percent:.3f}".rstrip("0").rstrip(".")
    return f"{text}%"


def tts_volume_percent_to_db(percent: float) -> float:
    """Convert a linear volume percentage to an ffmpeg decibel gain."""
    return 20.0 * math.log10(percent / 100.0)


def format_gain_db(gain_db: float) -> str:
    """Return a compact, stable decibel string for logs and ffmpeg."""
    if abs(gain_db) < 0.0005:
        gain_db = 0.0
    return f"{gain_db:.3f}".rstrip("0").rstrip(".")


def set_tts_volume_percent(percent: float) -> None:
    """Persist the TTS volume percentage for all agent announcements."""
    TTS_VOLUME_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TTS_VOLUME_FILE.with_suffix(".tmp")
    tmp.write_text(format_tts_volume_percent(percent) + "\n", encoding="utf-8")
    tmp.replace(TTS_VOLUME_FILE)


def set_acc_silent(enabled: bool) -> None:
    """Persist the silent toggle flag so all runtimes honor it."""
    SILENT_FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SILENT_FLAG_FILE.with_suffix(".tmp")
    tmp.write_text("1\n" if enabled else "0\n", encoding="utf-8")
    tmp.replace(SILENT_FLAG_FILE)


def voice_label(agent_display: str = "", label: str = "", kind: str = "") -> str:
    """Return the short runtime name used for TTS announcements."""
    canonical = {
        "codex": "codex",
        "qwen": "Local",
        "api": "API",
        "claude": "claude",
    }
    if kind in canonical:
        return canonical[kind]

    display = (agent_display or "").strip()
    label = (label or "").strip()
    normalized = display or label
    if normalized == "Codex Agent":
        return "codex"
    if normalized.startswith("Local"):
        return "Local"
    return normalized


def codex_home_for_kind(kind: str, env: dict[str, str]) -> str:
    """Return the Codex home directory for an agent kind."""
    if env.get("CODEX_HOME"):
        return env["CODEX_HOME"]
    if kind == "qwen":
        return str(Path.home() / ".codex-qwen")
    if kind == "api":
        return str(Path.home() / ".codex-api")
    return str(Path.home() / ".codex")


def amplify_audio(input_path: Path, output_path: Path, gain_db: float) -> bool:
    """Create a gain-adjusted copy of an audio file.

    Kokoro output is quiet (peaks near -8 dBFS), so users routinely raise the
    volume past the point where positive gain would push peaks above 0 dBFS.
    Baking that gain straight into the 16-bit samples would hard-clip them into
    buzzy distortion, making higher levels sound broken rather than louder. To
    keep amplified speech clean, a brick-wall limiter follows the gain stage
    whenever we boost; attenuation (gain <= 0) never clips, so it is left
    untouched to avoid the limiter's lookahead coloration.
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or abs(gain_db) < 0.0005:
        return False
    gain_text = format_gain_db(gain_db)
    audio_filter = f"volume={gain_text}dB"
    if gain_db > 0:
        audio_filter += ",alimiter=limit=0.95:level=false"
    try:
        result = subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(input_path),
                "-filter:a",
                audio_filter,
                str(output_path),
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception as exc:
        append_voice_log(f"ffmpeg amplify exception: {exc}")
        return False
    if result.returncode == 0:
        append_voice_log(f"amplified {input_path} to {output_path} filter={audio_filter}")
        return True
    append_voice_log(f"ffmpeg amplify failed rc={result.returncode}: {(result.stderr or '').strip()}")
    return False


def resolve_uvx() -> str | None:
    """Resolve the uvx executable used for TTS."""
    for candidate in (
        shutil.which("uvx"),
        str(Path.home() / ".local/bin/uvx"),
        str(Path.home() / ".cargo/bin/uvx"),
    ):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def _capture_command(cmd: list[str], timeout: float = 1.0) -> str:
    """Run ``cmd`` and return its stripped stdout, or "" on any failure."""
    if not cmd or not shutil.which(cmd[0]):
        return ""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


def _xprop_desktop_index(args: list[str]) -> int | None:
    """Return the 0-based EWMH desktop index from an ``xprop`` query."""
    out = _capture_command(["xprop"] + args)
    # Example: "_NET_WM_DESKTOP(CARDINAL) = 3"
    if "=" not in out:
        return None
    value = out.rsplit("=", 1)[1].strip()
    try:
        index = int(value)
    except ValueError:
        return None
    return index if index >= 0 else None


def detect_terminal_workspace(window_id: str = "") -> str:
    """Best-effort detection of the workspace hosting the CLI's terminal.

    Works across compositors: GNOME/X11 and other EWMH window managers (via
    ``xprop``), sway (via ``swaymsg``), and Hyprland (via ``hyprctl``). On X11
    the CLI's own terminal window (``$WINDOWID``) is preferred, with the active
    window and the visible workspace as fallbacks. Returns "" when undetectable.
    """
    sway = _capture_command(["swaymsg", "-t", "get_workspaces"])
    if sway:
        try:
            for workspace in json.loads(sway):
                if isinstance(workspace, dict) and workspace.get("focused"):
                    name = str(workspace.get("name") or workspace.get("num") or "").strip()
                    if name:
                        return name
        except Exception:
            pass
    hypr = _capture_command(["hyprctl", "activeworkspace", "-j"])
    if hypr:
        try:
            data = json.loads(hypr)
            name = str(data.get("name") or data.get("id") or "").strip()
            if name:
                return name
        except Exception:
            pass

    wid = (window_id or os.environ.get("WINDOWID", "")).strip()
    if wid:
        index = _xprop_desktop_index(["-id", wid, "_NET_WM_DESKTOP"])
        if index is not None:
            return str(index + 1)
    active = _capture_command(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
    if "=" in active:
        active_id = active.rsplit("=", 1)[1].strip().split(",")[0].strip()
        if active_id and active_id not in {"0x0", "0"}:
            index = _xprop_desktop_index(["-id", active_id, "_NET_WM_DESKTOP"])
            if index is not None:
                return str(index + 1)
    index = _xprop_desktop_index(["-root", "_NET_CURRENT_DESKTOP"])
    if index is not None:
        return str(index + 1)
    return ""


def agent_announcement_text(
    label: str,
    project_name: str,
    event: str,
    current_project_path: str = "",
    task_description: str = "",
    completion_message: str = "",
    model_name: str = "",
) -> str:
    """Build the spoken start or finish message for a tracked agent."""
    prefix = f"{model_name.strip()}. " if model_name.strip() else ""
    if event == "finish" and completion_message.strip():
        return f"{prefix}{completion_message.strip()}"
    if label in {"codex", "claude"}:
        display_label = label
    else:
        display_label = label.capitalize() if label else "Agent"
    folder = project_folder_name(current_project_path)
    if event == "start":
        if project_name:
            return f"{prefix}Project {project_name} started"
        return f"{prefix}{display_label} started"
    if not current_project_path:
        if project_name:
            return f"{prefix}Finished working on Project {project_name}"
        return f"{prefix}{display_label} ended"
    return f"{prefix}{display_label} finished on {folder}"


def clarify_announcement_text(
    project_name: str,
    current_project_path: str = "",
) -> str:
    """Build the spoken clarification question for a tracked agent."""
    target = project_name.strip()
    if not target and current_project_path.strip():
        target = project_folder_name(current_project_path)
    if target:
        return f"Project {target} needs your input. What should we do next?"
    return "I need your input. What should we do next?"


# ── ATTS-aware configuration resolution (env + state, with ACC fallback) ──────
def current_tts_speed() -> float:
    """Return the configured TTS speed multiplier.

    Resolution order: ``ATTS_SPEED`` (or legacy ``AGENT_COMMAND_CENTER_TTS_SPEED``)
    env override > persisted ``agent-tts speed`` value (ATTS state, then legacy
    ACC state) > the built-in default.
    """
    env = _first_env("ATTS_SPEED", "AGENT_COMMAND_CENTER_TTS_SPEED")
    if env is not None and env.strip():
        try:
            return parse_tts_speed(env.strip())
        except ValueError:
            append_voice_log(f"invalid ATTS_SPEED={env!r}; ignoring")
    text = _read_state_file("tts-speed")
    if text:
        try:
            return parse_tts_speed(text)
        except ValueError:
            append_voice_log(f"invalid persisted TTS speed={text!r}; using default")
    return DEFAULT_TTS_SPEED


def persisted_tts_volume_percent() -> float | None:
    """Return the saved volume percentage (ATTS, then legacy ACC), or None."""
    text = _read_state_file("tts-volume")
    if not text:
        return None
    try:
        return parse_tts_volume_percent(text)
    except ValueError:
        append_voice_log(f"invalid persisted TTS volume={text!r}; using default")
        return None


def current_tts_volume_percent() -> float:
    """Return the configured TTS volume percentage.

    Resolution order mirrors :func:`current_tts_speed`. Older generated shells
    exported the legacy default ``125``; that exact value is treated as unset
    when a valid saved value exists so it never shadows the current setting.
    """
    env = _first_env("ATTS_VOLUME_PERCENT", "AGENT_COMMAND_CENTER_TTS_VOLUME_PERCENT")
    if env is not None and env.strip():
        env_text = env.strip()
        if env_text == LEGACY_DEFAULT_TTS_VOLUME_ENV:
            persisted = persisted_tts_volume_percent()
            if persisted is not None:
                return persisted
        else:
            try:
                return parse_tts_volume_percent(env_text)
            except ValueError:
                append_voice_log(f"invalid ATTS_VOLUME_PERCENT={env!r}; ignoring")
    persisted = persisted_tts_volume_percent()
    if persisted is not None:
        return persisted
    return DEFAULT_TTS_VOLUME_PERCENT


def remove_legacy_default_tts_volume_env(env: dict[str, str]) -> None:
    """Drop stale generated default volume exports from a child environment."""
    if persisted_tts_volume_percent() is None:
        return
    for name in ("ATTS_VOLUME_PERCENT", "AGENT_COMMAND_CENTER_TTS_VOLUME_PERCENT"):
        if env.get(name, "").strip() == LEGACY_DEFAULT_TTS_VOLUME_ENV:
            env.pop(name, None)


def acc_silent_enabled() -> bool:
    """Return whether silent mode is muting TTS announcements.

    ``ATTS_SILENT`` (or legacy ``ACC_SILENT``) overrides everything for a single
    invocation; otherwise the persisted ``silent`` flag file is consulted.
    """
    env = _first_env("ATTS_SILENT", "ACC_SILENT")
    if env is not None and env.strip() != "":
        return env.strip().lower() in TRUTHY
    text = _read_state_file("silent")
    return text.lower() in TRUTHY


def voice_for_kind(kind: str, env: dict[str, str]) -> str:
    """Return the configured TTS voice for an agent kind."""
    explicit = env.get("ATTS_VOICE") or env.get("CODEX__TTS_VOICE")
    if explicit:
        return explicit
    if kind == "qwen":
        return "af_heart"
    if kind == "claude":
        return os.environ.get("ATTS_CLAUDE_VOICE") or os.environ.get("CLAUDE_TTS_VOICE", "af_sky")
    if kind == "api":
        return "af_bella"
    return "af_bella"


def with_workspace_suffix(text: str, workspace: str | None = None) -> str:
    """Append ``on workspace <N>`` to a spoken message (best-effort).

    Set ``ATTS_ANNOUNCE_WORKSPACE=0`` (or legacy
    ``AGENT_COMMAND_CENTER_ANNOUNCE_WORKSPACE=0``) to disable.
    """
    if not text:
        return text
    disabled = (_first_env("ATTS_ANNOUNCE_WORKSPACE", "AGENT_COMMAND_CENTER_ANNOUNCE_WORKSPACE") or "1").strip().lower()
    if disabled in {"0", "false", "no", "off"}:
        return text
    workspace = detect_terminal_workspace() if workspace is None else workspace
    workspace = (workspace or "").strip()
    if not workspace:
        return text
    suffix = f"on workspace {workspace}"
    stripped = text.rstrip().rstrip(".")
    if stripped.lower().endswith(suffix.lower()):
        return text
    return f"{stripped} {suffix}"


def _no_audio() -> bool:
    """Return whether audio playback is globally suppressed for this process."""
    return _first_env("ATTS_NO_AUDIO", "CODEX_AGENT_TRACKER_NO_AUDIO") is not None


def play_audio(audio_path: Path, ignore_silent: bool = False) -> bool:
    """Play an audio file with the first available player.

    Honors ``ATTS_NO_AUDIO`` (clips are still generated/cached but never played)
    and silent mode (unless ``ignore_silent``). When suppressed this returns
    ``True`` so callers do not fall back to a desktop synthesizer.
    """
    if _no_audio():
        append_voice_log(f"playback suppressed (ATTS_NO_AUDIO) for {audio_path}")
        return True
    if not ignore_silent and acc_silent_enabled():
        append_voice_log(f"playback suppressed (silent) for {audio_path}")
        return True
    for player in ("pw-play", "paplay", "aplay"):
        player_path = shutil.which(player)
        if not player_path:
            continue
        try:
            result = subprocess.run(
                [player_path, str(audio_path)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except Exception as exc:
            append_voice_log(f"{player} exception: {exc}")
            continue
        if result.returncode == 0:
            append_voice_log(f"played {audio_path} with {player}")
            return True
        append_voice_log(f"{player} failed rc={result.returncode}: {(result.stderr or '').strip()}")
    return False


def fallback_speak(text: str, ignore_silent: bool = False) -> None:
    """Speak text with a desktop fallback synthesizer (spd-say/espeak-ng).

    Honors ``ATTS_NO_AUDIO`` and silent mode (unless ``ignore_silent``).
    """
    if _no_audio():
        append_voice_log(f"fallback_speak suppressed (ATTS_NO_AUDIO) text={text!r}")
        return
    if not ignore_silent and acc_silent_enabled():
        append_voice_log(f"fallback_speak suppressed (silent) text={text!r}")
        return
    for cmd in (("spd-say", text), ("espeak-ng", text)):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            return


def speak_with_kokoro(
    text: str,
    voice: str,
    codex_home: Path,
    play: bool = True,
    ignore_silent: bool = False,
) -> bool:
    """Generate and play speech with Kokoro TTS.

    The Kokoro model assets are read from ``<codex_home>/tts``; generated clips
    are cached under the ATTS state directory. ``ignore_silent`` is forwarded to
    :func:`play_audio` so the ``silent`` toggle can voice its own confirmation.
    """
    uvx = resolve_uvx()
    if not text or not voice or not uvx:
        append_voice_log(f"kokoro skipped text={bool(text)} voice={voice!r} uvx={bool(uvx)}")
        return False

    tts_dir = codex_home / "tts"
    if not (tts_dir / "kokoro-v1.0.onnx").is_file() or not (tts_dir / "voices-v1.0.bin").is_file():
        append_voice_log(f"kokoro missing files in {tts_dir}")
        return False

    speed = current_tts_speed()
    volume_percent = current_tts_volume_percent()
    gain_db = tts_volume_percent_to_db(volume_percent)
    safe_voice = "".join(ch if ch.isalnum() else "_" for ch in voice.lower())[:24] or "voice"
    safe_text = "".join(ch if ch.isalnum() else "_" for ch in text.lower())[:32] or "agent"
    speed_text = format_tts_speed(speed)
    volume_text = format_tts_volume_percent(volume_percent)
    text_hash = hashlib.sha1(f"{voice}\0{speed_text}\0{volume_text}\0{text}".encode("utf-8")).hexdigest()[:10]
    safe_name = f"{safe_voice}_{safe_text}_{text_hash}"
    speed_suffix = f"_s{speed_text.replace('.', '_')}"
    volume_suffix = f"_v{volume_text.rstrip('%').replace('.', '_')}"
    audio_dir = STATE_DIR / "voice-cache"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"{safe_name}{speed_suffix}{volume_suffix}.wav"
    raw_audio_path = Path("/tmp") / f"agent_tts_{safe_name}_raw.wav"
    input_path = Path("/tmp") / f"agent_tts_{safe_name}.txt"

    if audio_path.is_file():
        append_voice_log(f"using cached {audio_path} voice={voice} text={text!r}")
        if not play:
            return True
        return play_audio(audio_path, ignore_silent=ignore_silent)

    try:
        input_path.write_text(text, encoding="utf-8")
        env = os.environ.copy()
        local_lib = tts_dir / "lib"
        if local_lib.is_dir():
            existing = env.get("LD_LIBRARY_PATH", "")
            env["LD_LIBRARY_PATH"] = f"{local_lib}:{existing}" if existing else str(local_lib)
        subprocess.run(
            [
                uvx,
                "--from",
                "kokoro-tts",
                "kokoro-tts",
                str(input_path),
                str(raw_audio_path if abs(gain_db) >= 0.0005 else audio_path),
                "--voice",
                voice,
                "--speed",
                speed_text,
            ],
            cwd=tts_dir,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        append_voice_log(f"kokoro failed rc={exc.returncode}: {(exc.stderr or '').strip()}")
        return False
    except Exception as exc:
        append_voice_log(f"kokoro exception: {exc}")
        return False

    if abs(gain_db) >= 0.0005:
        if not amplify_audio(raw_audio_path, audio_path, gain_db):
            try:
                raw_audio_path.replace(audio_path)
                append_voice_log(f"using unamplified fallback {audio_path}")
            except Exception as exc:
                append_voice_log(f"audio fallback failed: {exc}")
                return False

    append_voice_log(f"generated {audio_path} voice={voice} speed={speed_text} volume={volume_text} text={text!r}")
    if not play:
        return True
    return play_audio(audio_path, ignore_silent=ignore_silent)


# ── High-level speak entrypoints used by the CLI ──────────────────────────────
def default_codex_home() -> Path:
    """Return the default Codex home that holds the Kokoro model assets."""
    return Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()


def speak(text: str, voice: str, codex_home: Path | None = None, play: bool = True, ignore_silent: bool = False) -> bool:
    """Speak literal ``text``, appending the workspace suffix and falling back.

    Returns True when Kokoro handled it; on failure a desktop synthesizer speaks
    the same text (unless playback is disabled).
    """
    home = codex_home or default_codex_home()
    spoken = with_workspace_suffix(text)
    if speak_with_kokoro(spoken, voice, home, play=play, ignore_silent=ignore_silent):
        return True
    if play:
        fallback_speak(spoken, ignore_silent=ignore_silent)
    return False
