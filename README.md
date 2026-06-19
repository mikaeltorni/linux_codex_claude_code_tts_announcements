# Linux Codex/Claude Code TTS Announcements

TTS announcement hooks for Codex and Claude Code AI agents on Linux. This repository contains scripts that automatically install text-to-speech announcements when codex or claudecode are detected in the system.

## What it does

When installed, this repo detects whether `codex` or `claude` (Claude Code) binaries exist on PATH, then installs TTS-aware wrapper scripts at:
- `$HOME/.config/codex-tts-hooks/` — wraps codex calls with announcements
- `$HOME/.config/claude-tts-hooks/` — wraps claude code calls with announcements

## Prerequisites

- `codex-agent-tracker` must be installed (provides the `announce` command)
- TTS voice configuration via environment variables (`CODEX__TTS_VOICE`, `CLAUDE_TTS_VOICE`)

## Installation

```bash
# User-level install (skips root-only steps):
bash install.sh

# Full install including apt packages:
sudo bash install.sh
```

## Integration with Agent Command Center

The agent command_center repository's installer can automatically clone and run this TTS repo as part of its local agent setup. See `agent_command_center/scripts/install_standalone.sh` for integration details.

## Disclaimer

This software is provided under the MIT License on an **“as is”** basis, without warranties of any kind. To the maximum extent permitted by applicable law, the authors and copyright holders shall not be liable for any claims, damages, losses, or other liability arising from the use of this software.

You are solely responsible for determining whether this software is suitable, safe, lawful, and appropriate for your intended use. Unless explicitly stated otherwise, this project is general-purpose software and is not designed, tested, certified, or approved for safety-critical, medical, automotive, aviation, industrial-control, life-support, cybersecurity-critical, financial-critical, or other high-risk use cases.

The authors and copyright holders make no guarantees regarding security, reliability, availability, correctness, compliance, non-infringement, or fitness for any particular purpose.

This notice is intended to clarify the nature of the project and does not impose additional restrictions beyond the MIT License.
