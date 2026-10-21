"""Public installer checks using isolated homes and a real terminal."""

import json
import os
import pty
import select
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = Path(os.environ.get('ISC_FUNCTIONS_DIR', Path.home() / 'projects/linux_installation_scripts_functions'))


def run_manual(home, keys, checkout=ROOT, providers="none", owner=None):
    """Run the public installer on a terminal and answer provider and voice prompts.

    Parameters: home - isolated target home; keys - bytes to send per prompt; checkout - installer checkout; providers - optional CLI selection; owner - optional fixture provider repository.
    Returns: terminal output after successful installation.
    """
    print(f"home={home}, keys={keys}, checkout={checkout}, providers={providers}, owner={owner}")
    binary_dir = home / 'bin'
    binary_dir.mkdir(exist_ok=True)
    for name in ('bash', 'python3', 'dirname', 'mkdir', 'install', 'ln', 'date', 'sed',
                 'tail', 'mv', 'awk', 'tr', 'sort', 'mktemp', 'tput', 'stty', 'cut',
                 'id', 'readlink', 'cat', 'rm', 'wc', 'cp', 'touch', 'chmod', 'env',
                 'basename', 'sleep', 'head', 'tee', 'grep'):
        target = binary_dir / name
        if not target.exists():
            target.symlink_to('/usr/bin/' + name)
    master, slave = pty.openpty()
    process = subprocess.Popen(
        ['bash', str(checkout / 'install.sh')], stdin=slave, stdout=slave, stderr=slave,
        env={'HOME': str(home), 'TTS_TARGET_HOME': str(home), 'PATH': str(binary_dir),
             'ISC_FUNCTIONS_DIR': str(FRAMEWORK), 'TTS_SKIP_SYSTEMD': '1',
             'ATTS_INSTALL_GPU_RUNTIME': '0', 'TTS_LOG_DIR': str(home / 'logs'),
             'TTS_INSTALL_HARNESSES': providers,
             **({'TTS_CLI_SETUP_DIR': str(owner)} if owner is not None else {})},
    )
    os.close(slave)
    output = b''
    answered = 0
    deadline = time.monotonic() + 10
    try:
        while time.monotonic() < deadline:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output += chunk
                while answered < len(keys) and output.count(b'Enter to confirm') > answered:
                    os.write(master, keys[answered])
                    answered += 1
            if process.poll() is not None:
                break
        try:
            status = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            raise AssertionError(output.decode(errors='replace')) from None
        assert status == 0, output.decode(errors='replace')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        os.close(master)
    result = output.decode(errors='replace')
    print(result)
    return result


def test_manual_detects_harnesses_and_persists_arrow_selection(tmp_path):
    """Select voices only for detected homes, retaining independent user hooks.

    Parameters: tmp_path - isolated installation directory.
    Returns: None.
    """
    print(f"tmp_path={tmp_path}")
    home = tmp_path / 'home'
    codex = home / '.codex-account-2'
    codex.mkdir(parents=True)
    (codex / 'hooks.json').write_text(json.dumps({'hooks': {'Stop': [
        {'hooks': [{'type': 'command', 'command': 'echo keep'}]}]}}))
    (home / '.claude').mkdir()
    output = run_manual(home, [b'\x1b[B\n', b'\n'])
    assert 'Voice for codex' in output
    assert 'Voice for claude' in output
    assert 'Voice for grok' not in output
    saved = json.loads((home / '.config/agent-tts/voices.json').read_text())
    assert saved['codex'] == 'af_sky'
    assert saved['claude'] == 'af_sky'
    hooks = json.loads((codex / 'hooks.json').read_text())['hooks']
    assert 'echo keep' in json.dumps(hooks)
    assert 'ATTS_CODEX_VOICE=af_sky' in json.dumps(hooks)
    assert set(hooks) >= {'UserPromptSubmit', 'Stop', 'PermissionRequest'}
    assert not (home / '.grok').exists()
    assert not (home / '.cline').exists()
    assert not (home / '.codex').exists()
    run_manual(home, [b'\n', b'\n'])
    assert json.loads((home / '.config/agent-tts/voices.json').read_text()) == saved
    assert json.loads((codex / 'hooks.json').read_text()) == {'hooks': hooks}
    print(None)


def test_manual_cancel_preserves_preferences_and_hooks(tmp_path):
    """Cancel without changing harness configuration or saved choices.

    Parameters: tmp_path - isolated installation directory.
    Returns: None.
    """
    print(f"tmp_path={tmp_path}")
    home = tmp_path / 'home'
    (home / '.codex').mkdir(parents=True)
    run_manual(home, [b'q'])
    assert not (home / '.config/agent-tts/voices.json').exists()
    assert not (home / '.codex/hooks.json').exists()
    print(None)


def test_editable_install_catalog_preserves_saved_voice(tmp_path):
    """Changing the install.sh list offers new choices and retains saved voices.

    Parameters: tmp_path - isolated checkout and target home.
    Returns: None.
    """
    print(f"tmp_path={tmp_path}")
    checkout = tmp_path / 'checkout'
    shutil.copytree(ROOT, checkout, ignore=shutil.ignore_patterns('.git', 'target', 'tmp', '.log', '__pycache__', '.pytest_cache'))
    installer = checkout / 'install.sh'
    source = installer.read_text()
    assert 'TTS_VOICES=(' in source
    source = source.replace('TTS_VOICES=(', 'TTS_VOICES=(am_onyx ')
    installer.write_text(source)
    home = tmp_path / 'home'
    (home / '.codex').mkdir(parents=True)
    output = run_manual(home, [b'\x1b[A\n'], checkout)
    assert 'am_onyx' in output
    assert json.loads((home / '.config/agent-tts/voices.json').read_text())['codex'] == 'am_onyx'
    run_manual(home, [b'\n'], checkout)
    assert json.loads((home / '.config/agent-tts/voices.json').read_text())['codex'] == 'am_onyx'
    print(None)


def test_accepting_defaults_keeps_all_current_runtime_voices(tmp_path):
    """Accept each current voice without silently changing the built-in defaults.

    Parameters: tmp_path - isolated target home.
    Returns: None.
    """
    print(f"tmp_path={tmp_path}")
    home = tmp_path / 'home'
    expected = {'codex': 'af_bella', 'claude': 'af_sky', 'qwen': 'af_heart',
                'cline': 'af_aoede', 'grok': 'af_kore', 'openrouter': 'af_jessica',
                'nvidia': 'af_sarah', 'opencode': 'af_heart'}
    for relative in ('.codex', '.claude', '.codex-qwen', '.cline', '.grok',
                     '.codex-openrouter', '.codex-nvidia', '.config/opencode'):
        (home / relative).mkdir(parents=True)
    run_manual(home, [b'\n'] * len(expected))
    assert json.loads((home / '.config/agent-tts/voices.json').read_text()) == expected
    print(None)


def test_sync_installs_new_accounts_without_changing_choices(tmp_path):
    """Reconcile a later account noninteractively with saved choices and settings.

    Parameters: tmp_path - isolated target home.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    home = tmp_path / 'home'
    (home / '.codex').mkdir(parents=True)
    run_manual(home, [b'\x1b[B\n'])
    preferences = (home / '.config/agent-tts/voices.json').read_text()
    events = home / '.config/agent-tts/announcements.env'
    events.write_text('ATTS_ANNOUNCE_START=0\nATTS_ANNOUNCE_FINISH=1\n')
    account = home / '.codex-account-3'
    account.mkdir()
    env = {'HOME': str(home), 'TTS_TARGET_HOME': str(home), 'PATH': str(home / 'bin'),
           'ISC_FUNCTIONS_DIR': str(FRAMEWORK), 'TTS_SKIP_SYSTEMD': '1',
           'ATTS_INSTALL_GPU_RUNTIME': '0', 'TTS_LOG_DIR': str(home / 'logs')}
    result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--sync-harnesses'],
                            env=env, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr + result.stdout
    assert 'Enter to confirm' not in result.stdout
    hooks = (account / 'hooks.json').read_text()
    assert 'ATTS_CODEX_VOICE=af_sky' in hooks
    assert (home / '.config/agent-tts/voices.json').read_text() == preferences
    assert events.read_text() == 'ATTS_ANNOUNCE_START=0\nATTS_ANNOUNCE_FINISH=1\n'
    (account / 'hooks.json').unlink()
    result = subprocess.run([str(home / '.local/bin/tts-reconcile')], env=env,
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert (account / 'hooks.json').read_text() == hooks
    (home / '.config/agent-tts/harness-hooks.enabled').unlink()
    (account / 'hooks.json').unlink()
    result = subprocess.run([str(home / '.local/bin/tts-reconcile')], env=env,
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert not (account / 'hooks.json').exists()
    print(None)


def test_sync_rejects_invalid_preferences_without_replacing_user_hooks(tmp_path):
    """Reject damaged voice data and unknown arguments while preserving hooks.

    Parameters: tmp_path - isolated target home.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    home = tmp_path / 'home'
    (home / '.codex').mkdir(parents=True)
    run_manual(home, [b'\n'])
    hooks = home / '.codex/hooks.json'
    before = hooks.read_text()
    preferences = home / '.config/agent-tts/voices.json'
    preferences.write_text('["bad"]')
    env = {'HOME': str(home), 'TTS_TARGET_HOME': str(home), 'PATH': str(home / 'bin'),
           'ISC_FUNCTIONS_DIR': str(FRAMEWORK), 'TTS_SKIP_SYSTEMD': '1',
           'ATTS_INSTALL_GPU_RUNTIME': '0', 'TTS_LOG_DIR': str(home / 'logs')}
    for arguments in (['--sync-harnesses'], ['--sync-harnesses', '--bad']):
        result = subprocess.run(['bash', str(ROOT / 'install.sh'), *arguments],
                                env=env, text=True, capture_output=True, timeout=20)
        assert result.returncode != 0, arguments
        assert hooks.read_text() == before, arguments
        assert preferences.read_text() == '["bad"]', arguments
    print(None)


def test_disabling_integration_removes_only_managed_hooks_and_keeps_voices(tmp_path):
    """Opting out removes managed hooks and prevents future automatic recreation.

    Parameters: tmp_path - isolated target home.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    home = tmp_path / 'home'
    (home / '.codex-qwen').mkdir(parents=True)
    run_manual(home, [b'\n'])
    hooks = home / '.codex-qwen/hooks.json'
    data = json.loads(hooks.read_text())
    data['hooks']['Stop'].append({'hooks': [{'type': 'command', 'command': 'echo keep'}]})
    hooks.write_text(json.dumps(data))
    preferences = (home / '.config/agent-tts/voices.json').read_text()
    env = {'HOME': str(home), 'TTS_TARGET_HOME': str(home), 'PATH': str(home / 'bin'),
           'ISC_FUNCTIONS_DIR': str(FRAMEWORK), 'TTS_SKIP_SYSTEMD': '1',
           'ATTS_INSTALL_GPU_RUNTIME': '0', 'TTS_LOG_DIR': str(home / 'logs')}
    result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--disable-harnesses'],
                            env=env, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr + result.stdout
    assert not (home / '.config/agent-tts/harness-hooks.enabled').exists()
    assert 'notify_agent' not in hooks.read_text()
    assert 'echo keep' in hooks.read_text()
    assert (home / '.config/agent-tts/voices.json').read_text() == preferences
    result = subprocess.run([str(home / '.local/bin/tts-reconcile')], env=env,
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert 'notify_agent' not in hooks.read_text()
    print(None)


def test_uninstalling_hook_files_disables_reconciliation(tmp_path):
    """Removing the hook runtime also removes its automatic entrypoint and opt-in.

    Parameters: tmp_path - isolated target home.
    Returns: None.
    """
    print(f'tmp_path={tmp_path}')
    home = tmp_path / 'home'
    (home / '.codex').mkdir(parents=True)
    run_manual(home, [b'\n'])
    saved = (home / '.config/agent-tts/voices.json').read_text()
    env = {'HOME': str(home), 'TTS_TARGET_HOME': str(home), 'PATH': str(home / 'bin'),
           'ISC_FUNCTIONS_DIR': str(FRAMEWORK), 'TTS_SKIP_SYSTEMD': '1',
           'ATTS_INSTALL_GPU_RUNTIME': '0', 'TTS_LOG_DIR': str(home / 'logs')}
    result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--uninstall', 'hook_files'],
                            env=env, text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert not (home / '.config/agent-tts/harness-hooks.enabled').exists()
    assert not (home / '.local/bin/tts-reconcile').exists()
    assert (home / '.config/agent-tts/voices.json').read_text() == saved
    print(None)
