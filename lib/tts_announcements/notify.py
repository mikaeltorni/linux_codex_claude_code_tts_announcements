"""Shared notify hook logic for Codex, Claude Code, and Cline.

The module accepts Codex notify JSON as the first CLI argument and Claude/Cline
hook JSON on stdin. It delegates speech and title updates to
``codex-agent-tracker`` so announcement wording remains centralized there.

Components:
  - RuntimeContext: Immutable resolved metadata for one hook event.
  - parse_payload: Decode a Codex argv or Claude stdin JSON payload.
  - context_for: Build a RuntimeContext from a payload and the environment.
  - announce / clarify / update_title / notify_turn_complete: Tracker actions.
  - transcript_prompt: Extract the latest user prompt from a Claude transcript.
  - handle_codex / handle_claude / handle_cline: Route payloads to tracker actions.
  - main: CLI entry point for all supported hook styles.

Diagnostic logging is delegated to :mod:`tts_announcements.logging_utils`; all
log lines from this module use the ``"notify"`` component tag.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_tts import engine as tts_engine

from . import logging_utils as log

#: Component tag applied to every log line emitted by this module.
LOG_COMPONENT = "notify"

#: Default voice used for clarification/attention prompts when none is configured.
DEFAULT_CLARIFY_VOICE = "af_jessica"

#: Substring marking Claude Code's idle "waiting for input" Notification. Claude
#: emits this ~60s after a turn ends when the user has not replied, and re-emits
#: it while the session stays idle. It is not a genuine clarification request, so
#: speaking the attention prompt for it just re-fires "what should we do" at the
#: end of a finished turn (redundant with the finish chime). Matched
#: case-insensitively against the normalized message text.
IDLE_NOTIFICATION_MARKER = "waiting for your input"


def _env_flag(name: str) -> bool:
    """Return whether the environment variable ``name`` is set to a truthy value.

    Args:
        name: Environment variable to read; ``1``/``true``/``yes``/``on``
            (case-insensitive) count as set.
    """
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def lifecycle_is_tracker_managed() -> bool:
    """Return whether ACC already owns start/end speech for this child process."""
    return _env_flag("ATTS_LIFECYCLE_TRACKED")


def announcements_suppressed() -> bool:
    """Return whether this process opted out of all TTS announcements.

    Monitoring surfaces that run a real CLI TUI without a human behind it —
    e.g. the agentic-cli-status tmux debug console — export
    ``ATTS_SUPPRESS_ANNOUNCEMENTS=1`` so their lifecycle hooks never speak
    (otherwise every login announces a fake session such as
    "Project mk started" from the console's home-directory Claude window).
    """
    return _env_flag("ATTS_SUPPRESS_ANNOUNCEMENTS")


@dataclass(frozen=True)
class RuntimeContext:
    """Resolved runtime metadata for an incoming hook event.

    Attributes:
        label: Agent label used in announcements (e.g. ``"codex"`` or ``"claude"``).
        project_name: Human-readable project name spoken in announcements.
        project_path: Filesystem path of the active project.
        voice: Configured TTS voice id, or an empty string to use the default.
        codex_home: Path to the agent's home/config directory.
        model_name: Optional model name to mention in announcements; ``""`` to omit.
    """

    label: str
    project_name: str
    project_path: str
    voice: str
    codex_home: Path
    model_name: str = ""


def append_log(message: str, home: Path | None = None) -> None:
    """Append a best-effort diagnostic line to the notify log.

    Thin backward-compatible wrapper that records at INFO level through the
    centralized logging utility.

    Args:
        message: The diagnostic text to record (kept to a single line).
        home: Optional base home directory forwarded to the logger; ``None``
            uses the current user's home directory.

    Returns:
        None.
    """
    log.info(message, component=LOG_COMPONENT, home=home)


def tracker_path() -> Path:
    """Return the preferred ``codex-agent-tracker`` executable path.

    Returns:
        Path: ``~/.local/bin/codex-agent-tracker`` when that file exists,
        otherwise the bare command name ``codex-agent-tracker`` to be resolved
        via ``PATH``.
    """
    local = Path.home() / ".local/bin/codex-agent-tracker"
    if local.is_file():
        return local
    return Path("codex-agent-tracker")


def run_tracker(args: list[str]) -> bool:
    """Run ``codex-agent-tracker`` with ``args`` and suppress hook output.

    Args:
        args: Argument vector appended after the tracker executable path.

    Returns:
        bool: ``True`` if the tracker exited with status 0, ``False`` if it
        exited non-zero or could not be launched.
    """
    try:
        result = subprocess.run(
            [str(tracker_path()), *args],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        log.error(f"tracker launch failed: {exc}", component=LOG_COMPONENT)
        return False
    if result.returncode != 0:
        log.warn(
            f"tracker exited {result.returncode} for args {args[:1]}",
            component=LOG_COMPONENT,
        )
        return False
    log.debug(f"tracker ok for args {args[:1]}", component=LOG_COMPONENT)
    return True


def parse_payload(argv: list[str], stdin_text: str | None = None) -> dict[str, Any]:
    """Parse a Codex argv payload or Claude stdin payload.

    Args:
        argv: Process argument vector; ``argv[1]`` is treated as a Codex JSON
            payload when present and non-blank.
        stdin_text: Optional pre-read stdin contents (used by tests). When
            ``None`` and no argv payload is present, stdin is read directly.

    Returns:
        dict[str, Any]: The decoded JSON object, or an empty dict when no
        payload is present or the payload is not a JSON object.
    """
    raw = argv[1] if len(argv) > 1 and argv[1].strip() else stdin_text
    if raw is None:
        try:
            raw = sys.stdin.read()
        except Exception as exc:
            log.error(f"stdin read failed: {exc}", component=LOG_COMPONENT)
            raw = ""
    raw = raw.strip()
    if not raw:
        log.debug("empty payload", component=LOG_COMPONENT)
        return {}
    try:
        payload = json.loads(raw)
    except ValueError:
        log.warn(f"invalid payload {raw[:120]!r}", component=LOG_COMPONENT)
        return {}
    return payload if isinstance(payload, dict) else {}


def normalize_text(value: str) -> str:
    """Collapse repeated whitespace for spoken labels.

    Args:
        value: Raw text to normalize; ``None``-like falsy values are treated as
            an empty string.

    Returns:
        str: ``value`` with runs of whitespace collapsed to single spaces and
        leading/trailing whitespace removed.
    """
    return " ".join((value or "").split())


def workspace_path_from(payload: dict[str, Any]) -> str:
    """Resolve the primary workspace path from Claude/Codex or Cline payloads."""
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        return cwd
    roots = payload.get("workspaceRoots")
    if isinstance(roots, list) and roots and isinstance(roots[0], str):
        return roots[0]
    return ""


def project_name_from(payload: dict[str, Any]) -> str:
    """Resolve a human project name from environment metadata or cwd.

    Resolution order: ``CODEX_AGENT_PROJECT_NAME`` env var, then the basename of
    ``CODEX_AGENT_PROJECT_PATH`` or the payload ``cwd``.

    Args:
        payload: Decoded hook payload; its ``cwd`` field is used as a fallback.

    Returns:
        str: The resolved project name, or an empty string when none can be
        determined.
    """
    name = normalize_text(os.environ.get("CODEX_AGENT_PROJECT_NAME", ""))
    if name:
        return name
    project_path = os.environ.get("CODEX_AGENT_PROJECT_PATH", "")
    path = project_path or workspace_path_from(payload)
    if path:
        resolved = Path(path).expanduser()
        return resolved.name or str(resolved)
    return ""


def runtime_kind(default_label: str, label: str) -> str:
    """Resolve the agent kind for payload formats shared by multiple runtimes."""
    explicit = normalize_text(os.environ.get("CODEX_AGENT_KIND", "")).casefold()
    if explicit in {"api", "claude", "cline", "codex", "grok", "qwen"}:
        return explicit
    normalized_label = normalize_text(label).casefold()
    if normalized_label.startswith(("local", "qwen")):
        return "qwen"
    for kind in ("claude", "cline", "codex", "grok", "api"):
        if normalized_label.startswith(kind):
            return kind
    return default_label if default_label in {"claude", "cline", "codex", "grok"} else "codex"


def voice_for_kind(kind: str) -> str:
    """Resolve the runtime's TTS voice, always returning a concrete default.

    Delegates to the ``agent-tts`` engine — the single owner of voice selection
    (see the repository README) — so the same env precedence *and* the per-kind
    Kokoro default (e.g. claude -> ``af_sky``) apply whether an agent is launched
    through the ACC ``cca`` wrapper, which exports ``CODEX__TTS_VOICE``, or the
    bare ``claude`` binary, which exports nothing.

    Returning a concrete voice rather than an empty string is what keeps the
    bare-binary path on Kokoro: ``engine.speak_with_kokoro`` bails on a falsy
    voice and the announcement silently drops to the robotic desktop synthesizer
    fallback. Before this delegation the hook passed ``--voice ""`` whenever no
    voice env var was set, so plain ``claude`` spoke the desktop fallback voice
    while ``cca`` spoke the real ``af_sky`` Kokoro voice.
    """
    return tts_engine.voice_for_kind(kind, os.environ)


def context_for(payload: dict[str, Any], default_label: str) -> RuntimeContext:
    """Build runtime context from payload and environment.

    Args:
        payload: Decoded hook payload; its ``cwd`` field contributes to the
            resolved project path and name.
        default_label: Label to use when ``CODEX_AGENT_LABEL`` is unset. The
            effective label or explicit ``CODEX_AGENT_KIND`` selects runtime
            voice variables and the default config home.

    Returns:
        RuntimeContext: Fully resolved, immutable context for the event.
    """
    project_path = os.environ.get("CODEX_AGENT_PROJECT_PATH", "")
    cwd = workspace_path_from(payload)
    label = normalize_text(os.environ.get("CODEX_AGENT_LABEL", "")) or default_label
    kind = runtime_kind(default_label, label)
    voice = voice_for_kind(kind)
    default_home = Path.home() / {
        "claude": ".claude",
        "qwen": ".codex-qwen",
        "api": ".codex-api",
        "cline": ".cline",
        "grok": ".grok",
    }.get(kind, ".codex")
    codex_home = Path(os.environ.get("CODEX_HOME") or default_home)
    model_name = normalize_text(
        os.environ.get("CODEX_AGENT_LMSTUDIO_MODEL", "")
        or (os.environ.get("QWEN_CODEX_LMSTUDIO_MODEL", "") if kind == "qwen" else "")
    )
    return RuntimeContext(
        label=label,
        project_name=project_name_from(payload),
        project_path=project_path or cwd,
        voice=voice,
        codex_home=codex_home.expanduser(),
        model_name=model_name,
    )


def announce(
    event: str,
    context: RuntimeContext,
    task_description: str = "",
    feature_key: str = "",
) -> bool:
    """Ask the tracker to speak a start or finish announcement.

    Args:
        event: Announcement event keyword, typically ``"start"`` or ``"finish"``.
        context: Resolved runtime context supplying label, project, and voice.
        task_description: Optional task summary spoken on finish; omitted when
            empty.
        feature_key: Stable runtime session id used to isolate the title/finish
            label cache from concurrent sessions in the same project.

    Returns:
        bool: ``True`` when the tracker reported success, ``False`` otherwise.
    """
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
    if feature_key:
        args.extend(["--feature-key", feature_key])
    if task_description:
        args.extend(["--task-description", task_description])
    return run_tracker(args)


def clarify(context: RuntimeContext, question: str) -> bool:
    """Ask the tracker to speak a clarification or attention prompt.

    Args:
        context: Resolved runtime context supplying label and project metadata.
        question: The text to speak as the attention/clarification prompt.

    Returns:
        bool: ``True`` when the tracker reported success, ``False`` otherwise.
    """
    voice = os.environ.get("CLAUDE_CLARIFY_VOICE", "").strip() or DEFAULT_CLARIFY_VOICE
    return run_tracker(
        [
            "clarify",
            "--question",
            question,
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


def update_title(prompt: str, context: RuntimeContext, feature_key: str = "") -> bool:
    """Ask the tracker to update the terminal title for a submitted prompt.

    Args:
        prompt: The submitted user prompt; whitespace is normalized before use.
        context: Resolved runtime context supplying the project path and home.
        feature_key: Stable runtime session id used to isolate this title label
            from concurrent sessions in the same project.

    Returns:
        bool: ``True`` when the tracker reported success, ``False`` otherwise.
    """
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
    if feature_key:
        args.extend(["--feature-key", feature_key])
    if kitty_window_id:
        args.extend(["--kitty-window-id", kitty_window_id])
    if terminal_device:
        args.extend(["--terminal-device", terminal_device])
    return run_tracker(args)


def notify_turn_complete(status: int = 0) -> bool:
    """Tell the tracker that a directly tracked Codex turn completed.

    Args:
        status: Exit status of the completed turn; ``0`` indicates success.

    Returns:
        bool: ``True`` when the tracker reported success. ``False`` when no
        ``CODEX_AGENT_RUN_ID`` token is set (nothing to report) or the tracker
        failed.
    """
    token = os.environ.get("CODEX_AGENT_RUN_ID", "")
    if not token:
        log.debug("no run token; skipping turn-complete", component=LOG_COMPONENT)
        return False
    return run_tracker(["turn-complete", "--status", str(status), "--token", token])


def transcript_prompt(transcript_path: str) -> str:
    """Return the latest real user prompt from a Claude transcript JSONL.

    Scans the transcript from the end, skipping sidechain entries, tool-result
    turns, and synthetic messages that begin with ``<``.

    Args:
        transcript_path: Filesystem path to the Claude transcript ``.jsonl``
            file. An empty string yields an empty result.

    Returns:
        str: The most recent genuine user prompt text, or an empty string when
        none is found or the file cannot be read.
    """
    if not transcript_path:
        return ""
    try:
        lines = Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError) as exc:
        log.warn(f"transcript read failed: {exc}", component=LOG_COMPONENT)
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


def handle_codex(payload: dict[str, Any]) -> int:
    """Handle Codex notify payloads.

    Args:
        payload: Decoded Codex notify JSON object.

    Returns:
        int: Always ``0`` (hook exit code; notify hooks never fail the run).
    """
    event_type = payload.get("type")
    context = context_for(payload, "codex")
    log.info(
        f"{context.label} type={event_type} cwd={payload.get('cwd')}",
        component=LOG_COMPONENT,
    )
    if event_type == "agent-turn-complete":
        notify_turn_complete(int(payload.get("status", 0) or 0))
    return 0


def handle_claude(payload: dict[str, Any]) -> int:
    """Handle Claude Code hook payloads.

    Routes the ``hook_event_name`` to the matching tracker action: session
    start/finish announcements, terminal title updates, and attention prompts.

    Args:
        payload: Decoded Claude Code hook JSON object.

    Returns:
        int: Always ``0`` (hook exit code; notify hooks never fail the run).
    """
    event = payload.get("hook_event_name", "")
    context = context_for(payload, "claude")
    feature_key = normalize_text(str(payload.get("session_id", "")))
    log.info(
        f"Claude event={event} project={context.project_name} "
        f"session_scoped={bool(feature_key)} cwd={payload.get('cwd')}",
        component=LOG_COMPONENT,
    )

    if lifecycle_is_tracker_managed() and event in {"SessionStart", "Stop", "SubagentStop"}:
        log.debug(f"skip tracker-managed Claude lifecycle event={event}", component=LOG_COMPONENT)
        return 0

    if event == "SessionStart":
        # Claude Code re-fires SessionStart on resume/compact/clear, not just for
        # a genuinely new session. Announcing on those replays the "started"
        # chime minutes after the real start (and again after every context
        # compaction), so only a true startup is announced.
        source = str(payload.get("source", "startup"))
        if source == "startup":
            announce("start", context, feature_key=feature_key)
        else:
            log.debug(f"skip start announce for source={source}", component=LOG_COMPONENT)
    elif event in {"Stop", "SubagentStop"}:
        task = transcript_prompt(str(payload.get("transcript_path", "")))
        announce("finish", context, task_description=task, feature_key=feature_key)
    elif event == "UserPromptSubmit":
        update_title(str(payload.get("prompt", "")), context, feature_key=feature_key)
    elif event in {"Notification", "PermissionRequest"}:
        raw_message = normalize_text(str(payload.get("message", "")))
        # Claude fires a Notification both for genuine attention (permission
        # requests) and for the idle "waiting for your input" timeout that recurs
        # after a turn has already finished. Suppress the idle variant so the
        # attention prompt only speaks when there is actually something to ask.
        if event == "Notification" and IDLE_NOTIFICATION_MARKER in raw_message.casefold():
            log.debug(
                f"skip clarify for idle notification: {raw_message!r}",
                component=LOG_COMPONENT,
            )
            return 0
        default_message = f"{context.label.capitalize()} needs your attention"
        clarify(context, raw_message or default_message)
    return 0


def handle_cline(payload: dict[str, Any]) -> int:
    """Route documented and current Cline lifecycle payloads to the tracker.

    Cline has no dedicated "needs attention" event like Claude's Notification,
    so the ``PreToolUse`` (``tool_call``) hook is used instead: when Cline calls
    its ``ask_question`` tool, an attention prompt is spoken, matching the
    clarification behavior of Claude and Codex. Every other tool call is silent.

    Args:
        payload: Cline hook JSON. Public releases use event filenames such as
            ``TaskStart`` while Cline 3.x payloads use ``agent_start`` names.

    Returns:
        int: Always ``0`` so TTS cannot block a Cline task.
    """
    event = str(payload.get("hookName", ""))
    context = context_for(payload, "cline")
    log.info(
        f"Cline event={event} project={context.project_name}",
        component=LOG_COMPONENT,
    )
    lifecycle_events = {
        "TaskStart",
        "TaskResume",
        "agent_start",
        "agent_resume",
        "TaskComplete",
        "TaskCancel",
        "TaskError",
        "agent_end",
        "agent_abort",
        "agent_error",
    }
    if lifecycle_is_tracker_managed() and event in lifecycle_events:
        log.debug(f"skip tracker-managed Cline lifecycle event={event}", component=LOG_COMPONENT)
        return 0
    if event in {"TaskStart", "TaskResume", "agent_start", "agent_resume"}:
        announce("start", context)
    elif event in {
        "TaskComplete",
        "TaskCancel",
        "TaskError",
        "agent_end",
        "agent_abort",
        "agent_error",
    }:
        section = (
            payload.get("taskComplete")
            or payload.get("taskCancel")
            or payload.get("taskError")
            or {}
        )
        task = normalize_text(str(section.get("task", ""))) if isinstance(section, dict) else ""
        announce("finish", context, task_description=task)
    elif event in {"UserPromptSubmit", "prompt_submit"}:
        section = payload.get("userPromptSubmit") or {}
        prompt = str(section.get("prompt", "")) if isinstance(section, dict) else ""
        update_title(prompt, context)
    elif event in {"PreToolUse", "tool_call"}:
        # PreToolUse fires before every tool call. Only the ask_question tool
        # pauses for user input, so speak an attention prompt for it and stay
        # silent for routine tool execution (the bash hook guard skips the
        # Python process entirely for non-attention tools).
        tool_call = payload.get("tool_call") or {}
        if not isinstance(tool_call, dict):
            return 0
        if str(tool_call.get("name", "")) != "ask_question":
            return 0
        tool_input = tool_call.get("input") or {}
        question = normalize_text(
            str(tool_input.get("question", "")) if isinstance(tool_input, dict) else ""
        )
        default_message = f"{context.label.capitalize()} needs your attention"
        clarify(context, question or default_message)
    return 0


#: Grok notification-hook events that mean "the agent finished working".
GROK_FINISH_EVENTS = {"turn_complete", "task_complete", "agent_error"}


def handle_grok(environ: dict[str, str] | None = None) -> int:
    """Route a Grok notification hook to the matching tracker action.

    Grok's ``[[ui.notifications.hooks]]`` contract passes no stdin payload;
    the event arrives as the ``GROK_EVENT``, ``GROK_MESSAGE``, and
    ``GROK_SESSION_ID`` environment variables (see the Grok CLI configuration
    guide). The hook runs in the session's working directory, so ``os.getcwd``
    supplies the project path.

    Args:
        environ: Environment mapping to read; defaults to ``os.environ``.

    Returns:
        int: Always ``0`` so TTS can never fail a Grok turn.
    """
    env = os.environ if environ is None else environ
    event = normalize_text(env.get("GROK_EVENT", "")).casefold()
    message = normalize_text(env.get("GROK_MESSAGE", ""))
    session_id = normalize_text(env.get("GROK_SESSION_ID", ""))
    try:
        cwd = os.getcwd()
    except OSError:
        cwd = ""
    context = context_for({"cwd": cwd}, "grok")
    log.info(
        f"Grok event={event} project={context.project_name} "
        f"session_scoped={bool(session_id)} cwd={cwd}",
        component=LOG_COMPONENT,
    )
    if lifecycle_is_tracker_managed() and event in {"session_ready", *GROK_FINISH_EVENTS}:
        log.debug(f"skip tracker-managed Grok lifecycle event={event}", component=LOG_COMPONENT)
        return 0
    if event == "session_ready":
        announce("start", context, feature_key=session_id)
    elif event in GROK_FINISH_EVENTS:
        announce("finish", context, feature_key=session_id)
    elif event == "approval_required":
        default_message = f"{context.label.capitalize()} needs your attention"
        clarify(context, message or default_message)
    else:
        log.debug(f"ignoring unmapped Grok event {event!r}", component=LOG_COMPONENT)
    return 0


def main(argv: list[str] | None = None, stdin_text: str | None = None) -> int:
    """CLI entry point for both Codex and Claude hook styles.

    Args:
        argv: Process argument vector; defaults to ``sys.argv`` when ``None``.
        stdin_text: Optional pre-read stdin contents (used by tests); ``None``
            reads stdin on demand.

    Returns:
        int: Process exit code, always ``0`` so a hook never fails the agent run.
    """
    argv = argv if argv is not None else sys.argv
    if announcements_suppressed():
        log.debug(
            "skip hook: ATTS_SUPPRESS_ANNOUNCEMENTS is set", component=LOG_COMPONENT
        )
        return 0
    if "--grok" in argv[1:]:
        return handle_grok()
    payload = parse_payload(argv, stdin_text=stdin_text)
    if not payload:
        return 0
    if "hookName" in payload:
        return handle_cline(payload)
    if "hook_event_name" in payload:
        return handle_claude(payload)
    return handle_codex(payload)
