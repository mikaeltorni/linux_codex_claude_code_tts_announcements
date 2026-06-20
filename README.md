# Linux Codex/Claude Code TTS Announcements

TTS announcement hooks for Codex and Claude Code AI agents on Linux. This repository installs notify hooks that call `codex-agent-tracker` for start, finish, attention, and danger announcements.

## Repository dependencies

Unlike the other setup repositories, this one is **not** standalone — it is a
*plugin* of the Agent Command Center:

- **Runtime (hard):**
  [`agent_command_center`](https://github.com/mikaeltorni/agent_command_center)
  must be installed. The hooks installed here call its `codex-agent-tracker`
  binary to speak announcements, and logging defaults to ACC's log directory.
  Without the tracker, the installed hooks have nothing to call.
- **Build-time (soft):** the shared installer component framework
  [`linux_installation_scripts_functions`](https://github.com/mikaeltorni/linux_installation_scripts_functions) —
  loaded from a sibling checkout when present, otherwise downloaded on demand.

In the desktop setup chain this repository is installed *by* Agent Command
Center (its optional `tts_announcements` component), never on its own.

See the full cross-repository map in
[installation_scripts/DEPENDENCIES.md](https://github.com/mikaeltorni/installation_scripts/blob/master/DEPENDENCIES.md).

## What it does

When installed, this repo:

- copies hook code to `$HOME/.local/share/codex-claude-tts-announcements/`
- writes a generated Codex `notify = [...]` block in `$HOME/.codex/config.toml`
- adds generated Claude Code hook commands to `$HOME/.claude/settings.json`
- removes the retired Agent Command Center `notify_agent.py` hook entries

It does not replace or symlink the `codex` or `claude` binaries.

## Prerequisites

- `codex-agent-tracker` must be installed (provides the `announce` command)
- TTS voice configuration via environment variables (`CODEX__TTS_VOICE`, `CLAUDE_TTS_VOICE`)

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
