"""Agent TTS (ATTS) — the standalone agent text-to-speech engine.

This package owns all agent speech: Kokoro synthesis, playback, volume/speed
tunables, voice selection, and the spoken start/finish/clarify wording. It is
invoked through the ``agent-tts`` CLI and has no dependency on Agent Command
Center; runtimes delegate speech to it.

Modules:
  - engine: synthesis, playback, configuration, and wording.
  - cli: the ``agent-tts`` argument surface.
"""
