# Linux Codex/Claude Code TTS Announcements

> Part of [installation_scripts](https://github.com/mikaeltorni/installation_scripts) — the standalone **`agent-tts`** text-to-speech engine and notify hooks for **Codex**, **Claude Code**, and **Qwen** agents. Tested on Ubuntu 24.04.4 LTS; the Python engine is largely portable but the audio playback backend is currently Linux-specific (Windows/macOS untested).

The agent text-to-speech home for Codex, Claude Code, and Qwen on Linux. This
repository ships two things:

1. **`agent-tts`** — the standalone speech engine that owns *all* agent TTS:
   Kokoro synthesis, ffmpeg volume amplification, playback, voice selection, the
   speed/volume/silent tunables, and the spoken start/finish/clarify wording.
2. **Notify hooks** — Codex and Claude Code hooks that turn agent lifecycle
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
  finish label is summarized once and shared with the terminal title. When the
  tracker is absent the hooks simply do nothing; nothing here *requires* ACC to
  build or install.
- **Build-time (soft):** the shared installer component framework
  [`linux_installation_scripts_functions`](https://github.com/mikaeltorni/linux_installation_scripts_functions) —
  loaded from a sibling checkout when present, otherwise downloaded on demand.

Agent Command Center delegates all speech to this repository's `agent-tts`
engine, so in the desktop setup chain ACC installs this repository through its
recommended (default-on) `tts_announcements` component.

See the full cross-repository map in
[installation_scripts/DEPENDENCIES.md](https://github.com/mikaeltorni/installation_scripts/blob/master/DEPENDENCIES.md).

## What it does

When installed, this repo:

- installs the `agent-tts` speech engine and links `~/.local/bin/agent-tts`
- copies hook code to `$HOME/.local/share/codex-claude-tts-announcements/`
- writes a generated Codex `notify = [...]` block in `$HOME/.codex/config.toml`
- adds a Codex `PermissionRequest` attention hook to `$HOME/.codex/hooks.json`
- adds generated Claude Code hook commands to `$HOME/.claude/settings.json`
- removes the retired Agent Command Center `notify_agent.py` hook entries

It does not replace or symlink the `codex` or `claude` binaries.

## The `agent-tts` engine

```bash
agent-tts voice --text "hello" --voice af_sky   # speak a literal line
agent-tts speed 1.5                              # read/set the speed multiplier
agent-tts volume 1000                            # read/set the volume percentage
agent-tts silent toggle                          # mute/unmute all announcements
```

Tunables (env overrides win over the persisted values):

- `ATTS_SPEED` — speech speed multiplier (default `1.5`).
- `ATTS_VOLUME_PERCENT` — linear volume percentage (default `1000`).
- `ATTS_SILENT` — set truthy to mute one invocation.
- `ATTS_VOICE` — global voice override.
- `ATTS_CODEX_VOICE`, `ATTS_CLAUDE_VOICE`, and `ATTS_QWEN_VOICE` —
  per-runtime overrides when `ATTS_VOICE` is unset. Legacy
  `CODEX_TTS_VOICE`, `CLAUDE_TTS_VOICE`, and `QWEN_CODEX_TTS_VOICE` remain
  supported. ACC wrappers' normalized `CODEX__TTS_VOICE` also remains
  supported and takes precedence over per-runtime legacy names.
- `ATTS_ANNOUNCE_WORKSPACE=0` — disable the spoken workspace suffix.
- `ATTS_NO_AUDIO` — generate/cache clips but never play (used by tests).
- `ATTS_STATE_DIR` — override the engine state/cache directory.
- `ATTS_LOG_DIR` — override where `agent-tts` writes `voice.log`.

## Logging

Python diagnostics are routed through `lib/tts_announcements/logging_utils.py`.
By default, source-checkout logs are written under this repository's `.log/`
directory, while installed integrations can override the sink with
`ATTS_LOG_DIR` or `AGENT_COMMAND_CENTER_LOG_DIR`. The Bash installer mirrors its
status messages to `install.log` under `TTS_LOG_DIR` or the repository `.log/`
directory without changing its stdout output.

## Prerequisites

- The Kokoro model assets under `<codex-home>/tts` (installed by Agent Command
  Center's LM Studio component) and `uvx` for synthesis; `ffmpeg` for volume.
- For the notify hooks: `codex-agent-tracker` (Agent Command Center).

## Installation

```bash
bash install.sh              # interactive component menu (or default-on set)
bash install.sh --default    # install all default-on components, no prompts
bash install.sh --all        # install every component
bash install.sh --list-components
bash install.sh --select engine,claude_stop   # install exactly these
```

### Selectable components

Every individual notify hook is its own optional, default-on component, so you
can wire up exactly the runtimes and lifecycle events you use. The `engine` and
`hook_files` core stay default-on, and **each hook component also self-installs
that core**, so the program works no matter which subset you pick.

| Component | What it installs |
|---|---|
| `engine` | `agent-tts` speech engine + `~/.local/bin/agent-tts` symlink |
| `hook_files` | notify hook code under `~/.local/share/codex-claude-tts-announcements/` |
| `codex_notify` | Codex lifecycle `notify = [...]` block in `~/.codex/config.toml` |
| `codex_attention` | Codex `PermissionRequest` attention hook in `~/.codex/hooks.json` |
| `claude_session_start` | Claude Code `SessionStart` hook |
| `claude_stop` | Claude Code `Stop` hook |
| `claude_subagent_stop` | Claude Code `SubagentStop` hook |
| `claude_user_prompt` | Claude Code `UserPromptSubmit` hook |
| `claude_notification` | Claude Code `Notification` hook |

The Claude and Codex hook writers are idempotent and preserve unrelated
user-authored hooks; reruns also remove the retired Agent Command Center
`notify_agent.py` hook entries. None of these replace or symlink the `codex` or
`claude` binaries.

## Integration with Agent Command Center

The Agent Command Center repository can clone and run this installer when `AGENT_COMMAND_CENTER_INSTALL_TTS_ANNOUNCEMENTS=1` is set. See `agent_command_center/scripts/install_standalone.sh` for integration details.

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
