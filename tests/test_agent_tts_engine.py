"""Behavioral tests for the Agent TTS (ATTS) speech engine.

These cover the config resolution, env precedence (ATTS_* over legacy ACC
names), persistence round-trips, silent toggle, voice selection, workspace
suffixing, and the spoken wording — without ever producing real audio
(``ATTS_NO_AUDIO`` is forced on).
"""

import importlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "lib"
ROOT = LIB.parent
if str(LIB) not in sys.path:
    sys.path.insert(0, str(LIB))

_ATTS_ENV = (
    "ATTS_SPEED",
    "ATTS_VOLUME_PERCENT",
    "ATTS_SILENT",
    "ATTS_VOICE",
    "ATTS_CODEX_VOICE",
    "ATTS_CLAUDE_VOICE",
    "ATTS_QWEN_VOICE",
    "ATTS_CLINE_VOICE",
    "ATTS_MODEL_DIR",
    "ATTS_DEVICE",
    "ATTS_GPU_RUNTIME_DIR",
    "ATTS_GPU_MIN_FREE_MIB",
    "ATTS_ANNOUNCE_WORKSPACE",
    "ATTS_NO_AUDIO",
    "AGENT_COMMAND_CENTER_TTS_SPEED",
    "AGENT_COMMAND_CENTER_TTS_VOLUME_PERCENT",
    "ACC_SILENT",
    "CODEX__TTS_VOICE",
    "CODEX_TTS_VOICE",
    "CLAUDE_TTS_VOICE",
    "CLAUDE_CODE_TTS_VOICE",
    "QWEN_CODEX_TTS_VOICE",
    "CLINE_TTS_VOICE",
    "GROK_TTS_VOICE",
    "ATTS_GROK_VOICE",
    "OPENROUTER_CODEX_TTS_VOICE",
    "ATTS_OPENROUTER_VOICE",
    "NVIDIA_CODEX_TTS_VOICE",
    "ATTS_NVIDIA_VOICE",
)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    """Reload the engine with a private state dir and no real audio."""
    for name in _ATTS_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ATTS_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("ATTS_LOG_DIR", str(tmp_path / "log"))
    monkeypatch.setenv("ATTS_ANNOUNCE_WORKSPACE", "0")
    monkeypatch.setenv("ATTS_NO_AUDIO", "1")
    import agent_tts.engine as e
    importlib.reload(e)
    return e


def test_speed_round_trip(engine):
    """A persisted speed is read back and overrides the default."""
    assert engine.current_tts_speed() == engine.DEFAULT_TTS_SPEED
    engine.set_tts_speed(2.0)
    assert engine.current_tts_speed() == 2.0


def test_speed_env_overrides_persisted(engine, monkeypatch):
    """ATTS_SPEED wins over a persisted value."""
    engine.set_tts_speed(2.0)
    monkeypatch.setenv("ATTS_SPEED", "0.75")
    assert engine.current_tts_speed() == 0.75


def test_speed_legacy_env_fallback(engine, monkeypatch):
    """The legacy ACC speed env still applies when ATTS_SPEED is unset."""
    monkeypatch.setenv("AGENT_COMMAND_CENTER_TTS_SPEED", "1.25")
    assert engine.current_tts_speed() == 1.25


def test_volume_round_trip_and_percent_format(engine):
    """Volume persists and formats as a percent string."""
    assert engine.current_tts_volume_percent() == engine.DEFAULT_TTS_VOLUME_PERCENT
    engine.set_tts_volume_percent(250.0)
    assert engine.current_tts_volume_percent() == 250.0
    assert engine.format_tts_volume_percent(250.0) == "250%"


def test_volume_legacy_default_125_is_ignored_when_saved(engine, monkeypatch):
    """The stale legacy default export (125) defers to a saved value."""
    engine.set_tts_volume_percent(400.0)
    monkeypatch.setenv("ATTS_VOLUME_PERCENT", engine.LEGACY_DEFAULT_TTS_VOLUME_ENV)
    assert engine.current_tts_volume_percent() == 400.0


def test_volume_to_db_monotonic(engine):
    """Louder percentages map to larger decibel gains; 100% is 0 dB."""
    assert engine.tts_volume_percent_to_db(100.0) == pytest.approx(0.0)
    assert engine.tts_volume_percent_to_db(200.0) > engine.tts_volume_percent_to_db(100.0)


def test_silent_toggle_persists(engine):
    """The silent flag round-trips through the state file."""
    assert engine.acc_silent_enabled() is False
    engine.set_acc_silent(True)
    assert engine.acc_silent_enabled() is True


def test_silent_env_override(engine, monkeypatch):
    """ATTS_SILENT overrides the persisted flag for one invocation."""
    engine.set_acc_silent(False)
    monkeypatch.setenv("ATTS_SILENT", "1")
    assert engine.acc_silent_enabled() is True


def test_silent_legacy_env(engine, monkeypatch):
    """The legacy ACC_SILENT env is still honored."""
    monkeypatch.setenv("ACC_SILENT", "yes")
    assert engine.acc_silent_enabled() is True


def test_voice_for_kind_precedence(engine, monkeypatch):
    """ATTS_VOICE wins; otherwise per-kind defaults apply."""
    assert engine.voice_for_kind("claude", {}) == "af_sky"
    assert engine.voice_for_kind("qwen", {}) == "af_heart"
    assert engine.voice_for_kind("cline", {}) == "af_aoede"
    assert engine.voice_for_kind("grok", {}) == "af_kore"
    assert engine.voice_for_kind("openrouter", {}) == "af_jessica"
    assert engine.voice_for_kind("nvidia", {}) == "af_sarah"
    assert engine.voice_for_kind("codex", {"ATTS_VOICE": "af_custom"}) == "af_custom"
    assert engine.voice_for_kind("codex", {"CODEX__TTS_VOICE": "af_legacy"}) == "af_legacy"


def test_codex_home_for_kind_covers_every_runtime(engine):
    """Every agent kind resolves its own config home through the shared engine."""
    expected = {
        "codex": ".codex",
        "qwen": ".codex-qwen",
        "api": ".codex-api",
        "claude": ".claude",
        "cline": ".cline",
        "grok": ".grok",
        "openrouter": ".codex-openrouter",
        "nvidia": ".codex-nvidia",
    }

    assert {
        kind: Path(engine.codex_home_for_kind(kind, {})).name
        for kind in expected
    } == expected


def test_voice_for_kind_claude_legacy_env(engine, monkeypatch):
    """The legacy CLAUDE_TTS_VOICE still selects the Claude voice."""
    monkeypatch.setenv("CLAUDE_TTS_VOICE", "af_river")
    assert engine.voice_for_kind("claude", {}) == "af_river"


def test_voice_for_kind_claude_code_legacy_env(engine, monkeypatch):
    """The Claude Code voice alias selects the same Claude voice path."""
    monkeypatch.setenv("CLAUDE_CODE_TTS_VOICE", "af_claude_code")
    assert engine.voice_for_kind("claude", {}) == "af_claude_code"


def test_voice_for_kind_claude_env_beats_normalized_wrapper(engine):
    """Claude-specific voice config wins over a stale normalized wrapper value."""
    assert (
        engine.voice_for_kind(
            "claude",
            {
                "CODEX__TTS_VOICE": "af_wrapper",
                "CLAUDE_TTS_VOICE": "af_claude",
            },
        )
        == "af_claude"
    )


def test_voice_for_kind_supports_runtime_specific_variables(engine):
    """Codex, Claude, and Qwen each honor their ATTS and legacy voice names."""
    assert engine.voice_for_kind("codex", {"ATTS_CODEX_VOICE": "af_codex"}) == "af_codex"
    assert engine.voice_for_kind("claude", {"ATTS_CLAUDE_VOICE": "af_claude"}) == "af_claude"
    assert engine.voice_for_kind("claude", {"CLAUDE_CODE_TTS_VOICE": "af_legacy_claude"}) == "af_legacy_claude"
    assert engine.voice_for_kind("qwen", {"ATTS_QWEN_VOICE": "af_qwen"}) == "af_qwen"
    assert engine.voice_for_kind("cline", {"ATTS_CLINE_VOICE": "af_cline"}) == "af_cline"
    assert engine.voice_for_kind("cline", {"CLINE_TTS_VOICE": "af_legacy_cline"}) == "af_legacy_cline"
    assert engine.voice_for_kind("codex", {"CODEX_TTS_VOICE": "af_legacy_codex"}) == "af_legacy_codex"
    assert engine.voice_for_kind("openrouter", {"ATTS_OPENROUTER_VOICE": "af_or"}) == "af_or"
    assert engine.voice_for_kind("openrouter", {"OPENROUTER_CODEX_TTS_VOICE": "af_legacy_or"}) == "af_legacy_or"
    assert engine.voice_for_kind("nvidia", {"ATTS_NVIDIA_VOICE": "af_nv"}) == "af_nv"
    assert engine.voice_for_kind("nvidia", {"NVIDIA_CODEX_TTS_VOICE": "af_legacy_nv"}) == "af_legacy_nv"
    assert engine.voice_for_kind("qwen", {"QWEN_CODEX_TTS_VOICE": "af_legacy_qwen"}) == "af_legacy_qwen"


def test_default_voices_are_pairwise_distinct(engine, capsys):
    """Each runtime's built-in default Kokoro voice must differ from the others."""
    defaults = {
        kind: engine.voice_for_kind(kind, {})
        for kind in ("codex", "claude", "qwen", "cline", "grok", "openrouter", "nvidia")
    }
    voices = list(defaults.values())
    assert len(voices) == len(set(voices)), f"duplicate default voices: {defaults}"
    assert defaults["grok"] == "af_kore"
    assert defaults["grok"] != defaults["qwen"]
    # ACC uses af_nova for cline while this engine uses af_aoede; Grok must
    # stay distinct from both cross-repo cline defaults.
    acc_cline_default = "af_nova"
    assert defaults["grok"] != defaults["cline"]
    assert defaults["grok"] != acc_cline_default
    print(f"tts_engine_default_voices={defaults}")
    print(f"acc_cline_default={acc_cline_default}")
    print(f"grok_default={defaults['grok']}")


def test_grok_voice_honors_acc_launch_metadata(engine):
    """ACC's GROK_TTS_VOICE export must resolve to the Grok default."""
    assert engine.voice_for_kind("grok", {"GROK_TTS_VOICE": "af_kore"}) == "af_kore"


def test_grok_default_beats_stale_global_codex_tts_voice(engine, monkeypatch):
    """A shell-wide CODEX__TTS_VOICE must not override Grok's distinct default."""
    monkeypatch.setenv("CODEX__TTS_VOICE", "af_heart")
    assert engine.voice_for_kind("grok", {}) == "af_kore"
    assert engine.voice_for_kind("grok", {"CODEX__TTS_VOICE": "af_heart"}) == "af_kore"
    assert engine.voice_for_kind("qwen", {}) == "af_heart"


def test_cline_and_claude_reuse_shared_codex_kokoro_assets(engine, monkeypatch, tmp_path):
    """Agent homes without TTS models should use the shared ~/.codex assets."""
    shared = tmp_path / ".codex/tts"
    shared.mkdir(parents=True)
    (shared / "kokoro-v1.0.onnx").write_bytes(b"model")
    (shared / "voices-v1.0.bin").write_bytes(b"voices")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert engine.resolve_tts_dir(tmp_path / ".cline") == shared
    assert engine.resolve_tts_dir(tmp_path / ".claude") == shared


def test_auto_device_uses_installed_cuda_runtime_with_vram_headroom(
    engine, monkeypatch, tmp_path
):
    """Auto mode selects CUDA only when its runtime and free VRAM are ready."""
    runtime = tmp_path / "gpu-runtime"
    (runtime / "onnxruntime").mkdir(parents=True)
    (runtime / "python/onnxruntime").mkdir(parents=True)
    (runtime / "nvidia/cudnn/lib").mkdir(parents=True)
    monkeypatch.setenv("ATTS_GPU_RUNTIME_DIR", str(runtime))
    monkeypatch.setattr(engine, "gpu_free_memory_mib", lambda: 1536)

    assert engine.resolve_kokoro_device() == "cuda"
    env = engine.kokoro_subprocess_env(Path("/models"), "cuda")
    assert env["ONNX_PROVIDER"] == "CUDAExecutionProvider"
    assert env["PYTHONPATH"].split(":", 1)[0] == str(runtime / "python")
    assert str(runtime / "nvidia/cudnn/lib") in env["LD_LIBRARY_PATH"]


def test_auto_device_keeps_cpu_when_vram_headroom_is_too_small(
    engine, monkeypatch, tmp_path
):
    """Auto mode must not contend with LM Studio below the safety threshold."""
    runtime = tmp_path / "gpu-runtime"
    (runtime / "onnxruntime").mkdir(parents=True)
    (runtime / "python/onnxruntime").mkdir(parents=True)
    monkeypatch.setenv("ATTS_GPU_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("ATTS_GPU_MIN_FREE_MIB", "1024")
    monkeypatch.setattr(engine, "gpu_free_memory_mib", lambda: 900)

    assert engine.resolve_kokoro_device() == "cpu"


def test_forced_cpu_does_not_inject_cuda_runtime(engine, monkeypatch, tmp_path):
    """ATTS_DEVICE=cpu remains an explicit escape hatch on NVIDIA systems."""
    monkeypatch.setenv("ATTS_DEVICE", "cpu")
    monkeypatch.setenv("ATTS_GPU_RUNTIME_DIR", str(tmp_path / "gpu-runtime"))

    assert engine.resolve_kokoro_device() == "cpu"
    env = engine.kokoro_subprocess_env(Path("/models"), "cpu")
    assert "ONNX_PROVIDER" not in env


def test_cuda_missing_output_retries_kokoro_once_on_cpu(
    engine, monkeypatch, tmp_path
):
    """A zero-exit CUDA run without audio must retry the CPU provider."""
    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    (tts_dir / "kokoro-v1.0.onnx").write_bytes(b"model")
    (tts_dir / "voices-v1.0.bin").write_bytes(b"voices")
    monkeypatch.setattr(engine, "resolve_uvx", lambda: "/usr/bin/uvx")
    monkeypatch.setattr(engine, "resolve_tts_dir", lambda _home: tts_dir)
    monkeypatch.setattr(engine, "resolve_kokoro_device", lambda: "cuda")
    monkeypatch.setattr(engine, "current_tts_volume_percent", lambda: 100.0)
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args[0], kwargs["env"]))
        if len(calls) == 2:
            Path(args[0][7]).write_bytes(b"wav")
        return engine.subprocess.CompletedProcess(args[0], 0)

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    assert engine.speak_with_kokoro(
        "hello", "af_sky", tmp_path, play=False
    ) is True
    assert calls[0][0][1:3] == ["--python", "3.12"]
    assert calls[0][1]["ONNX_PROVIDER"] == "CUDAExecutionProvider"
    assert "ONNX_PROVIDER" not in calls[1][1]


def test_workspace_suffix_disabled(engine):
    """ATTS_ANNOUNCE_WORKSPACE=0 (set by the fixture) returns text unchanged."""
    assert engine.with_workspace_suffix("Project X started") == "Project X started"


def test_announcement_wording(engine):
    """Start/finish/clarify wording matches the shared phrasing."""
    assert engine.agent_announcement_text("codex", "demo", "start") == "Project demo started"
    assert (
        engine.agent_announcement_text("codex", "demo", "finish", completion_message="did a thing")
        == "did a thing"
    )
    assert engine.clarify_announcement_text("demo").startswith("Project demo needs your input")
    assert engine.clarify_announcement_text("").startswith("I need your input")


def test_play_audio_suppressed_returns_true(engine):
    """With ATTS_NO_AUDIO set, playback is suppressed but reports success."""
    assert engine.play_audio(Path("/nonexistent.wav")) is True


def test_no_audio_false_value_does_not_suppress_playback(engine, monkeypatch, tmp_path):
    """An explicit ``ATTS_NO_AUDIO=0`` must leave real playback enabled."""
    audio = tmp_path / "speech.wav"
    audio.write_bytes(b"wav")
    monkeypatch.setenv("ATTS_NO_AUDIO", "0")
    monkeypatch.setattr(
        engine.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "pw-play" else None,
    )
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return engine.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    assert engine.play_audio(audio) is True
    assert calls == [["/usr/bin/pw-play", str(audio)]]


def test_play_audio_serializes_concurrent_players(engine, monkeypatch, tmp_path):
    """Concurrent announcements must never overlap audio-player processes."""
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    monkeypatch.delenv("ATTS_NO_AUDIO", raising=False)
    monkeypatch.setattr(
        engine.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "pw-play" else None,
    )
    guard = threading.Lock()
    active = 0
    maximum_active = 0
    start = threading.Barrier(2)

    def fake_run(command, **kwargs):
        nonlocal active, maximum_active
        with guard:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.1)
        with guard:
            active -= 1
        return engine.subprocess.CompletedProcess(command, 0)

    def play(path):
        start.wait()
        assert engine.play_audio(path) is True

    monkeypatch.setattr(engine.subprocess, "run", fake_run)
    threads = [
        threading.Thread(target=play, args=(first,)),
        threading.Thread(target=play, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert all(not thread.is_alive() for thread in threads)
    assert maximum_active == 1


def test_concurrent_identical_synthesis_runs_kokoro_once(tmp_path):
    """Two detached copies requesting one cache key must share one synthesis."""
    bin_dir = tmp_path / "bin"
    model_dir = tmp_path / "models"
    state_dir = tmp_path / "state"
    bin_dir.mkdir()
    model_dir.mkdir()
    (model_dir / "kokoro-v1.0.onnx").write_bytes(b"model")
    (model_dir / "voices-v1.0.bin").write_bytes(b"voices")
    call_log = tmp_path / "uvx-calls"
    release = tmp_path / "release-uvx"
    uvx = bin_dir / "uvx"
    uvx.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'call\\n' >> \"$UV_CALL_LOG\"\n"
        "while [ ! -e \"$UV_RELEASE\" ]; do sleep 0.01; done\n"
        "printf 'complete-wav' > \"$7\"\n",
        encoding="utf-8",
    )
    uvx.chmod(0o755)
    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("ATTS_"):
            env.pop(name)
    env.update(
        {
            "ATTS_STATE_DIR": str(state_dir),
            "ATTS_LOG_DIR": str(tmp_path / "log"),
            "ATTS_MODEL_DIR": str(model_dir),
            "ATTS_DEVICE": "cpu",
            "ATTS_VOLUME_PERCENT": "100",
            "ATTS_ANNOUNCE_WORKSPACE": "0",
            "ATTS_NO_AUDIO": "1",
            "UV_CALL_LOG": str(call_log),
            "UV_RELEASE": str(release),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
        }
    )
    command = [
        str(ROOT / "scripts/agent-tts"),
        "voice",
        "--text",
        "same announcement",
        "--voice",
        "af_sky",
        "--no-play",
    ]

    first = subprocess.Popen(command, env=env)
    deadline = time.monotonic() + 3
    while not call_log.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert call_log.exists(), "first synthesis never reached the fake uvx"
    second = subprocess.Popen(command, env=env)
    time.sleep(0.2)
    release.touch()

    assert first.wait(timeout=5) == 0
    assert second.wait(timeout=5) == 0
    assert call_log.read_text(encoding="utf-8").splitlines() == ["call"]


def test_synthesis_publishes_cache_only_after_output_is_complete(tmp_path):
    """A half-written Kokoro file must never be visible as a cache hit."""
    bin_dir = tmp_path / "bin"
    model_dir = tmp_path / "models"
    state_dir = tmp_path / "state"
    bin_dir.mkdir()
    model_dir.mkdir()
    (model_dir / "kokoro-v1.0.onnx").write_bytes(b"model")
    (model_dir / "voices-v1.0.bin").write_bytes(b"voices")
    ready = tmp_path / "uvx-ready"
    release = tmp_path / "release-uvx"
    uvx = bin_dir / "uvx"
    uvx.write_text(
        "#!/usr/bin/env bash\n"
        "printf 'partial' > \"$7\"\n"
        "touch \"$UV_READY\"\n"
        "while [ ! -e \"$UV_RELEASE\" ]; do sleep 0.01; done\n"
        "printf 'complete-wav' > \"$7\"\n",
        encoding="utf-8",
    )
    uvx.chmod(0o755)
    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("ATTS_"):
            env.pop(name)
    env.update(
        {
            "ATTS_STATE_DIR": str(state_dir),
            "ATTS_LOG_DIR": str(tmp_path / "log"),
            "ATTS_MODEL_DIR": str(model_dir),
            "ATTS_DEVICE": "cpu",
            "ATTS_VOLUME_PERCENT": "100",
            "ATTS_ANNOUNCE_WORKSPACE": "0",
            "ATTS_NO_AUDIO": "1",
            "UV_READY": str(ready),
            "UV_RELEASE": str(release),
            "PATH": f"{bin_dir}:/usr/bin:/bin",
        }
    )
    command = [
        str(ROOT / "scripts/agent-tts"),
        "voice",
        "--text",
        "atomic announcement",
        "--voice",
        "af_sky",
        "--no-play",
    ]

    process = subprocess.Popen(command, env=env)
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    try:
        assert ready.exists(), "synthesis never produced its partial output"
        cache_dir = state_dir / "voice-cache"
        assert list(cache_dir.glob("*.wav")) == []
    finally:
        # Never strand the fake subprocess if the regression assertion fails.
        release.touch()

    assert process.wait(timeout=5) == 0
    published = list(cache_dir.glob("*.wav"))
    assert len(published) == 1
    assert published[0].read_bytes() == b"complete-wav"


def test_stale_synthesis_workdirs_are_cleaned(engine, tmp_path):
    """Killed synthesis processes leave only age-bounded temporary state."""
    temp_root = tmp_path / "voice-cache/.tmp"
    stale = temp_root / "stale-work"
    recent = temp_root / "recent-work"
    stale.mkdir(parents=True)
    recent.mkdir()
    (stale / "input.txt").write_text("stale", encoding="utf-8")
    (recent / "input.txt").write_text("recent", encoding="utf-8")
    old = time.time() - engine.STALE_SYNTHESIS_SECONDS - 1
    os.utime(stale, (old, old))

    engine._cleanup_stale_synthesis_dirs(temp_root)

    assert not stale.exists()
    assert recent.is_dir()


def test_kokoro_synthesis_has_a_timeout(engine, monkeypatch, tmp_path):
    """A hung provider must fail cleanly instead of holding its cache lock forever."""
    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    (tts_dir / "kokoro-v1.0.onnx").write_bytes(b"model")
    (tts_dir / "voices-v1.0.bin").write_bytes(b"voices")
    monkeypatch.setattr(engine, "resolve_uvx", lambda: "/usr/bin/uvx")
    monkeypatch.setattr(engine, "resolve_tts_dir", lambda _home: tts_dir)
    monkeypatch.setattr(engine, "resolve_kokoro_device", lambda: "cpu")
    monkeypatch.setattr(engine, "current_tts_volume_percent", lambda: 100.0)
    seen = []

    def fake_run(command, **kwargs):
        seen.append(kwargs.get("timeout"))
        raise engine.subprocess.TimeoutExpired(command, kwargs.get("timeout"))

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    assert engine.speak_with_kokoro("timeout", "af_sky", tmp_path, play=False) is False
    assert seen == [engine.KOKORO_TIMEOUT_SECONDS]
    temp_root = engine.STATE_DIR / "voice-cache/.tmp"
    assert not temp_root.exists() or not any(temp_root.iterdir())


def test_state_file_read_errors_are_logged(engine, monkeypatch):
    """Unreadable persisted state falls back cleanly with a diagnostic log."""
    def fail_read_text(self, encoding=None):
        raise OSError("boom")

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    assert engine._read_state_file("tts-speed") == ""
    with (engine.LOG_DIR / "voice.log").open(encoding="utf-8") as handle:
        contents = handle.read()
    assert "state read failed" in contents


def test_capture_command_timeout_is_logged(engine, monkeypatch):
    """Workspace helper command timeouts are observable but non-fatal."""
    def fake_run(*args, **kwargs):
        raise engine.subprocess.TimeoutExpired(cmd=["xprop"], timeout=1.0)

    monkeypatch.setattr(engine.shutil, "which", lambda command: f"/usr/bin/{command}")
    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    assert engine._capture_command(["xprop", "-root"]) == ""
    contents = (engine.LOG_DIR / "voice.log").read_text(encoding="utf-8")
    assert "command timed out" in contents


def test_fallback_speak_logs_missing_synthesizer(engine, monkeypatch):
    """If no desktop fallback exists, the skipped speech path is logged."""
    monkeypatch.delenv("ATTS_NO_AUDIO", raising=False)
    monkeypatch.setattr(engine.shutil, "which", lambda command: None)

    engine.fallback_speak("hello")

    contents = (engine.LOG_DIR / "voice.log").read_text(encoding="utf-8")
    assert "fallback_speak skipped: no fallback synthesizer found" in contents


def test_fallback_speak_waits_and_tries_the_second_synthesizer(
    engine, monkeypatch
):
    """Fallback speech stays serialized and recovers from a failed spd-say."""
    monkeypatch.delenv("ATTS_NO_AUDIO", raising=False)
    monkeypatch.setattr(engine.shutil, "which", lambda command: f"/usr/bin/{command}")
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return engine.subprocess.CompletedProcess(
            command,
            1 if command[0] == "spd-say" else 0,
        )

    monkeypatch.setattr(engine.subprocess, "run", fake_run)

    assert engine.fallback_speak("hello") is True
    assert calls == [
        ("spd-say", "--wait", "hello"),
        ("espeak-ng", "hello"),
    ]


def test_workspace_x11_probe_backs_off_after_total_failure(engine, monkeypatch):
    """A failing xprop environment is probed once, then skipped for the cooldown.

    Regression: on desktops without EWMH properties every announcement ran
    three failing ``xprop`` commands, spamming ``command failed rc=1`` lines
    into voice.log on each 5-second poll.
    """
    monkeypatch.delenv("WINDOWID", raising=False)
    calls = []
    monkeypatch.setattr(
        engine, "_capture_command", lambda cmd, timeout=1.0: calls.append(cmd) or ""
    )
    engine._X11_PROBE_FAILED_AT = None

    assert engine.detect_terminal_workspace() == ""
    xprop_first = sum(1 for cmd in calls if cmd[0] == "xprop")
    assert xprop_first > 0

    assert engine.detect_terminal_workspace() == ""
    xprop_second = sum(1 for cmd in calls if cmd[0] == "xprop") - xprop_first
    assert xprop_second == 0  # cooldown suppresses repeated probes


def test_workspace_x11_probe_retries_after_cooldown_and_resets_on_success(
    engine, monkeypatch
):
    monkeypatch.delenv("WINDOWID", raising=False)
    outputs = {"xprop": "_NET_CURRENT_DESKTOP(CARDINAL) = 2"}
    monkeypatch.setattr(
        engine,
        "_capture_command",
        lambda cmd, timeout=1.0: outputs.get(cmd[0], ""),
    )
    # Failure recorded long ago: the cooldown has expired, probing resumes.
    engine._X11_PROBE_FAILED_AT = (
        engine.time.monotonic() - engine.X11_PROBE_RETRY_SECONDS - 1
    )

    assert engine.detect_terminal_workspace() == "3"
    assert engine._X11_PROBE_FAILED_AT is None
