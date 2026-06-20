"""TTS announcement hook package for Codex and Claude Code.

Modules:
  - logging_utils: Centralized leveled logging used by every other module.
  - notify: Runtime hook logic that delegates speech/title to codex-agent-tracker.
  - install_hooks: Install-time, idempotent config writers for both agents.
"""
