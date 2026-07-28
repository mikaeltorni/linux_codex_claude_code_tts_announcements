# Clean Installation Compatibility

This repository is part of the `installation_scripts` Linux setup chain. Keep
the standalone `install.sh` idempotent and compatible with a clean checkout.
Every runtime dependency, downloaded asset, hook file, and default the feature
needs must be represented in the installer. The installer must not replace or
symlink the `codex` or `claude` binaries; it only writes generated,
marker-delimited hook blocks into their config files.

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


## Mandatory programming guidelines prompt

Every agent task in this repository must load the shared
`general-programming-guidelines` skill before the first file edit, using the
harness-native invocation for the runtime in use:

- Codex-family (`ca`, `qa`, `oa`, `na`, …): `$general-programming-guidelines`
- Claude Code, Cline, Grok: `/general-programming-guidelines`
- OpenCode: load `general-programming-guidelines` with the skill tool

Agent Command Center prepends this bare invocation to every dispatched prompt, so the
harness activates the skill before reading the task. When you start a task by hand, invoke it
yourself first. Then follow its Work Loop — dedicated worktree branch before
the first edit, tests, logging, documentation — and do not report the task done
until its Definition of Done checklist passes.
Always finish the delivery: commit in the worktree, merge into the default
branch with `git merge --no-ff`, then reload whatever consumes the change
(installer, skill deployment, service, session). You do not need to be asked.
Never push to a remote and never rewrite history unless the user explicitly
requests it.

