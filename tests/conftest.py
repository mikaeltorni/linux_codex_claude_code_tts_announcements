"""Shared pytest fixtures for the TTS announcements test suite.

The notify router and agent-tts engine read a family of ``ATTS_*`` (and a few
``CODEX__TTS_*`` / ``GROK_*`` / ``QWEN_*``) environment variables at runtime.
On a developer or agent machine these are exported by the live tracker session
(for example ``ATTS_LIFECYCLE_TRACKED=1``, which makes lifecycle hooks defer to
the tracker and stay silent). If that ambient state leaks into the in-process
notify tests, lifecycle-announcement assertions fail even though the product is
correct. This module makes every test hermetic by stripping that env family
before each test; tests that need a flag set do so explicitly via monkeypatch.
"""

import pytest

# Exact runtime-behavior variables the notify router / engine consult.
_TTS_RUNTIME_ENV_VARS = (
    "ATTS_SUPPRESS_ANNOUNCEMENTS",
    "ATTS_LIFECYCLE_TRACKED",
    "CODEX__TTS_VOICE",
    "CODEX_AGENT_FEATURE_KEY",
    "CODEX_AGENT_MODEL_NAME",
    "CODEX_AGENT_LMSTUDIO_MODEL",
    "GROK_EVENT",
    "GROK_FINISH_EVENTS",
    "GROK_MESSAGE",
    "GROK_SESSION_ID",
    "NVIDIA_CODEX_TTS_VOICE",
    "OPENROUTER_CODEX_TTS_VOICE",
    "QWEN_CODEX_LMSTUDIO_MODEL",
)


@pytest.fixture(autouse=True)
def _isolate_tts_runtime_env(monkeypatch):
    """Strip tracker-exported TTS env so ambient session state can't leak in.

    Args:
        monkeypatch: pytest's environment/attribute patcher.

    Removes every ``ATTS_*`` variable plus the specific cross-agent voice and
    Grok/Qwen variables the router reads, so each test starts from a clean,
    reproducible baseline regardless of the shell that launched pytest.
    """
    import os

    for name in list(os.environ):
        if name.startswith("ATTS_"):
            monkeypatch.delenv(name, raising=False)
    for name in _TTS_RUNTIME_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
