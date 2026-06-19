"""Shared notify hook logic for Codex and Claude Code.

The module accepts Codex notify JSON as the first CLI argument and Claude Code
hook JSON on stdin. It delegates speech and title updates to
``codex-agent-tracker`` so announcement wording remains centralized there.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CLARIFY_VOICE = "af_jessica"
DEFAULT_DANGER_VOICE = "am_onyx"
DESTRUCTIVE_COMMAND_RE = re.compile(
    r"(?ix)"
    r"\b(rm\s+-[^\n;&|]*r[^\n;&|]*\s+(?:/|~|\$HOME)|"
    r"git\s+push\s+--force|"
    r"git\s+reset\s+--hard|"
    r"mkfs(?:\.[a-z0-9]+)?\s|"
    r"dd\s+.*\bof=/dev/|"
    r"chmod\s+-R\s+777\s+(?:/|~|\$HOME))"
)


@dataclass(frozen=True)
class RuntimeContext:
    """Resolved runtime metadata for an incoming hook event."""

    label: str
    project_name: str
    project_path: str
    voice: str
    codex_home: Path
    model_name: str = ""


def log_dir(home: Path | None = None) -> Path:
    """Return the repository-local log directory used by ACC."""
    configured = os.environ.get("AGENT_COMMAND_CENTER_LOG_DIR", "")
    if configured:
        return Path(configured).expanduser()
    return (home or Path.home()) / "projects" / "agent_command_center" / ".log"


def append_log(message: str, home: Path | None = None) -> None:
    """Append a best-effort diagnostic line to the notify log."""
    try:
        path = log_dir(home) / "notify.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
    except Exception:
        pass


def tracker_path() -> Path:
    """Return the preferred codex-agent-tracker executable path."""
    local = Path.home() / ".local/bin/codex-agent-tracker"
    if local.is_file():
        return local
    return Path("codex-agent-tracker")


def run_tracker(args: list[str]) -> bool:
    """Run ``codex-agent-tracker`` with ``args`` and suppress hook output."""
    try:
        result = subprocess.run(
            [str(tracker_path()), *args],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return result.returncode == 0


def parse_payload(argv: list[str], stdin_text: str | None = None) -> dict[str, Any]:
    """Parse a Codex argv payload or Claude stdin payload."""
    raw = argv[1] if len(argv) > 1 and argv[1].strip() else stdin_text
    if raw is None:
        try:
            raw = sys.stdin.read()
        except Exception:
            raw = ""
    raw = raw.strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except ValueError:
        append_log(f"invalid payload {raw[:120]!r}")
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_text(value: str) -> str:
    """Collapse repeated whitespace for spoken labels."""
    return " ".join((value or "").split())


def project_name_from(payload: dict[str, Any]) -> str:
    """Resolve a human project name from environment metadata or cwd."""
    name = normalize_text(os.environ.get("CODEX_AGENT_PROJECT_NAME", ""))
    if name:
        return name
    project_path = os.environ.get("CODEX_AGENT_PROJECT_PATH", "")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    path = project_path or cwd
    if path:
        resolved = Path(path).expanduser()
        return resolved.name or str(resolved)
    return ""


def context_for(payload: dict[str, Any], default_label: str) -> RuntimeContext:
    """Build runtime context from payload and environment."""
    project_path = os.environ.get("CODEX_AGENT_PROJECT_PATH", "")
    cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
    label = normalize_text(os.environ.get("CODEX_AGENT_LABEL", "")) or default_label
    voice = (
        os.environ.get("CODEX__TTS_VOICE")
        or os.environ.get("CLAUDE_TTS_VOICE")
        or os.environ.get("CLAUDE_CODE_TTS_VOICE")
        or ""
    )
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / (".claude" if default_label == "claude" else ".codex"))
    model_name = normalize_text(os.environ.get("CODEX_AGENT_LMSTUDIO_MODEL", ""))
    return RuntimeContext(
        label=label,
        project_name=project_name_from(payload),
        project_path=project_path or cwd,
        voice=voice,
        codex_home=codex_home.expanduser(),
        model_name=model_name,
    )


def announce(event: str, context: RuntimeContext, task_description: str = "") -> bool:
    """Ask the tracker to speak a start or finish announcement."""
    args = [
        "announce",
        "--event",
        event,
        "--label",
        context.label,
        "--project-name",
        context.project_name,
        "--project-path",
        context.project_path,
        "--voice",
        context.voice,
        "--codex-home",
        str(context.codex_home),
    ]
    if context.model_name:
        args.extend(["--model-name", context.model_name])
    if task_description:
        args.extend(["--task-description", task_description])
    return run_tracker(args)


def clarify(context: RuntimeContext, question: str) -> bool:
    """Ask the tracker to speak a clarification or attention prompt."""
    voice = os.environ.get("CLAUDE_CLARIFY_VOICE", "").strip() or DEFAULT_CLARIFY_VOICE
    return run_tracker(
        [
            "clarify",
            "--question",
            question,
            "--label",
            context.label,
            "--project-name",
            context.project_name,
            "--project-path",
            context.project_path,
            "--voice",
            voice,
            "--codex-home",
            str(context.codex_home),
        ]
    )


def update_title(prompt: str, context: RuntimeContext) -> bool:
    """Ask the tracker to update the terminal title for a submitted prompt."""
    args = [
        "title",
        "--prompt",
        normalize_text(prompt),
        "--project-path",
        context.project_path,
        "--codex-home",
        str(context.codex_home),
    ]
    kitty_window_id = os.environ.get("KITTY_WINDOW_ID", "")
    terminal_device = os.environ.get("CODEX_AGENT_TERMINAL_DEVICE", "")
    if kitty_window_id:
        args.extend(["--kitty-window-id", kitty_window_id])
    if terminal_device:
        args.extend(["--terminal-device", terminal_device])
    return run_tracker(args)


def notify_turn_complete(status: int = 0) -> bool:
    """Tell the tracker that a directly tracked Codex turn completed."""
    token = os.environ.get("CODEX_AGENT_RUN_ID", "")
    if not token:
        return False
    return run_tracker(["turn-complete", "--status", str(status), "--token", token])


def transcript_prompt(transcript_path: str) -> str:
    """Return the latest real user prompt from a Claude transcript JSONL."""
    if not transcript_path:
        return ""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return ""
    for raw in reversed(lines):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if entry.get("type") != "user" or entry.get("isSidechain"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            if any(isinstance(block, dict) and block.get("type") == "tool_result" for block in content):
                continue
            text = " ".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        else:
            text = ""
        text = normalize_text(text)
        if text and not text.startswith("<"):
            return text
    return ""


def danger_reason(payload: dict[str, Any]) -> str:
    """Return a short reason when a Claude tool payload looks destructive."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command", "")
    if not isinstance(command, str):
        return ""
    match = DESTRUCTIVE_COMMAND_RE.search(command)
    return normalize_text(match.group(0)) if match else ""


def handle_codex(payload: dict[str, Any]) -> int:
    """Handle Codex notify payloads."""
    event_type = payload.get("type")
    context = context_for(payload, "codex")
    append_log(f"{context.label} type={event_type} cwd={payload.get('cwd')}")
    if event_type == "agent-turn-complete":
        notify_turn_complete(int(payload.get("status", 0) or 0))
    return 0


def handle_claude(payload: dict[str, Any]) -> int:
    """Handle Claude Code hook payloads."""
    event = payload.get("hook_event_name", "")
    context = context_for(payload, "claude")
    append_log(f"Claude event={event} project={context.project_name} cwd={payload.get('cwd')}")

    if event == "SessionStart":
        announce("start", context)
    elif event in {"Stop", "SubagentStop"}:
        task = transcript_prompt(str(payload.get("transcript_path", "")))
        announce("finish", context, task_description=task)
    elif event == "UserPromptSubmit":
        update_title(str(payload.get("prompt", "")), context)
    elif event == "Notification":
        message = normalize_text(str(payload.get("message", ""))) or "Claude needs your attention"
        clarify(context, message)
    elif event == "PreToolUse":
        reason = danger_reason(payload)
        if reason:
            voice = os.environ.get("CLAUDE_DANGER_VOICE", "").strip() or DEFAULT_DANGER_VOICE
            run_tracker(
                [
                    "voice",
                    "--text",
                    f"Warning. Claude is about to run {reason}",
                    "--voice",
                    voice,
                    "--codex-home",
                    str(context.codex_home),
                ]
            )
    return 0


def main(argv: list[str] | None = None, stdin_text: str | None = None) -> int:
    """CLI entry point for both Codex and Claude hook styles."""
    argv = argv if argv is not None else sys.argv
    payload = parse_payload(argv, stdin_text=stdin_text)
    if not payload:
        return 0
    if "hook_event_name" in payload:
        return handle_claude(payload)
    return handle_codex(payload)
