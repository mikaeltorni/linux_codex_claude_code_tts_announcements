# Linux Codex/Claude Code TTS Announcements

> Part of [installation_scripts](https://github.com/mikaeltorni/installation_scripts) — the standalone **`agent-tts`** text-to-speech engine and notify hooks for **Codex**, **Claude Code**, **Cline**, **Grok**, **Qwen**, **OpenRouter**, and **NVIDIA** agents. Tested on Ubuntu 24.04.4 LTS; the Python engine is largely portable but the audio playback backend is currently Linux-specific (Windows/macOS untested).

The agent text-to-speech home for the supported coding agents on Linux. This
repository ships two things:

1. **`agent-tts`** — the standalone speech engine that owns *all* agent TTS:
   Kokoro synthesis, ffmpeg volume amplification, playback, voice selection, the
   speed/volume/silent tunables, and the spoken start/finish/clarify wording.
2. **Notify hooks** — Codex, Claude Code, Cline, and Grok hooks that turn agent lifecycle
   events into spoken start/finish/attention/danger announcements.

## Repository dependencies

This repository has two layers with different dependencies:

- **The `agent-tts` engine is fully standalone.** It owns its tunables under the
  `ATTS_` ("agent TTS") environment namespace and a dedicated state directory,
  and has no dependency on Agent Command Center. The previous Agent Command
  Center names (`AGENT_COMMAND_CENTER_TTS_SPEED`, `..._VOLUME_PERCENT`,
  `ACC_SILENT`, `CODEX__TTS_VOICE`, `CLAUDE_TTS_VOICE`,
  `CODEX_AGENT_TRACKER_NO_AUDIO`) are still honored as fallbacks.
- **The notify hooks delegate orchestration to `codex-agent-tracker`** (Agent
  Command Center) for start/finish/attention announcements, so that the spoken
  finish label is summarized once and shared with the terminal title. Claude
  hooks forward the runtime session id so concurrent sessions in one project
  cannot reuse each other's title/finish labels. When the tracker is absent the
  hooks simply do nothing; nothing here *requires* ACC to build or install.
- **Build-time (soft):** the shared installer component framework
  [`linux_installation_scripts_functions`](https://github.com/mikaeltorni/linux_installation_scripts_functions) —
  loaded from a sibling checkout when present. A standalone private checkout
  uses existing Git credentials to clone it non-interactively under the user
  cache; public deployments can still download it from a raw mirror. Override
  those sources with `ISC_FUNCTIONS_GIT_URL` or `ISC_FUNCTIONS_RAW`.

Agent Command Center delegates all speech to this repository's `agent-tts`
engine and installs it through its recommended (default-on) `tts_announcements`
component: the master setup chain clones this repository first and Agent Command
Center then configures the engine, voice categories, and hooks as part of its
own install. Installing this repository on its own works too — its `install.sh`
sets up the engine and hooks independently.

See the full cross-repository map in
[installation_scripts/DEPENDENCIES.md](https://github.com/mikaeltorni/installation_scripts/blob/master/DEPENDENCIES.md).

## What it does

Spoken model prefixes use **Luna**, **Terra**, **Sol**, and **Astra** without
GPT or version numbers, including announcements from already-running sessions.
Earlier models retain their full names, such as **GPT 5 point 5**.

When installed, this repo:

- installs the `agent-tts` speech engine and links `~/.local/bin/agent-tts`
- installs a hash-locked ONNX Runtime CUDA target when an NVIDIA GPU and `uv`
  are available; CPU synthesis remains the fallback
- copies hook code to `$HOME/.local/share/codex-claude-tts-announcements/`
- adds Codex `UserPromptSubmit` and `Stop` lifecycle hooks to the primary
  `$HOME/.codex` home and every existing `$HOME/.codex-account-N` home
- runs Codex `Stop` speech as a background hook and detaches again inside the
  notifier, so completion audio cannot hold up either new sessions or sessions
  that cached an older foreground hook definition
- removes the retired response-level Codex `notify = [...]` callback from each
  corresponding `config.toml`
- adds a Codex `PermissionRequest` attention hook to every managed Codex home
- adds generated Claude Code hook commands to `$HOME/.claude/settings.json`
- adds executable Cline lifecycle hooks under `$HOME/.cline/hooks/`
- removes the retired Agent Command Center `notify_agent.py` hook entries

It does not replace or symlink the `codex` or `claude` binaries.

## The `agent-tts` engine

```bash
agent-tts voice --text "hello" --voice af_sky   # speak a literal line
agent-tts speed 1.5                              # read/set the speed multiplier
agent-tts volume 1000                            # read/set the volume percentage
agent-tts silent toggle                          # mute/unmute all announcements
```

Detached agents can finish simultaneously. Cache generation is locked per
utterance and published atomically, so identical requests share one complete
WAV instead of racing over a partial file. Playback (including the desktop
fallback synthesizers) is serialized across processes so announcements do not
overlap or break the PipeWire/PulseAudio connection. Identical requests that
arrive within one 30-second burst are coalesced at that shared playback boundary,
so competing detached hooks cannot turn the lock into a queue that repeats the
same clip; a later turn can still repeat the wording normally. Direct `voice`,
`announce`, and `clarify` commands return nonzero when neither Kokoro nor a
fallback can handle the message. Kokoro calls time out instead of holding a
cache lock forever, and later runs remove abandoned temporary work directories
after their safe age threshold.

Tunables (env overrides win over the persisted values):

- `ATTS_SPEED` — speech speed multiplier (default `1.5`).
- `ATTS_VOLUME_PERCENT` — linear volume percentage (default `1000`).
- `ATTS_SILENT` — set truthy to mute one invocation.
- `ATTS_SUPPRESS_ANNOUNCEMENTS` — set truthy in a CLI's environment to make
  every notification hook and direct `agent-tts announce`/`clarify` call of
  that process exit silently. Used by monitoring surfaces and informational
  CLI probes that are not human-driven agent sessions, whose lifecycle hooks
  would otherwise announce fake starts and finishes.
- `ATTS_VOICE` — global voice override.
- `ATTS_CODEX_VOICE`, `ATTS_CLAUDE_VOICE`, `ATTS_CLINE_VOICE`,
  `ATTS_GROK_VOICE`, `ATTS_QWEN_VOICE`, `ATTS_OPENROUTER_VOICE`, and
  `ATTS_NVIDIA_VOICE` —
  per-runtime overrides when `ATTS_VOICE` is unset. Legacy
  `CODEX_TTS_VOICE`, `CLAUDE_TTS_VOICE`, `GROK_TTS_VOICE`, and
  `QWEN_CODEX_TTS_VOICE`, plus `OPENROUTER_CODEX_TTS_VOICE` and
  `NVIDIA_CODEX_TTS_VOICE`, remain supported. ACC wrappers' normalized
  `CODEX__TTS_VOICE` remains a fallback for Codex, Claude, Qwen, and Cline.
- Default Kokoro voices per runtime (when no override is set): codex `af_bella`,
  claude `af_sky`, qwen/Local `af_heart`, cline `af_aoede`, grok `af_kore`,
  OpenRouter `af_jessica`, and NVIDIA `af_sarah` (all distinct). Grok,
  OpenRouter, and NVIDIA ignore a generic shell-wide `CODEX__TTS_VOICE` so a
  stale Local/Qwen export cannot override their reserved per-runtime voices.
- `ATTS_MODEL_DIR` — optional shared Kokoro model directory. Cline and Claude
  automatically reuse `~/.codex/tts` when their own config homes have no model
  assets, avoiding duplicate downloads and robotic fallback speech.
- `ATTS_DEVICE` — `auto` (default), `cuda`/`gpu`, or `cpu`. Auto mode uses the
  installed CUDA runtime only when at least 1024 MiB of VRAM is free. A CUDA
  synthesis error is logged and retried once on CPU.
- `ATTS_GPU_MIN_FREE_MIB` — change the auto-mode free-VRAM guard (default
  `1024`). `ATTS_GPU_RUNTIME_DIR` overrides the installer-managed runtime path.
  Note: because every announcement is a fresh `uvx`/ONNX subprocess, a
  one-sentence clip is dominated by cold process and model-load startup (~6 s),
  not inference — CUDA does not make short announcements meaningfully faster. GPU
  mainly helps longer text; the boot prewarm below is what removes the first-run
  stall.

### Boot prewarm (`boot_prewarm` component)

The `boot_prewarm` component installs a `systemd --user` oneshot,
`agent-tts-prewarm.service` (`WantedBy=default.target`), that runs one silent
`agent-tts prewarm` at login. This warms the `uvx` environment, the ONNX model,
and the OS page cache before the first agent turn speaks, so the first
announcement no longer pays the cold ~6 s startup on the critical path.
Warming is best-effort (`Nice=10`, no audio, always exits 0) and never stalls
the session. Run `agent-tts prewarm` by hand to warm the current shell.
- `ATTS_ANNOUNCE_WORKSPACE=0` — disable the spoken workspace suffix. On
  desktops where every `xprop` workspace probe fails (e.g. GNOME on
  Wayland without usable EWMH properties), probing automatically backs off
  for 5 minutes after a fully-failed attempt instead of re-running failing
  probes — and logging their failures — on every announcement.
- `ATTS_ANNOUNCE_START`, `ATTS_ANNOUNCE_FINISH`, and
  `ATTS_ANNOUNCE_ATTENTION` — override the independently installed lifecycle
  categories. Their persisted values live in
  `~/.config/agent-tts/announcements.env`.
- `ATTS_EVENT_CONFIG_FILE` — override that persisted event-settings path.
- `ATTS_NO_AUDIO` — when truthy, generate/cache clips but never play (used by
  tests); an explicit false value such as `0` leaves playback enabled.
- `ATTS_STATE_DIR` — override the engine state/cache directory.
- `ATTS_LOG_DIR` — override where `agent-tts` writes `voice.log`.

## Logging

Python diagnostics are routed through `lib/tts_announcements/logging_utils.py`.
By default, source-checkout logs are written under this repository's `.log/`
directory, while installed integrations can override the sink with
`ATTS_LOG_DIR` or `AGENT_COMMAND_CENTER_LOG_DIR`. The Bash installer mirrors its
status messages to `install.log` under `TTS_LOG_DIR` or the repository `.log/`
directory without changing its stdout output.

Free text forwarded to `codex-agent-tracker` on its command line (prompts,
task descriptions, attention questions) is whitespace-normalized and clipped
to 600 characters before exec: these strings only feed spoken announcements
and terminal titles, and unbounded text previously aborted the launch with
`[Errno 7] Argument list too long`, silently dropping the announcement.

## Prerequisites

- The Kokoro model assets under `<codex-home>/tts` (installed by Agent Command
  Center's LM Studio component) and `uvx` for synthesis; `ffmpeg` for volume.
- Optional GPU synthesis needs an NVIDIA GPU and `uv`. The installer places the
  CUDA 12/cuDNN runtime under
  `~/.local/share/codex-claude-tts-announcements/gpu-runtime`; set
  `ATTS_INSTALL_GPU_RUNTIME=0` while installing to keep a CPU-only setup.
- For the notify hooks: `codex-agent-tracker` (Agent Command Center).

## Installation

```bash
bash install.sh              # interactive component menu (or default-on set)
bash install.sh --default    # install all default-on components, no prompts
bash install.sh --all        # install every component
bash install.sh --list-components
bash install.sh --select engine,claude_stop   # install exactly these
```

GPU Python dependencies are pinned in `uv.lock` and exported with hashes in
`requirements-gpu.txt`. The project-level `exclude-newer = "24 hours"` policy
prevents newly published dependency releases from entering a regenerated lock;
plain `pip install <package>` is not a supported installation path.

### Selectable components

Every individual notify hook is its own optional, default-on component, so you
can wire up exactly the runtimes and lifecycle events you use. The `engine` and
`hook_files` core stay default-on, and **each hook component also self-installs
that core**, so the program works no matter which subset you pick.

| Component | What it installs |
|---|---|
| `engine` | `agent-tts` speech engine + `~/.local/bin/agent-tts` symlink |
| `hook_files` | notify hook code under `~/.local/share/codex-claude-tts-announcements/` |
| `boot_prewarm` | login-time `agent-tts-prewarm.service` user unit |
| `start_voice` | enable start announcements for every runtime |
| `finish_voice` | enable end announcements for every runtime |
| `attention_voice` | enable ask-for-further-changes / needs-input announcements |
| `codex_notify` | Codex `UserPromptSubmit` start and `Stop` finish hooks in primary and numbered account homes (detached from slow synthesis/title work, with legacy `notify` migration) |
| `codex_attention` | Codex `PermissionRequest` attention hook in primary and numbered account homes |
| `grok_notify` | Grok `[[ui.notifications.hooks]]` lifecycle block in `~/.grok/config.toml` (start/finish/attention via `$GROK_EVENT`) |
| `claude_session_start` | Claude Code `SessionStart` hook |
| `claude_stop` | Claude Code `Stop` hook |
| `claude_subagent_stop` | Claude Code `SubagentStop` hook |
| `claude_user_prompt` | Claude Code `UserPromptSubmit` hook |
| `claude_notification` | Claude Code `Notification` hook |
| `cline_task_start` | Cline `TaskStart` hook |
| `cline_task_resume` | Cline `TaskResume` hook |
| `cline_task_complete` | Cline `TaskComplete` hook |
| `cline_task_cancel` | Cline `TaskCancel` hook |
| `cline_task_error` | Cline `TaskError` hook (supported by current CLI releases) |
| `cline_user_prompt` | Cline `UserPromptSubmit` hook |
| `cline_pre_tool_use` | Cline `PreToolUse` hook — speaks an attention prompt when Cline calls `ask_question` |

The Claude and Codex hook writers are idempotent and preserve unrelated
user-authored hooks; reruns also remove the retired Agent Command Center
`notify_agent.py` hook entries. None of these replace or symlink the `codex` or
`claude` binaries.

## Integration with Agent Command Center

The master `installation_scripts/install.sh` exposes this repository directly.
For backward-compatible standalone ACC installs,
`AGENT_COMMAND_CENTER_INSTALL_TTS_ANNOUNCEMENTS=1` still delegates to this
installer.

## Detect, reconfigure, and uninstall

This installer tracks what it has installed and can re-apply or remove it, so you
can refresh configuration after a repo update or cleanly back a feature out.

```bash
bash install.sh --detect            # show each component as installed|absent
bash install.sh --reconfigure a,b   # re-apply (idempotent) these component ids
bash install.sh --uninstall a,b     # uninstall these component ids
```

In the interactive menu (run `bash install.sh` on a terminal, or via the master
installer), already-installed components show a green `✓`. Select one with
**space** to **reconfigure** it (`~`), press **`u`** to mark it for **uninstall**
(`✗`), or press **`r`** to reconfigure every installed component at once. Detection
uses a live check where deterministic and otherwise an install receipt under
`${XDG_STATE_HOME:-~/.local/state}/isc/receipts/`; a component without a reversal
step simply clears that receipt on uninstall.

## Disclaimer

This software is provided under the MIT License on an **“as is”** basis, without warranties of any kind. To the maximum extent permitted by applicable law, the authors and copyright holders shall not be liable for any claims, damages, losses, or other liability arising from the use of this software.

You are solely responsible for determining whether this software is suitable, safe, lawful, and appropriate for your intended use. Unless explicitly stated otherwise, this project is general-purpose software and is not designed, tested, certified, or approved for safety-critical, medical, automotive, aviation, industrial-control, life-support, cybersecurity-critical, financial-critical, or other high-risk use cases.

The authors and copyright holders make no guarantees regarding security, reliability, availability, correctness, compliance, non-infringement, or fitness for any particular purpose.

This notice is intended to clarify the nature of the project and does not impose additional restrictions beyond the MIT License.
