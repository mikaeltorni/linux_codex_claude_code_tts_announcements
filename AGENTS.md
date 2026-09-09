# Clean Installation Compatibility

The `linux-configuration` skill owns the clean-install and root-optional
installer rules; they are not restated here. Repository-specific installer
facts:

The installer must not replace or symlink the `codex` or `claude` binaries; it
only writes generated, marker-delimited hook blocks into their config files.

# Ownership: this repo owns all agent speech

The `agent-tts` engine owns *all* agent text-to-speech — Kokoro synthesis,
ffmpeg volume amplification, playback, voice selection, the speed/volume/silent
tunables (the `ATTS_` environment namespace, with the legacy
`AGENT_COMMAND_CENTER_TTS_*` / `ACC_SILENT` / `*_TTS_VOICE` names honored as
fallbacks), and the spoken start/finish/clarify wording. Agent Command Center
delegates every announcement to this engine and keeps no synthesizer of its own;
implement speech changes here, not in ACC.

The engine is fully standalone. The notify hooks (Codex, Claude Code, Cline,
Grok) delegate orchestration to ACC's `codex-agent-tracker` so a finish label is
summarized once and shared with the terminal title, but they degrade to a no-op
when the tracker is absent — nothing here may become a hard dependency on ACC.
Feature labels are keyed per session: ACC launchers export
`CODEX_AGENT_FEATURE_KEY`, and hooks prefer that inherited key over the hook
payload's session id (`runtime_feature_key` in `notify.py`) so a tracked
session's title updates and its tracker-driven finish announcement resolve the
same stored label; concurrent sessions in one project must never speak each
other's task. Untracked launches keep the payload session id as the key.
The framework dependency (`linux_installation_scripts_functions`) is soft
(sibling checkout or on-demand download). Grok keeps a distinct voice isolated
from Qwen; preserve that separation when touching voice defaults.

# Install wiring and idempotent migration

This repository is **clone-only**: the master clones it first, and Agent Command
Center installs it through its recommended (default-on) `tts_announcements`
component. Do not add it to the master's direct `INSTALL_REPOS`.

Hook installation must stay idempotent *and* migrate configs written by earlier
marker/path schemes. Component `detect_*` functions must match the **current**
managed marker or install-root `notify_agent.py` path — not a bare
`notify_agent.py` substring — otherwise a config carrying an older block reads as
"already installed", the runtime skips it, and the migration in the `configure_*`
functions never runs. Cover the migration path with the `tests/` install
contract when you change a marker or the managed command.


## Shared workflow

This file intentionally contains project-specific ownership, data-safety,
component, integration, and deployment facts. The reusable workflow rules
live in the selected skills and must not be copied into every project file.

Before editing, read this project file, then load:

- `general-programming-guidelines` for the engineering workflow;
- `commits` for capability boundaries and commit verification;
- `worktree` for isolation, branch, merge, and consumer reapplication; and
- `linux-configuration` when the task touches GNOME, desktop settings,
  systemd user services, or any `install.sh`.

Those skills are the cross-project source of truth for workflow, delivery,
desktop deployment, clean-install compatibility, and root-optional installer
rules. Project-specific sections here may narrow ownership or add required
verification, but must not restate or contradict those shared policies.
