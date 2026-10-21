"""Public regressions for the silent standalone Codex greeting on a fresh VM."""

import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('runtime', ['python', 'rust'])
def test_greeting_hooks_speak_without_tracker(tmp_path, runtime):
    """Route real start, finish and attention payloads to the installed speech owner.

    Parameters: tmp_path - isolated home; runtime - public Python or Rust entrypoint.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}, runtime={runtime}')
    home = tmp_path / 'home'
    binary = home / '.local/bin/agent-tts'
    binary.parent.mkdir(parents=True)
    calls = home / 'speech-calls'
    binary.write_text('#!/usr/bin/python3\nimport json, os, sys\nwith open(os.environ["SPEECH_CALLS"], "a") as output:\n output.write(json.dumps(sys.argv[1:])+"\\n")\n')
    binary.chmod(0o755)
    environment = {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'SPEECH_CALLS': str(calls),
                   'ATTS_CODEX_HOOK_BACKGROUND': '1', 'CODEX_AGENT_KIND': 'codex',
                   'CODEX_AGENT_MODEL_NAME': 'GPT-6-Luna', 'CODEX_AGENT_FEATURE_KEY': 'greeting',
                   'CODEX_AGENT_TRACKER': str(home/'absent-tracker')}
    entry = [sys.executable, str(ROOT/'scripts/notify_agent.py')] if runtime == 'python' else [str(ROOT/'target/debug/notify-agent')]
    for event in ('UserPromptSubmit', 'Stop', 'PermissionRequest'):
        payload = {'hook_event_name': event, 'prompt': 'hi', 'cwd': '/projects/hello',
                   'session_id': 'greeting', 'turn_id': 'reported-greeting'}
        result = subprocess.run(entry, input=json.dumps(payload), text=True,
                                capture_output=True, env=environment, timeout=10)
        assert result.returncode == 0, (event, result.stderr)
    assert calls.is_file(), 'greeting hooks did not call agent-tts without ACC'
    actual = [json.loads(line) for line in calls.read_text().splitlines()]
    assert len(actual) == 3, actual
    assert [call[0] for call in actual] == ['announce', 'announce', 'clarify']
    for call, event in zip(actual[:2], ('start', 'finish')):
        assert call[call.index('--event')+1] == event, call
        assert call[call.index('--voice')+1] == 'af_bella', call
        assert call[call.index('--project-path')+1] == '/projects/hello', call
        assert '--feature-key' not in call, call
    print(None)


def test_prepare_speech_is_an_explicit_owner_operation(tmp_path):
    """Expose complete runtime preparation while retaining cheap hook reconciliation.

    Parameters: tmp_path - isolated installation home.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    environment = {'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin',
                   'TTS_INSTALL_SPEECH_RUNTIME': '0', 'ATTS_INSTALL_GPU_RUNTIME': '0'}
    result = subprocess.run(['bash', str(ROOT/'install.sh'), '--prepare-speech'],
                            text=True, capture_output=True, env=environment, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path/'.local/bin/agent-tts').is_file()
    print(None)


@pytest.mark.parametrize('runtime', ['python', 'rust'])
@pytest.mark.parametrize('status', [0, 9])
def test_existing_tracker_never_replays_through_standalone(tmp_path, runtime, status):
    """Keep tracker ownership for success and failure without duplicate speech.

    Parameters: tmp_path - isolated home; runtime - public hook entrypoint; status - tracker exit code.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}, runtime={runtime}, status={status}')
    commands = tmp_path/'.local/bin'
    commands.mkdir(parents=True)
    tracker = commands/'codex-agent-tracker'
    tracker.write_text(f'#!/bin/sh\nprintf tracker >> "$HOME/tracker-calls"\nexit {status}\n')
    tracker.chmod(0o755)
    speech = commands/'agent-tts'
    speech.write_text('#!/bin/sh\nprintf duplicate > "$HOME/unwanted-speech"\n')
    speech.chmod(0o755)
    environment = {'HOME': str(tmp_path), 'PATH': '/usr/bin:/bin',
                   'CODEX_AGENT_TRACKER': str(tracker), 'ATTS_CODEX_HOOK_BACKGROUND': '1'}
    entry = [sys.executable, str(ROOT/'scripts/notify_agent.py')] if runtime == 'python' else [str(ROOT/'target/debug/notify-agent')]
    result = subprocess.run(entry, input=json.dumps({'hook_event_name':'Stop','cwd':'/projects/hello'}),
                            text=True, capture_output=True, env=environment, timeout=10)
    assert result.returncode == 0, result.stderr
    assert (tmp_path/'tracker-calls').read_text() == 'tracker'
    assert not (tmp_path/'unwanted-speech').exists()
    print(None)


def test_prepare_speech_rejects_corrupt_assets_without_replacing_them(tmp_path):
    """Reject a damaged managed model through the public installer before activation.

    Parameters: tmp_path - isolated home and preexisting runtime/model fixtures.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    root = tmp_path/'.local/share/codex-claude-tts-announcements'
    runtime = root/'speech-runtime'
    (runtime/'bin').mkdir(parents=True)
    (runtime/'bin/python').symlink_to(sys.executable)
    (runtime/'.requirements.sha256').write_text(hashlib.sha256((ROOT/'requirements-speech.txt').read_bytes()).hexdigest())
    model = root/'models/kokoro-v1.0.onnx'
    model.parent.mkdir()
    model.write_bytes(b'damaged-existing-model')
    tools = tmp_path/'tools'
    tools.mkdir()
    uv = tools/'uv'
    uv.write_text('#!/bin/sh\nexit 99\n')
    uv.chmod(0o755)
    result = subprocess.run(['bash', str(ROOT/'install.sh'), '--prepare-speech'],
                            env={'HOME':str(tmp_path),'PATH':f'{tools}:/usr/bin:/bin'},
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'Checksum mismatch' in result.stderr
    assert model.read_bytes() == b'damaged-existing-model'
    assert not (tmp_path/'.config/agent-tts/harness-hooks.enabled').exists()
    print(None)
