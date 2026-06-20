# Linux Codex/Claude Code TTS Announcements

The agent text-to-speech home for Codex and Claude Code on Linux. This
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
- `ATTS_VOICE` / `ATTS_CLAUDE_VOICE` — voice overrides.
- `ATTS_ANNOUNCE_WORKSPACE=0` — disable the spoken workspace suffix.
- `ATTS_NO_AUDIO` — generate/cache clips but never play (used by tests).
- `ATTS_STATE_DIR` — override the engine state/cache directory.

## Prerequisites

- The Kokoro model assets under `<codex-home>/tts` (installed by Agent Command
  Center's LM Studio component) and `uvx` for synthesis; `ffmpeg` for volume.
- For the notify hooks: `codex-agent-tracker` (Agent Command Center).

## Installation

```bash
bash install.sh
```

## Integration with Agent Command Center

The Agent Command Center repository can clone and run this installer when `AGENT_COMMAND_CENTER_INSTALL_TTS_ANNOUNCEMENTS=1` is set. See `agent_command_center/scripts/install_standalone.sh` for integration details.

## Disclaimer

This software is provided under the MIT License on an **“as is”** basis, without warranties of any kind. To the maximum extent permitted by applicable law, the authors and copyright holders shall not be liable for any claims, damages, losses, or other liability arising from the use of this software.

You are solely responsible for determining whether this software is suitable, safe, lawful, and appropriate for your intended use. Unless explicitly stated otherwise, this project is general-purpose software and is not designed, tested, certified, or approved for safety-critical, medical, automotive, aviation, industrial-control, life-support, cybersecurity-critical, financial-critical, or other high-risk use cases.

The authors and copyright holders make no guarantees regarding security, reliability, availability, correctness, compliance, non-infringement, or fitness for any particular purpose.

This notice is intended to clarify the nature of the project and does not impose additional restrictions beyond the MIT License.
